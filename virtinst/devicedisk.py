#
# Classes for building disk device xml
#
# Copyright 2006-2008, 2012-2014 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
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

import os
import stat
import pwd
import subprocess
import logging
import re

import urlgrabber.progress as progress

from . import diskbackend
from . import util
from .device import VirtualDevice
from .xmlbuilder import XMLProperty


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


def _make_storage_backend(conn, nomanaged, path, vol_object):
    parent_pool = None
    if (not vol_object and path and not nomanaged):
        (vol_object, parent_pool) = diskbackend.manage_path(conn, path)

    backend = diskbackend.StorageBackend(conn, path, vol_object, parent_pool)
    return backend


def _make_storage_creator(conn, backend, vol_install, clone_path,
                          *creator_args):
    parent_pool = backend.get_parent_pool()
    if backend.exists(auto_check=False) and backend.path is not None:
        if not clone_path:
            return

    if backend.path and not (vol_install or parent_pool or clone_path):
        raise RuntimeError(_("Don't know how to create storage for "
            "path '%s'. Use libvirt APIs to manage the parent directory "
            "as a pool first.") % backend.path)

    if not (backend.path or vol_install or parent_pool or clone_path):
        return

    return diskbackend.StorageCreator(conn, backend.path,
        parent_pool, vol_install, clone_path, *creator_args)


class VirtualDisk(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_DISK

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
    DRIVER_TAP_QED = "qed"
    driver_types = [DRIVER_TAP_RAW, DRIVER_TAP_QCOW,
        DRIVER_TAP_VMDK, DRIVER_TAP_VDISK, DRIVER_TAP_QED]

    CACHE_MODE_NONE = "none"
    CACHE_MODE_WRITETHROUGH = "writethrough"
    CACHE_MODE_WRITEBACK = "writeback"
    CACHE_MODE_DIRECTSYNC = "directsync"
    CACHE_MODE_UNSAFE = "unsafe"
    cache_types = [CACHE_MODE_NONE, CACHE_MODE_WRITETHROUGH,
        CACHE_MODE_WRITEBACK, CACHE_MODE_DIRECTSYNC, CACHE_MODE_UNSAFE]

    DISCARD_MODE_IGNORE = "ignore"
    DISCARD_MODE_UNMAP = "unmap"
    discard_types = [DISCARD_MODE_IGNORE, DISCARD_MODE_UNMAP]

    DEVICE_DISK = "disk"
    DEVICE_LUN = "lun"
    DEVICE_CDROM = "cdrom"
    DEVICE_FLOPPY = "floppy"
    devices = [DEVICE_DISK, DEVICE_LUN, DEVICE_CDROM, DEVICE_FLOPPY]

    TYPE_FILE = "file"
    TYPE_BLOCK = "block"
    TYPE_DIR = "dir"
    TYPE_VOLUME = "volume"
    types = [TYPE_FILE, TYPE_BLOCK, TYPE_DIR, TYPE_VOLUME]

    IO_MODE_NATIVE = "native"
    IO_MODE_THREADS = "threads"
    io_modes = [IO_MODE_NATIVE, IO_MODE_THREADS]

    error_policies = ["ignore", "stop", "enospace", "report"]

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
    def pretty_disk_bus(bus):
        if bus in ["ide", "sata", "scsi", "usb", "sd"]:
            return bus.upper()
        if bus in ["xen"]:
            return bus.capitalize()
        if bus == "virtio":
            return "VirtIO"
        if bus == "spapr-vscsi":
            return "vSCSI"
        return bus

    @staticmethod
    def path_definitely_exists(conn, path):
        """
        Check if path exists.

        return True if we are certain, False otherwise. Path may in fact
        exist if we return False, but we can't exhaustively know in all
        cases.

        (In fact if cached storage volume data is out of date, the volume
         may have disappeared behind out back, but that shouldn't have bad
         effects in practice.)
        """
        if path is None:
            return False

        try:
            (vol, pool) = diskbackend.check_if_path_managed(conn, path)
            ignore = pool

            if vol:
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
        if username == "root":
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
    def check_path_search(conn, path):
        # Only works for qemu and DAC
        if conn.is_remote() or not conn.is_qemu_system():
            return None, []

        from virtcli import cliconfig
        user = cliconfig.default_qemu_user
        try:
            for i in conn.caps.host.secmodels:
                if i.model != "dac":
                    continue

                label = (i.baselabels.get("kvm") or
                         i.baselabels.get("qemu"))
                if not label:
                    continue

                pwuid = pwd.getpwuid(
                    int(label.split(":")[0].replace("+", "")))
                if pwuid:
                    user = pwuid[0]
        except:
            logging.debug("Exception grabbing qemu DAC user", exc_info=True)
            return None, []

        return user, VirtualDisk.check_path_search_for_user(conn, path, user)

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
    def path_in_use_by(conn, path, shareable=False, read_only=False):
        """
        Return a list of VM names that are using the passed path.

        @param conn: virConnect to check VMs
        @param path: Path to check for
        @param shareable: Path we are checking is marked shareable, so
            don't warn if it conflicts with another shareable source.
        @param read_only: Path we are checking is marked read_only, so
            don't warn if it conflicts with another read_only source.
        """
        if not path:
            return []

        # Find all volumes that have 'path' somewhere in their backing chain
        vols = []
        volmap = dict((vol.backing_store, vol)
                      for vol in conn.fetch_all_vols() if vol.backing_store)
        backpath = path
        while backpath in volmap:
            vol = volmap[backpath]
            if vol in vols:
                break
            backpath = vol.target_path
            vols.append(backpath)

        ret = []
        vms = conn.fetch_all_guests()
        for vm in vms:
            if not read_only:
                if path in [vm.os.kernel, vm.os.initrd, vm.os.dtb]:
                    ret.append(vm.name)
                    continue

            for disk in vm.get_devices("disk"):
                if disk.path in vols and vm.name not in ret:
                    # VM uses the path indirectly via backing store
                    ret.append(vm.name)
                    break

                if disk.path != path:
                    continue

                if shareable and disk.shareable:
                    continue
                if read_only and disk.read_only:
                    continue

                ret.append(vm.name)
                break

        return ret

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
    def build_vol_install(*args, **kwargs):
        return diskbackend.build_vol_install(*args, **kwargs)

    @staticmethod
    def num_to_target(num):
        """
        Convert an index in range (1, 1024) to a disk /dev number
        (like hda, hdb, hdaa, etc.)
        """
        digits = []
        for factor in range(0, 3):
            amt = (num % (26 ** (factor + 1))) / (26 ** factor)
            if amt == 0 and num >= (26 ** (factor + 1)):
                amt = 26
            num -= amt
            digits.insert(0, amt)

        seen_valid = False
        gen_t = ""
        for digit in digits:
            if digit == 0:
                if not seen_valid:
                    continue
                digit = 1

            seen_valid = True
            gen_t += "%c" % (ord('a') + digit - 1)

        return gen_t


    @staticmethod
    def target_to_num(tgt):
        """
        Convert disk /dev number (like hda, hdb, hdaa, etc.) to an index
        """
        num = 0
        k = 0
        if tgt[0] == 'x':
            # This case is here for 'xvda'
            tgt = tgt[1:]
        for i, c in enumerate(reversed(tgt[2:])):
            if i != 0:
                k = 1
            num += (ord(c) - ord('a') + k) * (26 ** i)
        return num


    _XML_PROP_ORDER = [
        "type", "device",
        "driver_name", "driver_type",
        "driver_cache", "driver_discard", "driver_io", "error_policy",
        "_source_file", "_source_dev", "_source_dir", "_source_volume",
        "target", "bus",
    ]

    def __init__(self, *args, **kwargs):
        VirtualDevice.__init__(self, *args, **kwargs)

        self.__storage_backend = None
        self._storage_creator = None

        self.nomanaged = False


    #############################
    # Public property-esque API #
    #############################

    def _get_path(self):
        if self._storage_creator:
            return self._storage_creator.path
        return self._storage_backend.path
    def _set_path(self, val):
        if self._storage_creator:
            raise ValueError("Can't change disk path if storage creation info "
                             "has been set.")
        self._change_backend(val, None)
        self._set_xmlpath(self.path)
    path = property(_get_path, _set_path)

    def set_vol_object(self, vol_object):
        self._change_backend(None, vol_object)
        self._set_xmlpath(self.path)

    def set_vol_install(self, vol_install):
        self._storage_creator = diskbackend.StorageCreator(self.conn,
            None, None, vol_install, None, None, None, None, None)
        self._set_xmlpath(self.path)

    def get_vol_object(self):
        return self._storage_backend.get_vol_object()
    def get_vol_install(self):
        if not self._storage_creator:
            return None
        return self._storage_creator.get_vol_install()
    def get_parent_pool(self):
        if self.get_vol_install():
            return self.get_vol_install().pool
        return self._storage_backend.get_parent_pool()

    def get_size(self):
        if self._storage_creator:
            return self._storage_creator.get_size()
        return self._storage_backend.get_size()


    #############################
    # Internal defaults helpers #
    #############################

    def _get_default_type(self):
        if self._storage_creator:
            return self._storage_creator.get_dev_type()
        return self._storage_backend.get_dev_type()

    def _get_default_driver_name(self):
        if not self.path:
            return None
        if self.conn.is_qemu():
            return self.DRIVER_QEMU
        return None

    def _get_default_driver_type(self):
        """
        Set driver type from passed parameters

        Where possible, we want to force /driver/@type = "raw" if installing
        a QEMU VM. Without telling QEMU to expect a raw file, the emulator
        is forced to autodetect, which has security implications:

        http://lists.gnu.org/archive/html/qemu-devel/2008-04/msg00675.html
        """
        if self.driver_name != self.DRIVER_QEMU:
            return None

        if self._storage_creator:
            drvtype = self._storage_creator.get_driver_type()
        else:
            drvtype = self._storage_backend.get_driver_type()
        return _qemu_sanitize_drvtype(self.type, drvtype)


    ##################
    # XML properties #
    ##################

    _source_file = XMLProperty("./source/@file")
    _source_dev = XMLProperty("./source/@dev")
    _source_dir = XMLProperty("./source/@dir")
    _source_volume = XMLProperty("./source/@volume")

    def _disk_type_to_object_prop_name(self):
        disk_type = self.type
        if disk_type == VirtualDisk.TYPE_BLOCK:
            return "_source_dev"
        elif disk_type == VirtualDisk.TYPE_DIR:
            return "_source_dir"
        elif disk_type == VirtualDisk.TYPE_VOLUME:
            return "_source_volume"
        else:
            return "_source_file"
    def _get_xmlpath(self):
        # Hack to avoid an ordering problem when building XML.
        # If both path and type are unset, but we try to read back disk.path,
        # it triggers default_type->storage_backend->path->default_type...
        # loop
        if (not self._storage_creator and
            not self.__storage_backend and
            not self._source_file and
            not self._source_dev and
            not self._source_dir and
            not self._source_volume):
            return None

        propname = self._disk_type_to_object_prop_name()
        return getattr(self, propname)
    def _set_xmlpath(self, val):
        self._source_dev = None
        self._source_dir = None
        self._source_volume = None
        self._source_file = None

        propname = self._disk_type_to_object_prop_name()
        return setattr(self, propname, val)

    source_pool = XMLProperty("./source/@pool")
    startup_policy = XMLProperty("./source/@startupPolicy")

    device = XMLProperty("./@device",
                         default_cb=lambda s: s.DEVICE_DISK)
    type = XMLProperty("./@type", default_cb=_get_default_type)
    driver_name = XMLProperty("./driver/@name",
                              default_cb=_get_default_driver_name)
    driver_type = XMLProperty("./driver/@type",
                              default_cb=_get_default_driver_type)


    bus = XMLProperty("./target/@bus")
    target = XMLProperty("./target/@dev")
    removable = XMLProperty("./target/@removable", is_onoff=True)

    read_only = XMLProperty("./readonly", is_bool=True)
    shareable = XMLProperty("./shareable", is_bool=True)
    driver_cache = XMLProperty("./driver/@cache")
    driver_discard = XMLProperty("./driver/@discard")
    driver_io = XMLProperty("./driver/@io")

    error_policy = XMLProperty("./driver/@error_policy")
    serial = XMLProperty("./serial")

    iotune_rbs = XMLProperty("./iotune/read_bytes_sec", is_int=True)
    iotune_ris = XMLProperty("./iotune/read_iops_sec", is_int=True)
    iotune_tbs = XMLProperty("./iotune/total_bytes_sec", is_int=True)
    iotune_tis = XMLProperty("./iotune/total_iops_sec", is_int=True)
    iotune_wbs = XMLProperty("./iotune/write_bytes_sec", is_int=True)
    iotune_wis = XMLProperty("./iotune/write_iops_sec", is_int=True)


    #################################
    # Validation assistance methods #
    #################################

    def _get_storage_backend(self):
        if self.__storage_backend is None:
            self.__storage_backend = diskbackend.StorageBackend(
                self.conn, self._get_xmlpath(), None, None)
        return self.__storage_backend
    def _set_storage_backend(self, val):
        self.__storage_backend = val
    _storage_backend = property(_get_storage_backend, _set_storage_backend)

    def set_create_storage(self, size=None, sparse=True,
                           fmt=None, vol_install=None,
                           clone_path=None, backing_store=None,
                           fake=False):
        """
        Function that sets storage creation parameters. If this isn't
        called, we assume that no storage creation is taking place and
        will error accordingly.

        @size is in gigs
        @fake: If true, make like we are creating storage but fail
            if we ever asked to do so.
        """
        def _validate_path(p):
            if p is None:
                return
            try:
                d = VirtualDisk(self.conn)
                d.path = p

                # If this disk isn't managed, make sure we only perform
                # non-managed lookup.
                if (self._storage_creator or
                    (self.path and self._storage_backend.exists())):
                    d.nomanaged = not self.__managed_storage()
                d.set_create_storage(fake=True)
                d.validate()
            except Exception, e:
                raise ValueError(_("Error validating path %s: %s") % (p, e))

        path = self.path

        # Validate clone_path
        if clone_path is not None:
            clone_path = os.path.abspath(clone_path)
        if backing_store is not None:
            backing_store = os.path.abspath(backing_store)

        if not fake:
            _validate_path(clone_path)
            _validate_path(backing_store)

        if fake and size is None:
            size = .000001

        backend = _make_storage_backend(self.conn,
            self.nomanaged, path, None)
        creator_args = (backing_store, size, sparse, fmt)
        creator = _make_storage_creator(self.conn, backend,
                                        vol_install, clone_path,
                                        *creator_args)

        self._storage_creator = creator
        if self._storage_creator:
            self._storage_creator.fake = bool(fake)
            self._set_xmlpath(self.path)
        else:
            if (vol_install or clone_path):
                raise RuntimeError("Need storage creation but it "
                                   "didn't happen.")
            if fmt and self.driver_name == self.DRIVER_QEMU:
                self.driver_type = fmt

    def is_cdrom(self):
        return self.device == self.DEVICE_CDROM
    def is_floppy(self):
        return self.device == self.DEVICE_FLOPPY
    def is_disk(self):
        return self.device == self.DEVICE_DISK

    def can_be_empty(self):
        return self.is_floppy() or self.is_cdrom()

    def _change_backend(self, path, vol_object):
        backend = _make_storage_backend(self.conn, self.nomanaged,
                                        path, vol_object)
        self._storage_backend = backend

    def sync_path_props(self):
        """
        Fills in the values of type, driver_type, and driver_name for
        the associated backing storage. This needs to be manually called
        if changing an existing disk's media.
        """
        path = self._get_xmlpath()

        self.type = self._get_default_type()
        self.driver_name = self._get_default_driver_name()
        self.driver_type = self._get_default_driver_type()

        # Need to retrigger this if self.type changed
        self._set_xmlpath(path)

    def wants_storage_creation(self):
        """
        If true, this disk needs storage creation parameters or things
        will error.
        """
        return self.path and not self._storage_backend.exists()

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

        if not self.creating_storage():
            if not self._storage_backend.exists():
                raise ValueError(
                    _("Must specify storage creation parameters for "
                      "non-existent path '%s'.") % self.path)

            if (self.type == self.TYPE_DIR and
                not self.is_floppy()):
                raise ValueError(_("The path '%s' must be a file or a "
                                   "device, not a directory") % self.path)
            return True

        self._storage_creator.validate(self.device, self.type)

        # Applicable for managed or local storage
        err, msg = self.is_size_conflict()
        if err:
            raise ValueError(msg)
        if msg:
            logging.warn(msg)


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

    def set_defaults(self, guest):
        if self.is_cdrom():
            self.read_only = True

        if (guest.os.is_xenpv() and
            self.type == VirtualDisk.TYPE_FILE and
            self.driver_name is None and
            util.is_blktap_capable(self.conn)):
            self.driver_name = VirtualDisk.DRIVER_TAP

        if not self.conn.is_qemu():
            return
        if not self.is_disk():
            return
        if not self.type == self.TYPE_BLOCK:
            return

        # Enable cache=none and io=native for block devices. Would
        # be nice if qemu did this for us but that time has long passed.
        if not self.driver_cache:
            self.driver_cache = self.CACHE_MODE_NONE
        if not self.driver_io:
            self.driver_io = self.IO_MODE_NATIVE


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

    def is_conflict_disk(self, conn=None):
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

        ret = self.path_in_use_by(conn, self.path,
                                  shareable=self.shareable,
                                  read_only=self.read_only)
        return ret


    def get_target_prefix(self, used_targets=None):
        """
        Returns the suggested disk target prefix (hd, xvd, sd ...) for the
        disk.
        @returns: str prefix, or None if no reasonable guess can be made
        """
        # The upper limits here aren't necessarilly 1024, but let the HV
        # error as appropriate.
        def _return(prefix):
            nummap = {
                "vd": 1024,
                "xvd": 1024,
                "fd": 2,
                "hd": 4,
                "sd": 1024,
            }
            return prefix, nummap[prefix]

        if self.bus == "virtio":
            return _return("vd")
        elif self.bus == "xen":
            return _return("xvd")
        elif self.bus == "fdc" or self.is_floppy():
            return _return("fd")
        elif self.bus == "ide":
            return _return("hd")
        elif self.bus or not used_targets:
            # sata, scsi, usb, sd
            return _return("sd")

        # If guest already has some disks defined
        preforder = ["vd", "xvd", "sd", "hd"]
        for pref in preforder:
            for target in used_targets:
                if target.startswith(pref):
                    return _return(pref)
        return _return("sd")

    def generate_target(self, skip_targets, pref_ctrl=None):
        """
        Generate target device ('hda', 'sdb', etc..) for disk, excluding
        any targets in 'skip_targets'.  If given the 'pref_ctrl'
        parameter, it tries to select the target so that the disk is
        mapped onto that controller.
        Sets self.target, and returns the generated value.

        @param skip_targets: list of targets to exclude
        @type skip_targets: C{list}
        @param pref_ctrl: preferred controller to connect the disk to
        @type pref_ctrl: C{int}
        @raise ValueError: can't determine target type, no targets available
        @returns generated target
        @rtype C{str}
        """
        prefix, maxnode = self.get_target_prefix(skip_targets)
        skip_targets = [t for t in skip_targets if t and t.startswith(prefix)]
        skip_targets.sort()

        def get_target():
            first_found = None

            ran = range(maxnode)
            if pref_ctrl is not None:
                # We assume narrow SCSI bus and libvirt assigning 7
                # (1-7, 8-14, etc.) devices per controller
                ran = range(pref_ctrl * 7, (pref_ctrl + 1) * 7)

            for i in ran:
                gen_t = prefix + self.num_to_target(i + 1)
                if gen_t in skip_targets:
                    skip_targets.remove(gen_t)
                    continue
                if not skip_targets:
                    return gen_t
                elif not first_found:
                    first_found = gen_t
            if first_found:
                return first_found

        ret = get_target()
        if ret:
            self.target = ret
            return ret

        if pref_ctrl is not None:
            # This basically means that we either chose full
            # controller or didn't add any
            raise ValueError(_("Controller number %d for disk of type %s has "
                               "no empty slot to use" % (pref_ctrl, prefix)))
        else:
            raise ValueError(_("Only %s disks of type '%s' are supported"
                               % (maxnode, prefix)))

VirtualDisk.register_type()
