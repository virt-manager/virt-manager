#
# Common code for all guests
#
# Copyright 2006-2009, 2013, 2014 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
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

import urlgrabber.progress as progress
import libvirt

from virtcli import cliconfig

from . import osdict
from . import util
from . import support
from .clock import Clock
from .cpu import CPU
from .device import VirtualDevice
from .deviceaudio import VirtualAudio
from .devicechar import VirtualChannelDevice, VirtualConsoleDevice
from .devicecontroller import VirtualController
from .devicegraphics import VirtualGraphics
from .deviceinput import VirtualInputDevice
from .deviceredirdev import VirtualRedirDevice
from .devicevideo import VirtualVideoDevice
from .distroinstaller import DistroInstaller
from .domainblkiotune import DomainBlkiotune
from .domainfeatures import DomainFeatures
from .domainmemorybacking import DomainMemorybacking
from .domainmemorytune import DomainMemorytune
from .domainnumatune import DomainNumatune
from .domainresource import DomainResource
from .idmap import IdMap
from .osxml import OSXML
from .pm import PM
from .seclabel import Seclabel
from .xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


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
        except libvirt.libvirtError, e:
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
        except:
            return
        raise ValueError(_("Guest name '%s' is already in use.") % name)


    _XML_ROOT_NAME = "domain"
    _XML_PROP_ORDER = ["type", "name", "uuid", "title", "description",
        "maxmemory", "memory", "blkiotune", "memtune", "memoryBacking",
        "vcpus", "curvcpus", "numatune", "bootloader", "os", "idmap", "features",
        "cpu", "clock", "on_poweroff", "on_reboot", "on_crash", "resource", "pm",
        "emulator", "_devices", "seclabel"]

    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)

        self.autostart = False
        self.replace = False

        # Allow virt-manager to override the default graphics type
        self.default_graphics_type = cliconfig.default_graphics

        self.skip_default_console = False
        self.skip_default_channel = False
        self.skip_default_sound = False
        self.skip_default_usbredir = False
        self.skip_default_graphics = False
        self.x86_cpu_default = self.cpu.SPECIAL_MODE_HOST_MODEL_ONLY

        self._os_variant = None
        self._random_uuid = None
        self._install_devices = []

        # The libvirt virDomain object we 'Create'
        self.domain = None

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
                         default_cb=lambda s: 1,
                         set_converter=_set_memory)
    maxmemory = XMLProperty("./memory", is_int=True)

    def _set_vcpus(self, val):
        if val is None:
            return None

        # Don't force set curvcpus unless already specified
        if self.curvcpus is not None and self.curvcpus > val:
            self.curvcpus = val
        return val
    vcpus = XMLProperty("./vcpu", is_int=True,
                        set_converter=_set_vcpus,
                        default_cb=lambda s: 1)
    curvcpus = XMLProperty("./vcpu/@current", is_int=True)

    def _validate_cpuset(self, val):
        DomainNumatune.validate_cpuset(self.conn, val)
    cpuset = XMLProperty("./vcpu/@cpuset",
                         validate_cb=_validate_cpuset)

    def _get_default_uuid(self):
        if self._random_uuid is None:
            self._random_uuid = util.generate_uuid(self.conn)
        return self._random_uuid
    uuid = XMLProperty("./uuid",
                       validate_cb=lambda s, v: util.validate_uuid(v),
                       default_cb=_get_default_uuid)

    id = XMLProperty("./@id", is_int=True)
    type = XMLProperty("./@type", default_cb=lambda s: "xen")
    bootloader = XMLProperty("./bootloader")
    description = XMLProperty("./description")
    title = XMLProperty("./title")
    emulator = XMLProperty("./devices/emulator")

    on_poweroff = XMLProperty("./on_poweroff",
                              default_cb=lambda s: "destroy")
    on_reboot = XMLProperty("./on_reboot")
    on_crash = XMLProperty("./on_crash")

    os = XMLChildProperty(OSXML, is_single=True)
    features = XMLChildProperty(DomainFeatures, is_single=True)
    clock = XMLChildProperty(Clock, is_single=True)
    seclabel = XMLChildProperty(Seclabel, is_single=True)
    cpu = XMLChildProperty(CPU, is_single=True)
    numatune = XMLChildProperty(DomainNumatune, is_single=True)
    pm = XMLChildProperty(PM, is_single=True)
    blkiotune = XMLChildProperty(DomainBlkiotune, is_single=True)
    memtune = XMLChildProperty(DomainMemorytune, is_single=True)
    memoryBacking = XMLChildProperty(DomainMemorybacking, is_single=True)
    idmap = XMLChildProperty(IdMap, is_single=True)
    resource = XMLChildProperty(DomainResource, is_single=True)


    ###############################
    # Distro detection properties #
    ###############################

    def _get_os_variant(self):
        return self._os_variant
    def _set_os_variant(self, val):
        if val:
            val = val.lower()
            if osdict.lookup_os(val) is None:
                raise ValueError(
                    _("Distro '%s' does not exist in our dictionary") % val)

        logging.debug("Setting Guest.os_variant to '%s'", val)
        self._os_variant = val
    os_variant = property(_get_os_variant, _set_os_variant)


    ########################################
    # Device Add/Remove Public API methods #
    ########################################

    def add_device(self, dev):
        """
        Add the passed device to the guest's device list.

        @param dev: VirtualDevice instance to attach to guest
        """
        self._add_child(dev)

    def remove_device(self, dev):
        """
        Remove the passed device from the guest's device list

        @param dev: VirtualDevice instance
        """
        self._remove_child(dev)

    def get_devices(self, devtype):
        """
        Return a list of devices of type 'devtype' that will installed on
        the guest.

        @param devtype: Device type to search for (one of
                        VirtualDevice.virtual_device_types)
        """
        newlist = []
        for i in self._devices:
            if devtype == "all" or i.virtual_device_type == devtype:
                newlist.append(i)
        return newlist
    _devices = XMLChildProperty(
        [VirtualDevice.virtual_device_classes[_n]
         for _n in VirtualDevice.virtual_device_types],
        relative_xpath="./devices")

    def get_all_devices(self):
        """
        Return a list of all devices being installed with the guest
        """
        retlist = []
        for devtype in VirtualDevice.virtual_device_types:
            retlist.extend(self.get_devices(devtype))
        return retlist


    ############################
    # Install Helper functions #
    ############################

    def _prepare_install(self, meter, dry=False):
        for dev in self._install_devices:
            self.remove_device(dev)
        self._install_devices = []
        ignore = dry

        # Fetch install media, prepare installer devices
        self.installer.prepare(self, meter)

        # Initialize install device list
        for dev in self.installer.install_devices:
            self.add_device(dev)
            self._install_devices.append(dev)


    ##############
    # Public API #
    ##############

    def _prepare_get_xml(self):
        # We do a shallow copy of the device list here, and set the defaults.
        # This way, default changes aren't persistent, and we don't need
        # to worry about when to call set_defaults
        #
        # XXX: this is hacky, we should find a way to use xmlbuilder.copy(),
        # but need to make sure it's not a massive performance hit
        data = (self._devices[:], self.features, self.os)
        try:
            self._propstore["_devices"] = [dev.copy() for dev in self._devices]
            self._propstore["features"] = self.features.copy()
            self._propstore["os"] = self.os.copy()
        except:
            self._finish_get_xml(data)
            raise
        return data

    def _finish_get_xml(self, data):
        (self._propstore["_devices"],
         self._propstore["features"],
         self._propstore["os"]) = data

    def get_install_xml(self, *args, **kwargs):
        data = self._prepare_get_xml()
        try:
            return self._do_get_install_xml(*args, **kwargs)
        finally:
            self._finish_get_xml(data)

    def _do_get_install_xml(self, install=True, disk_boot=False):
        """
        Return the full Guest xml configuration.

        @param install: Whether we want the 'OS install' configuration or
                        the 'post-install' configuration. (Some installs,
                        like an import or livecd may not have an 'install'
                        config.)
        @type install: C{bool}
        @param disk_boot: Whether we should boot off the harddisk, regardless
                          of our position in the install process (this is
                          used for 2 stage installs, where the second stage
                          boots off the disk. You probably don't need to touch
                          this.)
        @type disk_boot: C{bool}
        """
        osblob_install = install and not disk_boot
        if osblob_install and not self.installer.has_install_phase():
            return None

        self.installer.alter_bootconfig(self, osblob_install, self.os)
        self._set_transient_device_defaults(install)

        action = install and "destroy" or "restart"
        self.on_reboot = action
        self.on_crash = action

        self._set_defaults()

        self.bootloader = None
        if (not install and
            self.os.is_xenpv() and
            not self.os.kernel):
            self.bootloader = "/usr/bin/pygrub"
            self.os.clear()

        return self.get_xml_config()

    def get_continue_inst(self):
        """
        Return True if this guest requires a call to 'continue_install',
        which means the OS requires a 2 stage install (windows)
        """
        # If we are doing an 'import' or 'liveCD' install, there is
        # no true install process, so continue install has no meaning
        if not self.installer.has_install_phase():
            return False

        return self._lookup_osdict_key("three_stage_install", False)


    ##########################
    # Actual install methods #
    ##########################

    def start_install(self, meter=None,
                      dry=False, return_xml=False, noboot=False):
        """
        Begin the guest install (stage1).
        @param return_xml: Don't create the guest, just return generated XML
        """
        if self.domain is not None:
            raise RuntimeError(_("Domain has already been started!"))

        is_initial = True

        self._prepare_install(meter, dry)
        try:
            # Create devices if required (disk images, etc.)
            if not dry:
                for dev in self.get_all_devices():
                    dev.setup(meter)

            start_xml, final_xml = self._build_xml(is_initial)
            if return_xml:
                return (start_xml, final_xml)
            if dry:
                return

            # Remove existing VM if requested
            self.check_vm_collision(self.conn, self.name,
                                    do_remove=self.replace)

            self.domain = self._create_guest(meter,
                                             start_xml, final_xml, is_initial,
                                             noboot)
            # Set domain autostart flag if requested
            self._flag_autostart()

            return self.domain
        finally:
            self.installer.cleanup()

    def continue_install(self, meter=None,
                         dry=False, return_xml=False):
        """
        Continue with stage 2 of a guest install. Only required for
        guests which have the 'continue' flag set (accessed via
        get_continue_inst)
        """
        is_initial = False
        start_xml, final_xml = self._build_xml(is_initial)
        if return_xml:
            return (start_xml, final_xml)
        if dry:
            return

        return self._create_guest(meter,
                                  start_xml, final_xml, is_initial, False)

    def _build_meter(self, meter, is_initial):
        if is_initial:
            meter_label = _("Creating domain...")
        else:
            meter_label = _("Starting domain...")

        if meter is None:
            meter = progress.BaseMeter()
        meter.start(size=None, text=meter_label)

        return meter

    def _build_xml(self, is_initial):
        log_label = is_initial and "install" or "continue"
        disk_boot = not is_initial

        start_xml = self.get_install_xml(install=True, disk_boot=disk_boot)
        final_xml = self.get_install_xml(install=False)

        logging.debug("Generated %s XML: %s",
                      log_label,
                      (start_xml and ("\n" + start_xml) or "None required"))
        logging.debug("Generated boot XML: \n%s", final_xml)

        return start_xml, final_xml

    def _create_guest(self, meter,
                      start_xml, final_xml, is_initial, noboot):
        """
        Actually do the XML logging, guest defining/creating

        @param is_initial: If running initial guest creation, else we
                           are continuing the install
        @param noboot: Don't boot guest if no install phase
        """
        meter = self._build_meter(meter, is_initial)
        doboot = not noboot or self.installer.has_install_phase()

        if is_initial and doboot:
            dom = self.conn.createLinux(start_xml or final_xml, 0)
        else:
            dom = self.conn.defineXML(start_xml or final_xml)
            if doboot:
                dom.create()

        self.domain = dom
        meter.end(0)

        self.domain = self.conn.defineXML(final_xml)
        if is_initial:
            try:
                logging.debug("XML fetched from libvirt object:\n%s",
                              dom.XMLDesc(0))
            except Exception, e:
                logging.debug("Error fetching XML from libvirt object: %s", e)

        return self.domain


    def _flag_autostart(self):
        """
        Set the autostart flag for self.domain if the user requested it
        """
        if not self.autostart:
            return

        try:
            self.domain.setAutostart(True)
        except libvirt.libvirtError, e:
            if util.is_error_nosupport(e):
                logging.warn("Could not set autostart flag: libvirt "
                             "connection does not support autostart.")
            else:
                raise e


    ###################################
    # Guest Dictionary Helper methods #
    ###################################

    def _get_os_object(self):
        ret = osdict.lookup_os(self.os_variant)
        if ret is None:
            ret = osdict.lookup_os("generic")
        return ret
    _os_object = property(_get_os_object)


    def _lookup_osdict_key(self, key, default):
        """
        Use self.os_variant to find key in OSTYPES
        @returns: dict value, or None if os_type/variant wasn't set
        """
        return osdict.lookup_osdict_key(self.os_variant, key, default)


    ###################
    # Device defaults #
    ###################

    def add_default_input_device(self):
        if self.os.is_container():
            return
        if not self.os.is_x86():
            return
        if self.get_devices("input"):
            return
        self.add_device(VirtualInputDevice(self.conn))

    def add_default_sound_device(self):
        if not self.os.is_hvm():
            return
        if not self.os.is_x86():
            return
        self.add_device(VirtualAudio(self.conn))

    def add_default_console_device(self):
        if self.skip_default_console:
            return
        if self.os.is_xenpv():
            return
        if self.get_devices("console") or self.get_devices("serial"):
            return

        dev = VirtualConsoleDevice(self.conn)
        dev.type = dev.TYPE_PTY

        if (self.os.is_x86() and
            self._lookup_osdict_key("virtioconsole", False) and
            self.conn.check_support(
            self.conn.SUPPORT_CONN_VIRTIO_CONSOLE)):
            dev.target_type = "virtio"

        self.add_device(dev)

    def add_default_video_device(self):
        if self.os.is_container():
            return
        if self.get_devices("video"):
            return
        if not self.get_devices("graphics"):
            return
        self.add_device(VirtualVideoDevice(self.conn))

    def add_default_usb_controller(self):
        if self.os.is_container():
            return
        if not self.os.is_x86():
            return
        if any([d.type == "usb" for d in self.get_devices("controller")]):
            return
        if not self.conn.check_support(
            self.conn.SUPPORT_CONN_DEFAULT_USB2):
            return
        for dev in VirtualController.get_usb2_controllers(self.conn):
            self.add_device(dev)

    def add_default_channels(self):
        if self.skip_default_channel:
            return
        if self.get_devices("channel"):
            return

        # Skip qemu-ga on ARM where virtio slots are currently limited
        if (self.conn.is_qemu() and
            not self.os.is_arm() and
            self._lookup_osdict_key("qemu_ga", False) and
            self.conn.check_support(self.conn.SUPPORT_CONN_AUTOSOCKET)):
            dev = VirtualChannelDevice(self.conn)
            dev.type = "unix"
            dev.target_type = "virtio"
            dev.target_name = dev.CHANNEL_NAME_QEMUGA
            self.add_device(dev)

    def add_default_graphics(self):
        if self.skip_default_graphics:
            return
        if self.get_devices("graphics"):
            return
        if self.os.is_container():
            return
        if self.os.arch not in ["x86_64", "i686", "ppc64", "ia64"]:
            return
        self.add_device(VirtualGraphics(self.conn))

    def add_default_devices(self):
        self.add_default_graphics()
        self.add_default_video_device()
        self.add_default_input_device()
        self.add_default_console_device()
        self.add_default_usb_controller()
        self.add_default_channels()

    def _set_transient_device_defaults(self, install):
        def do_remove_media(d):
            # Keep cdrom around, but with no media attached,
            # But only if we are a distro that doesn't have a multi
            # stage install (aka not Windows)
            return (d.is_cdrom() and
                    d.transient and
                    not install and
                    not self.get_continue_inst())

        def do_skip_disk(d):
            # Skip transient labeled non-media disks
            return (d.is_disk() and d.transient and not install)

        for dev in self.get_devices("disk"):
            if do_skip_disk(dev):
                self.remove_device(dev)
            elif do_remove_media(dev):
                dev.path = None

    def _set_defaults(self):
        self._set_osxml_defaults()
        self._set_clock_defaults()
        self._set_emulator_defaults()
        self._set_cpu_defaults()
        self._set_feature_defaults()

        for dev in self.get_all_devices():
            dev.set_defaults(self)
        self._add_implied_controllers()
        self._check_address_multi()
        self._set_disk_defaults()
        self._set_net_defaults()
        self._set_input_defaults()
        self._set_graphics_defaults()
        self._set_video_defaults()
        self._set_sound_defaults()

    def _is_full_os_container(self):
        if not self.os.is_container():
            return False
        for fs in self.get_devices("filesystem"):
            if fs.target == "/":
                return True
        return False

    def _set_osxml_defaults(self):
        if self.os.is_container() and not self.os.init:
            if self._is_full_os_container():
                self.os.init = "/sbin/init"
            self.os.init = self.os.init or "/bin/sh"

        if not self.os.loader and self.os.is_hvm() and self.type == "xen":
            self.os.loader = "/usr/lib/xen/boot/hvmloader"
        if self.os.os_type == "xen" and self.type == "xen":
            # Use older libvirt 'linux' value for back compat
            self.os.os_type = "linux"
        if self.os.kernel or self.os.init:
            self.os.bootorder = []

    def _set_clock_defaults(self):
        if not self.os.is_hvm():
            return

        if self.clock.offset is None:
            self.clock.offset = self._lookup_osdict_key("clock", "utc")

        if self.clock.timers:
            return
        if not self.os.is_x86():
            return
        if not self.conn.check_support(
            self.conn.SUPPORT_CONN_ADVANCED_CLOCK):
            return

        # Set clock policy that maps to qemu options:
        #   -no-hpet -no-kvm-pit-reinjection -rtc driftfix=slew
        #
        # hpet: Is unneeded and has a performance penalty
        # pit: While it has no effect on windows, it doesn't hurt and
        #   is beneficial for linux
        #
        # If libvirt/qemu supports it and using a windows VM, also
        # specify hypervclock.
        #
        # This is what has been recommended by the RH qemu guys :)

        rtc = self.clock.add_timer()
        rtc.name = "rtc"
        rtc.tickpolicy = "catchup"

        pit = self.clock.add_timer()
        pit.name = "pit"
        pit.tickpolicy = "delay"

        hpet = self.clock.add_timer()
        hpet.name = "hpet"
        hpet.present = False

        if (self._lookup_osdict_key("hyperv_features", False) and
            self.conn.check_support(self.conn.SUPPORT_CONN_HYPERV_CLOCK)):
            hyperv = self.clock.add_timer()
            hyperv.name = "hypervclock"
            hyperv.present = True

    def _set_emulator_defaults(self):
        if self.os.is_xenpv():
            self.emulator = None
            return

        if self.emulator:
            return

        if self.os.is_hvm() and self.type == "xen":
            if self.conn.caps.host.cpu.arch == "x86_64":
                self.emulator = "/usr/lib64/xen/bin/qemu-dm"
            else:
                self.emulator = "/usr/lib/xen/bin/qemu-dm"

    def _set_cpu_defaults(self):
        self.cpu.set_topology_defaults(self.vcpus)

        if not self.conn.is_test() and not self.conn.is_qemu():
            return
        if self.cpu.get_xml_config().strip():
            # User already configured CPU
            return

        if self.os.is_arm_machvirt() and self.type == "kvm":
            # Should be host-passthrough, but the libvirt support is
            # incomplete for arm cpu
            self.cpu.model = "host"

        elif self.os.is_arm64() and self.os.is_arm_machvirt():
            # -M virt defaults to a 32bit CPU, even if using aarch64
            self.cpu.model = "cortex-a57"

        elif self.os.is_x86() and self.type == "kvm":
            if self.os.arch != self.conn.caps.host.cpu.arch:
                return

            # We need this check to handle the user setting --cpu none on
            # the CLI to override our defaults
            if self.cpu.special_mode_was_set:
                return
            self.cpu.set_special_mode(self.x86_cpu_default)

    def _set_feature_defaults(self):
        if self.os.is_container():
            self.features.acpi = None
            self.features.apic = None
            self.features.pae = None
            if self._is_full_os_container():
                self.features.privnet = True
            return

        if not self.os.is_hvm():
            return

        default = True
        if (self._lookup_osdict_key("xen_disable_acpi", False) and
            not self.conn.check_support(support.SUPPORT_CONN_CAN_ACPI)):
            default = False

        if self.features.acpi == "default":
            self.features.acpi = self._lookup_osdict_key("acpi", default)
        if self.features.apic == "default":
            self.features.apic = self._lookup_osdict_key("apic", default)
        if self.features.pae == "default":
            self.features.pae = self.conn.caps.support_pae()

        if (self._lookup_osdict_key("hyperv_features", False) and
            self.conn.check_support(self.conn.SUPPORT_CONN_HYPERV_VAPIC)):
            if self.features.hyperv_relaxed is None:
                self.features.hyperv_relaxed = True
            if self.features.hyperv_vapic is None:
                self.features.hyperv_vapic = True
            if self.features.hyperv_spinlocks is None:
                self.features.hyperv_spinlocks = True
            if self.features.hyperv_spinlocks_retries is None:
                self.features.hyperv_spinlocks_retries = 8191

    def _add_implied_controllers(self):
        for dev in self.get_all_devices():
            # Add spapr-vio controller if needed
            if (dev.address.type == "spapr-vio" and
                dev.virtual_device_type == "disk" and
                not any([cont.address.type == "spapr-vio" for cont in
                        self.get_devices("controller")])):
                ctrl = VirtualController(self.conn)
                ctrl.type = "scsi"
                ctrl.address.set_addrstr("spapr-vio")
                self.add_device(ctrl)

    def _check_address_multi(self):
        addresses = {}
        for d in self.get_all_devices():
            if d.address.type != d.address.ADDRESS_TYPE_PCI:
                continue

            addr = d.address
            addrstr = "%d%d%d" % (d.address.domain,
                                  d.address.bus,
                                  d.address.slot)

            if addrstr not in addresses:
                addresses[addrstr] = {}
            if addr.function in addresses[addrstr]:
                raise ValueError(_("Duplicate address for devices %s and %s") %
                                 (str(d), str(addresses[addrstr][addr.function])))
            addresses[addrstr][addr.function] = d

        for devs in addresses.values():
            if len(devs) > 1 and 0 in devs:
                devs[0].address.multifunction = True

    def _can_virtio(self, key):
        if not self.conn.is_qemu():
            return False

        if self.os.is_arm_machvirt():
            # Only supports virtio
            return True

        if not self._lookup_osdict_key(key, False):
            return False

        if self.os.is_x86():
            return True

        if (self.os.is_arm_vexpress() and
            self.os.dtb and
            self._lookup_osdict_key("virtiommio", False) and
            self.conn.check_support(support.SUPPORT_CONN_VIRTIO_MMIO)):
            return True

        return False

    def _set_disk_defaults(self):
        os_disk_bus = self._lookup_osdict_key("diskbus", None)

        def set_disk_bus(d):
            if d.is_floppy():
                d.bus = "fdc"
                return
            if self.os.is_xenpv():
                d.bus = "xen"
                return
            if not self.os.is_hvm():
                d.bus = "ide"
                return

            if self._can_virtio("virtiodisk") and d.is_disk():
                d.bus = "virtio"
            elif os_disk_bus and d.is_disk():
                d.bus = os_disk_bus
            elif self.os.is_pseries():
                d.bus = "scsi"
            elif self.os.is_arm():
                d.bus = "sd"
            else:
                d.bus = "ide"

        used_targets = []
        for disk in self.get_devices("disk"):
            if not disk.bus:
                set_disk_bus(disk)

            # Generate disk targets
            if disk.target and not getattr(disk, "cli_set_target", False):
                used_targets.append(disk.target)
            else:
                used_targets.append(disk.generate_target(used_targets))

    def _set_net_defaults(self):
        if not self.os.is_hvm():
            net_model = None
        elif self._can_virtio("virtionet"):
            net_model = "virtio"
        else:
            net_model = self._lookup_osdict_key("netmodel", None)

        for net in self.get_devices("interface"):
            if net_model and not net.model:
                net.model = net_model

    def _set_input_defaults(self):
        input_type = self._lookup_osdict_key("inputtype", "mouse")
        input_bus = self._lookup_osdict_key("inputbus", "ps2")
        if self.os.is_xenpv():
            input_type = VirtualInputDevice.TYPE_MOUSE
            input_bus = VirtualInputDevice.BUS_XEN

        for inp in self.get_devices("input"):
            if (inp.type == inp.TYPE_DEFAULT and
                inp.bus  == inp.BUS_DEFAULT):
                inp.type = input_type
                inp.bus  = input_bus

    def _set_sound_defaults(self):
        if self.conn.check_support(
                support.SUPPORT_CONN_SOUND_ICH6):
            default = "ich6"
        elif self.conn.check_support(
                support.SUPPORT_CONN_SOUND_AC97):
            default = "ac97"
        else:
            default = "es1370"

        for sound in self.get_devices("sound"):
            if sound.model == sound.MODEL_DEFAULT:
                sound.model = default

    def _set_graphics_defaults(self):
        for gfx in self.get_devices("graphics"):
            if gfx.type != "default":
                continue

            gtype = self.default_graphics_type
            logging.debug("Using default_graphics=%s", gtype)
            if (gtype == "spice" and not
                self.conn.check_support(
                    self.conn.SUPPORT_CONN_GRAPHICS_SPICE)):
                logging.debug("spice requested but HV doesn't support it. "
                              "Using vnc.")
                gtype = "vnc"
            gfx.type = gtype

    def _add_spice_channels(self):
        if self.skip_default_channel:
            return

        for chn in self.get_devices("channel"):
            if chn.type == chn.TYPE_SPICEVMC:
                return

        if self.conn.check_support(self.conn.SUPPORT_CONN_CHAR_SPICEVMC):
            agentdev = VirtualChannelDevice(self.conn)
            agentdev.type = agentdev.TYPE_SPICEVMC
            self.add_device(agentdev)

    def _add_spice_sound(self):
        if self.skip_default_sound:
            return
        if self.get_devices("sound"):
            return
        self.add_default_sound_device()

    def _add_spice_usbredir(self):
        if self.skip_default_usbredir:
            return
        if self.get_devices("redirdev"):
            return
        if not self.conn.check_support(self.conn.SUPPORT_CONN_USBREDIR):
            return

        # If we use 4 devices here, we fill up all the emulated USB2 slots,
        # and directly assigned devices are forced to fall back to USB1
        # https://bugzilla.redhat.com/show_bug.cgi?id=1135488
        for ignore in range(2):
            dev = VirtualRedirDevice(self.conn)
            dev.bus = "usb"
            dev.type = "spicevmc"
            self.add_device(dev)

    def has_spice(self):
        for gfx in self.get_devices("graphics"):
            if gfx.type == gfx.TYPE_SPICE:
                return True

    def _set_video_defaults(self):
        if self.has_spice():
            self._add_spice_channels()
            self._add_spice_sound()
            self._add_spice_usbredir()

        video_model = self._os_object.get_videomodel(self)
        for video in self.get_devices("video"):
            if video.model == video.MODEL_DEFAULT:
                video.model = video_model
