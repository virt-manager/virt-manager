#
# Common code for all guests
#
# Copyright 2006-2009, 2013, 2014, 2015 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

import libvirt

from virtcli import CLIConfig

from . import util
from .devices import *  # pylint: disable=wildcard-import
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
    def validate_name(conn, name, check_collision=True, validate=True):
        if validate:
            util.validate_name(_("Guest"), name)
        if not check_collision:
            return

        try:
            conn.lookupByName(name)
        except Exception:
            return
        raise ValueError(_("Guest name '%s' is already in use.") % name)

    @staticmethod
    def get_recommended_machine(capsinfo):
        """
        Return the recommended machine type for the passed capsinfo.
        We only return this for arch cases where there's a very clear
        preference that's different from the default machine type
        """
        def _qemu_machine():
            if (capsinfo.arch in ["ppc64", "ppc64le"] and
                "pseries" in capsinfo.machines):
                return "pseries"

            if capsinfo.arch in ["armv7l", "aarch64"]:
                if "virt" in capsinfo.machines:
                    return "virt"
                if "vexpress-a15" in capsinfo.machines:
                    return "vexpress-a15"

            if capsinfo.arch in ["s390x"]:
                if "s390-ccw-virtio" in capsinfo.machines:
                    return "s390-ccw-virtio"

        if capsinfo.conn.is_qemu() or capsinfo.conn.is_test():
            return _qemu_machine()
        return None


    #################
    # init handling #
    #################

    XML_NAME = "domain"
    _XML_PROP_ORDER = [
        "type", "name", "uuid", "title", "description", "_metadata",
        "hotplugmemorymax", "hotplugmemoryslots", "maxmemory", "_memory",
        "blkiotune", "memtune", "memoryBacking",
        "_vcpus", "curvcpus", "vcpu_placement",
        "cpuset", "numatune", "resource", "sysinfo",
        "bootloader", "os", "idmap", "features", "cpu", "clock",
        "on_poweroff", "on_reboot", "on_crash",
        "pm", "emulator", "devices", "seclabels"]

    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)

        # Allow virt-manager to override the default graphics type
        self.default_graphics_type = CLIConfig.default_graphics

        self.skip_default_console = False
        self.skip_default_channel = False
        self.skip_default_sound = False
        self.skip_default_usbredir = False
        self.skip_default_graphics = False
        self.skip_default_rng = False
        self.x86_cpu_default = self.cpu.SPECIAL_MODE_APP_DEFAULT

        self.__osinfo = None
        self._capsinfo = None
        self._domcaps = None


    ######################
    # Property accessors #
    ######################

    name = XMLProperty("./name")

    def _set_memory(self, val):
        if val is not None:
            val = int(val)
            if self.maxmemory is None or self.maxmemory < val:
                self.maxmemory = val
        self._memory = val
    def _get_memory(self):
        return self._memory
    _memory = XMLProperty("./currentMemory", is_int=True)
    memory = property(_get_memory, _set_memory)

    maxmemory = XMLProperty("./memory", is_int=True)
    hotplugmemorymax = XMLProperty("./maxMemory", is_int=True)
    hotplugmemoryslots = XMLProperty("./maxMemory/@slots", is_int=True)

    def _set_vcpus(self, val):
        if val is not None:
            val = int(val)
            # Don't force set curvcpus unless already specified
            if self.curvcpus is not None and self.curvcpus > val:
                self.curvcpus = val
        self._vcpus = val
    def _get_vcpus(self):
        return self._vcpus
    _vcpus = XMLProperty("./vcpu", is_int=True)
    vcpus = property(_get_vcpus, _set_vcpus)

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
    _metadata = XMLChildProperty(DomainMetadata, is_single=True)

    xmlns_qemu = XMLChildProperty(DomainXMLNSQemu, is_single=True)


    ##############################
    # osinfo related definitions #
    ##############################

    def _get_osinfo(self):
        if self.__osinfo:
            return self.__osinfo

        os_id = self._metadata.libosinfo.os_id
        if os_id:
            self.__osinfo = OSDB.lookup_os_by_full_id(os_id)
            if not self.__osinfo:
                logging.debug("XML had libosinfo os id=%s but we didn't "
                        "find any libosinfo object matching that", os_id)

        if not self.__osinfo:
            self.set_os_name("generic")
        return self.__osinfo
    osinfo = property(_get_osinfo)

    def set_os_name(self, name):
        obj = OSDB.lookup_os(name)
        if obj is None:
            raise ValueError(_("Unknown OS name '%s'. "
                    "See `osinfo-query os` for valid values.") % name)

        logging.debug("Setting Guest osinfo %s", obj)
        self.__osinfo = obj
        self._metadata.libosinfo.os_id = self.__osinfo.full_id

    def set_os_full_id(self, full_id):
        obj = OSDB.lookup_os_by_full_id(full_id)
        if obj is None:
            raise ValueError(_("Unknown libosinfo ID '%s'") % full_id)

        logging.debug("Setting Guest osinfo %s", obj)
        self.__osinfo = obj
        self._metadata.libosinfo.os_id = self.__osinfo.full_id

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
    def supports_virtiodisk(self):
        return self._supports_virtio(self.osinfo.supports_virtiodisk())
    def _supports_virtioserial(self):
        return self._supports_virtio(self.osinfo.supports_virtioserial())


    ###############################
    # Public XML APIs and helpers #
    ###############################

    def add_device(self, dev):
        self.devices.add_child(dev)
    def remove_device(self, dev):
        self.devices.remove_child(dev)
    devices = XMLChildProperty(_DomainDevices, is_single=True)

    def prefers_uefi(self):
        """
        Return True if this config prefers UEFI. For example,
        arm+machvirt prefers UEFI since it's required for traditional
        install methods
        """
        return self.os.is_arm_machvirt()

    def get_uefi_path(self):
        """
        If UEFI firmware path is found, return it, otherwise raise an error
        """
        if not self.os.arch:
            self.set_capabilities_defaults()
        domcaps = self.lookup_domcaps()

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

        return path

    def set_uefi_path(self, path):
        """
        Configure UEFI for the VM, but only if libvirt is advertising
        a known UEFI binary path.
        """
        self.os.loader_ro = True
        self.os.loader_type = "pflash"
        self.os.loader = path

        # If the firmware name contains "secboot" it is probably build
        # with SMM feature required so we need to enable that feature,
        # otherwise the firmware may fail to load.  True secure boot is
        # currently supported only on x86 architecture and with q35 with
        # SMM feature enabled so change the machine to q35 as well.
        # To actually enforce the secure boot for the guest if Secure Boot
        # Mode is configured we need to enable loader secure feature.
        if (self.os.is_x86() and
            "secboot" in self.os.loader):
            self.features.smm = True
            self.os.loader_secure = True
            self.os.machine = "q35"

        # UEFI doesn't work with hyperv bits for some OS
        if self.osinfo.broken_uefi_with_hyperv():
            self.features.hyperv_relaxed = None
            self.features.hyperv_vapic = None
            self.features.hyperv_spinlocks = None
            self.features.hyperv_spinlocks_retries = None
            for i in self.clock.timers:
                if i.name == "hypervclock":
                    self.clock.timers.remove(i)

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
            self.osinfo.broken_uefi_with_hyperv()):
            return False
        return True

    def lookup_domcaps(self):
        # We need to regenerate domcaps cache if any of these values change
        def _compare(domcaps):
            if self.os.machine and self.os.machine != domcaps.machine:
                return False
            if self.type and self.type != domcaps.domain:
                return False
            if self.os.arch and self.os.arch != domcaps.arch:
                return False
            if self.emulator and self.emulator != domcaps.path:
                return False
            return True

        if not self._domcaps or not _compare(self._domcaps):
            self._domcaps = DomainCapabilities.build_from_guest(self)
        return self._domcaps

    def lookup_capsinfo(self):
        # We need to regenerate capsinfo cache if any of these values change
        def _compare(capsinfo):
            if self.type and self.type != capsinfo.hypervisor_type:
                return False
            if self.os.os_type and self.os.os_type != capsinfo.os_type:
                return False
            if self.os.arch and self.os.arch != capsinfo.arch:
                return False
            if self.os.machine and self.os.machine not in capsinfo.machines:
                return False
            return True

        if not self._capsinfo or not _compare(self._capsinfo):
            self._capsinfo = self.conn.caps.guest_lookup(
                os_type=self.os.os_type,
                arch=self.os.arch,
                typ=self.type,
                machine=self.os.machine)
        return self._capsinfo

    def set_capabilities_defaults(self, capsinfo=None):
        if capsinfo:
            self._capsinfo = capsinfo
        else:
            capsinfo = self.lookup_capsinfo()
        wants_default_type = not self.type and not self.os.os_type

        self.type = capsinfo.hypervisor_type
        self.os.os_type = capsinfo.os_type
        self.os.arch = capsinfo.arch
        if not self.os.loader:
            self.os.loader = capsinfo.loader
        if (not self.emulator and
            not self.os.is_xenpv() and
            not self.type == "vz"):
            self.emulator = capsinfo.emulator
        if not self.os.machine:
            self.os.machine = Guest.get_recommended_machine(capsinfo)

        if (wants_default_type and
            self.conn.is_qemu() and
            self.os.is_x86() and
            not self.type == "kvm"):
            logging.warning("KVM acceleration not available, using '%s'",
                            self.type)

    def set_defaults(self, _guest):
        if not self.uuid:
            self.uuid = util.generate_uuid(self.conn)
        if not self.vcpus:
            self.vcpus = 1

        self.set_capabilities_defaults()

        self._set_default_machine()
        self._set_default_uefi()

        self._add_default_graphics()
        self._add_default_video_device()
        self._add_default_input_device()
        self._add_default_console_device()
        self._add_default_usb_controller()
        self._add_default_channels()
        self._add_default_rng()

        self.clock.set_defaults(self)
        self.cpu.set_defaults(self)
        self.features.set_defaults(self)
        for seclabel in self.seclabels:
            seclabel.set_defaults(self)
        self.pm.set_defaults(self)
        self.os.set_defaults(self)

        for dev in self.devices.get_all():
            dev.set_defaults(self)

        self._add_implied_controllers()
        self._add_spice_devices()


    ########################
    # Private xml routines #
    ########################

    def _set_default_machine(self):
        if self.os.machine:
            return

        capsinfo = self.lookup_capsinfo()

        if (self.os.is_x86() and
            self.conn.is_qemu() and
            "q35" in capsinfo.machines and
            self.conn.check_support(self.conn.SUPPORT_QEMU_Q35_DEFAULT) and
            self.osinfo.supports_chipset_q35()):
            self.os.machine = "q35"
            return

        default = capsinfo.machines and capsinfo.machines[0] or None
        self.os.machine = default


    def _set_default_uefi(self):
        if (self.prefers_uefi() and
            not self.os.kernel and
            not self.os.loader and
            self.os.loader_ro is None and
            self.os.nvram is None):
            try:
                path = self.get_uefi_path()
                self.set_uefi_path(path)
            except RuntimeError as e:
                logging.debug("Error setting UEFI default",
                    exc_info=True)
                logging.warning("Couldn't configure UEFI: %s", e)
                logging.warning("Your VM may not boot successfully.")

    def _usb_disabled(self):
        controllers = [c for c in self.devices.controller if
            c.type == "usb"]
        if not controllers:
            return False
        return all([c.model == "none" for c in controllers])

    def _add_default_input_device(self):
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

    def _add_default_console_device(self):
        if self.skip_default_console:
            return
        if self.devices.console or self.devices.serial:
            return

        dev = DeviceConsole(self.conn)
        dev.type = dev.TYPE_PTY
        if self.os.is_s390x():
            dev.target_type = "sclp"
        self.add_device(dev)

    def _add_default_video_device(self):
        if self.os.is_container():
            return
        if self.devices.video:
            return
        if not self.devices.graphics:
            return
        self.add_device(DeviceVideo(self.conn))

    def _add_default_usb_controller(self):
        if any([d.type == "usb" for d in self.devices.controller]):
            return
        if not self.conn.is_qemu() and not self.conn.is_test():
            return

        qemu_usb3 = self.conn.check_support(self.conn.SUPPORT_CONN_QEMU_XHCI)
        usb2 = False
        usb3 = False
        if self.os.is_x86():
            usb3 = bool(self.osinfo.supports_usb3() and qemu_usb3)
            usb2 = not usb3
        elif self.os.is_arm_machvirt():
            # For machvirt, we always assume OS supports usb3
            if (qemu_usb3 and
                self.conn.check_support(
                        self.conn.SUPPORT_CONN_MACHVIRT_PCI_DEFAULT)):
                usb3 = True
        elif self.os.is_pseries():
            # For pseries, we always assume OS supports usb3
            if qemu_usb3:
                usb3 = True


        if usb2:
            for dev in DeviceController.get_usb2_controllers(self.conn):
                self.add_device(dev)
        elif usb3:
            self.add_device(
                DeviceController.get_usb3_controller(self.conn, self))

    def _add_default_channels(self):
        if self.skip_default_channel:
            return
        if self.devices.channel:
            return
        if self.os.is_s390x():
            # Not wanted for s390 apparently
            return

        if (self.conn.is_qemu() and
            self._supports_virtioserial() and
            self.conn.check_support(self.conn.SUPPORT_CONN_AUTOSOCKET)):
            dev = DeviceChannel(self.conn)
            dev.type = "unix"
            dev.target_type = "virtio"
            dev.target_name = dev.CHANNEL_NAME_QEMUGA
            self.add_device(dev)

    def _add_default_graphics(self):
        if self.skip_default_graphics:
            return
        if self.devices.graphics:
            return
        if self.os.is_container() and not self.conn.is_vz():
            return
        if self.os.arch not in ["x86_64", "i686", "ppc64", "ppc64le"]:
            return
        self.add_device(DeviceGraphics(self.conn))

    def _add_default_rng(self):
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

    def _add_spice_channels(self):
        if self.skip_default_channel:
            return
        for chn in self.devices.channel:
            if chn.type == chn.TYPE_SPICEVMC:
                return
        if not self._supports_virtioserial():
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
