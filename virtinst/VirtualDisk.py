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
import subprocess
import logging
import re

import urlgrabber.progress as progress

import virtinst
from virtinst import diskbackend
from virtinst import util
from virtinst.VirtualDevice import VirtualDevice
from virtinst.xmlbuilder import XMLProperty


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


def _distill_storage(conn, do_create, nomanaged,
                     path, vol_object, vol_install, clone_path, *args):
    """
    Validates and updates params when the backing storage is changed
    """
    pool = None
    path_is_pool = False
    storage_capable = conn.check_conn_support(conn.SUPPORT_CONN_STORAGE)

    if vol_object:
        pass
    elif not storage_capable:
        pass
    elif path and not nomanaged:
        path = os.path.abspath(path)
        vol_object, pool, path_is_pool = diskbackend.check_if_path_managed(
                                                            conn, path)

    creator = None
    backend = diskbackend.StorageBackend(conn, path, vol_object,
                                         path_is_pool and pool or None)
    if not do_create:
        return backend, None

    if backend.exists() and path is not None:
        if vol_install:
            raise ValueError("vol_install specified but %s exists." %
                             backend.path)
        elif not clone_path:
            return backend, None

    if path or vol_install or pool or clone_path:
        creator = diskbackend.StorageCreator(conn, path, pool,
                                             vol_install, clone_path, *args)
    return backend, creator


_TARGET_PROPS = ["file", "dev", "dir"]


class VirtualDisk(VirtualDevice):
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
                vol, ignore, path_is_pool = diskbackend.check_if_path_managed(
                                                            conn, path)
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
        names = []
        for vm in vms:
            found = False
            for disk in vm.get_devices("disk"):
                if disk.path != path:
                    continue
                if check_conflict:
                    if disk.shareable:
                        continue
                found = True
                break
            if found:
                names.append(vm.name)

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
        Return a volume instance from a pool name, vol name tuple
        """
        if not conn.check_conn_support(conn.SUPPORT_CONN_STORAGE):
            raise ValueError(_("Connection does not support storage lookup."))

        try:
            pool = conn.storagePoolLookupByName(name_tuple[0])
            return pool.storageVolLookupByName(name_tuple[1])
        except Exception, e:
            raise ValueError(_("Couldn't lookup volume object: %s" % str(e)))


    _XMLELEMENTORDER = ["driver", "source", "target"]
    _XMLPROPORDER = ["target", "bus"]

    def __init__(self, conn, parsexml=None, parsexmlnode=None):
        VirtualDevice.__init__(self, conn, parsexml, parsexmlnode)

        self._DEFAULT_SENTINEL = -1234
        self._device = self.DEVICE_DISK
        self._type = self._DEFAULT_SENTINEL
        self._driverName = self._DEFAULT_SENTINEL
        self._driverType = self._DEFAULT_SENTINEL

        self._storage_backend = diskbackend.StorageBackend(self.conn,
                                                           None, None, None)
        self._storage_creator = None

        self.nomanaged = False
        self.transient = False


    ##########################
    # Complex XML properties #
    ##########################

    def _get_path(self):
        if self._storage_creator:
            return self._storage_creator.path
        return self._storage_backend.path
    def _set_path(self, val):
        if self._storage_creator:
            raise ValueError("Can't change disk path if storage creation info "
                             "has been set.")
        self._change_backend(val, None)
        self._refresh_backend_settings()
    def _xml_get_xpath(self):
        xpath = None
        ret = "./source/@file"
        for prop in _TARGET_PROPS:
            xpath = "./source/@" + prop
            if self._xml_ctx.xpathEval(xpath):
                ret = xpath
                break
        return ret
    def _xml_set_xpath(self):
        return "./source/@" + self.disk_type_to_target_prop(self.type)
    path = XMLProperty(_get_path, _set_path, name="disk path",
                         xml_get_xpath=_xml_get_xpath,
                         xml_set_xpath=_xml_set_xpath,
                         clear_first=["./source/@" + target for target in
                                      _TARGET_PROPS])


    def get_type(self):
        if self._type != self._DEFAULT_SENTINEL:
            return self._type
        return self._get_default_type()
    def set_type(self, val):
        self._type = val
    type = XMLProperty(get_type, set_type,
                         xpath="./@type")

    def get_device(self):
        return self._device
    def set_device(self, val):
        self._device = val
    device = XMLProperty(get_device, set_device,
                           xpath="./@device")

    def get_driver_name(self):
        if self._driverName != self._DEFAULT_SENTINEL:
            return self._driverName
        return self._get_default_driver()[0]
    def set_driver_name(self, val):
        self._driverName = val
    driver_name = XMLProperty(get_driver_name, set_driver_name,
                                xpath="./driver/@name")

    def get_driver_type(self):
        if self._driverType != self._DEFAULT_SENTINEL:
            return self._driverType
        return self._get_default_driver()[1]
    def set_driver_type(self, val):
        self._driverType = val
    driver_type = XMLProperty(get_driver_type, set_driver_type,
                                xpath="./driver/@type")

    #########################
    # Simple XML properties #
    #########################

    bus = XMLProperty(xpath="./target/@bus")
    target = XMLProperty(xpath="./target/@dev")

    read_only = XMLProperty(xpath="./readonly", is_bool=True)
    shareable = XMLProperty(xpath="./shareable", is_bool=True)
    driver_cache = XMLProperty(xpath="./driver/@cache")
    driver_io = XMLProperty(xpath="./driver/@io")

    error_policy = XMLProperty(xpath="./driver/@error_policy")
    serial = XMLProperty(xpath="./serial")

    iotune_rbs = XMLProperty(xpath="./iotune/read_bytes_sec", is_int=True)
    iotune_ris = XMLProperty(xpath="./iotune/read_iops_sec", is_int=True)
    iotune_tbs = XMLProperty(xpath="./iotune/total_bytes_sec", is_int=True)
    iotune_tis = XMLProperty(xpath="./iotune/total_iops_sec", is_int=True)
    iotune_wbs = XMLProperty(xpath="./iotune/write_bytes_sec", is_int=True)
    iotune_wis = XMLProperty(xpath="./iotune/write_iops_sec", is_int=True)


    #############################
    # Public property-esque API #
    #############################

    def get_sparse(self):
        if self._storage_creator:
            return self._storage_creator.get_sparse()
        return None

    def get_vol_object(self):
        return self._storage_backend.get_vol_object()
    def get_vol_install(self):
        if not self._storage_creator:
            return None
        return self._storage_creator.get_vol_install()

    def get_size(self):
        if self._storage_creator:
            return self._storage_creator.get_size()
        return self._storage_backend.get_size()


    #################################
    # Validation assistance methods #
    #################################

    def set_create_storage(self, size=None, sparse=True,
                           fmt=None, vol_install=None, clone_path=None,
                           fake=False):
        """
        Function that sets storage creation parameters. If this isn't
        called, we assume that no storage creation is taking place and
        will error accordingly.

        @size is in gigs
        @fake: If true, make like we are creating storage but fail
            if we ever asked to do so.
        """
        if self._is_parse():
            raise ValueError("Cannot create storage for a parsed disk.")
        path = self.path

        # Validate clone_path
        if clone_path is not None:
            clone_path = os.path.abspath(clone_path)

            try:
                # If this disk isn't managed, make sure we only perform
                # non-managed lookup
                d = VirtualDisk(self.conn)
                d.path = clone_path
                d.nomanaged = not self.__managed_storage()
                d.set_create_storage(fake=True)
                d.validate()
            except Exception, e:
                raise ValueError(_("Error validating clone path: %s") % e)

        if fake and size is None:
            size = .000001

        ignore, creator = _distill_storage(
            self.conn, True, self.nomanaged, path, None,
            vol_install, clone_path,
            size, sparse, fmt)

        self._storage_creator = creator
        if self._storage_creator:
            self._storage_creator.fake = bool(fake)
            self._refresh_backend_settings()
        else:
            if (vol_install or clone_path):
                raise RuntimeError("Need storage creation but it "
                                   "didn't happen.")
            if fmt and self.driver_name == self.DRIVER_QEMU:
                self.driver_type = fmt


    def can_be_empty(self):
        return (self.device == self.DEVICE_FLOPPY or
                self.device == self.DEVICE_CDROM)

    def _change_backend(self, path, vol_object):
        backend, ignore = _distill_storage(
                                self.conn, False, self.nomanaged,
                                path, vol_object, None, None)
        self._storage_backend = backend

    def _refresh_backend_settings(self):
        self.refresh_xml_prop("type")
        self.refresh_xml_prop("driver_name")
        self.refresh_xml_prop("driver_type")


    def _get_default_type(self):
        if self._storage_creator:
            return self._storage_creator.get_dev_type()
        return self._storage_backend.get_dev_type()

    def _get_default_driver(self):
        """
        Set driverName and driverType from passed parameters

        Where possible, we want to force driverName = "raw" if installing
        a QEMU VM. Without telling QEMU to expect a raw file, the emulator
        is forced to autodetect, which has security implications:

        http://lists.gnu.org/archive/html/qemu-devel/2008-04/msg00675.html
        """
        drvname = self._driverName
        if drvname == self._DEFAULT_SENTINEL:
            drvname = None
        drvtype = self._driverType
        if drvtype == self._DEFAULT_SENTINEL:
            drvtype = None

        if self.conn.is_qemu() and not drvname:
            drvname = self.DRIVER_QEMU

        if drvname == self.DRIVER_QEMU:
            if self._storage_creator:
                drvtype = self._storage_creator.get_driver_type()
            else:
                drvtype = self._storage_backend.get_driver_type()
            drvtype = _qemu_sanitize_drvtype(self.type, drvtype)

        return drvname or None, drvtype or None

    def __managed_storage(self):
        """
        Return bool representing if managed storage parameters have
        been explicitly specified or filled in
        """
        if self._storage_creator:
            return self._storage_creator.is_managed()
        return self._storage_backend.is_managed()

    def creating_storage(self):
        """
        Return True if the user requested us to create a device
        """
        return bool(self._storage_creator)


    def validate(self):
        """
        function to validate all the complex interaction between the various
        disk parameters.
        """
        # No storage specified for a removable device type (CDROM, floppy)
        if self.path is None:
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

        # If not creating the storage, our job is easy
        if not create_media:
            if not self._storage_backend.exists():
                raise ValueError(
                    _("Must specify storage creation parameters for "
                      "non-existent path '%s'.") % self.path)

            # Make sure we have access to the local path
            if not managed_storage:
                if (os.path.isdir(self.path) and
                    not self.device == self.DEVICE_FLOPPY):
                    raise ValueError(_("The path '%s' must be a file or a "
                                       "device, not a directory") % self.path)

            return True

        self._storage_creator.validate(self.device, self.type)

        # Applicable for managed or local storage
        ret = self.is_size_conflict()
        if ret[0]:
            raise ValueError(ret[1])
        elif ret[1]:
            logging.warn(ret[1])


    def setup(self, meter=None):
        """
        Build storage (if required)

        If storage doesn't exist (a non-existent file 'path', or 'vol_install'
        was specified), we create it.

        @param meter: Progress meter to report file creation on
        @type meter: instanceof urlgrabber.BaseMeter
        """
        if not meter:
            meter = progress.BaseMeter()
        if not self._storage_creator:
            return

        volobj = self._storage_creator.create(meter)
        self._storage_creator = None
        if volobj:
            self._change_backend(None, volobj)

    def set_defaults(self):
        if self.device == self.DEVICE_CDROM:
            self.read_only = True

        if not virtinst.enable_rhel_defaults:
            return

        # Enable cache=none for non-CDROM devs
        if (self.conn.is_qemu() and
            not self.driver_cache and
            self.device != self.DEVICE_CDROM):
            self.driver_cache = self.CACHE_MODE_NONE

        # Enable AIO native for block devices
        if (self.conn.is_qemu() and
            not self.driver_io and
            self.device == self.DEVICE_DISK and
            self.type == self.TYPE_BLOCK):
            self.driver_io = self.IO_MODE_NATIVE


    def _get_xml_config(self):
        typeattr = self.type
        if self.type == VirtualDisk.TYPE_BLOCK:
            typeattr = 'dev'
        path = self.path
        if path:
            path = util.xml_escape(path)

        ret = "    <disk type='%s' device='%s'>\n" % (self.type, self.device)

        drvxml = ""
        if self.driver_type is not None:
            drvxml += " type='%s'" % self.driver_type
        if self.driver_name is not None:
            drvxml = (" name='%s'" % self.driver_name) + drvxml
        if drvxml:
            ret += "      <driver%s/>\n" % drvxml

        if path is not None:
            ret += "      <source %s='%s'/>\n" % (typeattr, path)

        addr = self.indent(self.address.get_xml_config(), 6)
        if addr:
            ret += addr
        ret += "    </disk>"
        ret = self._add_parse_bits(ret)

        # Remove <driver> block if path is None. Might not be strictly
        # requires but it's what we've always done
        if not self.path and "<driver" in ret:
            ret = "\n".join([l for l in ret.splitlines()
                             if "<driver" not in l])
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
        if not self._storage_creator:
            return (False, None)
        return self._storage_creator.is_size_conflict()

    def is_conflict_disk(self, conn):
        """
        check if specified storage is in use by any other VMs on passed
        connection.

        @return: list of colliding VM names
        @rtype: C{list}
        """
        if not self.path:
            return False
        if not conn:
            conn = self.conn

        check_conflict = self.shareable
        ret = self.path_in_use_by(conn, self.path,
                                  check_conflict=check_conflict)
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
