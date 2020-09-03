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
from .guest import Guest
from .devices import DeviceInterface
from .devices import DeviceDisk
from .logger import log
from .storage import StorageVolume
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
        raise RuntimeError(
            _("Could not remove old vm '%(vm)s': %(error)s") % {
                "vm": name,
                "error": str(e),
            })


def _generate_clone_name(conn, basename):
    """
    If the orig name is "foo-clone", we don't want the clone to be
    "foo-clone-clone", we want "foo-clone1"
    """
    match = re.search("-clone[1-9]*$", basename)
    start_num = 1
    force_num = False
    if match:
        num_match = re.search("[1-9]+$", match.group())
        if num_match:
            start_num = int(str(num_match.group())) + 1
            force_num = True
        basename = basename.replace(match.group(), "")

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


def _build_clone_vol_install(orig_disk, clone_disk):
    vol_install = DeviceDisk.build_vol_install(
        orig_disk.conn, os.path.basename(clone_disk.path),
        clone_disk.get_parent_pool(), .000001, False)
    vol_install.input_vol = orig_disk.get_vol_object()

    # Source and dest are managed. If they share the same pool,
    # replace vol_install with a CloneVolume instance, otherwise
    # simply set input_vol on the dest vol_install
    if (vol_install.pool.name() ==
        orig_disk.get_parent_pool().name()):
        vol_install.sync_input_vol()
    else:
        # Cross pool cloning
        # Sync only the format of the image.
        vol_install.sync_input_vol(only_format=True)

    return vol_install


def _build_clone_disk(orig_disk, clonepath, allow_create, sparse):
    conn = orig_disk.conn
    device = DeviceDisk.DEVICE_DISK
    if not clonepath:
        device = DeviceDisk.DEVICE_CDROM

    clone_disk = DeviceDisk(conn)
    clone_disk.path = clonepath
    clone_disk.device = device

    if not allow_create:
        clone_disk.validate()
        return clone_disk

    if clone_disk.get_vol_object():
        # Special case: non remote cloning of a guest using
        # managed block devices: fall back to local cloning if
        # we have permissions to do so. This validation check
        # caused a few bug reports in a short period of time,
        # so must be a common case.
        if (conn.is_remote() or
            clone_disk.type != clone_disk.TYPE_BLOCK or
            not orig_disk.path or
            not os.access(orig_disk.path, os.R_OK) or
            not clone_disk.path or
            not os.access(clone_disk.path, os.W_OK)):
            raise RuntimeError(
                _("Clone onto existing storage volume is not "
                  "currently supported: '%s'") % clone_disk.path)

    if (orig_disk.get_vol_object() and
        clone_disk.wants_storage_creation()):
        vol_install = _build_clone_vol_install(orig_disk, clone_disk)
        if not sparse:
            vol_install.allocation = vol_install.capacity
        clone_disk.set_vol_install(vol_install)
    elif orig_disk.path:
        clone_disk.set_local_disk_to_clone(orig_disk, sparse)

    clone_disk.validate()
    return clone_disk


class _CloneDiskInfo:
    """
    Class that tracks some additional information about how we want
    to default handle each disk of the source VM
    """
    def __init__(self, srcdisk):
        self.disk = DeviceDisk(srcdisk.conn, parsexml=srcdisk.get_xml())
        self._do_clone = self._do_we_clone_default()
        self.clone_disk = None

    def is_clone_requested(self):
        return self._do_clone
    def set_clone_requested(self, val):
        self._do_clone = val

    def _do_we_clone_default(self):
        if not self.disk.path:
            return False
        if self.disk.read_only:
            return False
        if self.disk.shareable:
            return False
        return True

    def check_clonable(self):
        try:
            # This forces DeviceDisk to resolve the storage backend
            self.disk.path = self.disk.path
            if self.disk.wants_storage_creation():
                raise ValueError(
                        _("Disk path '%s' does not exist.") % self.disk.path)
        except Exception as e:
            log.debug("Exception processing clone original path", exc_info=True)
            err = _("Could not determine original disk information: %s" % str(e))
            raise ValueError(err) from None

    def set_clone_path(self, path, allow_create, sparse):
        if allow_create:
            self.check_clonable()

        try:
            self.clone_disk = _build_clone_disk(
                    self.disk, path, allow_create, sparse)
        except Exception as e:
            log.debug("Error setting clone path.", exc_info=True)
            raise ValueError(
                _("Could not use path '%(path)s' for cloning: %(error)s") % {
                    "path": path,
                    "error": str(e),
                })


class Cloner(object):
    @staticmethod
    def generate_clone_name(conn, basename):
        return _generate_clone_name(conn, basename)

    @staticmethod
    def generate_clone_disk_path(conn, origname, newname, origpath):
        return _generate_clone_disk_path(conn, origname, newname, origpath)

    def __init__(self, conn, src_name=None, src_xml=None):
        self.conn = conn

        self._src_guest = None
        self._new_guest = None
        self._diskinfos = []
        self._init_src(src_name, src_xml)

        self._new_nvram_path = None
        self._nvram_disk = None

        self._sparse = True
        self._overwrite = True
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
                    disk.get_size(), disk.path)

    def _init_new_guest(self):
        """
        Perform the series of unconditional new VM changes we always make
        """
        self._new_guest.id = None
        self._new_guest.title = None
        self._new_guest.uuid = None
        self._new_guest.uuid = Guest.generate_uuid(self.conn)

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

    def set_clone_name(self, name):
        self._new_guest.name = name

    def set_clone_uuid(self, uuid):
        """
        Override the new VMs generated UUId
        """
        self._new_guest.uuid = uuid

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

    def get_diskinfos_to_clone(self):
        """
        Return a list of _CloneDiskInfo that are tagged for cloning
        """
        return [di for di in self.get_diskinfos() if di.is_clone_requested()]

    def set_nvram_path(self, val):
        """
        If the VM needs to have nvram content cloned, this overrides the
        destination path
        """
        self._new_nvram_path = val

    def set_overwrite(self, flg):
        """
        If False, no data is copied to the destination disks by default.
        Storage may be created, but it is empty.
        """
        self._overwrite = flg


    ######################
    # Functional methods #
    ######################

    def _prepare_nvram(self):
        new_nvram_path = self._new_nvram_path
        if new_nvram_path is None:
            nvram_dir = os.path.dirname(self._new_guest.os.nvram)
            new_nvram_path = os.path.join(
                    nvram_dir, "%s_VARS.fd" % self._new_guest.name)

        old_nvram = DeviceDisk(self.conn)
        old_nvram.path = self._new_guest.os.nvram
        nvram = DeviceDisk(self.conn)
        nvram.path = new_nvram_path
        diskinfo = _CloneDiskInfo(old_nvram)
        allow_create = self._overwrite

        if (allow_create and
            nvram.wants_storage_creation() and
            old_nvram.get_vol_object()):
            # We only run validation if there's some existing nvram we
            # can copy. It's valid for nvram to not exist at VM define
            # time, libvirt will create it for us
            diskinfo.set_clone_path(new_nvram_path, allow_create, self._sparse)
            self._nvram_disk = diskinfo.clone_disk
            self._nvram_disk.get_vol_install().reflink = self._reflink

        self._new_guest.os.nvram = nvram.path


    def prepare(self):
        """
        Validate and set up all parameters needed for the new (clone) VM
        """
        try:
            Guest.validate_name(self.conn, self._new_guest.name,
                                check_collision=not self._replace,
                                validate=False)
        except ValueError as e:
            raise ValueError(_("Invalid name for new guest: %s") % e)

        for diskinfo in self.get_diskinfos_to_clone():
            orig_disk = diskinfo.disk

            if not diskinfo.clone_disk:
                # User didn't set a path, generate one
                newpath = Cloner.generate_clone_disk_path(
                         self.conn, self.src_name,
                         self.new_guest.name,
                         orig_disk.path)
                diskinfo.set_clone_path(newpath,
                        self._overwrite, self._sparse)

            clone_disk = diskinfo.clone_disk
            assert clone_disk
            log.debug("Cloning srcpath=%s dstpath=%s",
                    orig_disk.path, clone_disk.path)

            if self._reflink:
                vol_install = clone_disk.get_vol_install()
                vol_install.reflink = self._reflink

            for disk in self._new_guest.devices.disk:
                if disk.target == orig_disk.target:
                    xmldisk = disk

            # Change the XML
            xmldisk.path = None
            xmldisk.type = clone_disk.type
            xmldisk.driver_name = orig_disk.driver_name
            xmldisk.driver_type = orig_disk.driver_type
            xmldisk.path = clone_disk.path

        if self._new_guest.os.nvram:
            self._prepare_nvram()

        # Save altered clone xml
        log.debug("Clone guest xml is\n%s", self._new_guest.get_xml())

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

            if self._overwrite:
                diskinfos = self.get_diskinfos_to_clone()
                for dst_dev in [d.clone_disk for d in diskinfos]:
                    dst_dev.build_storage(meter)
                if self._nvram_disk:
                    self._nvram_disk.build_storage(meter)
        except Exception as e:
            log.debug("Duplicate failed: %s", str(e))
            if dom:
                dom.undefine()
            raise

        log.debug("Duplicating finished.")
