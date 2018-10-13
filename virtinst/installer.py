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
from .installertreemedia import InstallerTreeMedia
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
    def __init__(self, conn, cdrom=None, location=None, install_bootdev=None):
        self.conn = conn

        self.livecd = False
        self.extra_args = []

        # Entry point for virt-manager 'Customize' wizard to change autostart
        self.autostart = False

        self._install_bootdev = install_bootdev
        self._install_kernel = None
        self._install_initrd = None
        self._install_cdrom_device = None
        self._defaults_are_set = False

        self._cdrom = None
        self._treemedia = None
        if cdrom:
            cdrom = InstallerTreeMedia.validate_path(self.conn, cdrom)
            self._cdrom = cdrom
            self._install_bootdev = "cdrom"
        if location:
            self._treemedia = InstallerTreeMedia(self.conn, location)


    ###################
    # Private helpers #
    ###################

    def _cdrom_path(self):
        if self._treemedia:
            return self._treemedia.cdrom_path()
        return self._cdrom

    def _add_install_cdrom_device(self, guest):
        if self._install_cdrom_device:
            return
        if not bool(self._cdrom_path()):
            return

        dev = DeviceDisk(self.conn)
        dev.device = dev.DEVICE_CDROM
        dev.path = self._cdrom_path()
        dev.sync_path_props()
        dev.validate()
        self._install_cdrom_device = dev

        # Insert the CDROM before any other CDROM, so boot=cdrom picks
        # it as the priority
        for idx, disk in enumerate(guest.devices.disk):
            if disk.is_cdrom():
                guest.devices.add_child(self._install_cdrom_device, idx=idx)
                return
        guest.add_device(self._install_cdrom_device)

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

    def _can_set_guest_bootorder(self, guest):
        return (not guest.os.is_container() and
            not guest.os.kernel and
            not any([d.boot.order for d in guest.devices.get_all()]))

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
        if self.extra_args:
            guest.os.kernel_args = " ".join(self.extra_args)

        bootdev = self._install_bootdev
        if bootdev and self._can_set_guest_bootorder(guest):
            guest.os.bootorder = self._build_boot_order(guest, bootdev)
        else:
            guest.os.bootorder = []


    ##########################
    # Internal API overrides #
    ##########################

    def _prepare(self, guest, meter):
        if self._treemedia:
            k, i, a = self._treemedia.prepare(guest, meter)
            self._install_kernel = k
            self._install_initrd = i
            if a and "VIRTINST_INITRD_TEST" not in os.environ:
                self.extra_args.append(a)

    def _cleanup(self, guest):
        if self._treemedia:
            self._treemedia.cleanup(guest)

    def _get_postinstall_bootdev(self, guest):
        if self.cdrom and self.livecd:
            return DomainOs.BOOT_DEVICE_CDROM

        if self._install_bootdev:
            if any([d for d in guest.devices.disk
                    if d.device == d.DEVICE_DISK]):
                return DomainOs.BOOT_DEVICE_HARDDISK
            return self._install_bootdev

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

    @property
    def location(self):
        if self._treemedia:
            return self._treemedia.location

    @property
    def cdrom(self):
        return self._cdrom

    def set_initrd_injections(self, initrd_injections):
        if self._treemedia:
            self._treemedia.initrd_injections = initrd_injections

    def set_install_defaults(self, guest):
        """
        Allow API users to set defaults ahead of time if they want it.
        Used by vmmDomainVirtinst so the 'Customize before install' dialog
        shows accurate values.

        If the user doesn't explicitly call this, it will be called by
        start_install()
        """
        if self._defaults_are_set:
            return

        self._add_install_cdrom_device(guest)

        if not guest.os.bootorder and self._can_set_guest_bootorder(guest):
            bootdev = self._get_postinstall_bootdev(guest)
            guest.os.bootorder = self._build_boot_order(guest, bootdev)

        guest.set_defaults(None)
        self._defaults_are_set = True

    def scratchdir_required(self):
        """
        Returns true if scratchdir is needed for the passed install parameters.
        Apps can use this to determine if they should attempt to ensure
        scratchdir permissions are adequate
        """
        return bool(self._treemedia)

    def has_install_phase(self):
        """
        Return True if the requested setup is actually installing an OS
        into the guest. Things like LiveCDs, Import, or a manually specified
        bootorder do not have an install phase.
        """
        if self.cdrom and self.livecd:
            return False
        return bool(self._cdrom or
                    self._install_bootdev or
                    self._treemedia)

    def check_location(self, guest):
        """
        Validate self.location seems to work. This will might hit the
        network so we don't want to do it on demand.
        """
        if self._treemedia:
            return self._treemedia.check_location(guest)
        return True

    def detect_distro(self, guest):
        """
        Attempt to detect the distro for the Installer's 'location'. If
        an error is encountered in the detection process (or if detection
        is not relevant for the Installer type), None is returned.

        :returns: distro variant string, or None
        """
        ret = None
        try:
            if self._treemedia:
                ret = self._treemedia.detect_distro(guest)
            elif self.cdrom:
                ret = InstallerTreeMedia.detect_iso_distro(guest, self.cdrom)
            else:
                logging.debug("No media for distro detection.")
        except Exception:
            logging.debug("Error attempting to detect distro.", exc_info=True)

        logging.debug("installer.detect_distro returned=%s", ret)
        return ret


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
            ret = guest.get_xml()
            return ret
        finally:
            self._remove_install_cdrom_media(guest)
            self._finish_get_install_xml(guest, data)

    def _build_xml(self, guest):
        install_xml = None
        if self.has_install_phase():
            install_xml = self._get_install_xml(guest)
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

        try:
            logging.debug("XML fetched from libvirt object:\n%s",
                          domain.XMLDesc(0))
        except Exception as e:
            logging.debug("Error fetching XML from libvirt object: %s", e)
        return domain

    def _flag_autostart(self, domain):
        """
        Set the autostart flag for domain if the user requested it
        """
        try:
            domain.setAutostart(True)
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
        Begin the guest install. Will add install media to the guest config,
        launch it, then redefine the XML with the postinstall config.

        :param return_xml: Don't create the guest, just return generated XML
        """
        guest.validate_name(guest.conn, guest.name)
        self.set_install_defaults(guest)

        try:
            self._cleanup(guest)
            self._prepare(guest, meter)

            if not dry:
                for dev in guest.devices.disk:
                    dev.build_storage(meter)

            install_xml, final_xml = self._build_xml(guest)
            if return_xml:
                return (install_xml, final_xml)
            if dry:
                return

            domain = self._create_guest(
                    guest, meter, install_xml, final_xml,
                    doboot, transient)

            if self.autostart:
                self._flag_autostart(domain)
            return domain
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
