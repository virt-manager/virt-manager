#
# Storage lookup/creation helpers
#
# Copyright 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import re
import stat
import subprocess

import libvirt

from .logger import log
from .storage import StoragePool, StorageVolume
from . import xmlutil


def _lookup_vol_by_path(conn, path):
    """
    Try to find a volume matching the full passed path. Call info() on
    it to ensure the volume wasn't removed behind libvirt's back
    """
    try:
        vol = conn.storageVolLookupByPath(path)
        vol.info()
        return vol, None
    except libvirt.libvirtError as e:
        # test_urls trigger empty errors here, because python
        # garbage collection kicks in after the failure but before
        # we read the error code, and libvirt virStoragePoolFree
        # public entry point clears the cached error. So ignore
        # an empty error code
        if (e.get_error_code() and
            e.get_error_code() != libvirt.VIR_ERR_NO_STORAGE_VOL):
            raise  # pragma: no cover
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


def _get_block_size(path):  # pragma: no cover
    try:
        fd = os.open(path, os.O_RDONLY)
        # os.SEEK_END is not present on all systems
        size = os.lseek(fd, 0, 2)
        os.close(fd)
    except Exception:
        size = 0
    return size


def _get_size(path):
    if not os.path.exists(path):
        return 0
    if _stat_is_block(path):
        return _get_block_size(path)  # pragma: no cover
    return os.path.getsize(path)


def _stat_is_block(path):
    if not os.path.exists(path):
        return False
    return stat.S_ISBLK(os.stat(path)[stat.ST_MODE])


def _check_if_path_managed(conn, path):
    """
    Try to lookup storage objects for the passed path.

    Returns (volume, parent pool). Only one is returned at a time.
    """
    vol, ignore = _lookup_vol_by_path(conn, path)
    if vol:
        return vol, vol.storagePoolLookupByVolume()

    pool = StoragePool.lookup_pool_by_path(conn, os.path.dirname(path))
    if not pool:
        return None, None

    # We have the parent pool, but didn't find a volume on first lookup
    # attempt. Refresh the pool and try again, in case we were just out
    # of date or the pool was inactive.
    try:
        StoragePool.ensure_pool_is_running(pool, refresh=True)
        vol, verr = _lookup_vol_by_path(conn, path)
        if verr:
            try:
                vol = _lookup_vol_by_basename(pool, path)
            except Exception:  # pragma: no cover
                pass
    except Exception as e:  # pragma: no cover
        vol = None
        pool = None
        verr = str(e)

    if not vol and not pool and verr:  # pragma: no cover
        raise ValueError(_("Cannot use storage %(path)s: %(err)s") %
            {'path': path, 'err': verr})

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


def _get_storage_search_path(path):
    # If the passed path is one of our artificial rbd:// style
    # URIs, parse out the path component, since that is what is needed
    # for looking up storage volumes by target path
    from .uri import URI
    uriobj = URI(path)
    if uriobj.scheme == "rbd":
        return uriobj.path.strip("/")
    return path


def manage_path(conn, path):
    """
    If path is not managed, try to create a storage pool to probe the path
    """
    if not conn.support.conn_storage():
        return None, None, None  # pragma: no cover
    if not path:
        return None, None, None

    if not path_is_url(path) and not path_is_network_vol(conn, path):
        path = os.path.abspath(path)

    searchpath = _get_storage_search_path(path)
    vol, pool = _check_if_path_managed(conn, searchpath)
    if vol or pool or not _can_auto_manage(path):
        return path, vol, pool

    dirname = os.path.dirname(path)
    poolname = os.path.basename(dirname).replace(" ", "_")
    if not poolname:
        poolname = "dirpool"
    poolname = StoragePool.find_free_name(conn, poolname)
    log.debug("Attempting to build pool=%s target=%s", poolname, dirname)

    poolxml = StoragePool(conn)
    poolxml.name = poolname
    poolxml.type = poolxml.TYPE_DIR
    poolxml.target_path = dirname
    pool = poolxml.install(build=False, create=True, autostart=True)

    vol = _lookup_vol_by_basename(pool, path)
    return path, vol, pool


def path_is_url(path):
    """
    Detect if path is a URL
    """
    return bool(re.match(r"[a-zA-Z]+(\+[a-zA-Z]+)?://.*", path or ""))


def path_is_network_vol(conn, path):
    """
    Detect if path is a network volume such as rbd, gluster, etc
    """
    for volxml in conn.fetch_all_vols():
        if path and volxml.target_path == path:
            return volxml.type == "network"
    return False


def _get_dev_type(path, vol_xml, vol_object, pool_xml, remote):
    """
    Try to get device type for volume.
    """
    if vol_xml and vol_xml.type:
        return vol_xml.type

    if pool_xml:
        t = pool_xml.get_disk_type()
        if t == StorageVolume.TYPE_BLOCK:
            return "block"
        elif t == StorageVolume.TYPE_NETWORK:
            return "network"

    if vol_object:  # pragma: no cover
        # This path is hard to test, because test suite XML always has
        # the vol_xml.type set
        t = vol_object.info()[0]
        if t == StorageVolume.TYPE_FILE:
            return "file"
        elif t == StorageVolume.TYPE_BLOCK:
            return "block"
        elif t == StorageVolume.TYPE_NETWORK:
            return "network"

    if path:
        if path_is_url(path):
            return "network"

        if remote:
            if not _can_auto_manage(path):
                # Just a heurisitic, if this path is one of the ones
                # we don't try to auto-import, then consider it a
                # block device, because managing those correctly is difficult
                return "block"

        else:
            if os.path.isdir(path):
                return "dir"
            elif _stat_is_block(path):
                return "block"  # pragma: no cover

    return "file"


def path_definitely_exists(conn, path):
    """
    Return True if the path certainly exists, False if we are unsure.
    See DeviceDisk entry point for more details
    """
    if path is None:
        return False

    try:
        (vol, pool) = _check_if_path_managed(conn, path)
        ignore = pool
        if vol:
            return True

        if not conn.is_remote():
            return os.path.exists(path)
    except Exception:  # pragma: no cover
        pass

    return False


#########################
# ACL/path perm helpers #
#########################

SETFACL = "setfacl"


def _fix_perms_acl(dirname, username):
    cmd = [SETFACL, "--modify", "user:%s:x" % username, dirname]
    proc = subprocess.Popen(cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    out, err = proc.communicate()

    log.debug("Ran command '%s'", cmd)
    if out or err:
        log.debug("out=%s\nerr=%s", out, err)

    if proc.returncode != 0:
        raise ValueError(err)


def _fix_perms_chmod(dirname):
    log.debug("Setting +x on %s", dirname)
    mode = os.stat(dirname).st_mode
    newmode = mode | stat.S_IXOTH
    os.chmod(dirname, newmode)
    if os.stat(dirname).st_mode != newmode:
        # Trying to change perms on vfat at least doesn't work
        # but also doesn't seem to error. Try and detect that
        raise ValueError(  # pragma: no cover
                _("Permissions on '%s' did not stick") % dirname)


def set_dirs_searchable(dirlist, username):
    useacl = True
    errdict = {}
    for dirname in dirlist:
        if useacl:
            try:
                _fix_perms_acl(dirname, username)
                continue
            except Exception as e:
                log.debug("setfacl failed: %s", e)
                log.debug("trying chmod")
                useacl = False

        try:
            # If we reach here, ACL setting failed, try chmod
            _fix_perms_chmod(dirname)
        except Exception as e:  # pragma: no cover
            errdict[dirname] = str(e)

    return errdict


def _is_dir_searchable(dirname, uid, username):
    """
    Check if passed directory is searchable by uid
    """
    try:
        statinfo = os.stat(dirname)
    except OSError:  # pragma: no cover
        return False

    if uid == statinfo.st_uid:
        flag = stat.S_IXUSR
    elif uid == statinfo.st_gid:
        flag = stat.S_IXGRP  # pragma: no cover
    else:
        flag = stat.S_IXOTH

    if bool(statinfo.st_mode & flag):
        return True

    # Check POSIX ACL (since that is what we use to 'fix' access)
    cmd = ["getfacl", dirname]
    try:
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        out, err = proc.communicate()
    except OSError:  # pragma: no cover
        log.debug("Didn't find the getfacl command.")
        return False

    if proc.returncode != 0:  # pragma: no cover
        log.debug("Cmd '%s' failed: %s", cmd, err)
        return False

    pattern = "user:%s:..x" % username
    return bool(re.search(pattern.encode("utf-8", "replace"), out))


def is_path_searchable(path, uid, username):
    """
    Check each dir component of the passed path, see if they are
    searchable by the uid/username, and return a list of paths
    which aren't searchable
    """
    if os.path.isdir(path):
        dirname = path
        base = "-"
    else:
        dirname, base = os.path.split(path)

    fixlist = []
    while base:
        if not _is_dir_searchable(dirname, uid, username):
            fixlist.append(dirname)
        dirname, base = os.path.split(dirname)

    return fixlist


##############################################
# Classes for tracking storage media details #
##############################################

class _StorageBase(object):
    """
    Storage base class, defining the API used by DeviceDisk
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
    def validate(self):
        raise NotImplementedError()
    def get_path(self):
        raise NotImplementedError()
    def is_stub(self):
        return False

    # Storage creation routines
    def is_size_conflict(self):
        raise NotImplementedError()
    def will_create_storage(self):
        raise NotImplementedError()

    def create(self, meter):
        ignore = meter  # pragma: no cover
        raise xmlutil.DevError(
            "%s can't create storage" % self.__class__.__name__)


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

    def create(self, meter):
        raise NotImplementedError
    def validate(self):
        raise NotImplementedError
    def get_size(self):
        raise NotImplementedError

    def get_path(self):
        if self._vol_install and not self._path:
            xmlobj = StoragePool(self._conn,
                parsexml=self._vol_install.pool.XMLDesc(0))
            if self.get_dev_type() == "network":
                self._path = self._vol_install.name
            else:
                self._path = os.path.join(
                        xmlobj.target_path, self._vol_install.name)
        return self._path

    def get_vol_install(self):
        return self._vol_install
    def get_vol_xml(self):
        return self._vol_install

    def get_dev_type(self):
        if not self._dev_type:
            self._dev_type = _get_dev_type(self._path, self._vol_install, None,
                                           self.get_parent_pool_xml(),
                                           self._conn.is_remote())
        return self._dev_type

    def get_driver_type(self):
        if self._vol_install:
            if self._vol_install.supports_format():
                return self._vol_install.format
        return "raw"

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


class ManagedStorageCreator(_StorageCreator):
    """
    Handles storage creation via libvirt APIs. All the actual creation
    logic lives in StorageVolume, this is mostly about pulling out bits
    from that class and mapping them to DeviceDisk elements
    """
    def __init__(self, conn, vol_install):
        _StorageCreator.__init__(self, conn)

        self._pool = vol_install.pool
        self._vol_install = vol_install

    def create(self, meter):
        return self._vol_install.install(meter=meter)
    def is_size_conflict(self):
        return self._vol_install.is_size_conflict()
    def validate(self):
        return self._vol_install.validate()
    def get_size(self):
        return float(self._vol_install.capacity) / 1024.0 / 1024.0 / 1024.0


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

    def get_size(self):
        return self._size

    def is_size_conflict(self):
        ret = False
        msg = None
        if self.get_dev_type() == "block":
            avail = _get_size(self._path)  # pragma: no cover
        else:
            vfs = os.statvfs(os.path.dirname(os.path.abspath(self._path)))
            avail = vfs.f_frsize * vfs.f_bavail
        need = int(self._size) * 1024 * 1024 * 1024
        if need > avail:  # pragma: no cover
            if self._sparse:
                msg = _("The filesystem will not have enough free space"
                        " to fully allocate the sparse file when the guest"
                        " is running.")
            else:
                ret = True
                msg = _("There is not enough free space to create the disk.")


            if msg:
                msg += " "
                msg += (_("%(mem1)s M requested > %(mem2)s M available") %
                        {"mem1": (need // (1024 * 1024)),
                         "mem2": (avail // (1024 * 1024))})
        return (ret, msg)

    def validate(self):
        if self._size is None:  # pragma: no cover
            raise ValueError(_("size is required for non-existent disk "
                               "'%s'" % self.get_path()))

        err, msg = self.is_size_conflict()
        if err:
            raise ValueError(msg)  # pragma: no cover
        if msg:
            log.warning(msg)  # pragma: no cover

    def create(self, meter):
        text = (_("Cloning %(srcfile)s") %
                {'srcfile': os.path.basename(self._input_path)})

        size_bytes = int(self.get_size() * 1024 * 1024 * 1024)
        meter.start(text, size_bytes)

        # Plain file clone
        self._clone_local(meter, size_bytes)

    def _clone_local(self, meter, size_bytes):
        if self._input_path == "/dev/null":  # pragma: no cover
            # Not really sure why this check is here,
            # but keeping for compat
            log.debug("Source dev was /dev/null. Skipping")
            return
        if self._input_path == self._output_path:
            log.debug("Source and destination are the same. Skipping.")
            return

        # If a destination file exists and sparse flag is True,
        # this priority takes an existing file.

        if (not os.path.exists(self._output_path) and self._sparse):
            clone_block_size = 4096
            sparse = True
            fd = None
            try:
                fd = os.open(self._output_path, os.O_WRONLY | os.O_CREAT,
                             0o640)
                os.ftruncate(fd, size_bytes)
            finally:
                if fd:
                    os.close(fd)
        else:
            clone_block_size = 1024 * 1024 * 10
            sparse = False

        log.debug("Local Cloning %s to %s, sparse=%s, block_size=%s",
                      self._input_path, self._output_path,
                      sparse, clone_block_size)

        zeros = b'\0' * 4096

        src_fd, dst_fd = None, None
        try:
            try:
                src_fd = os.open(self._input_path, os.O_RDONLY)
                dst_fd = os.open(self._output_path,
                                 os.O_WRONLY | os.O_CREAT, 0o640)

                i = 0
                while 1:
                    l = os.read(src_fd, clone_block_size)
                    s = len(l)
                    if s == 0:
                        meter.end()
                        break
                    # check sequence of zeros
                    if sparse and zeros == l:
                        os.lseek(dst_fd, s, 1)
                    else:
                        b = os.write(dst_fd, l)
                        if s != b:  # pragma: no cover
                            meter.end()
                            break
                    i += s
                    if i < size_bytes:
                        meter.update(i)
            except OSError as e:  # pragma: no cover
                log.debug("Error while cloning", exc_info=True)
                msg = (_("Error cloning diskimage "
                         "%(inputpath)s to %(outputpath)s: %(error)s") %
                         {"inputpath": self._input_path,
                          "outputpath": self._output_path,
                          "error": str(e)})
                raise RuntimeError(msg) from None
        finally:
            if src_fd is not None:
                os.close(src_fd)
            if dst_fd is not None:
                os.close(dst_fd)


class StorageBackendStub(_StorageBase):
    """
    Class representing a storage path for a parsed XML disk, that we
    don't want to do slow resolving of unless requested
    """
    def __init__(self, conn, path, dev_type, driver_type):
        _StorageBase.__init__(self, conn)
        self._path = path
        self._dev_type = dev_type
        self._driver_type = driver_type


    def get_path(self):
        return self._path
    def get_vol_object(self):
        return None
    def get_vol_xml(self):
        return None
    def get_parent_pool(self):
        return None
    def get_size(self):
        return 0
    def exists(self):
        return True
    def get_dev_type(self):
        return self._dev_type
    def get_driver_type(self):
        return self._driver_type

    def validate(self):
        return
    def get_vol_install(self):
        return None
    def is_size_conflict(self):
        return (False, None)
    def is_stub(self):
        return True
    def will_create_storage(self):
        return False


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
            raise xmlutil.DevError(
                "parent_pool must be specified")

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
            self._vol_xml.pool = self._parent_pool
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
                ret = _get_size(self._path)
            self._size = (float(ret) / 1024.0 / 1024.0 / 1024.0)
        return self._size

    def exists(self):
        if self._exists is None:
            if self._vol_object:
                self._exists = True
            elif self._path is None:
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
            if self.get_vol_xml().supports_format():
                return self.get_vol_xml().format
            return "raw"
        return None

    def validate(self):
        return
    def get_vol_install(self):
        return None
    def is_size_conflict(self):
        return (False, None)
    def will_create_storage(self):
        return False
