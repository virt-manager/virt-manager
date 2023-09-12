#
# Common code for all guests
#
# Copyright 2006-2009, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from . import cloudinit
from . import unattended
from . import volumeupload
from .installertreemedia import InstallerTreeMedia
from .installerinject import perform_cdrom_injections
from ..domain import DomainOs
from ..devices import DeviceDisk
from ..guest import Guest
from ..osdict import OSDB
from ..logger import log
from .. import progress
from .. import xmlutil


def _make_testsuite_path(path):
    return os.path.join("/VIRTINST-TESTSUITE",
            os.path.basename(path).split("-", 2)[-1])


class Installer(object):
    """
    Class for kicking off VM installs. The VM is set up separately in a Guest
    instance. This class tracks the install media/bootdev choice, alters the
    Guest XML, boots it for the install, then saves the post install XML
    config. The Guest is passed in via start_install, only install media
    selection is done at __init__ time

    :param cdrom: Path to a cdrom device or iso. Maps to virt-install --cdrom
    :param location: An install tree URI, local directory, or ISO/CDROM path.
        Largely handled by installtreemedia helper class. Maps to virt-install
        --location
    :param location_kernel: URL pointing to a kernel to fetch, or a relative
        path to indicate where the kernel is stored in location
    :param location_initrd: location_kernel, but pointing to an initrd
    :param install_kernel: Kernel to install off of
    :param install_initrd: Initrd to install off of
    :param install_kernel_args: Kernel args <cmdline> to use. This overwrites
        whatever the installer might request, unlike extra_args which will
        append arguments.
    :param no_install: If True, this installer specifically does not have
        an install phase. We are just using it to create the initial XML.
    """
    def __init__(self, conn, cdrom=None, location=None, install_bootdev=None,
            location_kernel=None, location_initrd=None,
            install_kernel=None, install_initrd=None, install_kernel_args=None,
            no_install=None, is_reinstall=False):
        self.conn = conn

        # Entry point for virt-manager 'Customize' wizard to change autostart
        self.autostart = False

        self._install_cdrom_device_added = False
        self._unattended_install_cdrom_device = None
        self._tmpfiles = []
        self._tmpvols = []
        self._defaults_are_set = False
        self._unattended_data = None
        self._cloudinit_data = None

        self._install_bootdev = install_bootdev
        self._no_install = no_install
        self._is_reinstall = is_reinstall
        self._pre_reinstall_xml = None

        self._treemedia = None
        self._treemedia_bootconfig = None
        self._cdrom = None
        if cdrom:
            cdrom = InstallerTreeMedia.validate_path(self.conn, cdrom)
            self._cdrom = cdrom
            self._install_bootdev = "cdrom"
        elif (location or location_kernel or location_initrd or
              install_kernel or install_initrd):
            self._treemedia = InstallerTreeMedia(self.conn, location,
                    location_kernel, location_initrd,
                    install_kernel, install_initrd, install_kernel_args)


    ##################
    # Static helpers #
    ##################

    @staticmethod
    def cleanup_created_disks(guest, meter):
        """
        Remove any disks we created as part of the install. Only ever
        called by clients.
        """
        clean_disks = [d for d in guest.devices.disk if d.storage_was_created]

        for disk in clean_disks:
            path = disk.get_source_path()
            log.debug("Removing created disk path=%s vol_object=%s",
                path, disk.get_vol_object())
            name = os.path.basename(path)

            try:
                meter.start(_("Removing disk '%s'") % name, None)

                if disk.get_vol_object():
                    disk.get_vol_object().delete()
                else:  # pragma: no cover
                    # This case technically shouldn't happen here, but
                    # it's here in case future assumptions change
                    os.unlink(path)

                meter.end()
            except Exception as e:  # pragma: no cover
                log.debug("Failed to remove disk '%s'",
                    name, exc_info=True)
                log.error("Failed to remove disk '%s': %s", name, e)


    ###################
    # Private helpers #
    ###################

    def _make_cdrom_device(self, path):
        dev = DeviceDisk(self.conn)
        dev.device = dev.DEVICE_CDROM
        dev.set_source_path(path)
        dev.sync_path_props()
        dev.validate()
        return dev

    def _cdrom_path(self):
        if self._treemedia:
            return self._treemedia.cdrom_path()
        return self._cdrom

    def _add_install_cdrom_device(self, guest):
        if self._install_cdrom_device_added:
            return  # pragma: no cover
        if not bool(self._cdrom_path()):
            return

        self._install_cdrom_device_added = True

        if self._is_reinstall:
            cdroms = [d for d in guest.devices.disk if d.is_cdrom()]
            if cdroms:
                dev = cdroms[0]
                dev.set_source_path(self._cdrom_path())
                return

        dev = self._make_cdrom_device(self._cdrom_path())
        if self._is_reinstall:
            dev.set_defaults(guest)

        # Insert the CDROM before any other CDROM, so boot=cdrom picks
        # it as the priority
        for idx, disk in enumerate(guest.devices.disk):
            if disk.is_cdrom():
                guest.devices.add_child(dev, idx=idx)
                return
        guest.add_device(dev)

    def _remove_install_cdrom_media(self, guest):
        if not self._install_cdrom_device_added:
            return
        if guest.osinfo.is_windows():
            # Keep media attached for windows which has a multi stage install
            return
        for disk in guest.devices.disk:
            if (disk.is_cdrom() and
                disk.get_source_path() == self._cdrom_path()):
                disk.set_source_path(None)
                disk.sync_path_props()
                break

    def _add_unattended_install_cdrom_device(self, guest, location):
        if self._unattended_install_cdrom_device:
            return  # pragma: no cover

        dev = self._make_cdrom_device(location)
        dev.set_defaults(guest)
        self._unattended_install_cdrom_device = dev.target
        guest.add_device(dev)

        if self.conn.in_testsuite():
            # Hack to set just the XML path differently for the test suite.
            # Setting this via regular 'path' will error that it doesn't exist
            dev.source.file = _make_testsuite_path(location)

    def _remove_unattended_install_cdrom_device(self, guest):
        if not self._unattended_install_cdrom_device:
            return

        disk = [d for d in guest.devices.disk if
                d.target == self._unattended_install_cdrom_device][0]
        disk.set_source_path(None)
        disk.sync_path_props()

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

    def _alter_treemedia_bootconfig(self, guest):
        if not self._treemedia:
            return

        kernel, initrd, kernel_args = self._treemedia_bootconfig
        if kernel:
            guest.os.kernel = (self.conn.in_testsuite() and
                    _make_testsuite_path(kernel) or kernel)
        if initrd:
            guest.os.initrd = (self.conn.in_testsuite() and
                    _make_testsuite_path(initrd) or initrd)
        if kernel_args:
            guest.os.kernel_args = kernel_args

    def _alter_bootconfig(self, guest):
        """
        Generate the portion of the guest xml that determines boot devices
        and parameters. (typically the <os></os> block)

        :param guest: Guest instance we are installing
        """
        guest.on_reboot = "destroy"
        self._alter_treemedia_bootconfig(guest)

        bootdev = self._install_bootdev
        if bootdev and self._can_set_guest_bootorder(guest):
            guest.os.bootorder = self._build_boot_order(guest, bootdev)
        else:
            guest.os.bootorder = []

    def _alter_install_resources(self, guest, meter):
        """
        Sets the appropriate amount of ram needed when performing a "network"
        based installation

        :param guest: Guest instance we are installing
        """
        if not self._treemedia:
            return
        if not self._treemedia.requires_internet(guest, meter):
            return

        ram = guest.osinfo.get_network_install_required_ram(guest)
        ram = (ram or 0) // 1024
        if ram > guest.currentMemory:
            msg = (_("Overriding memory to %(number)s MiB needed for "
                "%(osname)s network install.") %
                {"number": ram // 1024, "osname": guest.osinfo.name})
            log.warning(msg)
            guest.currentMemory = ram


    ################
    # Internal API #
    ################

    def _should_upload_media(self, guest):
        """
        Return True if we should upload media to the connection scratchdir.
        This doesn't consider if there is any media to upload, just whether
        we _should_ upload if there _is_ media.
        """
        scratchdir = InstallerTreeMedia.make_scratchdir(guest)
        system_scratchdir = InstallerTreeMedia.get_system_scratchdir(guest)

        if self.conn.is_remote():
            return True
        if self.conn.is_unprivileged():
            return False
        if scratchdir == system_scratchdir:
            return False  # pragma: no cover
        return True

    def _upload_media(self, guest, meter, paths):
        system_scratchdir = InstallerTreeMedia.get_system_scratchdir(guest)

        if (not self._should_upload_media(guest) and
            not xmlutil.in_testsuite()):
            # We have access to system scratchdir, don't jump through hoops
            log.debug("Have access to preferred scratchdir so"
                        " nothing to upload")  # pragma: no cover
            return paths  # pragma: no cover

        if not guest.conn.support_remote_url_install():
            # Needed for the test_urls suite
            log.debug("Media upload not supported")  # pragma: no cover
            return paths  # pragma: no cover

        newpaths, tmpvols = volumeupload.upload_paths(
                guest.conn, system_scratchdir, meter, paths)
        self._tmpvols += tmpvols
        return newpaths

    def _prepare_unattended_data(self, guest, meter, scripts):
        scratchdir = InstallerTreeMedia.make_scratchdir(guest)

        injections = []
        for script in scripts:
            expected_filename = script.get_expected_filename()
            unattended_cmdline = script.generate_cmdline()
            log.debug("Generated unattended cmdline: %s", unattended_cmdline)

            scriptpath = script.write()
            self._tmpfiles.append(scriptpath)
            injections.append((scriptpath, expected_filename))

        drivers_location = guest.osinfo.get_pre_installable_drivers_location(
                guest.os.arch)
        drivers = unattended.download_drivers(
                drivers_location, scratchdir, meter)
        injections.extend(drivers)
        self._tmpfiles.extend([driverpair[0] for driverpair in drivers])

        iso = perform_cdrom_injections(injections, scratchdir)
        self._tmpfiles.append(iso)
        iso = self._upload_media(guest, meter, [iso])[0]
        self._add_unattended_install_cdrom_device(guest, iso)

    def _prepare_unattended_scripts(self, guest, meter):
        url = None
        os_tree = None
        if self._treemedia:
            if self._treemedia.is_network_url():
                url = self.location
            os_media = self._treemedia.get_os_media(guest, meter)
            os_tree = self._treemedia.get_os_tree(guest, meter)
            injection_method = "initrd"
        else:
            if not guest.osinfo.is_windows():
                log.warning("Attempting unattended method=cdrom injection "
                        "for a non-windows OS. If this doesn't work, try "
                        "passing install media to --location")
            osguess = OSDB.guess_os_by_iso(self.cdrom)
            os_media = osguess[1] if osguess else None
            injection_method = "cdrom"

        return unattended.prepare_install_scripts(
                guest, self._unattended_data, url,
                os_media, os_tree, injection_method)

    def _prepare_treemedia(self, guest, meter, unattended_scripts):
        kernel, initrd, kernel_args = self._treemedia.prepare(guest, meter,
                unattended_scripts)

        paths = [kernel, initrd]
        kernel, initrd = self._upload_media(guest, meter, paths)
        self._treemedia_bootconfig = (kernel, initrd, kernel_args)

    def _prepare_cloudinit(self, guest, meter):
        scratchdir = InstallerTreeMedia.make_scratchdir(guest)
        filepairs = cloudinit.create_files(scratchdir, self._cloudinit_data)
        for filepair in filepairs:
            self._tmpfiles.append(filepair[0])

        iso = perform_cdrom_injections(filepairs, scratchdir, cloudinit=True)
        self._tmpfiles.append(iso)
        iso = self._upload_media(guest, meter, [iso])[0]
        self._add_unattended_install_cdrom_device(guest, iso)

    def _prepare(self, guest, meter):
        if self._is_reinstall:
            self._pre_reinstall_xml = guest.get_xml()

        unattended_scripts = None
        if self._unattended_data:
            unattended_scripts = self._prepare_unattended_scripts(guest, meter)

        if self._treemedia:
            self._prepare_treemedia(guest, meter, unattended_scripts)

        elif unattended_scripts:
            self._prepare_unattended_data(guest, meter, unattended_scripts)

        elif self._cloudinit_data:
            self._prepare_cloudinit(guest, meter)

    def _cleanup(self, guest):
        if self._treemedia:
            self._treemedia.cleanup(guest)

        for vol in self._tmpvols:
            log.debug("Removing volume '%s'", vol.name())
            vol.delete(0)
        self._tmpvols = []

        for f in self._tmpfiles:
            log.debug("Removing %s", str(f))
            os.unlink(f)
        self._tmpfiles = []

    def _get_postinstall_bootdev(self, guest):
        if self.cdrom and self._no_install:
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
        if not self._treemedia:
            raise RuntimeError("Install method does not support "
                    "initrd injections.")
        self._treemedia.set_initrd_injections(initrd_injections)

    def set_extra_args(self, extra_args):
        if not self._treemedia:
            raise RuntimeError("Kernel arguments are only supported with "
                    "location or kernel installs.")
        self._treemedia.set_extra_args(extra_args)

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
        if self._is_reinstall:
            self._pre_reinstall_xml = guest.get_xml()

        self._add_install_cdrom_device(guest)

        if not guest.os.bootorder and self._can_set_guest_bootorder(guest):
            bootdev = self._get_postinstall_bootdev(guest)
            guest.os.bootorder = self._build_boot_order(guest, bootdev)

        if not self._is_reinstall:
            guest.set_defaults(None)
        self._defaults_are_set = True

    def get_search_paths(self, guest):
        """
        Return a list of paths that the hypervisor will need search access
        for to perform this install.
        """
        search_paths = []
        if ((self._treemedia or
             self._cloudinit_data or
             self._unattended_data) and
             not self._should_upload_media(guest)):
            search_paths.append(InstallerTreeMedia.make_scratchdir(guest))
        if self._cdrom_path():
            search_paths.append(self._cdrom_path())
        return search_paths

    def has_install_phase(self):
        """
        Return True if the requested setup is actually installing an OS
        into the guest. Things like LiveCDs, Import, or a manually specified
        bootorder do not have an install phase.
        """
        if self._no_install:
            return False
        return bool(self._cdrom or
                    self._install_bootdev or
                    self._treemedia)

    def _requires_postboot_xml_changes(self):
        if self.has_cloudinit() or self.has_unattended():
            return True
        return self.has_install_phase()

    def options_specified(self):
        """
        Return True if some explicit install option was actually passed in
        """
        if self._no_install:
            return True
        return self.has_install_phase()

    def detect_distro(self, guest):
        """
        Attempt to detect the distro for the Installer's 'location'. If
        an error is encountered in the detection process (or if detection
        is not relevant for the Installer type), None is returned.

        :returns: distro variant string, or None
        """
        ret = None
        if self._treemedia:
            ret = self._treemedia.detect_distro(guest)
        elif self.cdrom:
            if guest.conn.is_remote():
                log.debug("Can't detect distro for cdrom "
                    "remote connection.")
            else:
                osguess = OSDB.guess_os_by_iso(self.cdrom)
                if osguess:
                    ret = osguess[0]
        else:
            log.debug("No media for distro detection.")

        log.debug("installer.detect_distro returned=%s", ret)
        return ret

    def set_unattended_data(self, unattended_data):
        self._unattended_data = unattended_data

    def set_cloudinit_data(self, cloudinit_data):
        self._cloudinit_data = cloudinit_data

    def has_cloudinit(self):
        return bool(self._cloudinit_data)
    def has_unattended(self):
        return bool(self._unattended_data)

    def get_generated_password(self):
        if self._cloudinit_data:
            return self._cloudinit_data.get_password_if_generated()


    ##########################
    # guest install handling #
    ##########################

    def _build_postboot_xml(self, guest_ro, final_xml, meter):
        initial_guest = Guest(self.conn, parsexml=final_xml)
        self._alter_bootconfig(initial_guest)
        self._alter_install_resources(initial_guest, meter)
        if self.has_cloudinit():
            initial_guest.set_smbios_serial_cloudinit()

            # When shim in the guest sees unpopulated EFI NVRAM, like when
            # we create a new UEFI VM, it invokes fallback.efi to populate
            # initial NVRAM boot entries. When the guest also has a TPM device,
            # shim will do a one time VM reset. This reset throws off the
            # reboot detection that is central to virt-install's install
            # process.
            #
            # The main install case that this will usually be relevant is
            # the combo of UEFI and --cloud-init. The latter usually implies
            # use of a distro cloud image, which will be using shim, and the
            # --cloud-init process requires a multi stage install compared
            # to just a plain import install.
            #
            # For that case, we disable the default TPM device for the first
            # boot.
            if (guest_ro.have_default_tpm and
                guest_ro.is_uefi() and
                len(initial_guest.devices.tpm)):
                log.debug(
                        "combo of default TPM, UEFI, and cloudinit is "
                        "used. assuming this VM is using a linux distro "
                        "cloud image with shim in the boot path. disabling "
                        "TPM for the first boot")
                initial_guest.remove_device(initial_guest.devices.tpm[0])

        final_guest = Guest(self.conn, parsexml=final_xml)
        self._remove_install_cdrom_media(final_guest)
        self._remove_unattended_install_cdrom_device(final_guest)

        return initial_guest.get_xml(), final_guest.get_xml()

    def _build_xml(self, guest, meter):
        initial_xml = None
        final_xml = guest.get_xml()
        if self._requires_postboot_xml_changes():
            initial_xml, final_xml = self._build_postboot_xml(
                    guest, final_xml, meter)
        final_xml = self._pre_reinstall_xml or final_xml

        log.debug("Generated initial_xml: %s",
            (initial_xml and ("\n" + initial_xml) or "None required"))
        log.debug("Generated final_xml: \n%s", final_xml)

        return initial_xml, final_xml

    def _manual_transient_create(self, initial_xml, final_xml, needs_boot):
        """
        For hypervisors (like vz) that don't implement createXML,
        we need to define+start, and undefine on start failure
        """
        domain = self.conn.defineXML(initial_xml or final_xml)
        if not needs_boot:
            return domain

        # Handle undefining the VM if the initial startup fails
        try:
            domain.create()
        except Exception:  # pragma: no cover
            try:
                domain.undefine()
            except Exception:
                pass
            raise

        if initial_xml and initial_xml != final_xml:
            domain = self.conn.defineXML(final_xml)
        return domain

    def _create_guest(self, guest,
                      meter, initial_xml, final_xml, doboot, transient):
        """
        Actually do the XML logging, guest defining/creating

        :param doboot: Boot guest even if it has no install phase
        """
        meter_label = _("Creating domain...")
        meter = progress.ensure_meter(meter)
        meter.start(meter_label, None)
        needs_boot = doboot or bool(initial_xml)

        if guest.type == "vz" and not self._is_reinstall:
            if transient:
                raise RuntimeError(_("Domain type 'vz' doesn't support "
                    "transient installs."))
            domain = self._manual_transient_create(
                    initial_xml, final_xml, needs_boot)

        else:
            if transient or needs_boot:
                domain = self.conn.createXML(initial_xml or final_xml, 0)
            if not transient:
                domain = self.conn.defineXML(final_xml)

        try:
            log.debug("XML fetched from libvirt object:\n%s",
                          domain.XMLDesc(0))
        except Exception as e:  # pragma: no cover
            log.debug("Error fetching XML from libvirt object: %s", e)
        meter.end()
        return domain

    def _flag_autostart(self, domain):
        """
        Set the autostart flag for domain if the user requested it
        """
        try:
            domain.setAutostart(True)
        except Exception as e:  # pragma: no cover
            if not self.conn.support.is_error_nosupport(e):
                raise
            log.warning("Could not set autostart flag: libvirt "
                            "connection does not support autostart.")


    ######################
    # Public install API #
    ######################

    def start_install(self, user_guest, meter=None,
                      dry=False, return_xml=False,
                      doboot=True, transient=False):
        """
        Begin the guest install. Will add install media to the guest config,
        launch it, then redefine the XML with the postinstall config.

        :param return_xml: Don't create the guest, just return generated XML
        """
        if not self._is_reinstall and not return_xml:
            Guest.validate_name(self.conn, user_guest.name)
        self.set_install_defaults(user_guest)
        disks = user_guest.devices.disk[:]

        # All installer XML alterations are made on this guest instance,
        # so the user_guest instance is left intact
        guest = Guest(self.conn, parsexml=user_guest.get_xml())
        guest.have_default_tpm = user_guest.have_default_tpm

        try:
            self._prepare(guest, meter)

            if not dry and not self._is_reinstall:
                for dev in disks:
                    dev.build_storage(meter)

            initial_xml, final_xml = self._build_xml(guest, meter)
            if dry or return_xml:
                return (initial_xml, final_xml)

            domain = self._create_guest(
                    guest, meter, initial_xml, final_xml,
                    doboot, transient)

            if self.autostart:
                self._flag_autostart(domain)
            return domain
        finally:
            self._cleanup(guest)
