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
                (_("Could not remove old vm '%s'") % name) +
                (": " + str(e)))


class Cloner(object):

    # Reasons why we don't default to cloning.
    CLONE_POLICY_NO_READONLY   = 1
    CLONE_POLICY_NO_SHAREABLE  = 2
    CLONE_POLICY_NO_EMPTYMEDIA = 3

    def __init__(self, conn):
        self.conn = conn

        # original guest name or uuid
        self._original_guest = None
        self.original_dom = None
        self._original_disks = []
        self._original_xml = None
        self._guest = None

        # clone guest
        self._clone_name = None
        self._clone_disks = []
        self._clone_macs = []
        self._clone_uuid = None
        self._clone_sparse = True
        self._clone_xml = None
        self.clone_nvram = None
        self._nvram_disk = None

        self._force_target = []
        self._skip_target = []
        self._preserve = True
        self._clone_running = False
        self._replace = False
        self._reflink = False

        # Default clone policy for back compat: don't clone readonly,
        # shareable, or empty disks
        self._clone_policy = []
        self.clone_policy = [self.CLONE_POLICY_NO_READONLY,
                             self.CLONE_POLICY_NO_SHAREABLE,
                             self.CLONE_POLICY_NO_EMPTYMEDIA]

        # Generate a random UUID at the start
        self.clone_uuid = Guest.generate_uuid(conn)


    ##############
    # Properties #
    ##############

    # Original guest name
    def get_original_guest(self):
        return self._original_guest
    def set_original_guest(self, original_guest):
        if self._lookup_vm(original_guest):
            self._original_guest = original_guest
    original_guest = property(get_original_guest, set_original_guest)

    # XML of the original guest
    def set_original_xml(self, val):
        self._original_xml = val
        self._original_guest = Guest(self.conn,
                                     parsexml=self._original_xml).name
    def get_original_xml(self):
        return self._original_xml
    original_xml = property(get_original_xml, set_original_xml)

    # Name to use for the new guest clone
    def get_clone_name(self):
        return self._clone_name
    def set_clone_name(self, name):
        try:
            Guest.validate_name(self.conn, name,
                                check_collision=not self.replace,
                                validate=False)
        except ValueError as e:
            raise ValueError(_("Invalid name for new guest: %s") % e)

        self._clone_name = name
    clone_name = property(get_clone_name, set_clone_name)

    # UUID to use for the new guest clone
    def set_clone_uuid(self, uuid):
        self._clone_uuid = uuid
    def get_clone_uuid(self):
        return self._clone_uuid
    clone_uuid = property(get_clone_uuid, set_clone_uuid)

    # Paths to use for the new disk locations
    def set_clone_paths(self, paths):
        disklist = []
        for path in xmlutil.listify(paths):
            try:
                device = DeviceDisk.DEVICE_DISK
                if not path:
                    device = DeviceDisk.DEVICE_CDROM

                disk = DeviceDisk(self.conn)
                disk.path = path
                disk.device = device

                if (not self.preserve_dest_disks and
                    disk.wants_storage_creation()):
                    vol_install = DeviceDisk.build_vol_install(
                        self.conn, os.path.basename(disk.path),
                        disk.get_parent_pool(), .000001, False)
                    disk.set_vol_install(vol_install)
                disk.validate()
                disklist.append(disk)
            except Exception as e:
                log.debug("Error setting clone path.", exc_info=True)
                raise ValueError(
                        (_("Could not use path '%s' for cloning") % path) +
                        (": " + str(e)))

        self._clone_disks = disklist
    def get_clone_paths(self):
        return [d.path for d in self.clone_disks]
    clone_paths = property(get_clone_paths, set_clone_paths)

    # DeviceDisk instances for the new disk paths
    @property
    def clone_disks(self):
        return self._clone_disks

    # MAC address for the new guest clone
    def set_clone_macs(self, mac):
        self._clone_macs = xmlutil.listify(mac)
    def get_clone_macs(self):
        return self._clone_macs
    clone_macs = property(get_clone_macs, set_clone_macs)

    # DeviceDisk instances of the original disks being cloned
    @property
    def original_disks(self):
        return self._original_disks

    # Generated XML for the guest clone
    def get_clone_xml(self):
        return self._clone_xml
    def set_clone_xml(self, clone_xml):
        self._clone_xml = clone_xml
    clone_xml = property(get_clone_xml, set_clone_xml)

    # Whether to attempt sparse allocation during cloning
    def get_clone_sparse(self):
        return self._clone_sparse
    def set_clone_sparse(self, flg):
        self._clone_sparse = flg
    clone_sparse = property(get_clone_sparse, set_clone_sparse)

    # If true, preserve ALL original disk devices
    def get_preserve(self):
        return self._preserve
    def set_preserve(self, flg):
        self._preserve = flg
    preserve = property(get_preserve, set_preserve)

    # If true, preserve ALL disk devices for the NEW guest.
    # This means no storage cloning.
    # This is a convenience access for not Cloner.preserve
    @property
    def preserve_dest_disks(self):
        return not self.preserve

    # List of disk targets that we force cloning despite
    # Cloner's recommendation
    def set_force_target(self, dev):
        if isinstance(dev, list):
            self._force_target = dev[:]
        else:
            self._force_target.append(dev)
    def get_force_target(self):
        return self._force_target
    force_target = property(get_force_target, set_force_target)

    # List of disk targets that we skip cloning despite Cloner's
    # recommendation. This takes precedence over force_target.")
    def set_skip_target(self, dev):
        if isinstance(dev, list):
            self._skip_target = dev[:]
        else:
            self._skip_target.append(dev)
    def get_skip_target(self):
        return self._skip_target
    skip_target = property(get_skip_target, set_skip_target)

    # List of policy rules for determining which vm disks to clone.
    # See CLONE_POLICY_*
    def set_clone_policy(self, policy_list):
        self._clone_policy = policy_list
    def get_clone_policy(self):
        return self._clone_policy
    clone_policy = property(get_clone_policy, set_clone_policy)

    # Allow cloning a running VM. If enabled, domain state is not
    # checked before cloning.
    def get_clone_running(self):
        return self._clone_running
    def set_clone_running(self, val):
        self._clone_running = bool(val)
    clone_running = property(get_clone_running, set_clone_running)

    # If enabled, don't check for clone name collision, simply undefine
    # any conflicting guest.
    def _get_replace(self):
        return self._replace
    def _set_replace(self, val):
        self._replace = bool(val)
    replace = property(_get_replace, _set_replace)

    # If true, use COW lightweight copy
    def _get_reflink(self):
        return self._reflink
    def _set_reflink(self, reflink):
        self._reflink = reflink
    reflink = property(_get_reflink, _set_reflink)


    ######################
    # Functional methods #
    ######################

    def setup_original(self):
        """
        Validate and setup all parameters needed for the original (cloned) VM
        """
        log.debug("Validating original guest parameters")

        if self.original_guest is None and self.original_xml is None:
            raise RuntimeError(_("Original guest name or XML is required."))

        if self.original_guest is not None and not self.original_xml:
            self.original_dom = self._lookup_vm(self.original_guest)
            flags = libvirt.VIR_DOMAIN_XML_SECURE
            self.original_xml = self.original_dom.XMLDesc(flags)

        log.debug("Original XML:\n%s", self.original_xml)

        self._guest = Guest(self.conn, parsexml=self.original_xml)
        self._guest.id = None

        # Pull clonable storage info from the original xml
        self._original_disks = self._get_original_disks_info()

        log.debug("Original paths: %s",
                      [d.path for d in self.original_disks])
        log.debug("Original sizes: %s",
                      [d.get_size() for d in self.original_disks])

        if not self.clone_running and self.original_dom:
            status = self.original_dom.info()[0]
            if status not in [libvirt.VIR_DOMAIN_SHUTOFF]:
                raise RuntimeError(_("Domain to clone must be shutoff."))

    def _setup_disk_clone_destination(self, orig_disk, clone_disk):
        """
        Helper that validates the new path location
        """
        if self.preserve_dest_disks:
            return

        if clone_disk.get_vol_object():
            # Special case: non remote cloning of a guest using
            # managed block devices: fall back to local cloning if
            # we have permissions to do so. This validation check
            # caused a few bug reports in a short period of time,
            # so must be a common case.
            if (self.conn.is_remote() or
                clone_disk.type != clone_disk.TYPE_BLOCK or
                not orig_disk.path or
                not os.access(orig_disk.path, os.R_OK) or
                not clone_disk.path or
                not os.access(clone_disk.path, os.W_OK)):
                raise RuntimeError(
                    _("Clone onto existing storage volume is not "
                      "currently supported: '%s'") % clone_disk.path)

        # Setup proper cloning inputs for the new virtual disks
        if (orig_disk.get_vol_object() and
            clone_disk.get_vol_install()):
            clone_vol_install = clone_disk.get_vol_install()

            # Source and dest are managed. If they share the same pool,
            # replace vol_install with a CloneVolume instance, otherwise
            # simply set input_vol on the dest vol_install
            if (clone_vol_install.pool.name() ==
                orig_disk.get_parent_pool().name()):
                vol_install = StorageVolume(self.conn)
                vol_install.input_vol = orig_disk.get_vol_object()
                vol_install.sync_input_vol()
                vol_install.name = clone_vol_install.name
            else:
                # Cross pool cloning
                # Sync only the format of the image.
                clone_vol_install.input_vol = orig_disk.get_vol_object()
                vol_install = clone_vol_install
                vol_install.input_vol = orig_disk.get_vol_object()
                vol_install.sync_input_vol(only_format=True)

            if not self.clone_sparse:
                vol_install.allocation = vol_install.capacity
            vol_install.reflink = self.reflink
            clone_disk.set_vol_install(vol_install)
        elif orig_disk.path:
            clone_disk.set_local_disk_to_clone(orig_disk, self.clone_sparse)

        clone_disk.validate()


    def _prepare_nvram(self):
        if self.clone_nvram is None:
            nvram_dir = os.path.dirname(self._guest.os.nvram)
            self.clone_nvram = os.path.join(nvram_dir,
                                            "%s_VARS.fd" % self._clone_name)

        old_nvram = DeviceDisk(self.conn)
        old_nvram.path = self._guest.os.nvram

        nvram = DeviceDisk(self.conn)
        nvram.path = self.clone_nvram

        if (not self.preserve_dest_disks and
            nvram.wants_storage_creation() and
            old_nvram.get_vol_object()):

            nvram_install = DeviceDisk.build_vol_install(
                    self.conn, os.path.basename(nvram.path),
                    nvram.get_parent_pool(), nvram.get_size(), False)
            nvram_install.input_vol = old_nvram.get_vol_object()
            nvram_install.sync_input_vol(only_format=True)
            nvram_install.reflink = self.reflink
            nvram.set_vol_install(nvram_install)

            nvram.validate()
            self._nvram_disk = nvram

        self._guest.os.nvram = nvram.path


    def setup_clone(self):
        """
        Validate and set up all parameters needed for the new (clone) VM
        """
        log.debug("Validating clone parameters.")

        self._clone_xml = self.original_xml

        if len(self.clone_disks) < len(self.original_disks):
            raise ValueError(_("More disks to clone than new paths specified. "
                               "(%(passed)d specified, %(need)d needed") %
                               {"passed": len(self.clone_disks),
                                "need": len(self.original_disks)})

        log.debug("Clone paths: %s", [d.path for d in self.clone_disks])

        self._guest.name = self._clone_name
        self._guest.uuid = self._clone_uuid
        self._guest.title = None

        self._clone_macs.reverse()
        for dev in self._guest.devices.graphics:
            if dev.port and dev.port != -1:
                log.warning(_("Setting the graphics device port to autoport, "
                               "in order to avoid conflicting."))
                dev.port = -1

        clone_macs = self._clone_macs[:]
        for iface in self._guest.devices.interface:
            iface.target_dev = None

            if clone_macs:
                mac = clone_macs.pop()
            else:
                mac = DeviceInterface.generate_mac(self.conn)
            iface.macaddr = mac

        # Changing storage XML
        for i, orig_disk in enumerate(self._original_disks):
            clone_disk = self._clone_disks[i]

            for disk in self._guest.devices.disk:
                if disk.target == orig_disk.target:
                    xmldisk = disk

            self._setup_disk_clone_destination(orig_disk, clone_disk)

            # Change the XML
            xmldisk.path = None
            xmldisk.type = clone_disk.type
            xmldisk.driver_name = orig_disk.driver_name
            xmldisk.driver_type = orig_disk.driver_type
            xmldisk.path = clone_disk.path

        # For guest agent channel, remove a path to generate a new one with
        # new guest name
        for channel in self._guest.devices.channel:
            if (channel.type == DeviceChannel.TYPE_UNIX and
                channel.target_name and channel.source.path and
                channel.target_name in channel.source.path):
                channel.source.path = None

        if self._guest.os.nvram:
            self._prepare_nvram()

        # Save altered clone xml
        self._clone_xml = self._guest.get_xml()
        log.debug("Clone guest xml is\n%s", self._clone_xml)

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
            if self.replace:
                _replace_vm(self.conn, self.clone_name)

            # Define domain early to catch any xml errors before duping storage
            dom = self.conn.defineXML(self.clone_xml)

            if self.preserve:
                for dst_dev in self.clone_disks:
                    dst_dev.build_storage(meter)
                if self._nvram_disk:
                    self._nvram_disk.build_storage(meter)
        except Exception as e:
            log.debug("Duplicate failed: %s", str(e))
            if dom:
                dom.undefine()
            raise

        log.debug("Duplicating finished.")

    def generate_clone_disk_path(self, origpath, newname=None):
        origname = self.original_guest
        newname = newname or self.clone_name
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
            return DeviceDisk.path_definitely_exists(self.conn, p)
        return generatename.generate_name(clonebase, cb, suffix=suffix)

    def generate_clone_name(self, basename=None):
        # If the orig name is "foo-clone", we don't want the clone to be
        # "foo-clone-clone", we want "foo-clone1"
        if not basename:
            basename = self.original_guest

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
                self.conn.lookupByName, n)
        basename = basename + "-clone"
        return generatename.generate_name(basename, cb,
                sep="", start_num=start_num, force_num=force_num)


    ############################
    # Private helper functions #
    ############################

    # Parse disk paths that need to be cloned from the original guest's xml
    # Return a list of DeviceDisk instances pointing to the original
    # storage
    def _get_original_disks_info(self):
        clonelist = []
        retdisks = []

        for disk in self._guest.devices.disk:
            if self._do_we_clone_device(disk):
                clonelist.append(disk)
                continue

        # Set up virtual disk to encapsulate all relevant path info
        for disk in clonelist:
            validate = not self.preserve_dest_disks

            try:
                device = DeviceDisk.DEVICE_DISK
                if not disk.path:
                    # Tell DeviceDisk we are a cdrom to allow empty media
                    device = DeviceDisk.DEVICE_CDROM

                newd = DeviceDisk(self.conn)
                newd.path = disk.path
                newd.device = device
                newd.driver_name = disk.driver_name
                newd.driver_type = disk.driver_type
                newd.target = disk.target
                if validate:
                    if newd.wants_storage_creation():
                        raise ValueError(_("Disk path '%s' does not exist.") %
                                         newd.path)
            except Exception as e:
                log.debug("Exception creating clone disk objects",
                    exc_info=True)
                raise ValueError(_("Could not determine original disk "
                                   "information: %s" % str(e)))
            retdisks.append(newd)

        return retdisks

    # Pull disk #i from the original guest xml, return it's source path
    # if it should be cloned
    # Cloning policy based on 'clone_policy', 'force_target' and 'skip_target'
    def _do_we_clone_device(self, disk):
        if disk.target in self.skip_target:
            return False

        if disk.target in self.force_target:
            return True

        # No media path
        if (not disk.path and
            self.CLONE_POLICY_NO_EMPTYMEDIA in self.clone_policy):
            return False

        # Readonly disks
        if (disk.read_only and
            self.CLONE_POLICY_NO_READONLY in self.clone_policy):
            return False

        # Shareable disks
        if (disk.shareable and
            self.CLONE_POLICY_NO_SHAREABLE in self.clone_policy):
            return False

        return True

    # Simple wrapper for checking a vm exists and returning the domain
    def _lookup_vm(self, name):
        try:
            return self.conn.lookupByName(name)
        except libvirt.libvirtError:
            raise ValueError(_("Domain '%s' was not found.") % str(name))
