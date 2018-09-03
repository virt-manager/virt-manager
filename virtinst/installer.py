#
# Common code for all guests
#
# Copyright 2006-2009, 2013 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import logging

import libvirt

from .devices import DeviceDisk
from .domain import DomainOs
from . import util


class Installer(object):
    """
    Installer classes attempt to encapsulate all the parameters needed
    to 'install' a guest: essentially, booting the guest with the correct
    media for the OS install phase (if there is one), and setting up the
    guest to boot to the correct media for all subsequent runs.

    Some of the actual functionality:

        - Determining what type of install media has been requested, and
          representing it correctly to the Guest

        - Fetching install kernel/initrd or boot.iso from a URL

        - Setting the boot device as appropriate depending on whether we
          are booting into an OS install, or booting post-install

    Some of the information that the Installer needs to know to accomplish
    this:

        - Install media location (could be a URL, local path, ...)
        - Virtualization type (parameter 'os_type') ('xen', 'hvm', etc.)
        - Hypervisor name (parameter 'type') ('qemu', 'kvm', 'xen', etc.)
        - Guest architecture ('i686', 'x86_64')
    """
    def __init__(self, conn):
        self.conn = conn
        self._location = None

        self.cdrom = False
        self.livecd = False
        self.extraargs = []

        self.initrd_injections = []

        self._install_kernel = None
        self._install_initrd = None
        self._install_cdrom_device = None

        self._tmpfiles = []
        self._tmpvols = []

        self.domain = None
        self.autostart = False
        self.replace = False


    #########################
    # Properties properties #
    #########################

    def get_location(self):
        return self._location
    def set_location(self, val):
        self._location = self._validate_location(val)
    location = property(get_location, set_location)


    ###################
    # Private helpers #
    ###################

    def _add_install_cdrom_device(self, guest):
        if self._install_cdrom_device:
            return
        if not self.needs_cdrom():
            return

        dev = DeviceDisk(self.conn)
        dev.device = dev.DEVICE_CDROM
        self._install_cdrom_device = dev
        guest.add_device(dev)

    def _insert_install_cdrom_media(self, guest):
        ignore = guest
        if not self._install_cdrom_device:
            return
        self._install_cdrom_device.path = self.cdrom_path()
        self._install_cdrom_device.sync_path_props()
        self._install_cdrom_device.validate()

    def _remove_install_cdrom_media(self, guest):
        if not self._install_cdrom_device:
            return
        if self.livecd:
            return
        if guest.osinfo.is_windows():
            # Keep media attached for windows which has a multi stage install
            return
        self._install_cdrom_device.path = None
        self._install_cdrom_device.sync_path_props()

    def _build_boot_order(self, guest, bootdev):
        bootorder = [bootdev]

        # If guest has an attached disk, always have 'hd' in the boot
        # list, so disks are marked as bootable/installable (needed for
        # windows virtio installs, and booting local disk from PXE)
        for disk in guest.devices.disk:
            if disk.device == disk.DEVICE_DISK:
                bootdev = "hd"
                if bootdev not in bootorder:
                    bootorder.append(bootdev)
                break
        return bootorder

    def _alter_bootconfig(self, guest):
        """
        Generate the portion of the guest xml that determines boot devices
        and parameters. (typically the <os></os> block)

        :param guest: Guest instance we are installing
        """
        guest.on_reboot = "destroy"

        if self._install_kernel:
            guest.os.kernel = self._install_kernel
        if self._install_initrd:
            guest.os.initrd = self._install_initrd
        if self.extraargs:
            guest.os.kernel_args = " ".join(self.extraargs)

        bootdev = self._get_install_bootdev(guest)
        if (bootdev and
            not guest.os.is_container() and
            not guest.os.kernel and
            not any(d.boot.order for d in guest.devices.get_all())):
            guest.os.bootorder = self._build_boot_order(guest, bootdev)
        else:
            guest.os.bootorder = []


    ##########################
    # Internal API overrides #
    ##########################

    def _validate_location(self, val):
        return val

    def _prepare(self, guest, meter):
        ignore = guest
        ignore = meter

    def _cleanup(self, guest):
        ignore = guest
        for f in self._tmpfiles:
            logging.debug("Removing %s", str(f))
            os.unlink(f)

        for vol in self._tmpvols:
            logging.debug("Removing volume '%s'", vol.name())
            vol.delete(0)

        self._tmpvols = []
        self._tmpfiles = []

    def _get_install_bootdev(self, guest):
        ignore = guest
        return None

    def _get_postinstall_bootdev(self, guest):
        device = guest.devices.disk and guest.devices.disk[0].device or None
        if device == DeviceDisk.DEVICE_DISK:
            return DomainOs.BOOT_DEVICE_HARDDISK
        elif device == DeviceDisk.DEVICE_CDROM:
            return DomainOs.BOOT_DEVICE_CDROM
        elif device == DeviceDisk.DEVICE_FLOPPY:
            return DomainOs.BOOT_DEVICE_FLOPPY
        return DomainOs.BOOT_DEVICE_HARDDISK


    ##############
    # Public API #
    ##############

    def get_postinstall_bootorder(self, guest):
        """
        Return the preferred guest postinstall bootorder
        """
        bootdev = self._get_postinstall_bootdev(guest)
        return self._build_boot_order(guest, bootdev)

    def scratchdir_required(self):
        """
        Returns true if scratchdir is needed for the passed install parameters.
        Apps can use this to determine if they should attempt to ensure
        scratchdir permissions are adequate
        """
        return False

    def has_install_phase(self):
        """
        Return True if the requested setup is actually installing an OS
        into the guest. Things like LiveCDs, Import, or a manually specified
        bootorder do not have an install phase.
        """
        return False

    def needs_cdrom(self):
        """
        If this installer uses cdrom media, so it needs a cdrom device
        attached to the VM
        """
        return False

    def cdrom_path(self):
        """
        Return the cdrom path needed for needs_cdrom() installs
        """
        return None

    def check_location(self, guest):
        """
        Validate self.location seems to work. This will might hit the
        network so we don't want to do it on demand.
        """
        ignore = guest
        return True

    def detect_distro(self, guest):
        """
        Attempt to detect the distro for the Installer's 'location'. If
        an error is encountered in the detection process (or if detection
        is not relevant for the Installer type), None is returned.

        :returns: distro variant string, or None
        """
        ignore = guest
        logging.debug("distro detection not available for this installer.")
        return None


    ##########################
    # guest install handling #
    ##########################

    def _prepare_get_install_xml(self, guest):
        # We do a shallow copy of the OS block here, so that we can
        # set the install time properties but not permanently overwrite
        # any config the user explicitly requested.
        data = (guest.os.bootorder, guest.os.kernel, guest.os.initrd,
                guest.os.kernel_args, guest.on_reboot)
        return data

    def _finish_get_install_xml(self, guest, data):
        (guest.os.bootorder, guest.os.kernel, guest.os.initrd,
                guest.os.kernel_args, guest.on_reboot) = data

    def _get_install_xml(self, guest):
        data = self._prepare_get_install_xml(guest)
        try:
            self._alter_bootconfig(guest)
            self._insert_install_cdrom_media(guest)
            ret = guest.get_xml()
            return ret
        finally:
            self._remove_install_cdrom_media(guest)
            self._finish_get_install_xml(guest, data)


    def _build_xml(self, guest):
        install_xml = None
        if self.has_install_phase():
            install_xml = self._get_install_xml(guest)
        else:
            self._insert_install_cdrom_media(guest)
        final_xml = guest.get_xml()

        logging.debug("Generated install XML: %s",
            (install_xml and ("\n" + install_xml) or "None required"))
        logging.debug("Generated boot XML: \n%s", final_xml)

        return install_xml, final_xml

    def _manual_transient_create(self, install_xml, final_xml, needs_boot):
        """
        For hypervisors (like vz) that don't implement createXML,
        we need to define+start, and undefine on start failure
        """
        domain = self.conn.defineXML(install_xml or final_xml)
        if not needs_boot:
            return domain

        # Handle undefining the VM if the initial startup fails
        try:
            domain.create()
        except Exception:
            try:
                domain.undefine()
            except Exception:
                pass
            raise

        if install_xml and install_xml != final_xml:
            domain = self.conn.defineXML(final_xml)
        return domain

    def _create_guest(self, guest,
                      meter, install_xml, final_xml, doboot, transient):
        """
        Actually do the XML logging, guest defining/creating

        :param doboot: Boot guest even if it has no install phase
        """
        meter_label = _("Creating domain...")
        meter = util.ensure_meter(meter)
        meter.start(size=None, text=meter_label)
        needs_boot = doboot or self.has_install_phase()

        if guest.type == "vz":
            if transient:
                raise RuntimeError(_("Domain type 'vz' doesn't support "
                    "transient installs."))
            domain = self._manual_transient_create(
                    install_xml, final_xml, needs_boot)

        else:
            if transient or needs_boot:
                domain = self.conn.createXML(install_xml or final_xml, 0)
            if not transient:
                domain = self.conn.defineXML(final_xml)

        self.domain = domain
        try:
            logging.debug("XML fetched from libvirt object:\n%s",
                          self.domain.XMLDesc(0))
        except Exception as e:
            logging.debug("Error fetching XML from libvirt object: %s", e)


    def _flag_autostart(self):
        """
        Set the autostart flag for self.domain if the user requested it
        """
        if not self.autostart:
            return

        try:
            self.domain.setAutostart(True)
        except libvirt.libvirtError as e:
            if util.is_error_nosupport(e):
                logging.warning("Could not set autostart flag: libvirt "
                             "connection does not support autostart.")
            else:
                raise e


    ######################
    # Public install API #
    ######################

    def start_install(self, guest, meter=None,
                      dry=False, return_xml=False,
                      doboot=True, transient=False):
        """
        Begin the guest install (stage1).
        :param return_xml: Don't create the guest, just return generated XML
        """
        if self.domain is not None:
            raise RuntimeError(_("Domain has already been started!"))

        self._add_install_cdrom_device(guest)
        guest.set_install_defaults()

        try:
            self._cleanup(guest)
            self._prepare(guest, meter)

            # Create devices if required (disk images, etc.)
            if not dry:
                for dev in guest.devices.get_all():
                    dev.setup(meter)

            install_xml, final_xml = self._build_xml(guest)
            if return_xml:
                return (install_xml, final_xml)
            if dry:
                return

            # Remove existing VM if requested
            guest.check_vm_collision(self.conn, guest.name,
                                     do_remove=self.replace)

            self._create_guest(guest, meter, install_xml, final_xml,
                               doboot, transient)

            # Set domain autostart flag if requested
            self._flag_autostart()
        finally:
            self._cleanup(guest)

    def get_created_disks(self, guest):
        return [d for d in guest.devices.disk if d.storage_was_created]

    def cleanup_created_disks(self, guest, meter):
        """
        Remove any disks we created as part of the install. Only ever
        called by clients.
        """
        clean_disks = self.get_created_disks(guest)
        if not clean_disks:
            return

        for disk in clean_disks:
            logging.debug("Removing created disk path=%s vol_object=%s",
                disk.path, disk.get_vol_object())
            name = os.path.basename(disk.path)

            try:
                meter.start(size=None, text=_("Removing disk '%s'") % name)

                if disk.get_vol_object():
                    disk.get_vol_object().delete()
                else:
                    os.unlink(disk.path)

                meter.end(0)
            except Exception as e:
                logging.debug("Failed to remove disk '%s'",
                    name, exc_info=True)
                logging.error("Failed to remove disk '%s': %s", name, e)


class PXEInstaller(Installer):
    def _get_install_bootdev(self, guest):
        ignore = guest
        return DomainOs.BOOT_DEVICE_NETWORK

    def _get_postinstall_bootdev(self, guest):
        if any([d for d in guest.devices.disk if d.device == d.DEVICE_DISK]):
            return DomainOs.BOOT_DEVICE_HARDDISK
        return DomainOs.BOOT_DEVICE_NETWORK

    def has_install_phase(self):
        return True
