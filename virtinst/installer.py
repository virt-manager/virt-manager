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

from .devices import DeviceDisk
from .domain import DomainOs


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

        self._tmpfiles = []
        self._tmpvols = []


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

    def alter_bootconfig(self, guest):
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

    def cleanup(self):
        """
        Remove any temporary files retrieved during installation
        """
        for f in self._tmpfiles:
            logging.debug("Removing %s", str(f))
            os.unlink(f)

        for vol in self._tmpvols:
            logging.debug("Removing volume '%s'", vol.name())
            vol.delete(0)

        self._tmpvols = []
        self._tmpfiles = []

    def prepare(self, guest, meter):
        self.cleanup()
        try:
            self._prepare(guest, meter)
        except Exception:
            self.cleanup()
            raise

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
