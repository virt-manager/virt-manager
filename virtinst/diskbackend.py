#
# Storage lookup/creation helpers
#
# Copyright 2013 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
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
import re
import stat
import statvfs

import libvirt

from .storage import StoragePool, StorageVolume


def _lookup_pool_by_dirname(conn, path):
    """
    Try to find the parent pool for the passed path.
    If found, and the pool isn't running, attempt to start it up.

    return pool, or None if not found
    """
    pool = StoragePool.lookup_pool_by_path(conn, os.path.dirname(path))
    if not pool:
        return None

    # Ensure pool is running
    if pool.info()[0] != libvirt.VIR_STORAGE_POOL_RUNNING:
        pool.create(0)
    return pool


def _lookup_vol_by_path(conn, path):
    """
    Try to find a volume matching the full passed path. Call info() on
    it to ensure the volume wasn't removed behind libvirt's back
    """
    try:
        vol = conn.storageVolLookupByPath(path)
        vol.info()
        return vol, None
    except libvirt.libvirtError, e:
        if (hasattr(libvirt, "VIR_ERR_NO_STORAGE_VOL") and
            e.get_error_code() != libvirt.VIR_ERR_NO_STORAGE_VOL):
            raise
        return None, e


def _lookup_vol_by_basename(pool, path):
    """
    Try to lookup a volume for 'path' in parent 'pool' by it's filename.
    This sometimes works in cases where full volume path lookup doesn't,
    since not all libvirt storage backends implement path lookup.
    """
    name = os.path.basename(path)
    if name in pool.listVolumes():
        return pool.storageVolLookupByName(name)


def _stat_disk(path):
    """
    Returns the tuple (isreg, size)
    """
    if not os.path.exists(path):
        return True, 0

    mode = os.stat(path)[stat.ST_MODE]

    # os.path.getsize('/dev/..') can be zero on some platforms
    if stat.S_ISBLK(mode):
        try:
            fd = os.open(path, os.O_RDONLY)
            # os.SEEK_END is not present on all systems
            size = os.lseek(fd, 0, 2)
            os.close(fd)
        except:
            size = 0
        return False, size
    elif stat.S_ISREG(mode):
        return True, os.path.getsize(path)

    return True, 0


def check_if_path_managed(conn, path):
    """
    Try to lookup storage objects for the passed path.

    Returns (volume, parent pool). Only one is returned at a time.
    """
    vol, ignore = _lookup_vol_by_path(conn, path)
    if vol:
        return vol, vol.storagePoolLookupByVolume()

    pool = _lookup_pool_by_dirname(conn, path)
    if not pool:
        return None, None

    # We have the parent pool, but didn't find a volume on first lookup
    # attempt. Refresh the pool and try again, incase we were just out
    # of date.
    try:
        pool.refresh(0)
        vol, verr = _lookup_vol_by_path(conn, path)
        if verr:
            try:
                vol = _lookup_vol_by_basename(pool, path)
            except:
                pass
    except Exception, e:
        vol = None
        pool = None
        verr = str(e)

    if not vol and not pool and verr:
        raise ValueError(_("Cannot use storage %(path)s: %(err)s") %
            {'path' : path, 'err' : verr})

    return vol, pool


def _can_auto_manage(path):
    path = path or ""
    skip_prefixes = ["/dev", "/sys", "/proc"]

    if path_is_url(path):
        return False

    for prefix in skip_prefixes:
        if path.startswith(prefix + "/") or path == prefix:
            return False
    return True


def manage_path(conn, path):
    """
    If path is not managed, try to create a storage pool to probe the path
    """
    if not conn.check_support(conn.SUPPORT_CONN_STORAGE):
        return None, None
    if not path:
        return None, None

    if not path_is_url(path):
        path = os.path.abspath(path)
    vol, pool = check_if_path_managed(conn, path)
    if vol or pool or not _can_auto_manage(path):
        return vol, pool

    dirname = os.path.dirname(path)
    poolname = os.path.basename(dirname).replace(" ", "_")
    if not poolname:
        poolname = "dirpool"
    poolname = StoragePool.find_free_name(conn, poolname)
    logging.debug("Attempting to build pool=%s target=%s", poolname, dirname)

    poolxml = StoragePool(conn)
    poolxml.name = poolname
    poolxml.type = poolxml.TYPE_DIR
    poolxml.target_path = dirname
    pool = poolxml.install(build=False, create=True, autostart=True)
    conn.clear_cache(pools=True)

    vol = _lookup_vol_by_basename(pool, path)
    return vol, pool


def path_is_url(path):
    """
    Detect if path is a URL
    """
    if not path:
        return False
    return bool(re.match("[a-zA-Z]+(\+[a-zA-Z]+)?://.*", path))


def _get_dev_type(path, vol_xml, vol_object, pool_xml, remote):
    """
    Try to get device type for volume.
    """
    if vol_xml:
        if vol_xml.type:
            return vol_xml.type

        # If vol_xml.type is None the vol_xml.file_type can return only
        # these types: block, network or file
        if vol_xml.file_type == libvirt.VIR_STORAGE_VOL_BLOCK:
            return "block"
        elif vol_xml.file_type == libvirt.VIR_STORAGE_VOL_NETWORK:
            return "network"

    if vol_object:
        t = vol_object.info()[0]
        if t == StorageVolume.TYPE_FILE:
            return "file"
        elif t == StorageVolume.TYPE_BLOCK:
            return "block"
        elif t == StorageVolume.TYPE_NETWORK:
            return "network"

    if pool_xml:
        t = pool_xml.get_disk_type()
        if t == StorageVolume.TYPE_BLOCK:
            return "block"
        elif t == StorageVolume.TYPE_NETWORK:
            return "network"

    if path:
        if path_is_url(path):
            return "network"

        if not remote:
            if os.path.isdir(path):
                return "dir"
            elif _stat_disk(path)[0]:
                return "file"
            else:
                return "block"

    return "file"


##############################################
# Classes for tracking storage media details #
##############################################

class _StorageBase(object):
    """
    Storage base class, defining the API used by VirtualDisk
    """
    def __init__(self, conn):
        self._conn = conn
        self._parent_pool_xml = None

    def get_size(self):
        raise NotImplementedError()
    def get_dev_type(self):
        raise NotImplementedError()
    def get_driver_type(self):
        raise NotImplementedError()
    def get_vol_install(self):
        raise NotImplementedError()
    def get_vol_object(self):
        raise NotImplementedError()
    def get_parent_pool(self):
        raise NotImplementedError()
    def get_parent_pool_xml(self):
        if not self._parent_pool_xml and self.get_parent_pool():
            self._parent_pool_xml = StoragePool(self._conn,
                parsexml=self.get_parent_pool().XMLDesc(0))
        return self._parent_pool_xml
    def validate(self, disk):
        raise NotImplementedError()
    def get_path(self):
        raise NotImplementedError()

    # Storage creation routines
    def is_size_conflict(self):
        raise NotImplementedError()
    def create(self, progresscb):
        raise NotImplementedError()
    def will_create_storage(self):
        raise NotImplementedError()


class _StorageCreator(_StorageBase):
    """
    Base object for classes that will actually create storage on disk
    """
    def __init__(self, conn):
        _StorageBase.__init__(self, conn)

        self._pool = None
        self._vol_install = None
        self._path = None
        self._size = None
        self._dev_type = None


    ##############
    # Public API #
    ##############

    def create(self, progresscb):
        raise NotImplementedError()

    def get_path(self):
        if self._vol_install and not self._path:
            xmlobj = StoragePool(self._conn,
                parsexml=self._vol_install.pool.XMLDesc(0))
            if self.get_dev_type() == "network":
                self._path = self._vol_install.name
            else:
                sep = "/"
                if xmlobj.target_path == "" or xmlobj.target_path[-1] == '/':
                    sep = ""
                self._path = (xmlobj.target_path + sep +
                              self._vol_install.name)
        return self._path

    def get_vol_install(self):
        return self._vol_install
    def get_vol_xml(self):
        return self._vol_install

    def get_size(self):
        if self._size is None:
            self._size = (float(self._vol_install.capacity) /
                          1024.0 / 1024.0 / 1024.0)
        return self._size

    def get_dev_type(self):
        if not self._dev_type:
            self._dev_type = _get_dev_type(self._path, self._vol_install, None,
                                           self.get_parent_pool_xml(),
                                           self._conn.is_remote())
        return self._dev_type

    def get_driver_type(self):
        if self._vol_install:
            if self._vol_install.supports_property("format"):
                return self._vol_install.format
        return "raw"

    def validate(self, disk):
        if disk.device in ["floppy", "cdrom"]:
            raise ValueError(_("Cannot create storage for %s device.") %
                             disk.device)

        if self._vol_install:
            self._vol_install.validate()
        else:
            if self._size is None:
                raise ValueError(_("size is required for non-existent disk "
                                   "'%s'" % self.get_path()))

        err, msg = self.is_size_conflict()
        if err:
            raise ValueError(msg)
        if msg:
            logging.warn(msg)

    def will_create_storage(self):
        return True
    def get_vol_object(self):
        return None
    def get_parent_pool(self):
        if self._vol_install:
            return self._vol_install.pool
        return None
    def exists(self):
        return False


class CloneStorageCreator(_StorageCreator):
    """
    Handles manually copying local files for Cloner

    Many clone scenarios will use libvirt storage APIs, which will use
    the ManagedStorageCreator
    """
    def __init__(self, conn, output_path, input_path, size, sparse):
        _StorageCreator.__init__(self, conn)

        self._path = output_path
        self._output_path = output_path
        self._input_path = input_path
        self._size = size
        self._sparse = sparse

    def is_size_conflict(self):
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

    def create(self, progresscb):
        text = (_("Cloning %(srcfile)s") %
                {'srcfile' : os.path.basename(self._input_path)})

        size_bytes = long(self.get_size() * 1024L * 1024L * 1024L)
        progresscb.start(filename=self._output_path, size=long(size_bytes),
                         text=text)

        # Plain file clone
        self._clone_local(progresscb, size_bytes)

    def _clone_local(self, meter, size_bytes):
        if self._input_path == "/dev/null":
            # Not really sure why this check is here,
            # but keeping for compat
            logging.debug("Source dev was /dev/null. Skipping")
            return
        if self._input_path == self._output_path:
            logging.debug("Source and destination are the same. Skipping.")
            return

        # If a destination file exists and sparse flag is True,
        # this priority takes an existing file.

        if (not os.path.exists(self._output_path) and self._sparse):
            clone_block_size = 4096
            sparse = True
            fd = None
            try:
                fd = os.open(self._output_path, os.O_WRONLY | os.O_CREAT, 0640)
                os.ftruncate(fd, size_bytes)
            finally:
                if fd:
                    os.close(fd)
        else:
            clone_block_size = 1024 * 1024 * 10
            sparse = False

        logging.debug("Local Cloning %s to %s, sparse=%s, block_size=%s",
                      self._input_path, self._output_path,
                      sparse, clone_block_size)

        zeros = '\0' * 4096

        src_fd, dst_fd = None, None
        try:
            try:
                src_fd = os.open(self._input_path, os.O_RDONLY)
                dst_fd = os.open(self._output_path,
                                 os.O_WRONLY | os.O_CREAT, 0640)

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
                                (self._input_path, self._output_path, str(e)))
        finally:
            if src_fd is not None:
                os.close(src_fd)
            if dst_fd is not None:
                os.close(dst_fd)


class ManagedStorageCreator(_StorageCreator):
    """
    Handles storage creation via libvirt APIs. All the actual creation
    logic lives in StorageVolume, this is mostly about pulling out bits
    from that class and mapping them to VirtualDisk elements
    """
    def __init__(self, conn, vol_install):
        _StorageCreator.__init__(self, conn)

        self._pool = vol_install.pool
        self._vol_install = vol_install

    def create(self, progresscb):
        return self._vol_install.install(meter=progresscb)
    def is_size_conflict(self):
        return self._vol_install.is_size_conflict()


class StorageBackend(_StorageBase):
    """
    Class that carries all the info about any existing storage that
    the disk references
    """
    def __init__(self, conn, path, vol_object, parent_pool):
        _StorageBase.__init__(self, conn)

        self._vol_object = vol_object
        self._parent_pool = parent_pool
        self._path = path

        if self._vol_object is not None:
            self._path = None

        if self._vol_object and not self._parent_pool:
            raise RuntimeError(
                "programming error: parent_pool must be specified")

        # Cached bits
        self._vol_xml = None
        self._parent_pool_xml = None
        self._exists = None
        self._size = None
        self._dev_type = None


    ##############
    # Public API #
    ##############

    def get_path(self):
        if self._vol_object:
            return self.get_vol_xml().target_path
        return self._path

    def get_vol_object(self):
        return self._vol_object
    def get_vol_xml(self):
        if self._vol_xml is None:
            self._vol_xml = StorageVolume(self._conn,
                parsexml=self._vol_object.XMLDesc(0))
        return self._vol_xml

    def get_parent_pool(self):
        return self._parent_pool

    def get_size(self):
        """
        Return size of existing storage
        """
        if self._size is None:
            ret = 0
            if self._vol_object:
                ret = self.get_vol_xml().capacity
            elif self._path:
                ret = _stat_disk(self._path)[1]
            self._size = (float(ret) / 1024.0 / 1024.0 / 1024.0)
        return self._size

    def exists(self):
        if self._exists is None:
            if self._path is None:
                self._exists = True
            elif self._vol_object:
                self._exists = True
            elif (not self.get_dev_type() == "network" and
                  not self._conn.is_remote() and
                  os.path.exists(self._path)):
                self._exists = True
            elif self._parent_pool:
                self._exists = False
            elif self.get_dev_type() == "network":
                self._exists = True
            elif (self._conn.is_remote() and
                  not _can_auto_manage(self._path)):
                # This allows users to pass /dev/sdX and we don't try to
                # validate it exists on the remote connection, since
                # autopooling /dev is perilous. Libvirt will error if
                # the device doesn't exist.
                self._exists = True
            else:
                self._exists = False
        return self._exists

    def get_dev_type(self):
        """
        Return disk 'type' value per storage settings
        """
        if self._dev_type is None:
            vol_xml = None
            if self._vol_object:
                vol_xml = self.get_vol_xml()
            self._dev_type = _get_dev_type(self._path, vol_xml, self._vol_object,
                                           self.get_parent_pool_xml(),
                                           self._conn.is_remote())
        return self._dev_type

    def get_driver_type(self):
        if self._vol_object:
            ret = self.get_vol_xml().format
            if ret != "unknown":
                return ret
        return None

    def validate(self, disk):
        ignore = disk
        return
    def get_vol_install(self):
        return None
    def is_size_conflict(self):
        return (False, None)
    def will_create_storage(self):
        return False
    def create(self, progresscb):
        ignore = progresscb
        raise RuntimeError("programming error: %s can't create storage" %
            self.__class__.__name__)
