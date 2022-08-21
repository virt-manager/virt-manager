#
# Copyright 2013, 2015 Red Hat, Inc.
# Copyright(c) FUJITSU Limited 2007.
#
# Cloning a virtual machine module.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import re
import os

import libvirt

from . import generatename
from . import progress
from . import xmlutil
from .guest import Guest
from .devices import DeviceInterface
from .devices import DeviceDisk
from .logger import log
from .devices import DeviceChannel


def _replace_vm(conn, name):
    """
    Remove the existing VM with the same name if requested
    """
    try:
        vm = conn.lookupByName(name)
    except libvirt.libvirtError:
        return

    try:

        log.debug("Explicitly replacing guest '%s'", name)
        if vm.ID() != -1:
            log.debug("Destroying guest '%s'", name)
            vm.destroy()

        log.debug("Undefining guest '%s'", name)
        vm.undefine()
    except libvirt.libvirtError as e:  # pragma: no cover
        msg = (_("Could not remove old vm '%(vm)s': %(error)s") % {
                "vm": name, "error": str(e)})
        raise RuntimeError(msg) from None


def _generate_clone_name(conn, basename):
    """
    If the orig name is "foo-clone", we don't want the clone to be
    "foo-clone-clone", we want "foo-clone1"
    """
    regex = r"-clone[1-9]*$"
    match = re.search(regex, basename)
    start_num = 1
    force_num = False
    if match:
        num_match = re.search("[1-9]+$", match.group())
        force_num = True
        if num_match:
            start_num = int(str(num_match.group())) + 1
        basename = basename[:match.start()]

    def cb(n):
        return generatename.check_libvirt_collision(
            conn.lookupByName, n)
    basename = basename + "-clone"
    return generatename.generate_name(basename, cb,
            sep="", start_num=start_num, force_num=force_num)


def _generate_clone_disk_path(conn, origname, newname, origpath):
    """
    Generate desired cloned disk path name, derived from the
    original path, original VM name, and proposed new VM name
    """
    if origpath is None:
        return None

    path = origpath
    suffix = ""

    # Try to split the suffix off the existing disk name. Ex.
    # foobar.img -> foobar-clone.img
    #
    # If the suffix is greater than 7 characters, assume it isn't
    # a file extension and is part of the disk name, at which point
    # just stick '-clone' on the end.
    if "." in origpath and len(origpath.rsplit(".", 1)[1]) <= 7:
        path, suffix = origpath.rsplit(".", 1)
        suffix = "." + suffix

    dirname = os.path.dirname(path)
    basename = os.path.basename(path)

    clonebase = basename + "-clone"
    if origname and basename == origname:
        clonebase = newname

    clonebase = os.path.join(dirname, clonebase)
    def cb(p):
        return DeviceDisk.path_definitely_exists(conn, p)
    return generatename.generate_name(clonebase, cb, suffix=suffix)


def _lookup_vm(conn, name):
    try:
        return conn.lookupByName(name)
    except libvirt.libvirtError:
        e = ValueError(_("Domain '%s' was not found.") % str(name))
        raise e from None


def _build_clone_vol_install(orig_disk, new_disk):
    # We set a stub size for initial creation
    # set_input_vol will overwrite it
    size = .000001
    sparse = False
    vol_install = DeviceDisk.build_vol_install(
        orig_disk.conn, os.path.basename(new_disk.get_source_path()),
        new_disk.get_parent_pool(), size, sparse)
    vol_install.set_input_vol(orig_disk.get_vol_object())

    return vol_install


def _build_clone_disk(orig_disk, clonepath, allow_create, sparse):
    conn = orig_disk.conn
    device = DeviceDisk.DEVICE_DISK
    if not clonepath:
        device = DeviceDisk.DEVICE_CDROM

    new_disk = DeviceDisk(conn)
    new_disk.set_source_path(clonepath)
    new_disk.device = device

    if not allow_create:
        new_disk.validate()
        return new_disk

    if new_disk.get_vol_object():
        # Special case: non remote cloning of a guest using
        # managed block devices: fall back to local cloning if
        # we have permissions to do so. This validation check
        # caused a few bug reports in a short period of time,
        # so must be a common case.
        if (conn.is_remote() or
            new_disk.type != new_disk.TYPE_BLOCK or
            not orig_disk.get_source_path() or
            not os.access(orig_disk.get_source_path(), os.R_OK) or
            not new_disk.get_source_path() or
            not os.access(new_disk.get_source_path(), os.W_OK)):
            raise RuntimeError(
                _("Clone onto existing storage volume is not "
                  "currently supported: '%s'") % new_disk.get_source_path())

    if (orig_disk.get_vol_object() and
        new_disk.wants_storage_creation()):
        vol_install = _build_clone_vol_install(orig_disk, new_disk)
        if not sparse:
            vol_install.allocation = vol_install.capacity
        new_disk.set_vol_install(vol_install)
    elif orig_disk.get_source_path():
        new_disk.set_local_disk_to_clone(orig_disk, sparse)

    new_disk.validate()
    return new_disk


def _get_cloneable_msg(disk):
    """
    If the disk storage is not cloneable, return a string explaining why
    """
    if disk.wants_storage_creation():
        return _("Disk path '%s' does not exist.") % disk.get_source_path()

    if disk.type == "network":
        proto = disk.source.protocol
        if proto == "rbd":
            # This case, rbd with managed storage, is implementable. It
            # requires open coding a bunch of work in cloner, or reworking
            # other disk code to add unique URIs for rbd volumes and pools
            return (
                _("Cloning rbd volumes is not yet supported.") +
                " https://github.com/virt-manager/virt-manager/issues/177")
        return _("Disk network type '%s' is not cloneable.") % proto


def _get_shareable_msg(disk):
    if disk.is_empty():
        return _("No storage to clone.")
    if disk.read_only:
        return _("Read Only")
    if disk.shareable or disk.transient_shareBacking:
        return _("Marked as shareable")


class _CloneDiskInfo:
    """
    Class that tracks some additional information about how we want
    to default handle each disk of the source VM

    For any source disk there's 3 main scenarios:

    * clone: Copy contents from src to dst. If dst path doesn't
            exist we attempt to create it. If it exists we overwrite it
    * preserve: Destination path is an existing, and no copying is performed.
    * share: Original disk XML is used unchanged for the new disk
    """
    _ACTION_SHARE = 1
    _ACTION_CLONE = 2
    _ACTION_PRESERVE = 3

    def __init__(self, srcdisk):
        self.disk = DeviceDisk(srcdisk.conn, parsexml=srcdisk.get_xml())
        self.disk.set_backend_for_existing_path()
        self.new_disk = None

        self._share_msg = _get_shareable_msg(self.disk)
        self._cloneable_msg = -1
        self._newpath_msg = None

        self._action = None
        self.set_clone_requested()
        if self.get_share_msg():
            self.set_share_requested()

    def is_clone_requested(self):
        return self._action in [self._ACTION_CLONE]
    def is_share_requested(self):
        return self._action in [self._ACTION_SHARE]
    def is_preserve_requested(self):
        return self._action in [self._ACTION_PRESERVE]

    def _set_action(self, action):
        if action != self._action:
            self._action = action
    def set_clone_requested(self):
        self._set_action(self._ACTION_CLONE)
    def set_share_requested(self):
        self._set_action(self._ACTION_SHARE)
    def set_preserve_requested(self):
        self._set_action(self._ACTION_PRESERVE)

    def set_new_path(self, path, sparse):
        allow_create = not self.is_preserve_requested()
        if allow_create:
            msg = self.get_cloneable_msg()
            if msg:
                return

        try:
            self.new_disk = Cloner.build_clone_disk(
                    self.disk, path, allow_create, sparse)
        except Exception as e:
            log.debug("Error setting clone path.", exc_info=True)
            err = (_("Could not use path '%(path)s' for cloning: %(error)s") %
                    {"path": path, "error": str(e)})
            self._newpath_msg = err

    def get_share_msg(self):
        return self._share_msg
    def get_cloneable_msg(self):
        if self._cloneable_msg == -1:
            self._cloneable_msg = _get_cloneable_msg(self.disk)
        return self._cloneable_msg
    def get_newpath_msg(self):
        return self._newpath_msg

    def raise_error(self):
        if self.is_clone_requested() and self.get_cloneable_msg():
            msg = self.get_cloneable_msg()
            err = _("Could not determine original disk information: %s" % msg)
            raise ValueError(err)
        if self.is_share_requested():
            return
        if self.get_newpath_msg():
            msg = self.get_newpath_msg()
            raise ValueError(msg)


class Cloner(object):
    @staticmethod
    def generate_clone_name(conn, basename):
        return _generate_clone_name(conn, basename)

    @staticmethod
    def generate_clone_disk_path(conn, origname, newname, origpath):
        return _generate_clone_disk_path(conn, origname, newname, origpath)

    @staticmethod
    def build_clone_disk(orig_disk, clonepath, allow_create, sparse):
        return _build_clone_disk(orig_disk, clonepath, allow_create, sparse)

    def __init__(self, conn, src_name=None, src_xml=None):
        self.conn = conn

        self._src_guest = None
        self._new_guest = None
        self._diskinfos = []
        self._nvram_diskinfo = None
        self._init_src(src_name, src_xml)

        self._new_nvram_path = None

        self._sparse = True
        self._replace = False
        self._reflink = False


    #################
    # Init routines #
    #################

    def _init_src(self, src_name, src_xml):
        """
        Set up the source VM info we are cloning, from passed in VM name
        or full XML
        """
        if not src_xml:
            dom = _lookup_vm(self.conn, src_name)
            status = dom.info()[0]
            if status not in [libvirt.VIR_DOMAIN_SHUTOFF]:
                raise RuntimeError(_("Domain to clone must be shutoff."))
            flags = libvirt.VIR_DOMAIN_XML_SECURE
            src_xml = dom.XMLDesc(flags)

        log.debug("Original XML:\n%s", src_xml)

        self._src_guest = Guest(self.conn, parsexml=src_xml)
        self._new_guest = Guest(self.conn, parsexml=src_xml)
        self._init_new_guest()

        # Collect disk info for every disk to determine if we will
        # default to cloning or not
        for disk in self._src_guest.devices.disk:
            self._diskinfos.append(_CloneDiskInfo(disk))
        for diskinfo in [d for d in self._diskinfos if d.is_clone_requested()]:
            disk = diskinfo.disk
            log.debug("Wants cloning: size=%s path=%s",
                    disk.get_size(), disk.get_source_path())

        if self._src_guest.os.nvram:
            old_nvram = DeviceDisk(self.conn)
            old_nvram.set_source_path(self._new_guest.os.nvram)
            self._nvram_diskinfo = _CloneDiskInfo(old_nvram)

    def _init_new_guest(self):
        """
        Perform the series of unconditional new VM changes we always make
        """
        self._new_guest.id = None
        self._new_guest.title = None
        self.set_clone_uuid(Guest.generate_uuid(self.conn))

        for dev in self._new_guest.devices.graphics:
            if dev.port and dev.port != -1:
                log.warning(_("Setting the graphics device port to autoport, "
                               "in order to avoid conflicting."))
                dev.port = -1

        for iface in self._new_guest.devices.interface:
            iface.target_dev = None
            iface.macaddr = DeviceInterface.generate_mac(self.conn)

        # For guest agent channel, remove a path to generate a new one with
        # new guest name
        for channel in self._new_guest.devices.channel:
            if (channel.type == DeviceChannel.TYPE_UNIX and
                channel.target_name and channel.source.path and
                channel.target_name in channel.source.path):
                channel.source.path = None

        new_name = Cloner.generate_clone_name(self.conn, self.src_name)
        log.debug("Auto-generated clone name '%s'", new_name)
        self.set_clone_name(new_name)


    ##############
    # Properties #
    ##############

    @property
    def src_name(self):
        """
        The name of the original VM we are cloning
        """
        return self._src_guest.name

    @property
    def new_guest(self):
        """
        The Guest instance of the new XML we will create
        """
        return self._new_guest

    @property
    def nvram_diskinfo(self):
        return self._nvram_diskinfo

    def set_clone_name(self, name):
        self._new_guest.name = name

    def set_clone_uuid(self, uuid):
        """
        Override the new VMs generated UUId
        """
        self._new_guest.uuid = uuid
        for sysinfo in self._new_guest.sysinfo:
            if sysinfo.system_uuid:
                sysinfo.system_uuid = uuid

    def set_replace(self, val):
        """
        If True, don't check for clone name collision, simply undefine
        any conflicting guest.
        """
        self._replace = bool(val)

    def set_reflink(self, reflink):
        """
        If true, use COW lightweight copy
        """
        self._reflink = reflink

    def set_sparse(self, flg):
        """
        If True, attempt sparse allocation during cloning
        """
        self._sparse = flg

    def get_diskinfos(self):
        """
        Return the list of _CloneDiskInfo instances
        """
        return self._diskinfos[:]

    def get_nonshare_diskinfos(self):
        """
        Return a list of _CloneDiskInfo that are tagged for cloning
        """
        return [di for di in self.get_diskinfos() if
                not di.is_share_requested()]

    def set_nvram_path(self, val):
        """
        If the VM needs to have nvram content cloned, this overrides the
        destination path
        """
        self._new_nvram_path = val


    ######################
    # Functional methods #
    ######################

    def _prepare_nvram(self):
        if not self._nvram_diskinfo:
            return

        new_nvram_path = self._new_nvram_path
        if new_nvram_path is None:
            nvram_dir = os.path.dirname(self._new_guest.os.nvram)
            new_nvram_path = os.path.join(
                    nvram_dir, "%s_VARS.fd" % self._new_guest.name)

        diskinfo = self._nvram_diskinfo
        new_nvram = DeviceDisk(self.conn)
        new_nvram.set_source_path(new_nvram_path)
        old_nvram = DeviceDisk(self.conn)
        old_nvram.set_source_path(diskinfo.disk.get_source_path())

        if (diskinfo.is_clone_requested() and
            new_nvram.wants_storage_creation() and
            diskinfo.disk.get_vol_object()):
            # We only run validation if there's some existing nvram we
            # can copy. It's valid for nvram to not exist at VM define
            # time, libvirt will create it for us
            diskinfo.set_new_path(new_nvram_path, self._sparse)
            diskinfo.raise_error()
            diskinfo.new_disk.get_vol_install().reflink = self._reflink
        else:
            # There's no action to perform for this case, so drop it
            self._nvram_diskinfo = None

        self._new_guest.os.nvram = new_nvram.get_source_path()


    def prepare(self):
        """
        Validate and set up all parameters needed for the new (clone) VM
        """
        try:
            Guest.validate_name(self.conn, self._new_guest.name,
                                check_collision=not self._replace,
                                validate=False)
        except ValueError as e:
            msg = _("Invalid name for new guest: %s") % e
            raise ValueError(msg) from None

        for diskinfo in self.get_nonshare_diskinfos():
            orig_disk = diskinfo.disk

            if not diskinfo.new_disk:
                # User didn't set a path, generate one
                newpath = Cloner.generate_clone_disk_path(
                         self.conn, self.src_name,
                         self.new_guest.name,
                         orig_disk.get_source_path())
                diskinfo.set_new_path(newpath, self._sparse)
                if not diskinfo.new_disk:
                    # We hit an error, clients will raise it later
                    continue

            new_disk = diskinfo.new_disk
            assert new_disk
            log.debug("Cloning srcpath=%s dstpath=%s",
                    orig_disk.get_source_path(), new_disk.get_source_path())

            if self._reflink:
                vol_install = new_disk.get_vol_install()
                vol_install.reflink = self._reflink

            for disk in self._new_guest.devices.disk:
                if disk.target == orig_disk.target:
                    xmldisk = disk

            # Change the XML
            xmldisk.set_source_path(None)
            xmldisk.type = new_disk.type
            xmldisk.driver_name = orig_disk.driver_name
            xmldisk.driver_type = orig_disk.driver_type
            xmldisk.set_source_path(new_disk.get_source_path())

        self._prepare_nvram()

        # Save altered clone xml
        diff = xmlutil.diff(self._src_guest.get_xml(),
                self._new_guest.get_xml())
        log.debug("Clone guest xml diff:\n%s", diff)

    def start_duplicate(self, meter=None):
        """
        Actually perform the duplication: cloning disks if needed and defining
        the new clone xml.
        """
        log.debug("Starting duplicate.")
        meter = progress.ensure_meter(meter)

        dom = None
        try:
            # Replace orig VM if required
            if self._replace:
                _replace_vm(self.conn, self._new_guest.name)

            # Define domain early to catch any xml errors before duping storage
            dom = self.conn.defineXML(self._new_guest.get_xml())

            diskinfos = self.get_diskinfos()
            if self._nvram_diskinfo:
                diskinfos.append(self._nvram_diskinfo)

            for diskinfo in diskinfos:
                if not diskinfo.is_clone_requested():
                    continue
                diskinfo.new_disk.build_storage(meter)
        except Exception as e:
            log.debug("Duplicate failed: %s", str(e))
            if dom:
                dom.undefine()
            raise

        log.debug("Duplicating finished.")
