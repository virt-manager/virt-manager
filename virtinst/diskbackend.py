#
# Storage lookup/creation helpers
#
# Copyright 2013  Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

import logging
import os
import statvfs

import libvirt

from virtinst import StoragePool, StorageVolume
from virtinst import util


def _check_if_pool_source(conn, path):
    """
    If passed path is a host disk device like /dev/sda, want to let the user
    use it
    """
    if not conn.check_conn_support(conn.SUPPORT_CONN_STORAGE):
        return None

    def check_pool(poolname, path):
        pool = conn.storagePoolLookupByName(poolname)
        xmlobj = StoragePool(conn, parsexml=pool.XMLDesc(0))
        if xmlobj.source_path == path:
            return pool

    running_list = conn.listStoragePools()
    inactive_list = conn.listDefinedStoragePools()
    for plist in [running_list, inactive_list]:
        for name in plist:
            p = check_pool(name, path)
            if p:
                return p
    return None


def check_if_path_managed(conn, path):
    """
    Determine if we can use libvirt storage APIs to create or lookup
    the passed path. If we can't, throw an error
    """
    vol = None
    pool = None
    verr = None
    path_is_pool = False

    def lookup_vol_by_path():
        try:
            vol = conn.storageVolLookupByPath(path)
            vol.info()
            return vol, None
        except libvirt.libvirtError, e:
            if (hasattr(libvirt, "VIR_ERR_NO_STORAGE_VOL")
                and e.get_error_code() != libvirt.VIR_ERR_NO_STORAGE_VOL):
                raise
            return None, e

    def lookup_vol_name(name):
        try:
            name = os.path.basename(path)
            if pool and name in pool.listVolumes():
                return pool.lookupByName(name)
        except:
            pass
        return None

    vol = lookup_vol_by_path()[0]
    if not vol:
        pool = StoragePool.lookup_pool_by_path(conn, os.path.dirname(path))

        # Is pool running?
        if pool and pool.info()[0] != libvirt.VIR_STORAGE_POOL_RUNNING:
            pool = None

    # Attempt to lookup path as a storage volume
    if pool and not vol:
        try:
            # Pool may need to be refreshed, but if it errors,
            # invalidate it
            pool.refresh(0)
            vol, verr = lookup_vol_by_path()
            if verr:
                vol = lookup_vol_name(os.path.basename(path))
        except Exception, e:
            vol = None
            pool = None
            verr = str(e)

    if not vol:
        # See if path is a pool source, and allow it through
        trypool = _check_if_pool_source(conn, path)
        if trypool:
            path_is_pool = True
            pool = trypool

    if not vol and not pool:
        if not conn.is_remote():
            # Building local disk
            return None, None, False

        if not verr:
            # Since there is no error, no pool was ever found
            err = (_("Cannot use storage '%(path)s': '%(rootdir)s' is "
                     "not managed on the remote host.") %
                      {'path' : path,
                        'rootdir' : os.path.dirname(path)})
        else:
            err = (_("Cannot use storage %(path)s: %(err)s") %
                    {'path' : path, 'err' : verr})

        raise ValueError(err)

    return vol, pool, path_is_pool


def build_vol_install(conn, path, pool, size, sparse):
    # Path wasn't a volume. See if base of path is a managed
    # pool, and if so, setup a StorageVolume object
    if size is None:
        raise ValueError(_("Size must be specified for non "
                           "existent volume path '%s'" % path))

    logging.debug("Path '%s' is target for pool '%s'. "
                  "Creating volume '%s'.",
                  os.path.dirname(path), pool.name(),
                  os.path.basename(path))

    cap = (size * 1024 * 1024 * 1024)
    if sparse:
        alloc = 0
    else:
        alloc = cap

    volinst = StorageVolume(conn)
    volinst.pool = pool
    volinst.name = os.path.basename(path)
    volinst.capacity = cap
    volinst.allocation = alloc
    return volinst



class _StorageBase(object):
    def get_size(self):
        raise NotImplementedError()
    def get_dev_type(self):
        raise NotImplementedError()
    def is_managed(self):
        raise NotImplementedError()
    def get_driver_type(self):
        raise NotImplementedError()


class StorageCreator(_StorageBase):
    def __init__(self, conn, path, pool,
                 vol_install, clone_path, backing_store,
                 size, sparse, fmt):
        _StorageBase.__init__(self)

        self._conn = conn
        self._pool = pool
        self._vol_install = vol_install
        self._path = path
        self._size = size
        self._sparse = sparse
        self._clone_path = clone_path
        self.fake = False

        if not self._vol_install and self._pool:
            self._vol_install = build_vol_install(conn, path, pool,
                                                   size, sparse)
        self._set_format(fmt)
        self._set_backing_store(backing_store)

        if self._vol_install:
            self._path = None
            self._size = None

        # Cached bits
        self._dev_type = None


    ###############
    # Private API #
    ###############

    def _set_format(self, val):
        if val is None:
            return

        if self._vol_install:
            if not self._vol_install.supports_property("format"):
                raise ValueError(_("Storage type does not support format "
                                   "parameter."))
            if self._vol_install.format != val:
                self._vol_install.format = val

        elif val != "raw":
            raise RuntimeError(_("Format cannot be specified for "
                                 "unmanaged storage."))

    def _set_backing_store(self, val):
        if val is None:
            return
        if not self._vol_install:
            raise RuntimeError(_("Cannot set backing store for unmanaged "
                                 "storage."))
        self._vol_install.backing_store = val


    ##############
    # Public API #
    ##############

    def _get_path(self):
        if self._vol_install and not self._path:
            xmlobj = StoragePool(self._conn,
                parsexml=self._vol_install.pool.XMLDesc(0))
            self._path = (xmlobj.target_path + "/" + self._vol_install.name)
        return self._path
    path = property(_get_path)

    def get_vol_install(self):
        return self._vol_install
    def get_sparse(self):
        return self._sparse

    def get_size(self):
        if not self._size:
            self._size = (float(self._vol_install.capacity) /
                          1024.0 / 1024.0 / 1024.0)
        return self._size

    def get_dev_type(self):
        if not self._dev_type:
            if self._vol_install:
                if self._vol_install.file_type == libvirt.VIR_STORAGE_VOL_FILE:
                    self._dev_type = "file"
                else:
                    self._dev_type = "block"
            else:
                self._dev_type = "file"
        return self._dev_type

    def get_driver_type(self):
        if self._vol_install:
            if self._vol_install.supports_property("format"):
                return self._vol_install.format
        return "raw"

    def is_managed(self):
        return bool(self._vol_install)

    def validate(self, device, devtype):
        if device in ["floppy", "cdrom"]:
            raise ValueError(_("Cannot create storage for %s device.") %
                               device)

        if self.is_managed():
            return self._vol_install.validate()

        if devtype == "block":
            raise ValueError(_("Local block device path '%s' must "
                               "exist.") % self.path)
        if not os.access(os.path.dirname(self.path), os.R_OK):
            raise ValueError("No read access to directory '%s'" %
                             os.path.dirname(self.path))
        if self._size is None:
            raise ValueError(_("size is required for non-existent disk "
                               "'%s'" % self.path))
        if not os.access(os.path.dirname(self.path), os.W_OK):
            raise ValueError(_("No write access to directory '%s'") %
                               os.path.dirname(self.path))

    def is_size_conflict(self):
        if self._vol_install:
            return self._vol_install.is_size_conflict()

        ret = False
        msg = None
        vfs = os.statvfs(os.path.dirname(self._path))
        avail = vfs[statvfs.F_FRSIZE] * vfs[statvfs.F_BAVAIL]
        need = long(self._size * 1024L * 1024L * 1024L)
        if need > avail:
            if self._sparse:
                msg = _("The filesystem will not have enough free space"
                        " to fully allocate the sparse file when the guest"
                        " is running.")
            else:
                ret = True
                msg = _("There is not enough free space to create the disk.")


            if msg:
                msg += (_(" %d M requested > %d M available") %
                        ((need / (1024 * 1024)), (avail / (1024 * 1024))))
        return (ret, msg)


    #############################
    # Storage creation routines #
    #############################

    def create(self, progresscb):
        if self.fake:
            raise RuntimeError("Storage creator is fake but creation "
                               "requested.")
        # If a clone_path is specified, but not vol_install.input_vol,
        # that means we are cloning unmanaged -> managed, so skip this
        if (self._vol_install and
            (not self._clone_path or self._vol_install.input_vol)):
            return self._vol_install.install(meter=progresscb)

        if self._clone_path:
            text = (_("Cloning %(srcfile)s") %
                    {'srcfile' : os.path.basename(self._clone_path)})
        else:
            text = _("Creating storage file %s") % os.path.basename(self._path)

        size_bytes = long(self._size * 1024L * 1024L * 1024L)
        progresscb.start(filename=self._path, size=long(size_bytes),
                         text=text)

        if self._clone_path:
            # Plain file clone
            self._clone_local(progresscb, size_bytes)
        else:
            # Plain file creation
            self._create_local_file(progresscb, size_bytes)

    def _create_local_file(self, progresscb, size_bytes):
        """
        Helper function which attempts to build self.path
        """
        fd = None
        path = self._path
        sparse = self._sparse

        try:
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_DSYNC)

                if sparse:
                    os.ftruncate(fd, size_bytes)
                else:
                    # 1 meg of nulls
                    mb = 1024 * 1024
                    buf = '\x00' * mb

                    left = size_bytes
                    while left > 0:
                        if left < mb:
                            buf = '\x00' * left
                        left = max(left - mb, 0)

                        os.write(fd, buf)
                        progresscb.update(size_bytes - left)
            except OSError, e:
                raise RuntimeError(_("Error creating diskimage %s: %s") %
                                   (path, str(e)))
        finally:
            if fd is not None:
                os.close(fd)
            progresscb.end(size_bytes)

    def _clone_local(self, meter, size_bytes):
        if self._clone_path == "/dev/null":
            # Not really sure why this check is here,
            # but keeping for compat
            logging.debug("Source dev was /dev/null. Skipping")
            return
        if self._clone_path == self._path:
            logging.debug("Source and destination are the same. Skipping.")
            return

        # if a destination file exists and sparse flg is True,
        # this priority takes a existing file.

        if (not os.path.exists(self._path) and self._sparse):
            clone_block_size = 4096
            sparse = True
            fd = None
            try:
                fd = os.open(self._path, os.O_WRONLY | os.O_CREAT)
                os.ftruncate(fd, size_bytes)
            finally:
                if fd:
                    os.close(fd)
        else:
            clone_block_size = 1024 * 1024 * 10
            sparse = False

        logging.debug("Local Cloning %s to %s, sparse=%s, block_size=%s",
                      self._clone_path, self._path, sparse, clone_block_size)

        zeros = '\0' * 4096

        src_fd, dst_fd = None, None
        try:
            try:
                src_fd = os.open(self._clone_path, os.O_RDONLY)
                dst_fd = os.open(self._path, os.O_WRONLY | os.O_CREAT)

                i = 0
                while 1:
                    l = os.read(src_fd, clone_block_size)
                    s = len(l)
                    if s == 0:
                        meter.end(size_bytes)
                        break
                    # check sequence of zeros
                    if sparse and zeros == l:
                        os.lseek(dst_fd, s, 1)
                    else:
                        b = os.write(dst_fd, l)
                        if s != b:
                            meter.end(i)
                            break
                    i += s
                    if i < size_bytes:
                        meter.update(i)
            except OSError, e:
                raise RuntimeError(_("Error cloning diskimage %s to %s: %s") %
                                   (self._clone_path, self._path, str(e)))
        finally:
            if src_fd is not None:
                os.close(src_fd)
            if dst_fd is not None:
                os.close(dst_fd)


class StorageBackend(_StorageBase):
    """
    Class that carries all the info about any existing storage that
    the disk references
    """
    def __init__(self, conn, path, vol_object, pool_object):
        _StorageBase.__init__(self)

        self._conn = conn
        self._vol_object = vol_object
        self._pool_object = pool_object
        self._path = path

        if self._vol_object is not None:
            self._pool_object = None
            self._path = None
        elif self._pool_object is not None:
            if self._path is None:
                raise ValueError("path must be specified is backend is "
                                 "pool object.")

        # Cached bits
        self._pool_xml = None
        self._vol_xml = None
        self._exists = None
        self._size = None
        self._dev_type = None


    ################
    # Internal API #
    ################

    def _get_pool_xml(self):
        if self._pool_xml is None:
            self._pool_xml = StoragePool(self._conn,
                parsexml=self._pool_object.XMLDesc(0))
        return self._pool_xml

    def _get_vol_xml(self):
        if self._vol_xml is None:
            self._vol_xml = StorageVolume(self._conn,
                parsexml=self._vol_object.XMLDesc(0))
        return self._vol_xml


    ##############
    # Public API #
    ##############

    def _get_path(self):
        if self._vol_object:
            return self._vol_object.path()
        return self._path
    path = property(_get_path)

    def get_vol_object(self):
        return self._vol_object

    def get_size(self):
        """
        Return size of existing storage
        """
        if self._size is None:
            ret = 0
            if self._vol_object:
                ret = self._get_vol_xml().capacity
            elif self._pool_object:
                ret = self._get_pool_xml().capacity
            elif self._path:
                ignore, ret = util.stat_disk(self.path)
            self._size = (float(ret) / 1024.0 / 1024.0 / 1024.0)
        return self._size

    def exists(self):
        if self._exists is None:
            if self.path is None:
                self._exists = True
            elif self._vol_object or self._pool_object:
                self._exists = True
            elif not self._conn.is_remote() and os.path.exists(self._path):
                self._exists = True
            else:
                self._exists = False
        return self._exists

    def get_dev_type(self):
        """
        Return disk 'type' value per storage settings
        """
        if self._dev_type is None:
            if self._vol_object:
                t = self._vol_object.info()[0]
                if t == libvirt.VIR_STORAGE_VOL_FILE:
                    self._dev_type = "file"
                elif t == libvirt.VIR_STORAGE_VOL_BLOCK:
                    self._dev_type = "block"
                else:
                    self._dev_type = "file"

            elif self._pool_object:
                self._dev_type = self._get_pool_xml().get_vm_disk_type()

            elif self._path:
                if os.path.isdir(self._path):
                    self._dev_type = "dir"
                elif util.stat_disk(self._path)[0]:
                    self._dev_type = "file"
                else:
                    self._dev_type = "block"

            if not self._dev_type:
                self._dev_type = "block"
        return self._dev_type

    def get_driver_type(self):
        if self._vol_object:
            return self._get_vol_xml().format
        return None

    def is_managed(self):
        return bool(self._vol_object or self._pool_object)
