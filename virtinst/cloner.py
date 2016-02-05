#
# Copyright 2013, 2015 Red Hat, Inc.
# Copyright(c) FUJITSU Limited 2007.
#
# Cloning a virtual machine module.
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
import re
import os

import libvirt

from . import util
from .guest import Guest
from .deviceinterface import VirtualNetworkInterface
from .devicedisk import VirtualDisk
from .storage import StorageVolume
from .devicechar import VirtualChannelDevice


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

        self._force_target = []
        self._skip_target = []
        self._preserve = True
        self._clone_running = False
        self._replace = False
        self._reflink = False

        # Default clone policy for back compat: don't clone readonly,
        # shareable, or empty disks
        self._clone_policy = [self.CLONE_POLICY_NO_READONLY,
                              self.CLONE_POLICY_NO_SHAREABLE,
                              self.CLONE_POLICY_NO_EMPTYMEDIA]

        # Generate a random UUID at the start
        self.clone_uuid = util.generate_uuid(conn)


    # Getter/Setter methods

    def get_original_guest(self):
        return self._original_guest
    def set_original_guest(self, original_guest):
        if self._lookup_vm(original_guest):
            self._original_guest = original_guest
    original_guest = property(get_original_guest, set_original_guest,
                              doc="Original guest name.")

    def set_original_xml(self, val):
        if type(val) is not str:
            raise ValueError(_("Original xml must be a string."))
        self._original_xml = val
        self._original_guest = Guest(self.conn,
                                     parsexml=self._original_xml).name
    def get_original_xml(self):
        return self._original_xml
    original_xml = property(get_original_xml, set_original_xml,
                            doc="XML of the original guest.")

    def get_clone_name(self):
        return self._clone_name
    def set_clone_name(self, name):
        try:
            Guest.validate_name(self.conn, name,
                                check_collision=not self.replace,
                                validate=False)
        except ValueError, e:
            raise ValueError(_("Invalid name for new guest: %s") % e)

        self._clone_name = name
    clone_name = property(get_clone_name, set_clone_name,
                          doc="Name to use for the new guest clone.")

    def set_clone_uuid(self, uuid):
        try:
            util.validate_uuid(uuid)
        except ValueError, e:
            raise ValueError(_("Invalid uuid for new guest: %s") % e)

        if util.vm_uuid_collision(self.conn, uuid):
            raise ValueError(_("UUID '%s' is in use by another guest.") %
                             uuid)
        self._clone_uuid = uuid
    def get_clone_uuid(self):
        return self._clone_uuid
    clone_uuid = property(get_clone_uuid, set_clone_uuid,
                          doc="UUID to use for the new guest clone")

    def set_clone_paths(self, paths):
        disklist = []
        for path in util.listify(paths):
            try:
                device = VirtualDisk.DEVICE_DISK
                if not path:
                    device = VirtualDisk.DEVICE_CDROM

                disk = VirtualDisk(self.conn)
                disk.path = path
                disk.device = device

                if (not self.preserve_dest_disks and
                    disk.wants_storage_creation()):
                    vol_install = VirtualDisk.build_vol_install(
                        self.conn, os.path.basename(disk.path),
                        disk.get_parent_pool(), .000001, False)
                    disk.set_vol_install(vol_install)
                disk.validate()
                disklist.append(disk)
            except Exception, e:
                logging.debug("Error setting clone path.", exc_info=True)
                raise ValueError(_("Could not use path '%s' for cloning: %s") %
                                 (path, str(e)))

        self._clone_disks = disklist
    def get_clone_paths(self):
        return [d.path for d in self.clone_disks]
    clone_paths = property(get_clone_paths, set_clone_paths,
                             doc="Paths to use for the new disk locations.")

    def get_clone_disks(self):
        return self._clone_disks
    clone_disks = property(get_clone_disks,
                           doc="VirtualDisk instances for the new"
                               " disk paths")

    def set_clone_macs(self, mac):
        maclist = util.listify(mac)
        for m in maclist:
            msg = VirtualNetworkInterface.is_conflict_net(self.conn, m)[1]
            if msg:
                raise RuntimeError(msg)

        self._clone_macs = maclist
    def get_clone_macs(self):
        return self._clone_macs
    clone_macs = property(get_clone_macs, set_clone_macs,
                          doc="MAC address for the new guest clone.")

    def get_original_disks(self):
        return self._original_disks
    original_disks = property(get_original_disks,
                              doc="VirtualDisk instances of the "
                                  "original disks being cloned.")

    def get_clone_xml(self):
        return self._clone_xml
    def set_clone_xml(self, clone_xml):
        self._clone_xml = clone_xml
    clone_xml = property(get_clone_xml, set_clone_xml,
                         doc="Generated XML for the guest clone.")

    def get_clone_sparse(self):
        return self._clone_sparse
    def set_clone_sparse(self, flg):
        self._clone_sparse = flg
    clone_sparse = property(get_clone_sparse, set_clone_sparse,
                            doc="Whether to attempt sparse allocation during "
                                "cloning.")

    def get_preserve(self):
        return self._preserve
    def set_preserve(self, flg):
        self._preserve = flg
    preserve = property(get_preserve, set_preserve,
                        doc="If true, preserve ALL original disk devices.")

    def get_preserve_dest_disks(self):
        return not self.preserve
    preserve_dest_disks = property(get_preserve_dest_disks,
                           doc="If true, preserve ALL disk devices for the "
                               "NEW guest. This means no storage cloning. "
                               "This is a convenience access for "
                               "(not Cloner.preserve)")

    def set_force_target(self, dev):
        if type(dev) is list:
            self._force_target = dev[:]
        else:
            self._force_target.append(dev)
    def get_force_target(self):
        return self._force_target
    force_target = property(get_force_target, set_force_target,
                            doc="List of disk targets that we force cloning "
                                "despite Cloner's recommendation.")

    def set_skip_target(self, dev):
        if type(dev) is list:
            self._skip_target = dev[:]
        else:
            self._skip_target.append(dev)
    def get_skip_target(self):
        return self._skip_target
    skip_target = property(get_skip_target, set_skip_target,
                           doc="List of disk targets that we skip cloning "
                               "despite Cloner's recommendation. This "
                               "takes precedence over force_target.")

    def set_clone_policy(self, policy_list):
        if type(policy_list) != list:
            raise ValueError(_("Cloning policy must be a list of rules."))
        self._clone_policy = policy_list
    def get_clone_policy(self):
        return self._clone_policy
    clone_policy = property(get_clone_policy, set_clone_policy,
                            doc="List of policy rules for determining which "
                                "vm disks to clone. See CLONE_POLICY_*")

    def get_clone_running(self):
        return self._clone_running
    def set_clone_running(self, val):
        self._clone_running = bool(val)
    clone_running = property(get_clone_running, set_clone_running,
                             doc="Allow cloning a running VM. If enabled, "
                                 "domain state is not checked before "
                                 "cloning.")

    def _get_replace(self):
        return self._replace
    def _set_replace(self, val):
        self._replace = bool(val)
    replace = property(_get_replace, _set_replace,
                       doc="If enabled, don't check for clone name collision, "
                           "simply undefine any conflicting guest.")
    def _get_reflink(self):
        return self._reflink
    def _set_reflink(self, reflink):
        self._reflink = reflink
    reflink = property(_get_reflink, _set_reflink,
            doc="If true, use COW lightweight copy")

    # Functional methods

    def setup_original(self):
        """
        Validate and setup all parameters needed for the original (cloned) VM
        """
        logging.debug("Validating original guest parameters")

        if self.original_guest is None and self.original_xml is None:
            raise RuntimeError(_("Original guest name or xml is required."))

        if self.original_guest is not None and not self.original_xml:
            self.original_dom = self._lookup_vm(self.original_guest)
            self.original_xml = self.original_dom.XMLDesc(0)

        logging.debug("Original XML:\n%s", self.original_xml)

        self._guest = Guest(self.conn, parsexml=self.original_xml)
        self._guest.id = None
        self._guest.replace = self.replace

        # Pull clonable storage info from the original xml
        self._original_disks = self._get_original_disks_info()

        logging.debug("Original paths: %s",
                      [d.path for d in self.original_disks])
        logging.debug("Original sizes: %s",
                      [d.get_size() for d in self.original_disks])

        # If domain has devices to clone, it must be 'off' or 'paused'
        if (not self.clone_running and
            (self.original_dom and len(self.original_disks) != 0)):
            status = self.original_dom.info()[0]

            if status not in [libvirt.VIR_DOMAIN_SHUTOFF,
                              libvirt.VIR_DOMAIN_PAUSED]:
                raise RuntimeError(_("Domain with devices to clone must be "
                                     "paused or shutoff."))

    def _setup_disk_clone_destination(self, orig_disk, clone_disk):
        """
        Helper that validates the new path location
        """
        if self.preserve_dest_disks:
            return

        if clone_disk.get_vol_object():
            # XXX We could always do this with vol upload?

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
                orig_disk.get_vol_object().storagePoolLookupByVolume().name()):
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

            vol_install.reflink = self.reflink
            clone_disk.set_vol_install(vol_install)
        elif orig_disk.path:
            clone_disk.set_local_disk_to_clone(orig_disk, self.clone_sparse)

        clone_disk.validate()


    def setup_clone(self):
        """
        Validate and set up all parameters needed for the new (clone) VM
        """
        logging.debug("Validating clone parameters.")

        self._clone_xml = self.original_xml

        if len(self.clone_disks) < len(self.original_disks):
            raise ValueError(_("More disks to clone than new paths specified. "
                               "(%(passed)d specified, %(need)d needed") %
                               {"passed" : len(self.clone_disks),
                                "need"   : len(self.original_disks)})

        logging.debug("Clone paths: %s", [d.path for d in self.clone_disks])

        self._guest.name = self._clone_name
        self._guest.uuid = self._clone_uuid
        self._clone_macs.reverse()
        for dev in self._guest.get_devices("graphics"):
            if dev.port and dev.port != -1:
                logging.warn(_("Setting the graphics device port to autoport, "
                               "in order to avoid conflicting."))
                dev.port = -1

        clone_macs = self._clone_macs[:]
        for iface in self._guest.get_devices("interface"):
            iface.target_dev = None

            if clone_macs:
                mac = clone_macs.pop()
            else:
                mac = VirtualNetworkInterface.generate_mac(self.conn)
            iface.macaddr = mac

        # Changing storage XML
        for i in range(len(self._original_disks)):
            orig_disk = self._original_disks[i]
            clone_disk = self._clone_disks[i]

            for disk in self._guest.get_devices("disk"):
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
        for channel in self._guest.get_devices("channel"):
            if channel.type == VirtualChannelDevice.TYPE_UNIX:
                channel.source_path = None

        # Save altered clone xml
        self._clone_xml = self._guest.get_xml_config()
        logging.debug("Clone guest xml is\n%s", self._clone_xml)

    def setup(self):
        """
        Helper function that wraps setup_original and setup_clone, with
        additional debug logging.
        """
        self.setup_original()
        self.setup_clone()

    def start_duplicate(self, meter=None):
        """
        Actually perform the duplication: cloning disks if needed and defining
        the new clone xml.
        """
        logging.debug("Starting duplicate.")
        meter = util.ensure_meter(meter)

        dom = None
        try:
            # Replace orig VM if required
            Guest.check_vm_collision(self.conn, self.clone_name,
                                     do_remove=self.replace)

            # Define domain early to catch any xml errors before duping storage
            dom = self.conn.defineXML(self.clone_xml)

            if self.preserve:
                for dst_dev in self.clone_disks:
                    dst_dev.setup(meter=meter)
        except Exception, e:
            logging.debug("Duplicate failed: %s", str(e))
            if dom:
                dom.undefine()
            raise

        logging.debug("Duplicating finished.")

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
        if origpath.count(".") and len(origpath.rsplit(".", 1)[1]) <= 7:
            path, suffix = origpath.rsplit(".", 1)
            suffix = "." + suffix

        dirname = os.path.dirname(path)
        basename = os.path.basename(path)

        clonebase = basename + "-clone"
        if origname and basename == origname:
            clonebase = newname

        clonebase = os.path.join(dirname, clonebase)
        return util.generate_name(
                    clonebase,
                    lambda p: VirtualDisk.path_definitely_exists(self.conn, p),
                    suffix,
                    lib_collision=False)

    def generate_clone_name(self):
        # If the orig name is "foo-clone", we don't want the clone to be
        # "foo-clone-clone", we want "foo-clone1"
        basename = self.original_guest

        match = re.search("-clone[1-9]*$", basename)
        start_num = 1
        if match:
            num_match = re.search("[1-9]+$", match.group())
            if num_match:
                start_num = int(str(num_match.group()))
            basename = basename.replace(match.group(), "")

        basename = basename + "-clone"
        return util.generate_name(basename,
                                  self.conn.lookupByName,
                                  sep="", start_num=start_num)



    ############################
    # Private helper functions #
    ############################

    # Parse disk paths that need to be cloned from the original guest's xml
    # Return a list of VirtualDisk instances pointing to the original
    # storage
    def _get_original_disks_info(self):
        clonelist = []
        retdisks = []

        for disk in self._guest.get_devices("disk"):
            if self._do_we_clone_device(disk):
                clonelist.append(disk)
                continue

        # Set up virtual disk to encapsulate all relevant path info
        for disk in clonelist:
            validate = not self.preserve_dest_disks

            try:
                device = VirtualDisk.DEVICE_DISK
                if not disk.path:
                    # Tell VirtualDisk we are a cdrom to allow empty media
                    device = VirtualDisk.DEVICE_CDROM

                newd = VirtualDisk(self.conn)
                newd.path = disk.path
                newd.device = device
                newd.driver_name = disk.driver_name
                newd.driver_type = disk.driver_type
                newd.target = disk.target
                if validate:
                    if newd.wants_storage_creation():
                        raise ValueError(_("Disk path '%s' does not exist.") %
                                         newd.path)
            except Exception, e:
                logging.debug("Exception creating clone disk objects",
                    exc_info=True)
                raise ValueError(_("Could not determine original disk "
                                   "information: %s" % str(e)))
            retdisks.append(newd)

        return retdisks

    # Pull disk #i from the original guest xml, return it's source path
    # if it should be cloned
    # Cloning policy based on 'clone_policy', 'force_target' and 'skip_target'
    def _do_we_clone_device(self, disk):
        if not disk.target:
            raise ValueError(_("XML has no 'dev' attribute in disk target"))

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
