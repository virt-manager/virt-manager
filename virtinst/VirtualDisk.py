#
# Classes for building disk device xml
#
# Copyright 2006-2008, 2012-2013  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
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

import os
import stat
import pwd
import statvfs
import subprocess
import logging
import re

import urlgrabber.progress as progress
import libvirt

import virtinst

from virtinst import util
from virtinst import Storage
from virtinst.VirtualDevice import VirtualDevice
from virtinst.XMLBuilderDomain import _xml_property


def _qemu_sanitize_drvtype(phystype, fmt, manual_format=False):
    """
    Sanitize libvirt storage volume format to a valid qemu driver type
    """
    raw_list = ["iso"]

    if phystype == VirtualDisk.TYPE_BLOCK:
        if not fmt:
            return VirtualDisk.DRIVER_QEMU_RAW
        if fmt and not manual_format:
            return VirtualDisk.DRIVER_QEMU_RAW

    if fmt in raw_list:
        return VirtualDisk.DRIVER_QEMU_RAW

    return fmt


def _name_uid(user):
    """
    Return UID for string username
    """
    pwdinfo = pwd.getpwnam(user)
    return pwdinfo[2]


def _is_dir_searchable(uid, username, path):
    """
    Check if passed directory is searchable by uid
    """
    try:
        statinfo = os.stat(path)
    except OSError:
        return False

    if uid == statinfo.st_uid:
        flag = stat.S_IXUSR
    elif uid == statinfo.st_gid:
        flag = stat.S_IXGRP
    else:
        flag = stat.S_IXOTH

    if bool(statinfo.st_mode & flag):
        return True

    # Check POSIX ACL (since that is what we use to 'fix' access)
    cmd = ["getfacl", path]
    try:
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        out, err = proc.communicate()
    except OSError:
        logging.debug("Didn't find the getfacl command.")
        return False

    if proc.returncode != 0:
        logging.debug("Cmd '%s' failed: %s", cmd, err)
        return False

    return bool(re.search("user:%s:..x" % username, out))


def _check_if_pool_source(conn, path):
    """
    If passed path is a host disk device like /dev/sda, want to let the user
    use it
    """
    if not conn.check_conn_support(conn.SUPPORT_CONN_STORAGE):
        return None

    def check_pool(poolname, path):
        pool = conn.storagePoolLookupByName(poolname)
        xml = pool.XMLDesc(0)

        for element in ["dir", "device", "adapter"]:
            xml_path = util.get_xml_path(xml,
                                          "/pool/source/%s/@path" % element)
            if xml_path == path:
                return pool

    running_list = conn.listStoragePools()
    inactive_list = conn.listDefinedStoragePools()
    for plist in [running_list, inactive_list]:
        for name in plist:
            p = check_pool(name, path)
            if p:
                return p
    return None


def _check_if_path_managed(conn, path):
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
        pool = util.lookup_pool_by_path(conn, os.path.dirname(path))

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


def _build_vol_install(conn, path, pool, size, sparse):
    # Path wasn't a volume. See if base of path is a managed
    # pool, and if so, setup a StorageVolume object
    if size is None:
        raise ValueError(_("Size must be specified for non "
                           "existent volume path '%s'" % path))

    logging.debug("Path '%s' is target for pool '%s'. "
                  "Creating volume '%s'.",
                  os.path.dirname(path), pool.name(),
                  os.path.basename(path))

    volclass = Storage.StorageVolume.get_volume_for_pool(pool_object=pool)
    cap = (size * 1024 * 1024 * 1024)
    if sparse:
        alloc = 0
    else:
        alloc = cap

    volinst = volclass(conn, name=os.path.basename(path),
                       capacity=cap, allocation=alloc, pool=pool)
    return volinst


class VirtualDisk(VirtualDevice):
    """
    Builds a libvirt domain disk xml description

    The VirtualDisk class is used for building libvirt domain xml descriptions
    for disk devices. If creating a disk object from an existing local block
    device or file, a path is all that should be required. If you want to
    create a local file, a size also needs to be specified.

    The remote case is a bit more complex. The options are:
        1. A libvirt virStorageVol instance (passed as 'volObject') for an
           existing storage volume.
        2. A virtinst L{StorageVolume} instance for creating a volume (passed
           as 'volInstall').
        3. An active connection ('conn') and a path to a storage volume on
           that connection.
        4. An active connection and a tuple of the form ("poolname",
           "volumename")
        5. An active connection and a path. The base of the path must
           point to the target path for an active pool.

    For cases 3 and 4, the lookup will be performed, and 'vol_object'
    will be set to the returned virStorageVol. For the last case, 'volInstall'
    will be populated for a StorageVolume instance. All the above cases also
    work on a local connection as well, the only difference being that
    option 3 won't necessarily error out if the volume isn't found.

    __init__ and setting all properties performs lots of validation,
    and will throw ValueError's if problems are found.
    """
    # pylint: disable=W0622
    # Redefining built-in 'type', but it matches the XML so keep it

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_DISK

    DRIVER_FILE = "file"
    DRIVER_PHY = "phy"
    DRIVER_TAP = "tap"
    DRIVER_QEMU = "qemu"
    driver_names = [DRIVER_FILE, DRIVER_PHY, DRIVER_TAP, DRIVER_QEMU]

    DRIVER_QEMU_RAW = "raw"
    # No list here, since there are many other valid values

    DRIVER_TAP_RAW = "aio"
    DRIVER_TAP_QCOW = "qcow"
    DRIVER_TAP_VMDK = "vmdk"
    DRIVER_TAP_VDISK = "vdisk"
    driver_types = [DRIVER_TAP_RAW, DRIVER_TAP_QCOW,
        DRIVER_TAP_VMDK, DRIVER_TAP_VDISK]

    CACHE_MODE_NONE = "none"
    CACHE_MODE_WRITETHROUGH = "writethrough"
    CACHE_MODE_WRITEBACK = "writeback"
    cache_types = [CACHE_MODE_NONE, CACHE_MODE_WRITETHROUGH,
        CACHE_MODE_WRITEBACK]

    DEVICE_DISK = "disk"
    DEVICE_LUN = "lun"
    DEVICE_CDROM = "cdrom"
    DEVICE_FLOPPY = "floppy"
    devices = [DEVICE_DISK, DEVICE_LUN, DEVICE_CDROM, DEVICE_FLOPPY]

    TYPE_FILE = "file"
    TYPE_BLOCK = "block"
    TYPE_DIR = "dir"
    types = [TYPE_FILE, TYPE_BLOCK, TYPE_DIR]

    _target_props = ["file", "dev", "dir"]

    IO_MODE_NATIVE = "native"
    IO_MODE_THREADS = "threads"
    io_modes = [IO_MODE_NATIVE, IO_MODE_THREADS]

    @staticmethod
    def disk_type_to_xen_driver_name(disk_type):
        """
        Convert a value of VirtualDisk.type to it's associated Xen
        <driver name=/> property
        """
        if disk_type == VirtualDisk.TYPE_BLOCK:
            return "phy"
        elif disk_type == VirtualDisk.TYPE_FILE:
            return "file"
        return "file"

    @staticmethod
    def disk_type_to_target_prop(disk_type):
        """
        Convert a value of VirtualDisk.type to it's associated XML
        target property name
        """
        if disk_type == VirtualDisk.TYPE_FILE:
            return "file"
        elif disk_type == VirtualDisk.TYPE_BLOCK:
            return "dev"
        elif disk_type == VirtualDisk.TYPE_DIR:
            return "dir"
        return "file"

    error_policies = ["ignore", "stop", "enospace"]

    @staticmethod
    def path_exists(conn, path):
        """
        Check if path exists. If we can't determine, return False
        """
        try:
            vol = None
            path_is_pool = False
            try:
                vol, ignore, path_is_pool = _check_if_path_managed(conn, path)
            except:
                pass

            if vol or path_is_pool:
                return True

            if not conn.is_remote():
                return os.path.exists(path)
        except:
            pass

        return False

    @staticmethod
    def check_path_search_for_user(conn, path, username):
        """
        Check if the passed user has search permissions for all the
        directories in the disk path.

        @return: List of the directories the user cannot search, or empty list
        @rtype : C{list}
        """
        if path is None:
            return []
        if conn.is_remote():
            return []

        try:
            uid = _name_uid(username)
        except Exception, e:
            logging.debug("Error looking up username: %s", str(e))
            return []

        fixlist = []

        if os.path.isdir(path):
            dirname = path
            base = "-"
        else:
            dirname, base = os.path.split(path)

        while base:
            if not _is_dir_searchable(uid, username, dirname):
                fixlist.append(dirname)

            dirname, base = os.path.split(dirname)

        return fixlist

    @staticmethod
    def fix_path_search_for_user(conn, path, username):
        """
        Try to fix any permission problems found by check_path_search_for_user

        @return: Return a dictionary of entries {broken path : error msg}
        @rtype : C{dict}
        """
        def fix_perms(dirname, useacl=True):
            if useacl:
                cmd = ["setfacl", "--modify", "user:%s:x" % username, dirname]
                proc = subprocess.Popen(cmd,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
                out, err = proc.communicate()

                logging.debug("Ran command '%s'", cmd)
                if out or err:
                    logging.debug("out=%s\nerr=%s", out, err)

                if proc.returncode != 0:
                    raise ValueError(err)
            else:
                logging.debug("Setting +x on %s", dirname)
                mode = os.stat(dirname).st_mode
                newmode = mode | stat.S_IXOTH
                os.chmod(dirname, newmode)
                if os.stat(dirname).st_mode != newmode:
                    # Trying to change perms on vfat at least doesn't work
                    # but also doesn't seem to error. Try and detect that
                    raise ValueError(_("Permissions on '%s' did not stick") %
                                     dirname)

        fixlist = VirtualDisk.check_path_search_for_user(conn, path, username)
        if not fixlist:
            return []

        fixlist.reverse()
        errdict = {}

        useacl = True
        for dirname in fixlist:
            try:
                try:
                    fix_perms(dirname, useacl)
                except:
                    # If acl fails, fall back to chmod and retry
                    if not useacl:
                        raise
                    useacl = False

                    logging.debug("setfacl failed, trying old fashioned way")
                    fix_perms(dirname, useacl)
            except Exception, e:
                errdict[dirname] = str(e)

        return errdict

    @staticmethod
    def path_in_use_by(conn, path, check_conflict=False):
        """
        Return a list of VM names that are using the passed path.

        @param conn: virConnect to check VMs
        @param path: Path to check for
        @param check_conflict: Only return names that are truly conflicting:
                               this will omit guests that are using the disk
                               with the 'shareable' flag, and possible other
                               heuristics
        """
        if not path:
            return

        vms = conn.fetch_all_guests()

        def count_cb(ctx):
            c = 0

            template = "count(/domain/devices/disk["
            if check_conflict:
                template += "not(shareable) and "
            template += "source/@%s='%s'])"

            for dtype in VirtualDisk._target_props:
                xpath = template % (dtype, util.xml_escape(path))
                c += ctx.xpathEval(xpath)

            return c

        names = []
        for vm in vms:
            xml = vm.XMLDesc(0)
            tmpcount = util.get_xml_path(xml, func=count_cb)
            if tmpcount:
                names.append(vm.name())

        return names

    @staticmethod
    def stat_local_path(path):
        """
        Return tuple (storage type, storage size) for the passed path on
        the local machine. This is a best effort attempt.

        @return: tuple of
                 (True if regular file, False otherwise, default is True,
                 max size of storage, default is 0)
        """
        try:
            return util.stat_disk(path)
        except:
            return (True, 0)

    @staticmethod
    def lookup_vol_object(conn, name_tuple):
        """
        Return a volume instance from parameters that are passed
        to disks volName init parameter
        """
        if (type(name_tuple) is not tuple or
            len(name_tuple) != 2 or
            (type(name_tuple[0]) is not type(name_tuple[1]) is not str)):
            raise ValueError(_("volName must be a tuple of the form "
                               "('poolname', 'volname')"))

        if not conn:
            raise ValueError(_("'volName' requires a passed connection."))
        if not conn.check_conn_support(conn.SUPPORT_CONN_STORAGE):
            raise ValueError(_("Connection does not support storage lookup."))

        try:
            pool = conn.storagePoolLookupByName(name_tuple[0])
            return pool.storageVolLookupByName(name_tuple[1])
        except Exception, e:
            raise ValueError(_("Couldn't lookup volume object: %s" % str(e)))

    def __init__(self, conn, path=None, size=None, transient=False, type=None,
                 device=None, driverName=None, driverType=None,
                 readOnly=False, sparse=True, volObject=None,
                 volInstall=None, volName=None, bus=None, shareable=False,
                 driverCache=None, format=None,
                 validate=True, parsexml=None, parsexmlnode=None,
                 driverIO=None, sizebytes=None, nomanaged=False):
        """
        @param path: filesystem path to the disk image.
        @type path: C{str}
        @param size: size of local file to create in gigabytes
        @type size: C{int} or C{long} or C{float}
        @param transient: whether to keep disk around after guest install
        @type transient: C{bool}
        @param type: disk media type (file, block, ...)
        @type type: C{str}
        @param device: Emulated device type (disk, cdrom, floppy, ...)
        @type device: member of devices
        @param driverName: name of driver
        @type driverName: member of driver_names
        @param driverType: type of driver
        @type driverType: member of driver_types
        @param readOnly: Whether emulated disk is read only
        @type readOnly: C{bool}
        @param sparse: Create file as a sparse file
        @type sparse: C{bool}
        @param conn: Connection disk is being installed on
        @type conn: libvirt.virConnect
        @param volObject: libvirt storage volume object to use
        @type volObject: libvirt.virStorageVol
        @param volInstall: StorageVolume instance to build for new storage
        @type volInstall: L{StorageVolume}
        @param volName: Existing StorageVolume lookup information,
                        (parent pool name, volume name)
        @type volName: C{tuple} of (C{str}, C{str})
        @param bus: Emulated bus type (ide, scsi, virtio, ...)
        @type bus: C{str}
        @param shareable: If disk can be shared among VMs
        @type shareable: C{bool}
        @param driverCache: Disk cache mode (none, writethrough, writeback)
        @type driverCache: member of cache_types
        @param format: Storage volume format to use when creating storage
        @type format: C{str}
        @param validate: Whether to validate passed parameters against the
                         local system. Omitting this may cause issues, be
                         warned!
        @type validate: C{bool}
        @param sizebytes: Optionally specify storage size in bytes. Takes
                          precedence over size if specified.
        @type sizebytes: C{int}
        """

        VirtualDevice.__init__(self, conn=conn,
                               parsexml=parsexml, parsexmlnode=parsexmlnode)

        self._path = None
        self._size = None
        self._type = None
        self._device = None
        self._sparse = None
        self._readOnly = None
        self._vol_object = None
        self._pool_object = None
        self._vol_install = None
        self._bus = None
        self._shareable = None
        self._driver_cache = None
        self._clone_path = None
        self._format = None
        self._driverName = driverName
        self._driverType = driverType
        self._driver_io = None
        self._error_policy = None
        self._serial = None
        self._target = None
        self._iotune_rbs = None
        self._iotune_ris = None
        self._iotune_tbs = None
        self._iotune_tis = None
        self._iotune_wbs = None
        self._iotune_wis = None
        self._validate = validate
        self._nomanaged = nomanaged

        # XXX: No property methods for these
        self.transient = transient

        if volName and not volObject:
            volObject = self.lookup_vol_object(conn, volName)

        if sizebytes is not None:
            size = (float(sizebytes) / float(1024 ** 3))

        if self._is_parse():
            self._validate = False
            return

        self.set_read_only(readOnly, validate=False)
        self.set_sparse(sparse, validate=False)
        self.set_type(type, validate=False)
        self.set_device(device or self.DEVICE_DISK, validate=False)
        self._set_path(path, validate=False)
        self._set_size(size, validate=False)
        self._set_vol_object(volObject, validate=False)
        self._set_vol_install(volInstall, validate=False)
        self._set_bus(bus, validate=False)
        self._set_shareable(shareable, validate=False)
        self._set_driver_cache(driverCache, validate=False)
        self._set_format(format, validate=False)
        self._set_driver_io(driverIO, validate=False)

        self.__change_storage(self.path,
                              self.vol_object,
                              self.vol_install)
        self.__validate_params()


    #
    # Parameters for specifying the backing storage
    #

    def _get_path(self):
        retpath = self._path
        if self.vol_object:
            retpath = self.vol_object.path()
        elif self.vol_install:
            retpath = (util.get_xml_path(self.vol_install.pool.XMLDesc(0),
                                         "/pool/target/path") + "/" +
                       self.vol_install.name)

        return retpath
    def _set_path(self, val, validate=True):
        if val is not None:
            self._check_str(val, "path")
            val = os.path.abspath(val)

        if validate:
            self.__change_storage(path=val)
        self.__validate_wrapper("_path", val, validate, self.path)
    def _xml_get_xpath(self):
        xpath = None
        for prop in self._target_props:
            xpath = "./source/@" + prop
            if self._xml_ctx.xpathEval(xpath):
                return xpath
        return "./source/@file"
    def _xml_set_xpath(self):
        return "./source/@" + self.disk_type_to_target_prop(self.type)
    path = _xml_property(_get_path, _set_path,
                         xml_get_xpath=_xml_get_xpath,
                         xml_set_xpath=_xml_set_xpath,)


    def _get_vol_object(self):
        return self._vol_object
    def _set_vol_object(self, val, validate=True):
        if val is not None and not isinstance(val, libvirt.virStorageVol):
            raise ValueError(_("vol_object must be a virStorageVol instance"))

        if validate:
            self.__change_storage(vol_object=val)
        self.__validate_wrapper("_vol_object", val, validate, self.vol_object)
    vol_object = property(_get_vol_object, _set_vol_object)

    def _get_vol_install(self):
        return self._vol_install
    def _set_vol_install(self, val, validate=True):
        if val is not None and not isinstance(val, Storage.StorageVolume):
            raise ValueError(_("vol_install must be a StorageVolume "
                               " instance."))

        if validate:
            self.__change_storage(vol_install=val)
        self.__validate_wrapper("_vol_install", val, validate, self.vol_install)
    vol_install = property(_get_vol_install, _set_vol_install)

    #
    # Other properties
    #
    def _get_clone_path(self):
        return self._clone_path
    def _set_clone_path(self, val, validate=True):
        if val is not None:
            self._check_str(val, "path")
            val = os.path.abspath(val)

            try:
                VirtualDisk(self.conn, path=val, nomanaged=True)
            except Exception, e:
                raise ValueError(_("Error validating clone path: %s") % e)
        self.__validate_wrapper("_clone_path", val, validate, self.clone_path)
    clone_path = property(_get_clone_path, _set_clone_path)

    def _get_size(self):
        retsize = self.__existing_storage_size()
        if retsize is None:
            if self.vol_install:
                retsize = self.vol_install.capacity / 1024.0 / 1024.0 / 1024.0
            else:
                retsize = self._size

        return retsize
    def _set_size(self, val, validate=True):
        if val is not None:
            if type(val) not in [int, float, long] or val < 0:
                raise ValueError(_("'size' must be a number greater than 0."))

        self.__validate_wrapper("_size", val, validate, self.size)
    size = property(_get_size, _set_size)

    def get_type(self):
        if self._type:
            return self._type
        return self.__existing_storage_dev_type()
    def set_type(self, val, validate=True):
        if val is not None:
            self._check_str(val, "type")
            if val not in self.types:
                raise ValueError(_("Unknown storage type '%s'" % val))
        self.__validate_wrapper("_type", val, validate, self.type)
    type = _xml_property(get_type, set_type,
                         xpath="./@type")

    def get_device(self):
        return self._device
    def set_device(self, val, validate=True):
        self._check_str(val, "device")
        if val not in self.devices:
            raise ValueError(_("Unknown device type '%s'" % val))

        if val == self._device:
            return

        if self._is_parse():
            self.bus = None
            self.target = None
        self.__validate_wrapper("_device", val, validate, self.device)
    device = _xml_property(get_device, set_device,
                           xpath="./@device")

    def get_driver_name(self):
        retname = self._driverName
        if not retname:
            retname, ignore = self.__get_default_driver()
        return retname
    def set_driver_name(self, val, validate=True):
        ignore = validate
        self._driverName = val
    driver_name = _xml_property(get_driver_name, set_driver_name,
                                xpath="./driver/@name")

    def get_driver_type(self):
        rettype = self._driverType
        if not rettype:
            ignore, rettype = self.__get_default_driver()
        return rettype
    def set_driver_type(self, val, validate=True):
        ignore = validate
        self._driverType = val
    driver_type = _xml_property(get_driver_type, set_driver_type,
                                xpath="./driver/@type")

    def get_sparse(self):
        return self._sparse
    def set_sparse(self, val, validate=True):
        self._check_bool(val, "sparse")
        self.__validate_wrapper("_sparse", val, validate, self.sparse)
    sparse = property(get_sparse, set_sparse)

    def get_read_only(self):
        return self._readOnly
    def set_read_only(self, val, validate=True):
        self._check_bool(val, "read_only")
        self.__validate_wrapper("_readOnly", val, validate, self.read_only)
    read_only = _xml_property(get_read_only, set_read_only,
                              xpath="./readonly", is_bool=True)

    def _get_bus(self):
        return self._bus
    def _set_bus(self, val, validate=True):
        if val is not None:
            self._check_str(val, "bus")
        self.__validate_wrapper("_bus", val, validate, self.bus)
    bus = _xml_property(_get_bus, _set_bus,
                        xpath="./target/@bus")
    def _get_target(self):
        return self._target
    def _set_target(self, val, validate=True):
        ignore = validate
        if val is not None:
            self._check_str(val, "target")
        self._target = val
    target = _xml_property(_get_target, _set_target,
                           xpath="./target/@dev")

    def _get_shareable(self):
        return self._shareable
    def _set_shareable(self, val, validate=True):
        self._check_bool(val, "shareable")
        self.__validate_wrapper("_shareable", val, validate, self.shareable)
    shareable = _xml_property(_get_shareable, _set_shareable,
                              xpath="./shareable", is_bool=True)

    def _get_driver_cache(self):
        return self._driver_cache
    def _set_driver_cache(self, val, validate=True):
        if val is not None:
            self._check_str(val, "cache")
            if val not in self.cache_types:
                raise ValueError(_("Unknown cache mode '%s'" % val))
        self.__validate_wrapper("_driver_cache", val, validate,
                                self.driver_cache)
    driver_cache = _xml_property(_get_driver_cache, _set_driver_cache,
                                 xpath="./driver/@cache")


    def _get_driver_io(self):
        return self._driver_io
    def _set_driver_io(self, val, validate=True):
        if val is not None:
            self._check_str(val, "driver_io")
            if val not in self.io_modes:
                raise ValueError(_("Unknown io mode '%s'" % val))
        self.__validate_wrapper("_driver_io", val, validate,
                                self.driver_io)
    driver_io = _xml_property(_get_driver_io, _set_driver_io,
                              xpath="./driver/@io")

    def _get_error_policy(self):
        return self._error_policy
    def _set_error_policy(self, val, validate=True):
        if val is not None:
            self._check_str(val, "error_policy")
            if val not in self.error_policies:
                raise ValueError(_("Unknown error policy '%s'" % val))
        self.__validate_wrapper("_error_policy", val, validate,
                                self.error_policy)
    error_policy = _xml_property(_get_error_policy, _set_error_policy,
                                 xpath="./driver/@error_policy")

    def _get_serial(self):
        return self._serial
    def _set_serial(self, val, validate=True):
        if val is not None:
            self._check_str(val, "serial")
        self.__validate_wrapper("_serial", val, validate,
                                self.serial)
    serial = _xml_property(_get_serial, _set_serial,
                           xpath="./serial")

    def _get_iotune_rbs(self):
        return self._iotune_rbs
    def _set_iotune_rbs(self, val):
        if not isinstance(val, int) or val < 0:
            raise ValueError(_("IOTune read bytes per second value must be an "
                               "integer"))
        self._iotune_rbs = val
    iotune_rbs = _xml_property(_get_iotune_rbs,
                               _set_iotune_rbs,
                               xpath="./iotune/read_bytes_sec",
                               get_converter=lambda s, x: int(x or 0),
                               set_converter=lambda s, x: int(x))

    def _get_iotune_ris(self):
        return self._iotune_ris
    def _set_iotune_ris(self, val):
        if not isinstance(val, int) or val < 0:
            raise ValueError(_("IOTune read iops per second value must be an "
                               "integer"))
        self._iotune_ris = val
    iotune_ris = _xml_property(_get_iotune_ris,
                               _set_iotune_ris,
                               xpath="./iotune/read_iops_sec",
                               get_converter=lambda s, x: int(x or 0),
                               set_converter=lambda s, x: int(x))

    def _get_iotune_tbs(self):
        return self._iotune_tbs
    def _set_iotune_tbs(self, val):
        if not isinstance(val, int) or val < 0:
            raise ValueError(_("IOTune total bytes per second value must be an "
                               "integer"))
        self._iotune_tbs = val
    iotune_tbs = _xml_property(_get_iotune_tbs,
                               _set_iotune_tbs,
                               xpath="./iotune/total_bytes_sec",
                               get_converter=lambda s, x: int(x or 0),
                               set_converter=lambda s, x: int(x))

    def _get_iotune_tis(self):
        return self._iotune_tis
    def _set_iotune_tis(self, val):
        if not isinstance(val, int) or val < 0:
            raise ValueError(_("IOTune total iops per second value must be an "
                               "integer"))
        self._iotune_tis = val
    iotune_tis = _xml_property(_get_iotune_tis,
                               _set_iotune_tis,
                               xpath="./iotune/total_iops_sec",
                               get_converter=lambda s, x: int(x or 0),
                               set_converter=lambda s, x: int(x))

    def _get_iotune_wbs(self):
        return self._iotune_wbs
    def _set_iotune_wbs(self, val):
        if not isinstance(val, int) or val < 0:
            raise ValueError(_("IOTune write bytes per second value must be an "
                               "integer"))
        self._iotune_wbs = val
    iotune_wbs = _xml_property(_get_iotune_wbs,
                               _set_iotune_wbs,
                               xpath="./iotune/write_bytes_sec",
                               get_converter=lambda s, x: int(x or 0),
                               set_converter=lambda s, x: int(x))

    def _get_iotune_wis(self):
        return self._iotune_wis
    def _set_iotune_wis(self, val):
        if not isinstance(val, int) or val < 0:
            raise ValueError(_("IOTune write iops per second value must be an "
                               "integer"))
        self._iotune_wis = val
    iotune_wis = _xml_property(_get_iotune_wis,
                               _set_iotune_wis,
                               xpath="./iotune/write_iops_sec",
                               get_converter=lambda s, x: int(x or 0),
                               set_converter=lambda s, x: int(x))

    def _get_format(self):
        return self._format
    def _set_format(self, val, validate=True):
        if val is not None:
            self._check_str(val, "format")
        self.__validate_wrapper("_format", val, validate, self.format)
    format = property(_get_format, _set_format)

    # Validation assistance methods

    # Initializes attribute if it hasn't been done, then validates args.
    # If validation fails, reset attribute to original value and raise error
    def __validate_wrapper(self, varname, newval, validate, origval):
        orig = origval
        setattr(self, varname, newval)

        if validate:
            try:
                self.__validate_params()
            except:
                setattr(self, varname, orig)
                raise

    def can_be_empty(self):
        return (self.device == self.DEVICE_FLOPPY or
                self.device == self.DEVICE_CDROM)

    def __change_storage(self, path=None, vol_object=None, vol_install=None):
        """
        Validates and updates params when the backing storage is changed
        """
        pool = None
        storage_capable = self.conn.check_conn_support(
                                            self.conn.SUPPORT_CONN_STORAGE)

        # Try to lookup self.path storage objects
        if vol_object or vol_install:
            pass
        elif not storage_capable:
            pass
        elif path:
            vol_object, pool, path_is_pool = _check_if_path_managed(self.conn,
                                                                    path)
            if (pool and
                not vol_object and
                not path_is_pool and
                not self._is_parse()):
                vol_install = _build_vol_install(self.conn,
                                                 path, pool,
                                                 self.size,
                                                 self.sparse)

            if not path_is_pool:
                pool = None

        # Finally, set the relevant params
        self._set_path(path, validate=False)
        self._set_vol_object(vol_object, validate=False)
        self._set_vol_install(vol_install, validate=False)
        self._pool_object = pool

        # XXX: Hack, we shouldn't have to conditionalize for parsing
        if self._is_parse():
            self.type = self.get_type()
            self.driver_name = self.get_driver_name()
            self.driver_type = self.get_driver_type()


    def __set_format(self):
        if not self.format:
            return

        if not self.creating_storage():
            return

        if self.vol_install:
            if not hasattr(self.vol_install, "format"):
                raise ValueError(_("Storage type does not support format "
                                   "parameter."))
            if self.vol_install.format != self.format:
                self.vol_install.format = self.format

        elif self.format != "raw":
            raise RuntimeError(_("Format cannot be specified for "
                                 "unmanaged storage."))

    def __existing_storage_size(self):
        """
        Return size of existing storage
        """
        if self.creating_storage():
            return

        if self.vol_object:
            newsize = util.get_xml_path(self.vol_object.XMLDesc(0),
                                         "/volume/capacity")
            try:
                newsize = float(newsize) / 1024.0 / 1024.0 / 1024.0
            except:
                newsize = 0
        elif self._pool_object:
            newsize = util.get_xml_path(self.vol_object.XMLDesc(0),
                                         "/pool/capacity")
            try:
                newsize = float(newsize) / 1024.0 / 1024.0 / 1024.0
            except:
                newsize = 0
        elif self.path is None:
            newsize = 0
        else:
            ignore, newsize = util.stat_disk(self.path)
            newsize = newsize / 1024.0 / 1024.0 / 1024.0

        return newsize

    def __existing_storage_dev_type(self):
        """
        Detect disk 'type' () from passed storage parameters
        """

        dtype = None
        if self.vol_object:
            # vol info is [vol type (file or block), capacity, allocation]
            t = self.vol_object.info()[0]
            if t == libvirt.VIR_STORAGE_VOL_FILE:
                dtype = self.TYPE_FILE
            elif t == libvirt.VIR_STORAGE_VOL_BLOCK:
                dtype = self.TYPE_BLOCK
            else:
                dtype = self.TYPE_FILE

        elif self.vol_install:
            if self.vol_install.file_type == libvirt.VIR_STORAGE_VOL_FILE:
                dtype = self.TYPE_FILE
            else:
                dtype = self.TYPE_BLOCK
        elif self._pool_object:
            xml = self._pool_object.XMLDesc(0)
            for source, source_type in [("dir", self.TYPE_DIR),
                                        ("device", self.TYPE_BLOCK),
                                        ("adapter", self.TYPE_BLOCK)]:
                if util.get_xml_path(xml, "/pool/source/%s/@dev" % source):
                    dtype = source_type
                    break

        elif self.path:
            if os.path.isdir(self.path):
                dtype = self.TYPE_DIR
            elif util.stat_disk(self.path)[0]:
                dtype = self.TYPE_FILE
            else:
                dtype = self.TYPE_BLOCK

        if not dtype:
            dtype = self._type or self.TYPE_BLOCK

        return dtype

    def __get_default_driver(self):
        """
        Set driverName and driverType from passed parameters

        Where possible, we want to force driverName = "raw" if installing
        a QEMU VM. Without telling QEMU to expect a raw file, the emulator
        is forced to autodetect, which has security implications:

        http://lists.gnu.org/archive/html/qemu-devel/2008-04/msg00675.html
        """
        drvname = self._driverName
        drvtype = self._driverType

        if self.conn.is_qemu() and not drvname:
            drvname = self.DRIVER_QEMU

        if self.format:
            if drvname == self.DRIVER_QEMU:
                drvtype = _qemu_sanitize_drvtype(self.type, self.format,
                                                 manual_format=True)

        elif self.vol_object:
            fmt = util.get_xml_path(self.vol_object.XMLDesc(0),
                                     "/volume/target/format/@type")
            if drvname == self.DRIVER_QEMU:
                drvtype = _qemu_sanitize_drvtype(self.type, fmt)

        elif self.vol_install:
            if drvname == self.DRIVER_QEMU:
                if hasattr(self.vol_install, "format"):
                    drvtype = _qemu_sanitize_drvtype(self.type,
                                                     self.vol_install.format)

        elif self.creating_storage():
            if drvname == self.DRIVER_QEMU:
                drvtype = self.DRIVER_QEMU_RAW

        return drvname or None, drvtype or None

    def __managed_storage(self):
        """
        Return bool representing if managed storage parameters have
        been explicitly specified or filled in
        """
        if self._nomanaged:
            return False
        return bool(self.vol_object is not None or
                    self.vol_install is not None or
                    self._pool_object is not None)

    def creating_storage(self):
        """
        Return True if the user requested us to create a device
        """
        if self.__no_storage():
            return False

        if self.__managed_storage():
            if self.vol_object or self._pool_object:
                return False
            return True

        if (not self.conn.is_remote() and
            self.path and
            os.path.exists(self.path)):
            return False

        return True

    def __no_storage(self):
        """
        Return True if no path or storage was specified
        """
        if self.__managed_storage():
            return False
        if self.path:
            return False
        return True


    def __validate_params(self):
        """
        function to validate all the complex interaction between the various
        disk parameters.
        """
        if not self._validate:
            return

        # No storage specified for a removable device type (CDROM, floppy)
        if self.__no_storage():
            if not self.can_be_empty():
                raise ValueError(_("Device type '%s' requires a path") %
                                 self.device)

            return True

        storage_capable = self.conn.check_conn_support(
                                        self.conn.SUPPORT_CONN_STORAGE)

        if self.conn.is_remote():
            if not storage_capable:
                raise ValueError(_("Connection doesn't support remote "
                                   "storage."))
            if not self.__managed_storage():
                raise ValueError(_("Must specify libvirt managed storage "
                                   "if on a remote connection"))

        # The main distinctions from this point forward:
        # - Are we doing storage API operations or local media checks?
        # - Do we need to create the storage?

        managed_storage = self.__managed_storage()
        create_media = self.creating_storage()

        self.__set_format()

        # If not creating the storage, our job is easy
        if not create_media:
            # Make sure we have access to the local path
            if not managed_storage:
                if (os.path.isdir(self.path) and
                    not self.device == self.DEVICE_FLOPPY):
                    raise ValueError(_("The path '%s' must be a file or a "
                                       "device, not a directory") % self.path)

            return True


        if (self.device == self.DEVICE_FLOPPY or
            self.device == self.DEVICE_CDROM):
            raise ValueError(_("Cannot create storage for %s device.") %
                               self.device)

        if not managed_storage:
            if self.type is self.TYPE_BLOCK:
                raise ValueError(_("Local block device path '%s' must "
                                   "exist.") % self.path)

            # Path doesn't exist: make sure we have write access to dir
            if not os.access(os.path.dirname(self.path), os.R_OK):
                raise ValueError("No read access to directory '%s'" %
                                 os.path.dirname(self.path))
            if self.size is None:
                raise ValueError(_("size is required for non-existent disk "
                                   "'%s'" % self.path))
            if not os.access(os.path.dirname(self.path), os.W_OK):
                raise ValueError(_("No write access to directory '%s'") %
                                   os.path.dirname(self.path))

        # Applicable for managed or local storage
        ret = self.is_size_conflict()
        if ret[0]:
            raise ValueError(ret[1])
        elif ret[1]:
            logging.warn(ret[1])

    # Storage creation routines
    def _do_create_storage(self, progresscb):
        # If a clone_path is specified, but not vol_install.input_vol,
        # that means we are cloning unmanaged -> managed, so skip this
        if (self.vol_install and
            (not self.clone_path or self.vol_install.input_vol)):
            self._set_vol_object(self.vol_install.install(meter=progresscb),
                                 validate=False)
            return

        if self.clone_path:
            text = (_("Cloning %(srcfile)s") %
                    {'srcfile' : os.path.basename(self.clone_path)})
        else:
            text = _("Creating storage file %s") % os.path.basename(self.path)

        size_bytes = long(self.size * 1024L * 1024L * 1024L)
        progresscb.start(filename=self.path, size=long(size_bytes),
                         text=text)

        if self.clone_path:
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
        path = self.path
        sparse = self.sparse

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

        # if a destination file exists and sparse flg is True,
        # this priority takes a existing file.
        if (not os.path.exists(self.path) and self.sparse):
            clone_block_size = 4096
            sparse = True
            fd = None
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT)
                os.ftruncate(fd, size_bytes)
            finally:
                if fd:
                    os.close(fd)
        else:
            clone_block_size = 1024 * 1024 * 10
            sparse = False

        logging.debug("Local Cloning %s to %s, sparse=%s, block_size=%s",
                      self.clone_path, self.path, sparse, clone_block_size)

        zeros = '\0' * 4096

        src_fd, dst_fd = None, None
        try:
            try:
                src_fd = os.open(self.clone_path, os.O_RDONLY)
                dst_fd = os.open(self.path, os.O_WRONLY | os.O_CREAT)

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
                                       (self.clone_path, self.path, str(e)))
        finally:
            if src_fd is not None:
                os.close(src_fd)
            if dst_fd is not None:
                os.close(dst_fd)

    def setup(self, meter=None):
        """
        Build storage (if required)

        If storage doesn't exist (a non-existent file 'path', or 'vol_install'
        was specified), we create it.

        @param conn: Optional connection to use if self.conn not specified
        @param meter: Progress meter to report file creation on
        @type meter: instanceof urlgrabber.BaseMeter
        """
        if not meter:
            meter = progress.BaseMeter()

        if self.creating_storage() or self.clone_path:
            self._do_create_storage(meter)

    def _get_xml_config(self, disknode=None):
        """
        @param disknode: device name in host (xvda, hdb, etc.). self.target
                         takes precedence.
        @type disknode: C{str}
        """
        # pylint: disable=W0221
        # Argument number differs from overridden method

        typeattr = self.type
        if self.type == VirtualDisk.TYPE_BLOCK:
            typeattr = 'dev'

        if self.target:
            disknode = self.target
        if not disknode:
            raise ValueError(_("'disknode' or self.target must be set!"))

        path = None
        if self.vol_object:
            path = self.vol_object.path()
        elif self.path:
            path = self.path
        if path:
            path = util.xml_escape(path)

        ret = "    <disk type='%s' device='%s'>\n" % (self.type, self.device)

        cache = self.driver_cache
        iomode = self.driver_io

        if virtinst.enable_rhel6_defaults:
            # Enable cache=none for non-CDROM devs
            if (self.conn.is_qemu() and
                not cache and
                self.device != self.DEVICE_CDROM):
                cache = self.CACHE_MODE_NONE

            # Enable AIO native for block devices
            if (self.conn.is_qemu() and
                not iomode and
                self.device == self.DEVICE_DISK and
                self.type == self.TYPE_BLOCK):
                iomode = self.IO_MODE_NATIVE

        if path:
            drvxml = ""
            if not self.driver_type is None:
                drvxml += " type='%s'" % self.driver_type
            if not cache is None:
                drvxml += " cache='%s'" % cache
            if not self.error_policy is None:
                drvxml += " error_policy='%s'" % self.error_policy
            if not iomode is None:
                drvxml += " io='%s'" % iomode

            if drvxml and self.driver_name is None:
                if self.conn.is_qemu():
                    self.driver_name = "qemu"

            if not self.driver_name is None:
                drvxml = (" name='%s'" % self.driver_name) + drvxml

            if drvxml:
                ret += "      <driver%s/>\n" % drvxml

        if path is not None:
            ret += "      <source %s='%s'/>\n" % (typeattr, path)

        bus_xml = ""
        if self.bus is not None:
            bus_xml = " bus='%s'" % self.bus
        ret += "      <target dev='%s'%s/>\n" % (disknode, bus_xml)

        ro = self.read_only

        if self.device == self.DEVICE_CDROM:
            ro = True
        if self.shareable:
            ret += "      <shareable/>\n"
        if ro:
            ret += "      <readonly/>\n"

        if self.serial:
            ret += ("      <serial>%s</serial>\n" %
                    util.xml_escape(self.serial))

        if (self.iotune_rbs or self.iotune_ris or
            self.iotune_tbs or self.iotune_tis or
            self.iotune_wbs or self.iotune_wis):
            ret += "      <iotune>\n"
            if self.iotune_rbs:
                ret += "        <read_bytes_sec>%s</read_bytes_sec>\n" % (self.iotune_rbs)
            if self.iotune_ris:
                ret += "        <read_iops_sec>%s</read_iops_sec>\n" % (self.iotune_ris)
            if self.iotune_tbs:
                ret += "        <total_bytes_sec>%s</total_bytes_sec>\n" % (self.iotune_tbs)
            if self.iotune_tis:
                ret += "        <total_iops_sec>%s</total_iops_sec>\n" % (self.iotune_tis)
            if self.iotune_wbs:
                ret += "        <write_bytes_sec>%s</write_bytes_sec>\n" % (self.iotune_wbs)
            if self.iotune_wis:
                ret += "        <write_iops_sec>%s</write_iops_sec>\n" % (self.iotune_wis)
            ret += "      </iotune>\n"

        addr = self.indent(self.address.get_xml_config(), 6)
        if addr:
            ret += addr
        ret += "    </disk>"
        return ret

    def is_size_conflict(self):
        """
        reports if disk size conflicts with available space

        returns a two element tuple:
            1. first element is True if fatal conflict occurs
            2. second element is a string description of the conflict or None
        Non fatal conflicts (sparse disk exceeds available space) will
        return (False, "description of collision")
        """

        if self.vol_install:
            return self.vol_install.is_size_conflict()

        if not self.creating_storage():
            return (False, None)

        ret = False
        msg = None
        vfs = os.statvfs(os.path.dirname(self.path))
        avail = vfs[statvfs.F_FRSIZE] * vfs[statvfs.F_BAVAIL]
        need = long(self.size * 1024L * 1024L * 1024L)
        if need > avail:
            if self.sparse:
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

    def is_conflict_disk(self, conn, return_names=False):
        """
        check if specified storage is in use by any other VMs on passed
        connection.

        @param conn: connection to check for collisions on
        @type conn: libvirt.virConnect
        @param return_names: Whether or not to return a list of VM names using
                             the same storage (default = False)
        @type return_names: C{bool}

        @return: True if a collision, False otherwise (list of names if
                 return_names passed)
        @rtype: C{bool}
        """
        if self.vol_object:
            path = self.vol_object.path()
        else:
            path = self.path

        if not path:
            return False

        if not conn:
            conn = self.conn

        check_conflict = self.shareable
        names = self.path_in_use_by(conn, path,
                                    check_conflict=check_conflict)

        ret = False
        if names:
            ret = True
        if return_names:
            ret = names

        return ret


    def get_target_prefix(self):
        """
        Returns the suggested disk target prefix (hd, xvd, sd ...) for the
        disk.
        @returns: str prefix, or None if no reasonable guess can be made
        """
        # The upper limits here aren't necessarilly 1024, but let the HV
        # error as appropriate.
        if self.bus == "virtio":
            return ("vd", 1024)
        elif self.bus in ["sata", "scsi", "usb"]:
            return ("sd", 1024)
        elif self.bus == "xen":
            return ("xvd", 1024)
        elif self.bus == "fdc" or self.device == self.DEVICE_FLOPPY:
            return ("fd", 2)
        elif self.bus == "ide":
            return ("hd", 4)
        else:
            return (None, None)

    def generate_target(self, skip_targets):
        """
        Generate target device ('hda', 'sdb', etc..) for disk, excluding
        any targets in 'skip_targets'. Sets self.target, and returns the
        generated value

        @param skip_targets: list of targets to exclude
        @type skip_targets: C{list}
        @raise ValueError: can't determine target type, no targets available
        @returns generated target
        @rtype C{str}
        """

        # Only use these targets if there are no other options
        except_targets = ["hdc"]

        prefix, maxnode = self.get_target_prefix()
        if prefix is None:
            raise ValueError(_("Cannot determine device bus/type."))

        # Special case: IDE cdrom should prefer hdc for back compat
        if self.device == self.DEVICE_CDROM and prefix == "hd":
            if "hdc" not in skip_targets:
                self.target = "hdc"
                return self.target

        if maxnode > (26 * 26 * 26):
            raise RuntimeError("maxnode value is too high")

        # Regular scanning
        for i in range(1, maxnode + 1):
            gen_t = prefix

            tmp = i
            digits = []
            for factor in range(0, 3):
                amt = (tmp % (26 ** (factor + 1))) / (26 ** factor)
                if amt == 0 and tmp >= (26 ** (factor + 1)):
                    amt = 26
                tmp -= amt
                digits.insert(0, amt)

            seen_valid = False
            for digit in digits:
                if digit == 0:
                    if not seen_valid:
                        continue
                    digit = 1

                seen_valid = True
                gen_t += "%c" % (ord('a') + digit - 1)

            if gen_t in except_targets:
                continue
            if gen_t not in skip_targets:
                self.target = gen_t
                return self.target

        # Check except_targets for any options
        for t in except_targets:
            if t.startswith(prefix) and t not in skip_targets:
                self.target = t
                return self.target
        raise ValueError(_("No more space for disks of type '%s'" % prefix))
