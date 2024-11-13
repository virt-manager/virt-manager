#
# Common code for all guests
#
# Copyright 2006-2009, 2013, 2014, 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import random

from . import generatename
from . import xmlutil
from .buildconfig import BuildConfig
from .devices import *  # pylint: disable=wildcard-import
from .domain import *  # pylint: disable=wildcard-import
from .domcapabilities import DomainCapabilities
from .logger import log
from .osdict import OSDB
from .xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty

_ignore = Device


class _DomainDevices(XMLBuilder):
    XML_NAME = "devices"
    _XML_PROP_ORDER = ['disk', 'controller', 'filesystem', 'interface',
            'smartcard', 'serial', 'parallel', 'console', 'channel',
            'input', 'tpm', 'graphics', 'sound', 'audio', 'video', 'hostdev',
            'redirdev', 'watchdog', 'memballoon', 'rng', 'panic',
            'shmem', 'memory', 'vsock', 'iommu']


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
    audio = XMLChildProperty(DeviceAudio)
    video = XMLChildProperty(DeviceVideo)
    hostdev = XMLChildProperty(DeviceHostdev)
    redirdev = XMLChildProperty(DeviceRedirdev)
    watchdog = XMLChildProperty(DeviceWatchdog)
    memballoon = XMLChildProperty(DeviceMemballoon)
    rng = XMLChildProperty(DeviceRng)
    panic = XMLChildProperty(DevicePanic)
    shmem = XMLChildProperty(DeviceShMem)
    memory = XMLChildProperty(DeviceMemory)
    vsock = XMLChildProperty(DeviceVsock)
    iommu = XMLChildProperty(DeviceIommu)

    def get_all(self):
        retlist = []
        # pylint: disable=protected-access
        devtypes = _DomainDevices._XML_PROP_ORDER
        for devtype in devtypes:
            retlist.extend(getattr(self, devtype))
        return retlist


class _IOThreadID(XMLBuilder):
    XML_NAME = "iothread"
    _XML_PROP_ORDER = ["id", "thread_pool_min", "thread_pool_max"]

    id = XMLProperty("./@id", is_int=True)
    thread_pool_min = XMLProperty("./@thread_pool_min", is_int=True)
    thread_pool_max = XMLProperty("./@thread_pool_max", is_int=True)


class _DefaultIOThread(XMLBuilder):
    XML_NAME = "defaultiothread"

    thread_pool_min = XMLProperty("./@thread_pool_min", is_int=True)
    thread_pool_max = XMLProperty("./@thread_pool_max", is_int=True)


class Guest(XMLBuilder):
    @staticmethod
    def validate_name(conn, name, check_collision=True, validate=True):
        if validate:
            XMLBuilder.validate_generic_name(_("Guest"), name)
        if not check_collision:
            return

        try:
            conn.lookupByName(name)
        except Exception:
            return
        raise ValueError(_("Guest name '%s' is already in use.") % name)

    @staticmethod
    def generate_uuid(conn):
        def _randomUUID():
            if conn.fake_conn_predictable():
                # Testing hack
                return "00000000-1111-2222-3333-444444444444"

            u = [random.randint(0, 255) for ignore in range(0, 16)]
            u[6] = (u[6] & 0x0F) | (4 << 4)
            u[8] = (u[8] & 0x3F) | (2 << 6)

            return "-".join(["%02x" * 4, "%02x" * 2, "%02x" * 2, "%02x" * 2,
                             "%02x" * 6]) % tuple(u)

        for ignore in range(256):
            uuid = _randomUUID()
            if not generatename.check_libvirt_collision(
                    conn.lookupByUUID, uuid):
                return uuid

        log.error(  # pragma: no cover
                "Failed to generate non-conflicting UUID")

    @staticmethod
    def generate_name(guest):
        def _pretty_arch(_a):
            if _a == "armv7l":
                return "arm"
            return _a

        force_num = False
        basename = guest.osinfo.name
        if basename.endswith("-unknown"):
            basename = basename.rsplit("-", 1)[0]

        if guest.osinfo.name == "generic":
            force_num = True
            if guest.os.is_container():
                basename = "container"
            else:
                basename = "vm"

        if guest.os.arch != guest.conn.caps.host.cpu.arch:
            basename += "-%s" % _pretty_arch(guest.os.arch)
            force_num = False

        def cb(n):
            return generatename.check_libvirt_collision(
                guest.conn.lookupByName, n)
        return generatename.generate_name(basename, cb,
            start_num=force_num and 1 or 2, force_num=force_num,
            sep=not force_num and "-" or "")


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
                if "vexpress-a15" in capsinfo.machines:  # pragma: no cover
                    return "vexpress-a15"

            if capsinfo.arch in ["s390x"]:
                if "s390-ccw-virtio" in capsinfo.machines:
                    return "s390-ccw-virtio"

            if capsinfo.arch in ["riscv64", "riscv32"]:
                if "virt" in capsinfo.machines:
                    return "virt"

        if capsinfo.conn.is_qemu() or capsinfo.conn.is_test():
            return _qemu_machine()
        return None


    #################
    # init handling #
    #################

    XML_NAME = "domain"
    _XML_PROP_ORDER = [
        "type", "name", "uuid", "genid", "genid_enable",
        "title", "description", "_metadata",
        "iothreads", "iothreadids", "defaultiothread",
        "maxMemory", "maxMemorySlots", "memory", "_currentMemory",
        "blkiotune", "memtune", "memoryBacking",
        "_vcpus", "vcpu_current", "vcpu_placement",
        "vcpu_cpuset", "vcpulist", "numatune", "resource", "sysinfo",
        "bootloader", "bootloader_args", "os", "idmap",
        "features", "cpu", "clock",
        "on_poweroff", "on_reboot", "on_crash",
        "pm", "emulator", "devices", "launchSecurity", "seclabels", "keywrap"]

    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)

        # Allow virt-manager to override the default graphics type
        self.default_graphics_type = BuildConfig.default_graphics

        self.skip_default_console = False
        self.skip_default_channel = False
        self.skip_default_sound = False
        self.skip_default_usbredir = False
        self.skip_default_graphics = False
        self.skip_default_rng = False
        self.skip_default_tpm = False
        self.skip_default_input = False
        self.have_default_tpm = False
        self.x86_cpu_default = self.cpu.SPECIAL_MODE_APP_DEFAULT

        # qemu 6.1, fairly new when we added this option, has an unfortunate
        # bug with >= 15 root ports, so we choose 14 instead of our original 16
        # https://gitlab.com/qemu-project/qemu/-/issues/641
        self.num_pcie_root_ports = 14

        self.skip_default_osinfo = False
        self.uefi_requested = None
        self.__osinfo = None
        self._capsinfo = None
        self._domcaps = None
        self._extra_drivers = None


    ######################
    # Property accessors #
    ######################

    name = XMLProperty("./name")

    iothreads = XMLProperty("./iothreads", is_int=True)
    iothreadids = XMLChildProperty(_IOThreadID, relative_xpath="./iothreadids")
    defaultiothread = XMLChildProperty(_DefaultIOThread)

    def _set_currentMemory(self, val):
        if val is not None:
            val = int(val)
            if self.memory is None or self.memory < val:
                self.memory = val
        self._currentMemory = val
    def _get_currentMemory(self):
        return self._currentMemory
    currentMemory = property(_get_currentMemory, _set_currentMemory)

    _currentMemory = XMLProperty("./currentMemory", is_int=True)
    memory = XMLProperty("./memory", is_int=True)
    maxMemory = XMLProperty("./maxMemory", is_int=True)
    maxMemorySlots = XMLProperty("./maxMemory/@slots", is_int=True)

    def _set_vcpus(self, val):
        if val is not None:
            val = int(val)
            # Don't force set curvcpus unless already specified
            if self.vcpu_current is not None and self.vcpu_current > val:
                self.vcpu_current = val
        self._vcpus = val
    def _get_vcpus(self):
        return self._vcpus
    _vcpus = XMLProperty("./vcpu", is_int=True)
    vcpus = property(_get_vcpus, _set_vcpus)

    vcpu_current = XMLProperty("./vcpu/@current", is_int=True)
    vcpu_placement = XMLProperty("./vcpu/@placement")
    vcpu_cpuset = XMLProperty("./vcpu/@cpuset")

    uuid = XMLProperty("./uuid")
    genid = XMLProperty("./genid")
    genid_enable = XMLProperty("./genid", is_bool=True)
    id = XMLProperty("./@id", is_int=True)
    type = XMLProperty("./@type")
    bootloader = XMLProperty("./bootloader")
    bootloader_args = XMLProperty("./bootloader_args")
    description = XMLProperty("./description")
    title = XMLProperty("./title")
    emulator = XMLProperty("./devices/emulator")

    on_poweroff = XMLProperty("./on_poweroff")
    on_reboot = XMLProperty("./on_reboot")
    on_crash = XMLProperty("./on_crash")
    on_lockfailure = XMLProperty("./on_lockfailure")

    vcpulist = XMLChildProperty(DomainVCPUs, is_single=True)
    seclabels = XMLChildProperty(DomainSeclabel)
    keywrap = XMLChildProperty(DomainKeyWrap, is_single=True)
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
    sysinfo = XMLChildProperty(DomainSysinfo)
    launchSecurity = XMLChildProperty(DomainLaunchSecurity, is_single=True)
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
                log.debug("XML had libosinfo os id=%s but we didn't "
                        "find any libosinfo object matching that", os_id)

        if not self.__osinfo:
            # If you hit this error, it means some part of the cli
            # tried to access osinfo before we can depend on it being
            # available. Try moving whatever bits need osinfo to be
            # triggered via set_defaults
            if self.skip_default_osinfo:
                raise xmlutil.DevError(
                        "osinfo is accessed before it has been set.")
            self.set_default_os_name()
        return self.__osinfo
    osinfo = property(_get_osinfo)

    def _set_os_obj(self, obj):
        self.__osinfo = obj
        self._metadata.libosinfo.os_id = obj.full_id

    def set_os_name(self, name):
        obj = OSDB.lookup_os(name, raise_error=True)
        log.debug("Setting Guest osinfo name %s", obj)
        self._set_os_obj(obj)

    def set_default_os_name(self):
        self.set_os_name("generic")

    def _supports_virtio(self, os_support):
        if not self.conn.is_qemu():
            return False

        # These _only_ support virtio so don't check the OS
        if (self.os.is_arm_machvirt() or
            self.os.is_riscv_virt() or
            self.os.is_s390x() or
            self.os.is_pseries() or
            self.os.is_loongarch64()):
            return True

        if not os_support:
            return False

        if self.os.is_x86():
            return True

        return False  # pragma: no cover

    def supports_virtionet(self):
        return self._supports_virtio(self.osinfo.supports_virtionet(self._extra_drivers))
    def supports_virtiodisk(self):
        return self._supports_virtio(self.osinfo.supports_virtiodisk(self._extra_drivers))
    def supports_virtioscsi(self):
        return self._supports_virtio(self.osinfo.supports_virtioscsi(self._extra_drivers))
    def _supports_virtioserial(self):
        return self._supports_virtio(self.osinfo.supports_virtioserial(self._extra_drivers))


    #####################
    # Bootorder helpers #
    #####################

    def _get_old_boot_order(self):
        return self.os.bootorder

    def _convert_old_boot_order(self):
        """Converts the old boot order (e.g. <boot dev='hd'/>) into the
        per-device boot order format.

        """
        boot_order = self._get_old_boot_order()
        ret = []
        disk = None
        cdrom = None
        floppy = None
        net = None

        for d in self.devices.disk:
            if not cdrom and d.device == "cdrom":
                cdrom = d
            if not floppy and d.device == "floppy":
                floppy = d
            if not disk and d.device not in ["cdrom", "floppy"]:
                disk = d
            if cdrom and disk and floppy:
                break

        for n in self.devices.interface:
            net = n
            break

        for b in boot_order:
            if b == "network" and net:
                ret.append(net.get_xml_id())
            elif b == "hd" and disk:
                ret.append(disk.get_xml_id())
            elif b == "cdrom" and cdrom:
                ret.append(cdrom.get_xml_id())
            elif b == "fd" and floppy:
                ret.append(floppy.get_xml_id())
        return ret

    def _get_device_boot_order(self):
        order = []
        for dev in self.get_bootable_devices():
            if not dev.boot.order:
                continue
            order.append((dev.get_xml_id(), dev.boot.order))

        if not order:
            # No devices individually marked bootable, convert traditional
            # boot XML to fine grained
            return self._convert_old_boot_order()

        order.sort(key=lambda p: p[1])
        return [p[0] for p in order]

    def get_boot_order(self, legacy=False):
        if legacy:
            return self._get_old_boot_order()
        return self._get_device_boot_order()

    def _set_device_boot_order(self, boot_order):
        """Sets the new device boot order for the domain"""
        # Unset the traditional boot order
        self.os.bootorder = []

        # Unset device boot order
        for dev in self.devices.get_all():
            dev.boot.order = None

        dev_map = dict((dev.get_xml_id(), dev) for dev in
                       self.get_bootable_devices())
        for boot_idx, dev_xml_id in enumerate(boot_order, 1):
            dev_map[dev_xml_id].boot.order = boot_idx

    def set_boot_order(self, boot_order, legacy=False):
        """Modifies the boot order"""
        if legacy:
            self.os.bootorder = boot_order
        else:
            self._set_device_boot_order(boot_order)

    def reorder_boot_order(self, dev, boot_index):
        """Sets boot order of `dev` to `boot_index`

        Sets the boot order for device `dev` to value `boot_index` and
        adjusts all other boot indices accordingly. Additionally the
        boot order defined in the 'os' node of a domain definition is
        disabled since they are mutually exclusive in libvirt.

        """
        # unset legacy boot order
        self.os.bootorder = []

        # Sort the bootable devices by boot order
        devs_sorted = sorted([device for device in self.get_bootable_devices()
                              if device.boot.order is not None],
                             key=lambda device: device.boot.order)

        # set new boot order
        dev.boot.order = boot_index

        next_boot_index = None
        for device in devs_sorted:
            if device is dev:
                continue

            if device.boot.order in [next_boot_index, boot_index]:
                next_boot_index = device.boot.order + 1
                device.boot.order = next_boot_index
                continue

            if next_boot_index is not None:
                # we found a hole so we can stop here
                break


    ###############################
    # Public XML APIs and helpers #
    ###############################

    def add_device(self, dev):
        self.devices.add_child(dev)

    def remove_device(self, dev):
        self.devices.remove_child(dev)
        self._remove_duplicate_console(dev)
        self._remove_spice_devices(dev)

    devices = XMLChildProperty(_DomainDevices, is_single=True)

    def find_device(self, origdev):
        """
        Try to find a child device that matches the content of
        the passed @origdev.
        """
        devlist = getattr(self.devices, origdev.DEVICE_TYPE)
        for idx, dev in enumerate(devlist):
            if origdev.compare_device(dev, idx):
                return dev
        return None

    def get_bootable_devices(self, exclude_redirdev=False):
        """
        Returns bootable devices of the guest definition. If
        @exclude_redirdev is `True` redirected devices will be
        skipped in the output.

        """
        devices = self.devices
        devs = devices.disk + devices.interface + devices.hostdev
        if not exclude_redirdev:
            devs = devs + devices.redirdev
        return devs

    def prefers_uefi(self):
        """
        Return True if this config prefers UEFI. For example,
        arm+machvirt prefers UEFI since it's required for traditional
        install methods
        """
        if (self.os.is_x86() and
            (self.conn.is_qemu() or self.conn.is_test())):
            # If OS has dropped support for 'bios', we have no
            # choice but to use EFI.
            # For other OS still prefer BIOS since it is faster
            # and doesn't break QEMU internal snapshots
            prefer_efi = self.osinfo.requires_firmware_efi(self.os.arch)
        else:
            prefer_efi = (self.os.is_arm_machvirt() or
                          self.os.is_riscv_virt() or
                          self.os.is_loongarch64() or
                          self.conn.is_bhyve())

        log.debug("Prefer EFI => %s", prefer_efi)
        return prefer_efi

    def is_uefi(self):
        if self.os.loader and self.os.loader_type == "pflash":
            return True
        return self.os.firmware == "efi"

    def set_uefi_path(self, path):
        """
        Set old style UEFI XML via loader path.
        Set up smm if needed for secureboot
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
            if not self.os.is_q35():
                log.warning("Changing machine type from '%s' to 'q35' "
                        "which is required for UEFI secure boot.",
                        self.os.machine)
                self.os.machine = "q35"

    def enable_uefi(self):
        """
        Enable UEFI using our default logic
        """
        domcaps = self.lookup_domcaps()
        if domcaps.supports_firmware_efi():
            self.os.firmware = "efi"
            return

        path = self._lookup_default_uefi_path()
        log.debug("Setting default UEFI path=%s", path)
        self.set_uefi_path(path)

    def disable_uefi(self):
        self.os.firmware = None
        self.os.loader = None
        self.os.loader_ro = None
        self.os.loader_type = None
        self.os.loader_secure = None
        self.os.nvram = None
        self.os.nvram_template = None
        for feature in self.os.firmware_features:
            self.os.remove_child(feature)

        # Force remove any properties we don't know about
        self._xmlstate.xmlapi.node_force_remove("./os/firmware")
        self._xmlstate.xmlapi.node_force_remove("./os/nvram")
        self._xmlstate.xmlapi.node_force_remove("./os/loader")

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

    def can_default_virtioscsi(self):
        """
        Return True if the guest supports virtio-scsi, and there's
        no other scsi controllers attached to the guest
        """
        has_any_scsi = any([d.type == "scsi" for d in self.devices.controller])
        return not has_any_scsi and self.supports_virtioscsi()

    def hyperv_supported(self):
        if not self.osinfo.is_windows():
            return False
        return True

    def lookup_domcaps(self):
        def _compare_machine(domcaps):
            if self.os.machine == domcaps.machine:
                return True
            try:
                capsinfo = self.lookup_capsinfo()
            except Exception:
                log.exception("Error fetching machine list for alias "
                              "resolution, assuming mismatch")
                return False
            if capsinfo.is_machine_alias(self.os.machine, domcaps.machine):
                return True
            return False

        # We need to regenerate domcaps cache if any of these values change
        def _compare(domcaps):
            if self.type == "test":
                # Test driver doesn't support domcaps. We kinda fake it in
                # some cases, but it screws up the checking here for parsed XML
                return True
            if self.os.machine and not _compare_machine(domcaps):
                return False
            if self.type and self.type != domcaps.domain:
                return False
            if self.os.arch and self.os.arch != domcaps.arch:
                return False  # pragma: no cover
            if self.emulator and self.emulator != domcaps.path:
                return False
            return True

        if not self._domcaps or not _compare(self._domcaps):
            self._domcaps = DomainCapabilities.build_from_guest(self)
        return self._domcaps

    def lookup_capsinfo(self):
        # We need to regenerate capsinfo cache if any of these values change
        def _compare(capsinfo):  # pragma: no cover
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
        if capsinfo:  # pragma: no cover
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
            self.type != "vz"):
            self.emulator = capsinfo.emulator
        if not self.os.machine:
            self.os.machine = Guest.get_recommended_machine(capsinfo)

        if (wants_default_type and
            self.conn.is_qemu() and
            self.os.is_x86() and
            self.type != "kvm"):
            log.warning(  # pragma: no cover
                    "KVM acceleration not available, using '%s'", self.type)

    def refresh_machine_type(self):
        """
        Reset the guests's machine type to the latest 'canonical' machine
        name that qemu reports. So if my VM is using ancient pc-0.11, we
        try to turn that into just `pc`

        The algorithm here is to fetch all machine types that are aliases
        for a stable name (like pc -> pc-i440fx-6.2), and see if our current
        machine type uses alias as a prefix. This is the format that qemu
        uses for its stable machine type names.
        """
        # We need to unset the machine type first, so we can perform
        # a successful capsinfo lookup, otherwise we will error when qemu
        # has deprecated and removed the old machine type
        original_machine_type = self.os.machine or ""
        self.os.machine = None

        capsinfo = self.lookup_capsinfo()
        mobjs = (capsinfo.domain and
                 capsinfo.domain.machines) or capsinfo.guest.machines
        canonical_names = [m.name for m in mobjs if m.canonical]

        for machine_alias in canonical_names:
            if machine_alias == "pc":
                prefix = "pc-i440fx-"
            elif machine_alias == "q35":
                prefix = "pc-q35-"
            else:
                # Example: pseries-X, virt-X, s390-ccw-virtio-X
                prefix = machine_alias + "-"

            if original_machine_type.startswith(prefix):
                self.os.machine = machine_alias
                return
        raise RuntimeError("Don't know how to refresh machine type '%s'" %
                original_machine_type)

    def set_smbios_serial_cloudinit(self):
        if (not self.conn.is_qemu() and
            not self.conn.is_test()):
            return  # pragma: no cover
        if (not self.os.is_x86() and
            not self.os.is_arm_machvirt()):
            return  # pragma: no cover
        if self.os.smbios_mode not in [None, "sysinfo"]:
            return

        sysinfos = [s for s in self.sysinfo if s.type == "smbios"]
        if not sysinfos:
            sysinfos = [self.sysinfo.add_new()]
        sysinfo = sysinfos[0]

        if sysinfo.system_serial:
            return
        self.os.smbios_mode = "sysinfo"
        sysinfo.type = "smbios"
        sysinfo.system_serial = "ds=nocloud"

    def sync_vcpus_topology(self, defCPUs):
        """
        <cpu> topology count and <vcpus> always need to match. Handle
        the syncing here since we are less constrained then doing it
        in CPU set_defaults
        """
        if not self.vcpus:
            if self.cpu.has_topology():
                self.vcpus = self.cpu.vcpus_from_topology()
            else:
                self.vcpus = defCPUs
        self.cpu.set_topology_defaults(self.vcpus)

    def change_graphics(self, val, inst):
        inst.type = val
        if val == "spice":
            self._add_spice_devices()
        else:
            self._remove_spice_devices(inst)

    def convert_to_q35(self, num_pcie_root_ports=None):
        self.os.machine = "q35"

        if num_pcie_root_ports is not None:
            self.num_pcie_root_ports = int(num_pcie_root_ports)

        for dev in self.devices.get_all():
            if (dev.DEVICE_TYPE == "controller" and
                dev.type in ["pci", "ide"]):
                self.remove_device(dev)
                continue

            if (dev.DEVICE_TYPE == "sound" and
                dev.model == "ich6"):
                dev.model = "ich9"

            if (dev.DEVICE_TYPE == "interface" and
                dev.model == "e1000"):
                dev.model = "e1000e"

            if (dev.DEVICE_TYPE == "disk" and
                dev.bus == "ide"):
                dev.bus = "sata"
                used_targets = [d.target for d in self.devices.disk if d.target]
                dev.generate_target(used_targets)
                dev.address.clear()

            if dev.address.type == "pci":
                dev.address.clear()

        self.add_q35_pcie_controllers()

    def _convert_spice_gl_to_egl_headless(self):
        if not self.has_spice():
            return

        spicedev = [g for g in self.devices.graphics if g.type == "spice"][0]
        if not spicedev.gl:
            return

        dev = DeviceGraphics(self.conn)
        dev.type = "egl-headless"
        dev.set_defaults(self.conn)
        if spicedev.rendernode:
            dev.rendernode = spicedev.rendernode
        self.add_device(dev)

    def _convert_to_vnc_graphics(self, agent):
        """
        If there's already VNC graphics configured, we leave it intact,
        but rip out all evidence of other graphics devices.

        If there's other non-VNC, non-egl-headless configured, we try to
        inplace convert the first device we encounter.

        If there's no graphics configured, set up a default VNC config.`
        """
        vnc_devs = [g for g in self.devices.graphics if g.type == "vnc"]
        # We ignore egl-headless, it's not a true graphical frontend
        other_devs = [g for g in self.devices.graphics if
                      g.type != "vnc" and g.type != "egl-headless"]

        # Guest already had a vnc device.
        # Remove all other devs and we are done
        if vnc_devs:
            for g in other_devs:
                self.remove_device(g)
            return

        # We didn't find any non-vnc device to convert.
        # Add a vnc device with default config
        if not other_devs:
            dev = DeviceGraphics(self.conn)
            dev.type = dev.TYPE_VNC
            dev.set_defaults(self.conn)
            self.add_device(dev)
            return

        # Convert the pre-existing graphics device to vnc
        # Remove the rest
        dev = other_devs.pop(0)
        srcdev = DeviceGraphics(self.conn, dev.get_xml())
        for g in other_devs:
            self.remove_device(g)

        dev.clear()
        dev.type = dev.TYPE_VNC
        dev.keymap = srcdev.keymap
        dev.port = srcdev.port
        dev.autoport = srcdev.autoport
        dev.passwd = srcdev.passwd
        dev.passwdValidTo = srcdev.passwdValidTo
        dev.listen = srcdev.listen
        for listen in srcdev.listens:
            srcdev.remove_child(listen)
            dev.add_child(listen)
        dev.set_defaults(self)

        if agent:
            agent.source.clipboard_copypaste = srcdev.clipboard_copypaste
            agent.source.mouse_mode = srcdev.mouse_mode

    def _convert_to_vnc_video(self):
        """
        If there's no video device, add a default one.
        If there's any qxl device, reset its config to app defaults.
        """
        if not self.devices.video:
            videodev = DeviceVideo(self.conn)
            videodev.set_defaults(self)
            self.add_device(videodev)
            return

        qxl_devs = [v for v in self.devices.video if v.model == "qxl"]
        if qxl_devs and not any(dev.primary for dev in self.devices.video):
            # Make sure `primary` flag is set, we need it up ahead
            self.devices.video[0].primary = True

        for dev in qxl_devs:
            is_primary = dev.primary
            dev.clear()
            dev.set_defaults(self)
            if not is_primary and dev.model != "virtio":
                # Device can't be non-primary, so just remove it
                log.debug("Can't use model=%s for non-primary video device, "
                          "removing it instead.", dev.model)
                self.remove_device(dev)

    def _add_qemu_vdagent(self):
        if any(c for c in self.devices.channel if
               c.type == c.TYPE_QEMUVDAGENT):
            return

        dev = DeviceChannel(self.conn)
        dev.type = dev.TYPE_QEMUVDAGENT
        dev.set_defaults(self)
        self.add_device(dev)
        return dev

    def convert_to_vnc(self, qemu_vdagent=False):
        """
        Convert existing XML to have one VNC graphics connection.
        """
        self._convert_spice_gl_to_egl_headless()

        # Rip out spice graphics devices unconditionally.
        # Could be necessary if XML is in broken state.
        self._force_remove_spice_devices()

        agent = None
        if qemu_vdagent:
            agent = self._add_qemu_vdagent()

        self._convert_to_vnc_graphics(agent)
        self._convert_to_vnc_video()

    def set_defaults(self, _guest):
        self.set_capabilities_defaults()

        if not self.uuid:
            self.uuid = Guest.generate_uuid(self.conn)

        self.sync_vcpus_topology(1)

        self._set_default_machine()
        self._set_default_uefi()

        self._add_default_graphics()
        self._add_default_video_device()
        self._add_default_input_device()
        self._add_default_console_device()
        self._add_default_usb_controller()
        self._add_default_channels()
        self._add_default_rng()
        self._add_default_memballoon()
        self._add_default_tpm()

        self.clock.set_defaults(self)
        self.cpu.set_defaults(self)
        self.features.set_defaults(self)
        for seclabel in self.seclabels:
            seclabel.set_defaults(self)
        self.pm.set_defaults(self)
        self.os.set_defaults(self)
        self.launchSecurity.set_defaults(self)

        for dev in self.devices.get_all():
            dev.set_defaults(self)

        self.add_virtioscsi_controller()
        self.add_q35_pcie_controllers()
        self._add_spice_devices()

    def add_extra_drivers(self, extra_drivers):
        self._extra_drivers = extra_drivers


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
            self.conn.support.qemu_q35_default() and
            self.osinfo.supports_chipset_q35()):
            self.os.machine = "q35"
            return

        default = capsinfo.machines and capsinfo.machines[0] or None
        self.os.machine = default

    def _lookup_default_uefi_path(self):
        """
        If a default UEFI firmware path is found, return it,
        otherwise raise an error
        """
        domcaps = self.lookup_domcaps()

        if not domcaps.supports_uefi_loader():
            raise RuntimeError(_("Libvirt version does not support UEFI."))

        if not domcaps.arch_can_uefi():
            raise RuntimeError(  # pragma: no cover
                _("Don't know how to setup UEFI for arch '%s'") %
                self.os.arch)

        path = domcaps.find_uefi_path_for_arch()
        if not path:  # pragma: no cover
            raise RuntimeError(_("Did not find any UEFI binary path for "
                "arch '%s'") % self.os.arch)

        return path

    def _set_default_uefi(self):
        if self.uefi_requested is False:
            return

        use_default_uefi = (self.prefers_uefi() and
            not self.os.kernel and
            not self.os.loader and
            self.os.loader_ro is None and
            self.os.nvram is None and
            self.os.firmware is None)

        if not use_default_uefi and not self.uefi_requested:
            return

        try:
            self.enable_uefi()
        except RuntimeError as e:
            if self.uefi_requested:
                raise
            log.debug("Error setting UEFI default", exc_info=True)
            log.warning("Couldn't configure UEFI: %s", e)
            log.warning("Your VM may not boot successfully.")

    def _usb_disabled(self):
        controllers = [c for c in self.devices.controller if
            c.type == "usb"]
        if not controllers:
            return False
        return all([c.model == "none" for c in controllers])

    def _add_default_input_device(self):
        if self.skip_default_input:
            return
        if self.os.is_container():
            return
        if self.os.is_xenpv():
            return
        if self.devices.input:
            return
        if not self.devices.graphics:
            return

        tablet = True
        keyboard = True
        if self.os.is_x86():
            # We don't historically add USB keyboard for x86,
            # default libvirt/qemu PS2 seems to be fine
            keyboard = False

        bus = None
        if self.os.is_s390x():
            # s390x guests need VirtIO input devices
            if self.osinfo.supports_virtioinput(self._extra_drivers):
                bus = "virtio"
        elif not self._usb_disabled():
            bus = "usb"

        if not bus:
            return

        def _add_input(itype):
            dev = DeviceInput(self.conn)
            dev.type = itype
            dev.bus = bus
            dev.set_defaults(self)
            self.add_device(dev)

        if tablet:
            _add_input("tablet")
        if keyboard:
            _add_input("keyboard")

    def _add_default_console_device(self):
        if self.skip_default_console:
            return
        if self.devices.console or self.devices.serial:
            return

        dev = DeviceConsole(self.conn)
        if self.conn.is_bhyve():
            nmdm_dev_prefix = '/dev/nmdm{}'.format(self.generate_uuid(self.conn))
            dev.type = dev.TYPE_NMDM
            dev.source.master = nmdm_dev_prefix + 'A'
            dev.source.slave = nmdm_dev_prefix + 'B'
        else:
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

        qemu_usb3 = self.conn.support.conn_qemu_xhci()
        usb2 = False
        usb3 = False
        if self.os.is_x86():
            usb3 = bool(self.osinfo.supports_usb3() and qemu_usb3)
            usb2 = not usb3
        elif self.os.is_arm_machvirt():
            # For machvirt, we always assume OS supports usb3
            if (qemu_usb3 and
                self.conn.support.conn_machvirt_pci_default()):
                usb3 = True
        elif self.os.is_riscv_virt():
            # For RISC-V we can assume the guest OS supports USB3, but we
            # have to make sure libvirt and QEMU are new enough to be using
            # PCI by default
            if (qemu_usb3 and
                self.conn.support.conn_riscv_virt_pci_default()):
                usb3 = True
        elif self.os.is_pseries():
            # For pseries, we always assume OS supports usb3
            if qemu_usb3:
                usb3 = True
        elif self.os.is_loongarch64():
            # For loongarch64, we always assume OS supports usb3
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

        if (self.conn.is_qemu() and
            self._supports_virtioserial() and
            self.conn.support.conn_autosocket()):
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
        if (not self.os.is_x86() and
            not self.os.is_pseries() and
            not self.os.is_loongarch64() and
            not self.os.is_arm_machvirt() and
            not self.os.is_riscv_virt()):
            return
        self.add_device(DeviceGraphics(self.conn))

    def _add_default_rng(self):
        if self.skip_default_rng:
            return
        if self.devices.rng:
            return
        if not (self.os.is_x86() or
                self.os.is_arm_machvirt() or
                self.os.is_riscv_virt() or
                self.os.is_s390x() or
                self.os.is_pseries() or
                self.os.is_loongarch64()):
            return

        if (self.conn.is_qemu() and
            self.osinfo.supports_virtiorng(self._extra_drivers) and
            self.conn.support.conn_rng_urandom()):
            dev = DeviceRng(self.conn)
            dev.type = "random"
            dev.device = "/dev/urandom"
            self.add_device(dev)

    def _add_default_tpm(self):
        if self.skip_default_tpm:
            return
        if self.devices.tpm:
            return

        # If the guest is using UEFI, we take that as a
        # flag that the VM is targeting a modern platform
        # and thus we should also provide an emulated TPM.
        if not self.is_uefi():
            return

        if not self.lookup_domcaps().supports_tpm_emulator():
            log.debug("Domain caps doesn't report TPM support")
            return

        log.debug("Adding default TPM")
        dev = DeviceTpm(self.conn)
        dev.type = DeviceTpm.TYPE_EMULATOR
        self.add_device(dev)
        self.have_default_tpm = True

    def _add_default_memballoon(self):
        if self.devices.memballoon:
            return
        if not self.conn.is_qemu():
            return

        # We know for certain that a memballoon is good to have with these
        # machine types; for other machine types, we leave the decision up
        # to libvirt
        if not (self.os.is_x86() or
                self.os.is_arm_machvirt() or
                self.os.is_riscv_virt() or
                self.os.is_s390x() or
                self.os.is_pseries() or
                self.os.is_loongarch64()):
            return

        if self.osinfo.supports_virtioballoon(self._extra_drivers):
            dev = DeviceMemballoon(self.conn)
            dev.model = "virtio"
            self.add_device(dev)

    def add_virtioscsi_controller(self):
        if not self.can_default_virtioscsi():
            return
        if not any([d for d in self.devices.disk if d.bus == "scsi"]):
            return

        ctrl = DeviceController(self.conn)
        ctrl.type = "scsi"
        ctrl.model = "virtio-scsi"
        ctrl.set_defaults(self)
        self.add_device(ctrl)

    def defaults_to_pcie(self):
        if self.os.is_q35():
            return True
        if self.os.is_arm_machvirt():
            return True
        if self.os.is_riscv_virt():
            return True
        if self.os.is_loongarch64():
            return True
        return False

    def add_q35_pcie_controllers(self):
        if any([c for c in self.devices.controller if c.type == "pci"]):
            return
        if not self.defaults_to_pcie():
            return

        added = False
        log.debug("Using num_pcie_root_ports=%s", self.num_pcie_root_ports)
        for dummy in range(max(self.num_pcie_root_ports, 0)):
            if not added:
                # Libvirt forces pcie-root to come first
                ctrl = DeviceController(self.conn)
                ctrl.type = "pci"
                ctrl.model = "pcie-root"
                ctrl.set_defaults(self)
                self.add_device(ctrl)
                added = True
            ctrl = DeviceController(self.conn)
            ctrl.type = "pci"
            ctrl.model = "pcie-root-port"
            ctrl.set_defaults(self)
            self.add_device(ctrl)

    def _add_spice_channels(self):
        if not self.lookup_domcaps().supports_channel_spicevmc():
            return  # pragma: no cover
        if self.skip_default_channel:
            return
        for chn in self.devices.channel:
            if chn.type == chn.TYPE_SPICEVMC:
                return

        # We explicitly don't check for virtioserial support here.
        # We did that for a while, which excluded windows, and
        # we received some complaints.
        # https://bugzilla.redhat.com/show_bug.cgi?id=1660123
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
            return  # pragma: no cover

        dev = DeviceSound(self.conn)
        dev.set_defaults(self)
        self.add_device(dev)

    def _add_spice_usbredir(self):
        if not self.lookup_domcaps().supports_redirdev_usb():
            return  # pragma: no cover
        if self.skip_default_usbredir:
            return
        if self.devices.redirdev:
            return
        if self._usb_disabled():
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
            self.conn.support.conn_vmport()):
            self.features.vmport = False

        self._add_spice_channels()
        self._add_spice_sound()
        self._add_spice_usbredir()

    def _remove_duplicate_console(self, dev):
        condup = DeviceConsole.get_console_duplicate(self, dev)
        if condup:
            log.debug("Found duplicate console device:\n%s", condup.get_xml())
            self.devices.remove_child(condup)

    def _remove_spice_audio(self):
        for audio in self.devices.audio:
            if audio.type == "spice":
                self.devices.remove_child(audio)

    def _remove_spice_channels(self):
        for channel in self.devices.channel:
            if channel.type == DeviceChannel.TYPE_SPICEVMC:
                self.devices.remove_child(channel)

    def _remove_spice_usbredir(self):
        for redirdev in self.devices.redirdev:
            if redirdev.type == "spicevmc":
                self.devices.remove_child(redirdev)

    def _remove_spiceport(self):
        for dev in self.devices.serial + self.devices.console:
            if dev.type == dev.TYPE_SPICEPORT:
                self.devices.remove_child(dev)

    def _force_remove_spice_devices(self):
        self._remove_spice_audio()
        self._remove_spice_channels()
        self._remove_spice_usbredir()
        self._remove_spiceport()

    def _remove_spice_devices(self, rmdev):
        if rmdev.DEVICE_TYPE != "graphics" or self.has_spice():
            return
        self._force_remove_spice_devices()
