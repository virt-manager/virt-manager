#
# Common code for all guests
#
# Copyright 2006-2009, 2013, 2014, 2015 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os

import libvirt

from virtcli import CLIConfig

from . import util
from .devices import *  # pylint: disable=wildcard-import
from .distroinstaller import DistroInstaller
from .domain import *  # pylint: disable=wildcard-import
from .domcapabilities import DomainCapabilities
from .osdict import OSDB
from .xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty

_ignore = Device


class _DomainDevices(XMLBuilder):
    XML_NAME = "devices"
    _XML_PROP_ORDER = ['disk', 'controller', 'filesystem', 'interface',
            'smartcard', 'serial', 'parallel', 'console', 'channel',
            'input', 'tpm', 'graphics', 'sound', 'video', 'hostdev',
            'redirdev', 'watchdog', 'memballoon', 'rng', 'panic',
            'memory']


    disk = XMLChildProperty(DeviceDisk)
    controller = XMLChildProperty(DeviceController)
    filesystem = XMLChildProperty(DeviceFilesystem)
    interface = XMLChildProperty(DeviceInterface)
    smartcard = XMLChildProperty(DeviceSmartcard)
    serial = XMLChildProperty(DeviceSerial)
    parallel = XMLChildProperty(DeviceParallel)
    console = XMLChildProperty(DeviceConsole)
    channel = XMLChildProperty(DeviceChannel)
    input = XMLChildProperty(DeviceInput)
    tpm = XMLChildProperty(DeviceTpm)
    graphics = XMLChildProperty(DeviceGraphics)
    sound = XMLChildProperty(DeviceSound)
    video = XMLChildProperty(DeviceVideo)
    hostdev = XMLChildProperty(DeviceHostdev)
    redirdev = XMLChildProperty(DeviceRedirdev)
    watchdog = XMLChildProperty(DeviceWatchdog)
    memballoon = XMLChildProperty(DeviceMemballoon)
    rng = XMLChildProperty(DeviceRng)
    panic = XMLChildProperty(DevicePanic)
    memory = XMLChildProperty(DeviceMemory)

    def get_all(self):
        retlist = []
        # pylint: disable=protected-access
        devtypes = _DomainDevices._XML_PROP_ORDER
        for devtype in devtypes:
            retlist.extend(getattr(self, devtype))
        return retlist


class Guest(XMLBuilder):
    @staticmethod
    def check_vm_collision(conn, name, do_remove):
        """
        Remove the existing VM with the same name if requested, or error
        if there is a collision.
        """
        vm = None
        try:
            vm = conn.lookupByName(name)
        except libvirt.libvirtError:
            pass

        if vm is None:
            return

        if not do_remove:
            raise RuntimeError(_("Domain named %s already exists!") % name)

        try:
            logging.debug("Explicitly replacing guest '%s'", name)
            if vm.ID() != -1:
                logging.info("Destroying guest '%s'", name)
                vm.destroy()

            logging.info("Undefining guest '%s'", name)
            vm.undefine()
        except libvirt.libvirtError as e:
            raise RuntimeError(_("Could not remove old vm '%s': %s") %
                               (str(e)))

    @staticmethod
    def validate_name(conn, name, check_collision, validate=True):
        if validate:
            util.validate_name(_("Guest"), name)
        if not check_collision:
            return

        try:
            conn.lookupByName(name)
        except Exception:
            return
        raise ValueError(_("Guest name '%s' is already in use.") % name)


    XML_NAME = "domain"
    _XML_PROP_ORDER = ["type", "name", "uuid", "title", "description",
        "hotplugmemorymax", "hotplugmemoryslots", "maxmemory", "memory",
        "blkiotune", "memtune", "memoryBacking",
        "vcpus", "curvcpus", "vcpu_placement",
        "cpuset", "numatune", "resource", "sysinfo",
        "bootloader", "os", "idmap", "features", "cpu", "clock",
        "on_poweroff", "on_reboot", "on_crash",
        "pm", "emulator", "devices", "seclabels"]

    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)

        self.autostart = False
        self.replace = False

        # Allow virt-manager to override the default graphics type
        self.default_graphics_type = CLIConfig.default_graphics

        self.skip_default_console = False
        self.skip_default_channel = False
        self.skip_default_sound = False
        self.skip_default_usbredir = False
        self.skip_default_graphics = False
        self.skip_default_rng = False
        self.x86_cpu_default = self.cpu.SPECIAL_MODE_HOST_MODEL_ONLY

        self.__osinfo = None
        self._install_cdrom_device = None
        self._defaults_are_set = False

        # The libvirt virDomain object we 'Create'
        self.domain = None

        # This is set via Capabilities.build_virtinst_guest
        self.capsinfo = None

        self.installer = DistroInstaller(self.conn)


    ######################
    # Property accessors #
    ######################

    def _validate_name(self, val):
        if val == self.name:
            return
        self.validate_name(self.conn, val, check_collision=not self.replace)
    name = XMLProperty("./name", validate_cb=_validate_name)

    def _set_memory(self, val):
        if val is None:
            return None

        if self.maxmemory is None or self.maxmemory < val:
            self.maxmemory = val
        return val
    memory = XMLProperty("./currentMemory", is_int=True,
                         set_converter=_set_memory)
    maxmemory = XMLProperty("./memory", is_int=True)
    hotplugmemorymax = XMLProperty("./maxMemory", is_int=True)
    hotplugmemoryslots = XMLProperty("./maxMemory/@slots", is_int=True)

    def _set_vcpus(self, val):
        if val is None:
            return None

        # Don't force set curvcpus unless already specified
        if self.curvcpus is not None and self.curvcpus > val:
            self.curvcpus = val
        return val
    vcpus = XMLProperty("./vcpu", is_int=True,
                        set_converter=_set_vcpus)
    curvcpus = XMLProperty("./vcpu/@current", is_int=True)
    vcpu_placement = XMLProperty("./vcpu/@placement")
    cpuset = XMLProperty("./vcpu/@cpuset")

    uuid = XMLProperty("./uuid")
    id = XMLProperty("./@id", is_int=True)
    type = XMLProperty("./@type")
    bootloader = XMLProperty("./bootloader")
    description = XMLProperty("./description")
    title = XMLProperty("./title")
    emulator = XMLProperty("./devices/emulator")

    on_poweroff = XMLProperty("./on_poweroff")
    on_reboot = XMLProperty("./on_reboot")
    on_crash = XMLProperty("./on_crash")
    on_lockfailure = XMLProperty("./on_lockfailure")

    seclabels = XMLChildProperty(DomainSeclabel)
    os = XMLChildProperty(DomainOs, is_single=True)
    features = XMLChildProperty(DomainFeatures, is_single=True)
    clock = XMLChildProperty(DomainClock, is_single=True)
    cpu = XMLChildProperty(DomainCpu, is_single=True)
    cputune = XMLChildProperty(DomainCputune, is_single=True)
    numatune = XMLChildProperty(DomainNumatune, is_single=True)
    pm = XMLChildProperty(DomainPm, is_single=True)
    blkiotune = XMLChildProperty(DomainBlkiotune, is_single=True)
    memtune = XMLChildProperty(DomainMemtune, is_single=True)
    memoryBacking = XMLChildProperty(DomainMemoryBacking, is_single=True)
    idmap = XMLChildProperty(DomainIdmap, is_single=True)
    resource = XMLChildProperty(DomainResource, is_single=True)
    sysinfo = XMLChildProperty(DomainSysinfo, is_single=True)

    xmlns_qemu = XMLChildProperty(DomainXMLNSQemu, is_single=True)


    ##############################
    # osinfo related definitions #
    ##############################

    def _set_osinfo(self, variant):
        obj = OSDB.lookup_os(variant)
        if not obj:
            obj = OSDB.lookup_os("generic")
        self.__osinfo = obj
    def _get_osinfo(self):
        if not self.__osinfo:
            self._set_osinfo(None)
        return self.__osinfo
    osinfo = property(_get_osinfo)

    def _get_os_variant(self):
        return self.osinfo.name
    def _set_os_variant(self, val):
        if val:
            val = val.lower()
            if OSDB.lookup_os(val) is None:
                raise ValueError(
                    _("Distro '%s' does not exist in our dictionary") % val)

        logging.debug("Setting Guest.os_variant to '%s'", val)
        self._set_osinfo(val)
    os_variant = property(_get_os_variant, _set_os_variant)

    def _supports_virtio(self, os_support):
        if not self.conn.is_qemu():
            return False

        # These _only_ support virtio so don't check the OS
        if (self.os.is_arm_machvirt() or
            self.os.is_s390x() or
            self.os.is_pseries()):
            return True

        if not os_support:
            return False

        if self.os.is_x86():
            return True

        return False

    def supports_virtionet(self):
        return self._supports_virtio(self.osinfo.supports_virtionet())


    ########################################
    # Device Add/Remove Public API methods #
    ########################################

    def add_device(self, dev):
        self.devices.add_child(dev)

    def remove_device(self, dev):
        self.devices.remove_child(dev)

    devices = XMLChildProperty(_DomainDevices, is_single=True)


    ############################
    # Install Helper functions #
    ############################

    def _prepare_install(self, meter, dry=False):
        ignore = dry

        # Fetch install media, prepare installer devices
        self.installer.prepare(self, meter)

        # Initialize install device list
        if self._install_cdrom_device:
            self._install_cdrom_device.path = self.installer.cdrom_path()
            self._install_cdrom_device.validate()

    def _prepare_get_install_xml(self):
        # We do a shallow copy of the OS block here, so that we can
        # set the install time properties but not permanently overwrite
        # any config the user explicitly requested.
        data = (self.os.bootorder, self.os.kernel, self.os.initrd,
                self.os.kernel_args, self.on_reboot)
        return data

    def _finish_get_install_xml(self, data):
        (self.os.bootorder, self.os.kernel, self.os.initrd,
                self.os.kernel_args, self.on_reboot) = data

    def _get_install_xml(self, *args, **kwargs):
        data = self._prepare_get_install_xml()
        try:
            return self._do_get_install_xml(*args, **kwargs)
        finally:
            self._finish_get_install_xml(data)

    def _do_get_install_xml(self, install):
        """
        Return the full Guest xml configuration.

        @install: Whether we want the 'OS install' configuration or
            the 'post-install' configuration. The difference is mostly
            whether the install media is attached and set as the boot
            device. Some installs, like an import or livecd, do not have
            an 'install' config.
        """
        if install and not self.installer.has_install_phase():
            return None

        self.installer.alter_bootconfig(self, install)
        if not install:
            self._remove_cdrom_install_media()

        if install:
            self.on_reboot = "destroy"

        self.os.set_defaults(self)
        return self.get_xml()


    ###########################
    # Private install helpers #
    ###########################

    def _build_xml(self):
        install_xml = self._get_install_xml(install=True)
        final_xml = self._get_install_xml(install=False)

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

    def _create_guest(self, meter, install_xml, final_xml, doboot, transient):
        """
        Actually do the XML logging, guest defining/creating

        :param doboot: Boot guest even if it has no install phase
        """
        meter_label = _("Creating domain...")
        meter = util.ensure_meter(meter)
        meter.start(size=None, text=meter_label)
        needs_boot = doboot or self.installer.has_install_phase()

        if self.type == "vz":
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



    ##############
    # Public API #
    ##############

    def start_install(self, meter=None,
                      dry=False, return_xml=False,
                      doboot=True, transient=False):
        """
        Begin the guest install (stage1).
        :param return_xml: Don't create the guest, just return generated XML
        """
        if self.domain is not None:
            raise RuntimeError(_("Domain has already been started!"))

        self.set_install_defaults()

        self._prepare_install(meter, dry)
        try:
            # Create devices if required (disk images, etc.)
            if not dry:
                for dev in self.devices.get_all():
                    dev.setup(meter)

            install_xml, final_xml = self._build_xml()
            if return_xml:
                return (install_xml, final_xml)
            if dry:
                return

            # Remove existing VM if requested
            self.check_vm_collision(self.conn, self.name,
                                    do_remove=self.replace)

            self._create_guest(meter, install_xml, final_xml,
                               doboot, transient)

            # Set domain autostart flag if requested
            self._flag_autostart()
        finally:
            self.installer.cleanup()

    def get_created_disks(self):
        return [d for d in self.devices.disk if d.storage_was_created]

    def cleanup_created_disks(self, meter):
        """
        Remove any disks we created as part of the install. Only ever
        called by clients.
        """
        clean_disks = self.get_created_disks()
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


    ###########################
    # XML convenience helpers #
    ###########################

    def set_uefi_default(self):
        """
        Configure UEFI for the VM, but only if libvirt is advertising
        a known UEFI binary path.
        """
        domcaps = DomainCapabilities.build_from_guest(self)

        if not domcaps.supports_uefi_xml():
            raise RuntimeError(_("Libvirt version does not support UEFI."))

        if not domcaps.arch_can_uefi():
            raise RuntimeError(
                _("Don't know how to setup UEFI for arch '%s'") %
                self.os.arch)

        path = domcaps.find_uefi_path_for_arch()
        if not path:
            raise RuntimeError(_("Did not find any UEFI binary path for "
                "arch '%s'") % self.os.arch)

        self.os.loader_ro = True
        self.os.loader_type = "pflash"
        self.os.loader = path

        self.check_uefi_secure()


    def check_uefi_secure(self):
        """
        If the firmware name contains "secboot" it is probably build
        with SMM feature required so we need to enable that feature,
        otherwise the firmware may fail to load.  True secure boot is
        currently supported only on x86 architecture and with q35 with
        SMM feature enabled so change the machine to q35 as well.
        To actually enforce the secure boot for the guest if Secure Boot
        Mode is configured we need to enable loader secure feature.
        """
        if not self.os.is_x86():
            return

        if "secboot" not in self.os.loader:
            return

        self.features.smm = True
        self.os.loader_secure = True
        self.os.machine = "q35"


    ###################
    # Device defaults #
    ###################

    def set_install_defaults(self):
        """
        Allow API users to set defaults ahead of time if they want it.
        Used by vmmDomainVirtinst so the 'Customize before install' dialog
        shows accurate values.

        If the user doesn't explicitly call this, it will be called by
        start_install()
        """
        if self._defaults_are_set:
            return

        self._set_defaults()
        self._defaults_are_set = True

    def stable_defaults(self, *args, **kwargs):
        return self.conn.stable_defaults(self.emulator, *args, **kwargs)

    def _usb_disabled(self):
        controllers = [c for c in self.devices.controller if
            c.type == "usb"]
        if not controllers:
            return False
        return all([c.model == "none" for c in controllers])

    def add_default_input_device(self):
        if self.os.is_container():
            return
        if self.devices.input:
            return
        if not self.devices.graphics:
            return
        if self._usb_disabled():
            return

        usb_tablet = False
        usb_keyboard = False
        if self.os.is_x86() and not self.os.is_xenpv():
            usb_tablet = self.osinfo.supports_usbtablet()
        if self.os.is_arm_machvirt():
            usb_tablet = True
            usb_keyboard = True

        if usb_tablet:
            dev = DeviceInput(self.conn)
            dev.type = "tablet"
            dev.bus = "usb"
            self.add_device(dev)
        if usb_keyboard:
            dev = DeviceInput(self.conn)
            dev.type = "keyboard"
            dev.bus = "usb"
            self.add_device(dev)

    def add_default_console_device(self):
        if self.skip_default_console:
            return
        if self.devices.console or self.devices.serial:
            return

        dev = DeviceConsole(self.conn)
        dev.type = dev.TYPE_PTY
        if self.os.is_s390x():
            dev.target_type = "sclp"
        self.add_device(dev)

    def add_default_video_device(self):
        if self.os.is_container():
            return
        if self.devices.video:
            return
        if not self.devices.graphics:
            return
        self.add_device(DeviceVideo(self.conn))

    def add_default_usb_controller(self):
        if self.os.is_container():
            return
        if any([d.type == "usb" for d in self.devices.controller]):
            return

        usb2 = False
        usb3 = False
        if self.os.is_x86():
            usb2 = True
        elif (self.os.is_arm_machvirt() and
              self.conn.check_support(
                  self.conn.SUPPORT_CONN_MACHVIRT_PCI_DEFAULT)):
            usb3 = True


        if not usb2 and not usb3:
            return

        if usb2:
            if not self.conn.check_support(
                    self.conn.SUPPORT_CONN_DEFAULT_USB2):
                return
            for dev in DeviceController.get_usb2_controllers(self.conn):
                self.add_device(dev)

        if usb3:
            self.add_device(
                DeviceController.get_usb3_controller(self.conn, self))

    def add_default_channels(self):
        if self.skip_default_channel:
            return
        if self.devices.channel:
            return
        if self.os.is_s390x():
            # Not wanted for s390 apparently
            return

        if (self.conn.is_qemu() and
            self._supports_virtio(self.osinfo.supports_virtioserial()) and
            self.conn.check_support(self.conn.SUPPORT_CONN_AUTOSOCKET)):
            dev = DeviceChannel(self.conn)
            dev.type = "unix"
            dev.target_type = "virtio"
            dev.target_name = dev.CHANNEL_NAME_QEMUGA
            self.add_device(dev)

    def add_default_graphics(self):
        if self.skip_default_graphics:
            return
        if self.devices.graphics:
            return
        if self.os.is_container() and not self.conn.is_vz():
            return
        if self.os.arch not in ["x86_64", "i686", "ppc64", "ppc64le"]:
            return
        self.add_device(DeviceGraphics(self.conn))

    def add_default_rng(self):
        if self.skip_default_rng:
            return
        if self.devices.rng:
            return
        if not (self.os.is_x86() or
                self.os.is_arm_machvirt() or
                self.os.is_pseries()):
            return

        if (self.conn.is_qemu() and
            self.osinfo.supports_virtiorng() and
            self.conn.check_support(self.conn.SUPPORT_CONN_RNG_URANDOM)):
            dev = DeviceRng(self.conn)
            dev.type = "random"
            dev.device = "/dev/urandom"
            self.add_device(dev)

    def add_default_devices(self):
        self.add_default_graphics()
        self.add_default_video_device()
        self.add_default_input_device()
        self.add_default_console_device()
        self.add_default_usb_controller()
        self.add_default_channels()
        self.add_default_rng()

    def _add_install_cdrom(self):
        if self._install_cdrom_device:
            return
        if not self.installer.needs_cdrom():
            return

        dev = DeviceDisk(self.conn)
        dev.device = dev.DEVICE_CDROM
        setattr(dev, "installer_media", not self.installer.livecd)
        self._install_cdrom_device = dev
        self.add_device(dev)

    def _remove_cdrom_install_media(self):
        for dev in self.devices.disk:
            # Keep the install cdrom device around, but with no media attached.
            # But only if we are installing windows which has a multi stage
            # install.
            if (dev.is_cdrom() and
                getattr(dev, "installer_media", False) and
                not self.osinfo.is_windows()):
                dev.path = None

    def _set_defaults(self):
        if not self.uuid:
            self.uuid = util.generate_uuid(self.conn)
        if not self.vcpus:
            self.vcpus = 1
        if self.os.is_xenpv() or self.type == "vz":
            self.emulator = None

        self._add_install_cdrom()
        self.clock.set_defaults(self)
        self.cpu.set_defaults(self)
        self.features.set_defaults(self)
        for seclabel in self.seclabels:
            seclabel.set_defaults(self)
        self.pm.set_defaults(self)

        for dev in self.devices.get_all():
            dev.set_defaults(self)

        self._set_disk_defaults()
        self._add_implied_controllers()
        self._add_spice_devices()

    def is_full_os_container(self):
        if not self.os.is_container():
            return False
        for fs in self.devices.filesystem:
            if fs.target == "/":
                return True
        return False

    def hyperv_supported(self):
        if not self.osinfo.is_windows():
            return False
        if (self.os.loader_type == "pflash" and
            self.os_variant in ("win2k8r2", "win7")):
            return False
        return True

    def update_defaults(self):
        # This is used only by virt-manager to reset any defaults that may have
        # changed through manual intervention via the customize wizard.

        # UEFI doesn't work with hyperv bits
        if not self.hyperv_supported():
            self.features.hyperv_relaxed = None
            self.features.hyperv_vapic = None
            self.features.hyperv_spinlocks = None
            self.features.hyperv_spinlocks_retries = None
            for i in self.clock.timers:
                if i.name == "hypervclock":
                    self.clock.remove_timer(i)

    def _add_implied_controllers(self):
        has_spapr_scsi = False
        has_virtio_scsi = False
        has_any_scsi = False
        for dev in self.devices.controller:
            if dev.type == "scsi":
                has_any_scsi = True
                if dev.address.type == "spapr-vio":
                    has_spapr_scsi = True
                if dev.model == "virtio":
                    has_virtio_scsi = True

        # Add spapr-vio controller if needed
        if not has_spapr_scsi:
            for dev in self.devices.disk:
                if dev.address.type == "spapr-vio":
                    ctrl = DeviceController(self.conn)
                    ctrl.type = "scsi"
                    ctrl.address.set_addrstr("spapr-vio")
                    ctrl.set_defaults(self)
                    self.add_device(ctrl)
                    break

        # Add virtio-scsi controller if needed
        if ((self.os.is_arm_machvirt() or self.os.is_pseries()) and
            not has_any_scsi and
            not has_virtio_scsi):
            for dev in self.devices.disk:
                if dev.bus == "scsi":
                    ctrl = DeviceController(self.conn)
                    ctrl.type = "scsi"
                    ctrl.model = "virtio-scsi"
                    ctrl.set_defaults(self)
                    self.add_device(ctrl)
                    break

    def _set_disk_defaults(self):
        disks = self.devices.disk

        def set_disk_bus(d):
            if d.is_floppy():
                d.bus = "fdc"
                return
            if self.os.is_xenpv():
                d.bus = "xen"
                return
            if not self.os.is_hvm():
                # This likely isn't correct, but it's kind of a catch all
                # for virt types we don't know how to handle.
                d.bus = "ide"
                return

            if self.os.is_arm_machvirt():
                # We prefer virtio-scsi for machvirt, gets us hotplug
                d.bus = "scsi"
            elif (d.is_disk() and
                  self._supports_virtio(self.osinfo.supports_virtiodisk())):
                d.bus = "virtio"
            elif self.os.is_pseries() and d.is_cdrom():
                d.bus = "scsi"
            elif self.os.is_arm():
                d.bus = "sd"
            elif self.os.is_q35():
                d.bus = "sata"
            else:
                d.bus = "ide"

        # Generate disk targets
        used_targets = []
        for disk in disks:
            if not disk.bus:
                set_disk_bus(disk)

        for disk in disks:
            if (disk.target and
                not getattr(disk, "cli_generated_target", False)):
                used_targets.append(disk.target)
            else:
                disk.cli_generated_target = False
                used_targets.append(disk.generate_target(used_targets))

    def _add_spice_channels(self):
        if self.skip_default_channel:
            return

        for chn in self.devices.channel:
            if chn.type == chn.TYPE_SPICEVMC:
                return

        dev = DeviceChannel(self.conn)
        dev.type = DeviceChannel.TYPE_SPICEVMC
        dev.set_defaults(self)
        self.add_device(dev)

    def _add_spice_sound(self):
        if self.skip_default_sound:
            return
        if self.devices.sound:
            return
        if not self.os.is_hvm():
            return
        if not (self.os.is_x86() or
                self.os.is_arm_machvirt):
            return

        dev = DeviceSound(self.conn)
        dev.set_defaults(self)
        self.add_device(dev)

    def _add_spice_usbredir(self):
        if self.skip_default_usbredir:
            return
        if self.devices.redirdev:
            return
        if not self.os.is_x86():
            return

        # If we use 4 devices here, we fill up all the emulated USB2 slots,
        # and directly assigned devices are forced to fall back to USB1
        # https://bugzilla.redhat.com/show_bug.cgi?id=1135488
        for ignore in range(2):
            dev = DeviceRedirdev(self.conn)
            dev.bus = "usb"
            dev.type = "spicevmc"
            dev.set_defaults(self)
            self.add_device(dev)

    def has_spice(self):
        for gfx in self.devices.graphics:
            if gfx.type == gfx.TYPE_SPICE:
                return True

    def has_gl(self):
        for gfx in self.devices.graphics:
            if gfx.gl:
                return True

    def has_listen_none(self):
        for gfx in self.devices.graphics:
            listen = gfx.get_first_listen_type()
            if listen and listen == "none":
                return True
        return False

    def _add_spice_devices(self):
        if not self.has_spice():
            return

        if (self.features.vmport is None and
            self.os.is_x86() and
            self.conn.check_support(self.conn.SUPPORT_CONN_VMPORT)):
            self.features.vmport = False

        self._add_spice_channels()
        self._add_spice_sound()
        self._add_spice_usbredir()
