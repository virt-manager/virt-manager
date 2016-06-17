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

from . import diskbackend
from . import util
from .device import VirtualDevice
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


def _qemu_sanitize_drvtype(phystype, fmt, manual_format=False):
    """
    Sanitize libvirt storage volume format to a valid qemu driver type
    """
    raw_list = ["iso"]

    if phystype == VirtualDisk.TYPE_BLOCK:
        if not fmt:
            return VirtualDisk.DRIVER_TYPE_RAW
        if fmt and not manual_format:
            return VirtualDisk.DRIVER_TYPE_RAW

    if fmt in raw_list:
        return VirtualDisk.DRIVER_TYPE_RAW

    return fmt


def _is_dir_searchable(uid, username, path):
    """
    Check if passed directory is searchable by uid
    """
    if "VIRTINST_TEST_SUITE" in os.environ:
        return True

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


class _DiskSeclabel(XMLBuilder):
    """
    This is for disk source <seclabel>. It's similar to a domain
    <seclabel> but has fewer options
    """
    _XML_ROOT_NAME = "seclabel"
    model = XMLProperty("./@model")
    relabel = XMLProperty("./@relabel", is_yesno=True)
    label = XMLProperty("./label")


class VirtualDisk(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_DISK

    DRIVER_NAME_PHY = "phy"
    DRIVER_NAME_QEMU = "qemu"
    DRIVER_TYPE_RAW = "raw"

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
    TYPE_NETWORK = "network"
    types = [TYPE_FILE, TYPE_BLOCK, TYPE_DIR, TYPE_NETWORK]

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
        return bus

    @staticmethod
    def path_definitely_exists(conn, path):
        """
        Check if path exists.

        return True if we are certain, False otherwise. Path may in fact
        exist if we return False, but we can't exhaustively know in all
        cases.

        (In fact if cached storage volume data is out of date, the volume
         may have disappeared behind our back, but that shouldn't have bad
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
        if diskbackend.path_is_url(path):
            return []

        try:
            # Get UID for string name
            uid = pwd.getpwnam(username)[2]
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

        from virtcli import CLIConfig
        user = CLIConfig.default_qemu_user
        try:
            for secmodel in conn.caps.host.secmodels:
                if secmodel.model != "dac":
                    continue

                label = None
                for baselabel in secmodel.baselabels:
                    if baselabel.type in ["qemu", "kvm"]:
                        label = baselabel.content
                        break
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
    def build_vol_install(conn, volname, poolobj, size, sparse,
                          fmt=None, backing_store=None, backing_format=None):
        """
        Helper for building a StorageVolume instance to pass to VirtualDisk
        for eventual storage creation.

        :param volname: name of the volume to be created
        :param size: size in bytes
        """
        from .storage import StorageVolume

        if size is None:
            raise ValueError(_("Size must be specified for non "
                               "existent volume '%s'" % volname))

        # This catches --disk /dev/idontexist,size=1 if /dev is unmanaged
        if not poolobj:
            raise RuntimeError(_("Don't know how to create storage for "
                "path '%s'. Use libvirt APIs to manage the parent directory "
                "as a pool first.") % volname)

        logging.debug("Creating volume '%s' on pool '%s'",
                      volname, poolobj.name())

        cap = (size * 1024 * 1024 * 1024)
        if sparse:
            alloc = 0
        else:
            alloc = cap

        volinst = StorageVolume(conn)
        volinst.pool = poolobj
        volinst.name = volname
        volinst.capacity = cap
        volinst.allocation = alloc
        volinst.backing_store = backing_store
        volinst.backing_format = backing_format

        if fmt:
            if not volinst.supports_property("format"):
                raise ValueError(_("Format attribute not supported for this "
                                   "volume type"))
            volinst.format = fmt

        return volinst

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
        "_source_file", "_source_dev", "_source_dir",
        "source_volume", "source_pool", "source_protocol", "source_name",
        "source_host_name", "source_host_port",
        "source_host_transport", "source_host_socket",
        "target", "bus",
    ]

    def __init__(self, *args, **kwargs):
        VirtualDevice.__init__(self, *args, **kwargs)

        self._storage_backend = None
        self.storage_was_created = False


    #############################
    # Public property-esque API #
    #############################

    def _get_path(self):
        if not self._storage_backend:
            xmlpath = self._get_xmlpath()
            if xmlpath:
                return xmlpath

            self._set_default_storage_backend()
        return self._storage_backend.get_path()
    def _set_path(self, newpath):
        if (self._storage_backend and
            self._storage_backend.will_create_storage()):
            raise ValueError(_("Can't change disk path if storage creation info "
                               "has been set."))

        # User explicitly changed 'path', so try to lookup its storage
        # object since we may need it
        (vol_object, parent_pool) = diskbackend.manage_path(self.conn, newpath)

        self._change_backend(newpath, vol_object, parent_pool)
        self._set_xmlpath(self.path)
    path = property(_get_path, _set_path)

    def set_vol_object(self, vol_object, parent_pool):
        logging.debug("disk.set_vol_object: volxml=\n%s",
            vol_object.XMLDesc(0))
        logging.debug("disk.set_vol_object: poolxml=\n%s",
            parent_pool.XMLDesc(0))
        self._change_backend(None, vol_object, parent_pool)
        self._set_xmlpath(self.path)

    def set_vol_install(self, vol_install):
        logging.debug("disk.set_vol_install: name=%s poolxml=\n%s",
            vol_install.name, vol_install.pool.XMLDesc(0))
        self._storage_backend = diskbackend.ManagedStorageCreator(
            self.conn, vol_install)
        self._set_xmlpath(self.path)

    def get_vol_object(self):
        return self._storage_backend.get_vol_object()
    def get_vol_install(self):
        return self._storage_backend.get_vol_install()
    def get_parent_pool(self):
        if self.get_vol_install():
            return self.get_vol_install().pool
        return self._storage_backend.get_parent_pool()

    def get_size(self):
        return self._storage_backend.get_size()


    #############################
    # Internal defaults helpers #
    #############################

    def _get_default_driver_name(self):
        if not self.path:
            return None

        # Recommended xen defaults from here:
        # https://bugzilla.redhat.com/show_bug.cgi?id=1171550#c9
        # If type block, use name=phy. Otherwise do the same as qemu
        if self.conn.is_xen() and self.type == self.TYPE_BLOCK:
            return self.DRIVER_NAME_PHY
        if self.conn.check_support(
                self.conn.SUPPORT_CONN_DISK_DRIVER_NAME_QEMU):
            return self.DRIVER_NAME_QEMU
        return None

    def _get_default_driver_type(self):
        """
        Set driver type from passed parameters

        Where possible, we want to force /driver/@type = "raw" if installing
        a QEMU VM. Without telling QEMU to expect a raw file, the emulator
        is forced to autodetect, which has security implications:

        http://lists.gnu.org/archive/html/qemu-devel/2008-04/msg00675.html
        """
        if self.driver_name != self.DRIVER_NAME_QEMU:
            return None

        drvtype = self._storage_backend.get_driver_type()
        return _qemu_sanitize_drvtype(self.type, drvtype)


    #############################
    # XML source media handling #
    #############################

    _source_file = XMLProperty("./source/@file")
    _source_dev = XMLProperty("./source/@dev")
    _source_dir = XMLProperty("./source/@dir")

    source_pool = XMLProperty("./source/@pool")
    source_volume = XMLProperty("./source/@volume")

    source_name = XMLProperty("./source/@name")
    source_protocol = XMLProperty("./source/@protocol")
    # Technically multiple host lines can be listed
    source_host_name = XMLProperty("./source/host/@name")
    source_host_port = XMLProperty("./source/host/@port", is_int=True)
    source_host_transport = XMLProperty("./source/host/@transport")
    source_host_socket = XMLProperty("./source/host/@socket")

    def _set_source_network_from_url(self, uri):
        from .uri import URI
        uriobj = URI(uri)

        if uriobj.scheme:
            self.source_protocol = uriobj.scheme
        if uriobj.transport:
            self.source_host_transport = uriobj.transport
        if uriobj.hostname:
            self.source_host_name = uriobj.hostname
        if uriobj.port:
            self.source_host_port = uriobj.port
        if uriobj.path:
            if self.source_host_transport:
                self.source_host_socket = uriobj.path
            else:
                self.source_name = uriobj.path
                if self.source_name.startswith("/"):
                    self.source_name = self.source_name[1:]

    def _set_source_network_from_storage(self, volxml, poolxml):
        self.source_protocol = poolxml.type
        if poolxml.hosts:
            self.source_host_name = poolxml.hosts[0].name
            self.source_host_port = poolxml.hosts[0].port

        path = ""
        if poolxml.source_name:
            path += poolxml.source_name
            if poolxml.source_path:
                path += poolxml.source_path
            if not path.endswith('/'):
                path += "/"
        path += volxml.name
        self.source_name = path
        self.type = "network"

    def _set_network_source_from_backend(self):
        if (self._storage_backend.get_vol_object() or
            self._storage_backend.get_vol_install()):
            volxml = self._storage_backend.get_vol_xml()
            poolxml = self._storage_backend.get_parent_pool_xml()
            self._set_source_network_from_storage(volxml, poolxml)
        elif self._storage_backend.get_path():
            self._set_source_network_from_url(self._storage_backend.get_path())

    def _build_url_from_network_source(self):
        ret = self.source_protocol
        if self.source_host_transport:
            ret += "+%s" % self.source_host_transport
        ret += "://"
        if self.source_host_name:
            ret += self.source_host_name
            if self.source_host_port:
                ret += ":" + str(self.source_host_port)
        if self.source_name:
            if not self.source_name.startswith("/"):
                ret += "/"
            ret += self.source_name
        elif self.source_host_socket:
            if not self.source_host_socket.startswith("/"):
                ret += "/"
            ret += self.source_host_socket
        return ret

    def _get_default_type(self):
        if self.source_pool or self.source_volume:
            return VirtualDisk.TYPE_VOLUME
        if self._storage_backend:
            return self._storage_backend.get_dev_type()
        if self.source_protocol:
            return VirtualDisk.TYPE_NETWORK
        return self.TYPE_FILE
    type = XMLProperty("./@type", default_cb=_get_default_type)

    def _clear_source_xml(self):
        """
        Unset all XML properties that describe the actual source media
        """
        self._source_file = None
        self._source_dev = None
        self._source_dir = None
        self.source_volume = None
        self.source_pool = None
        self.source_name = None
        self.source_protocol = None
        self.source_host_name = None
        self.source_host_port = None
        self.source_host_transport = None
        self.source_host_socket = None

    def _disk_type_to_object_prop_name(self):
        disk_type = self.type
        if disk_type == VirtualDisk.TYPE_BLOCK:
            return "_source_dev"
        elif disk_type == VirtualDisk.TYPE_DIR:
            return "_source_dir"
        elif disk_type == VirtualDisk.TYPE_FILE:
            return "_source_file"
        return None


    # _xmlpath is an abstraction for source file/block/dir paths, since
    # they don't have any special properties aside from needing to match
    # 'type' value with the source property used.
    def _get_xmlpath(self):
        if self._source_file:
            return self._source_file
        if self._source_dev:
            return self._source_dev
        if self._source_dir:
            return self._source_dir
        return None
    def _set_xmlpath(self, val):
        self._clear_source_xml()

        if self._storage_backend.get_dev_type() == "network":
            self._set_network_source_from_backend()
            return

        propname = self._disk_type_to_object_prop_name()
        if not propname:
            return
        return setattr(self, propname, val)


    ##################
    # XML properties #
    ##################

    device = XMLProperty("./@device",
                         default_cb=lambda s: s.DEVICE_DISK)
    driver_name = XMLProperty("./driver/@name",
                              default_cb=_get_default_driver_name)
    driver_type = XMLProperty("./driver/@type",
                              default_cb=_get_default_driver_type)

    sgio = XMLProperty("./@sgio")

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
    startup_policy = XMLProperty("./source/@startupPolicy")

    iotune_rbs = XMLProperty("./iotune/read_bytes_sec", is_int=True)
    iotune_ris = XMLProperty("./iotune/read_iops_sec", is_int=True)
    iotune_tbs = XMLProperty("./iotune/total_bytes_sec", is_int=True)
    iotune_tis = XMLProperty("./iotune/total_iops_sec", is_int=True)
    iotune_wbs = XMLProperty("./iotune/write_bytes_sec", is_int=True)
    iotune_wis = XMLProperty("./iotune/write_iops_sec", is_int=True)

    seclabels = XMLChildProperty(_DiskSeclabel, relative_xpath="./source")
    def add_seclabel(self):
        obj = _DiskSeclabel(self.conn)
        self.add_child(obj)
        return obj


    #################################
    # Validation assistance methods #
    #################################

    def _set_default_storage_backend(self):
        path = None
        vol_object = None
        parent_pool = None
        typ = self._get_default_type()

        if self.type == VirtualDisk.TYPE_NETWORK:
            # Fill in a completed URL for virt-manager UI, path comparison, etc
            path = self._build_url_from_network_source()

        if typ == VirtualDisk.TYPE_VOLUME:
            conn = self.conn
            if "weakref" in str(type(conn)):
                conn = conn()

            try:
                parent_pool = conn.storagePoolLookupByName(self.source_pool)
                vol_object = parent_pool.storageVolLookupByName(
                    self.source_volume)
            except:
                logging.debug("Error fetching source pool=%s vol=%s",
                    self.source_pool, self.source_volume, exc_info=True)

        if vol_object is None and path is None:
            path = self._get_xmlpath()

        self._change_backend(path, vol_object, parent_pool)

    def set_local_disk_to_clone(self, disk, sparse):
        """
        Set a path to manually clone (as in, not through libvirt)
        """
        self._storage_backend = diskbackend.CloneStorageCreator(self.conn,
            self.path, disk.path, disk.get_size(), sparse)

    def is_cdrom(self):
        return self.device == self.DEVICE_CDROM
    def is_floppy(self):
        return self.device == self.DEVICE_FLOPPY
    def is_disk(self):
        return self.device == self.DEVICE_DISK

    def can_be_empty(self):
        return self.is_floppy() or self.is_cdrom()

    def _change_backend(self, path, vol_object, parent_pool):
        backend = diskbackend.StorageBackend(self.conn, path,
                                             vol_object, parent_pool)
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
        if path:
            self._set_xmlpath(path)

    def wants_storage_creation(self):
        """
        If true, this disk needs storage creation parameters or things
        will error.
        """
        return (self._storage_backend and
                not self._storage_backend.exists())

    def validate(self):
        if self.path is None:
            if not self.can_be_empty():
                raise ValueError(_("Device type '%s' requires a path") %
                                 self.device)

            return

        if (self.type == VirtualDisk.TYPE_DIR and
            not self.is_floppy()):
            raise ValueError(_("The path '%s' must be a file or a "
                               "device, not a directory") % self.path)

        if not self._storage_backend:
            return

        if (not self._storage_backend.will_create_storage() and
            not self._storage_backend.exists()):
            raise ValueError(
                _("Must specify storage creation parameters for "
                  "non-existent path '%s'.") % self.path)

        self._storage_backend.validate(self)

    def setup(self, meter=None):
        """
        Build storage (if required)

        If storage doesn't exist (a non-existent file 'path', or 'vol_install'
        was specified), we create it.
        """
        if not self._storage_backend.will_create_storage():
            return

        meter = util.ensure_meter(meter)
        vol_object = self._storage_backend.create(meter)
        self.storage_was_created = True
        if not vol_object:
            return

        parent_pool = self.get_vol_install().pool
        self._change_backend(None, vol_object, parent_pool)

    def set_defaults(self, guest):
        if self.is_cdrom():
            self.read_only = True

        if self.is_cdrom() and guest.os.is_s390x():
            self.bus = "scsi"

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
        return self._storage_backend.is_size_conflict()

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
