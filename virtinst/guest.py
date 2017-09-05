#
# Common code for all guests
#
# Copyright 2006-2009, 2013, 2014, 2015 Red Hat, Inc.
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
import os

import libvirt

from virtcli import CLIConfig

from . import util
from . import support
from .osdict import OSDB
from .clock import Clock
from .cpu import CPU
from .device import VirtualDevice
from .deviceaudio import VirtualAudio
from .devicechar import VirtualChannelDevice, VirtualConsoleDevice
from .devicecontroller import VirtualController
from .devicedisk import VirtualDisk
from .devicegraphics import VirtualGraphics
from .deviceinput import VirtualInputDevice
from .devicepanic import VirtualPanicDevice
from .deviceredirdev import VirtualRedirDevice
from .devicerng import VirtualRNGDevice
from .devicevideo import VirtualVideoDevice
from .distroinstaller import DistroInstaller
from .domainblkiotune import DomainBlkiotune
from .domainfeatures import DomainFeatures
from .domainmemorybacking import DomainMemorybacking
from .domainmemorytune import DomainMemorytune
from .domainnumatune import DomainNumatune
from .domainresource import DomainResource
from .domcapabilities import DomainCapabilities
from .idmap import IdMap
from .osxml import OSXML
from .pm import PM
from .seclabel import Seclabel
from .sysinfo import SYSInfo
from .xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty
from .xmlnsqemu import XMLNSQemu


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


    _XML_ROOT_NAME = "domain"
    _XML_PROP_ORDER = ["type", "name", "uuid", "title", "description",
        "hotplugmemorymax", "hotplugmemoryslots", "maxmemory", "memory", "blkiotune",
        "memtune", "memoryBacking", "vcpus", "curvcpus", "vcpu_placement",
        "cpuset", "numatune", "resource", "sysinfo", "bootloader", "os", "idmap",
        "features", "cpu", "clock", "on_poweroff", "on_reboot", "on_crash",
        "pm", "emulator", "_devices", "seclabels"]

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

        self.__os_object = None
        self._random_uuid = None
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
                         default_cb=lambda s: 1,
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
                        set_converter=_set_vcpus,
                        default_cb=lambda s: 1)
    curvcpus = XMLProperty("./vcpu/@current", is_int=True)
    vcpu_placement = XMLProperty("./vcpu/@placement")

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

    on_poweroff = XMLProperty("./on_poweroff")
    on_reboot = XMLProperty("./on_reboot")
    on_crash = XMLProperty("./on_crash")
    on_lockfailure = XMLProperty("./on_lockfailure")

    seclabels = XMLChildProperty(Seclabel)
    os = XMLChildProperty(OSXML, is_single=True)
    features = XMLChildProperty(DomainFeatures, is_single=True)
    clock = XMLChildProperty(Clock, is_single=True)
    cpu = XMLChildProperty(CPU, is_single=True)
    numatune = XMLChildProperty(DomainNumatune, is_single=True)
    pm = XMLChildProperty(PM, is_single=True)
    blkiotune = XMLChildProperty(DomainBlkiotune, is_single=True)
    memtune = XMLChildProperty(DomainMemorytune, is_single=True)
    memoryBacking = XMLChildProperty(DomainMemorybacking, is_single=True)
    idmap = XMLChildProperty(IdMap, is_single=True)
    resource = XMLChildProperty(DomainResource, is_single=True)
    sysinfo = XMLChildProperty(SYSInfo, is_single=True)

    xmlns_qemu = XMLChildProperty(XMLNSQemu, is_single=True)


    ###############################
    # Distro detection properties #
    ###############################

    def _set_os_object(self, variant):
        obj = OSDB.lookup_os(variant)
        if not obj:
            obj = OSDB.lookup_os("generic")
        self.__os_object = obj
    def _get_os_object(self):
        if not self.__os_object:
            self._set_os_object(None)
        return self.__os_object
    _os_object = property(_get_os_object)

    def _get_os_variant(self):
        return self._os_object.name
    def _set_os_variant(self, val):
        if val:
            val = val.lower()
            if OSDB.lookup_os(val) is None:
                raise ValueError(
                    _("Distro '%s' does not exist in our dictionary") % val)

        logging.debug("Setting Guest.os_variant to '%s'", val)
        self._set_os_object(val)
    os_variant = property(_get_os_variant, _set_os_variant)


    ########################################
    # Device Add/Remove Public API methods #
    ########################################

    def add_device(self, dev):
        """
        Add the passed device to the guest's device list.

        @param dev: VirtualDevice instance to attach to guest
        """
        self.add_child(dev)

    def remove_device(self, dev):
        """
        Remove the passed device from the guest's device list

        @param dev: VirtualDevice instance
        """
        self.remove_child(dev)

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
        ignore = dry

        # Fetch install media, prepare installer devices
        self.installer.prepare(self, meter)

        # Initialize install device list
        if self._install_cdrom_device:
            self._install_cdrom_device.path = self.installer.cdrom_path()
            self._install_cdrom_device.validate()

    def _prepare_get_xml(self):
        # We do a shallow copy of the OS block here, so that we can
        # set the install time properties but not permanently overwrite
        # any config the user explicitly requested.
        data = (self.os, self.on_reboot)
        try:
            self._propstore["os"] = self.os.copy()
        except Exception:
            self._finish_get_xml(data)
            raise
        return data

    def _finish_get_xml(self, data):
        (self._propstore["os"],
         self.on_reboot) = data

    def _get_install_xml(self, *args, **kwargs):
        data = self._prepare_get_xml()
        try:
            return self._do_get_install_xml(*args, **kwargs)
        finally:
            self._finish_get_xml(data)

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

        self._set_osxml_defaults()

        self.bootloader = None
        if (not install and
            self.os.is_xenpv() and
            not self.os.kernel):
            self.bootloader = "/usr/bin/pygrub"
            self.os.clear()

        return self.get_xml_config()


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
            import sys
            exc_info = sys.exc_info()
            try:
                domain.undefine()
            except Exception:
                pass
            raise exc_info[0], exc_info[1], exc_info[2]

        if install_xml and install_xml != final_xml:
            domain = self.conn.defineXML(final_xml)
        return domain

    def _create_guest(self, meter, install_xml, final_xml, doboot, transient):
        """
        Actually do the XML logging, guest defining/creating

        @param doboot: Boot guest even if it has no install phase
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
        @param return_xml: Don't create the guest, just return generated XML
        """
        if self.domain is not None:
            raise RuntimeError(_("Domain has already been started!"))

        self.set_install_defaults()

        self._prepare_install(meter, dry)
        try:
            # Create devices if required (disk images, etc.)
            if not dry:
                for dev in self.get_all_devices():
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
        return [d for d in self.get_devices("disk") if d.storage_was_created]

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

        if (not self.conn.check_support(self.conn.SUPPORT_DOMAIN_FEATURE_SMM) or
            not self.conn.check_support(self.conn.SUPPORT_DOMAIN_LOADER_SECURE)):
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
        controllers = [c for c in self.get_devices("controller") if
            c.type == "usb"]
        if not controllers:
            return False
        return all([c.model == "none" for c in controllers])

    def add_default_input_device(self):
        if self.os.is_container():
            return
        if self.get_devices("input"):
            return
        if not self.get_devices("graphics"):
            return
        if self._usb_disabled():
            return

        usb_tablet = False
        usb_keyboard = False
        if self.os.is_x86():
            usb_tablet = self._os_object.supports_usbtablet()
        if self.os.is_arm_machvirt():
            usb_tablet = True
            usb_keyboard = True

        if usb_tablet:
            dev = VirtualInputDevice(self.conn)
            dev.type = "tablet"
            dev.bus = "usb"
            self.add_device(dev)
        if usb_keyboard:
            dev = VirtualInputDevice(self.conn)
            dev.type = "keyboard"
            dev.bus = "usb"
            self.add_device(dev)

    def add_default_console_device(self):
        if self.skip_default_console:
            return
        if self.get_devices("console") or self.get_devices("serial"):
            return

        dev = VirtualConsoleDevice(self.conn)
        dev.type = dev.TYPE_PTY
        if self.os.is_s390x():
            dev.target_type = "sclp"
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
        if any([d.type == "usb" for d in self.get_devices("controller")]):
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
            for dev in VirtualController.get_usb2_controllers(self.conn):
                self.add_device(dev)

        if usb3:
            self.add_device(
                VirtualController.get_usb3_controller(self.conn, self))

    def add_default_channels(self):
        if self.skip_default_channel:
            return
        if self.get_devices("channel"):
            return
        if self.os.is_s390x():
            # Not wanted for s390 apparently
            return

        if (self.conn.is_qemu() and
            self._os_object.supports_qemu_ga() and
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
        if self.os.is_container() and not self.conn.is_vz():
            return
        if self.os.arch not in ["x86_64", "i686", "ppc64", "ppc64le"]:
            return
        self.add_device(VirtualGraphics(self.conn))

    def add_default_rng(self):
        if self.skip_default_rng:
            return
        if self.get_devices("rng"):
            return
        if not (self.os.is_x86() or
                self.os.is_arm_machvirt() or
                self.os.is_pseries()):
            return

        if (self.conn.is_qemu() and
            self._os_object.supports_virtiorng() and
            self.conn.check_support(self.conn.SUPPORT_CONN_RNG_URANDOM)):
            dev = VirtualRNGDevice(self.conn)
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

        dev = VirtualDisk(self.conn)
        dev.device = dev.DEVICE_CDROM
        setattr(dev, "installer_media", not self.installer.livecd)
        self._install_cdrom_device = dev
        self.add_device(dev)

    def _remove_cdrom_install_media(self):
        for dev in self.get_devices("disk"):
            # Keep the install cdrom device around, but with no media attached.
            # But only if we are installing windows which has a multi stage
            # install.
            if (dev.is_cdrom() and
                getattr(dev, "installer_media", False) and
                not self._os_object.is_windows()):
                dev.path = None

    def _set_defaults(self):
        self._add_install_cdrom()

        # some options check for has_spice() which is resolved after this:
        self._set_graphics_defaults()

        self._set_clock_defaults()
        self._set_emulator_defaults()
        self._set_cpu_defaults()
        self._set_feature_defaults()
        self._set_pm_defaults()

        for dev in self.get_all_devices():
            dev.set_defaults(self)
        self._check_address_multi()
        self._set_disk_defaults()
        self._add_implied_controllers()
        self._set_net_defaults()
        self._set_video_defaults()
        self._set_sound_defaults()
        self._set_panic_defaults()

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
        if self.os.kernel or self.os.init:
            self.os.bootorder = []

    def _set_clock_defaults(self):
        if not self.os.is_hvm():
            return

        if self.clock.offset is None:
            self.clock.offset = self._os_object.get_clock()

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

        hv_clock = self.conn.check_support(self.conn.SUPPORT_CONN_HYPERV_CLOCK)
        hv_clock_rhel = self.conn.check_support(self.conn.SUPPORT_CONN_HYPERV_CLOCK_RHEL)

        if (self._os_object.is_windows() and self._hyperv_supported() and
            (hv_clock or (self.stable_defaults() and hv_clock_rhel))):
            hyperv = self.clock.add_timer()
            hyperv.name = "hypervclock"
            hyperv.present = True

    def _set_emulator_defaults(self):
        if self.os.is_xenpv() or self.type == "vz":
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
        if (self.cpu.get_xml_config().strip() or
            self.cpu.special_mode_was_set):
            # User already configured CPU
            return

        if self.os.is_arm_machvirt() and self.type == "kvm":
            self.cpu.mode = self.cpu.SPECIAL_MODE_HOST_PASSTHROUGH

        elif self.os.is_arm64() and self.os.is_arm_machvirt():
            # -M virt defaults to a 32bit CPU, even if using aarch64
            self.cpu.model = "cortex-a57"

        elif self.os.is_x86() and self.type == "kvm":
            if self.os.arch != self.conn.caps.host.cpu.arch:
                return

            self.cpu.set_special_mode(self.x86_cpu_default)
            if self._os_object.broken_x2apic():
                self.cpu.add_feature("x2apic", policy="disable")


    def _hyperv_supported(self):
        if (self.os.loader_type == "pflash" and
            self.os_variant in ("win2k8r2", "win7")):
            return False
        return True

    def update_defaults(self):
        # This is used only by virt-manager to reset any defaults that may have
        # changed through manual intervention via the customize wizard.

        # UEFI doesn't work with hyperv bits
        if not self._hyperv_supported():
            self.features.hyperv_relaxed = None
            self.features.hyperv_vapic = None
            self.features.hyperv_spinlocks = None
            self.features.hyperv_spinlocks_retries = None
            for i in self.clock.timers:
                if i.name == "hypervclock":
                    self.clock.remove_timer(i)

    def _set_feature_defaults(self):
        if self.os.is_container():
            self.features.acpi = None
            self.features.apic = None
            self.features.pae = None
            if self._is_full_os_container() and self.type != "vz":
                self.features.privnet = True
            return

        if not self.os.is_hvm():
            return

        default = True
        if (self._os_object.need_old_xen_disable_acpi() and
            not self.conn.check_support(support.SUPPORT_CONN_CAN_ACPI)):
            default = False

        if self.features.acpi == "default":
            if default:
                self.features.acpi = self.capsinfo.guest.supports_acpi()
            else:
                self.features.acpi = False
        if self.features.apic == "default":
            self.features.apic = self.capsinfo.guest.supports_apic()
        if self.features.pae == "default":
            if (self.os.is_hvm() and
                self.type == "xen" and
                self.os.arch == "x86_64"):
                self.features.pae = True
            else:
                self.features.pae = self.capsinfo.guest.supports_pae()

        if (self.features.vmport == "default" and
            self.os.is_x86() and
            self.has_spice() and
            self.conn.check_support(self.conn.SUPPORT_CONN_VMPORT)):
            self.features.vmport = False

        if (self._os_object.is_windows() and
            self._hyperv_supported() and
            self.conn.check_support(self.conn.SUPPORT_CONN_HYPERV_VAPIC)):
            if self.features.hyperv_relaxed is None:
                self.features.hyperv_relaxed = True
            if self.features.hyperv_vapic is None:
                self.features.hyperv_vapic = True
            if self.features.hyperv_spinlocks is None:
                self.features.hyperv_spinlocks = True
            if self.features.hyperv_spinlocks_retries is None:
                self.features.hyperv_spinlocks_retries = 8191

    def _set_pm_defaults(self):
        # When the suspend feature is exposed to VMs, an ACPI shutdown
        # event triggers a suspend in the guest, which causes a lot of
        # user confusion (especially compounded with the face that suspend
        # is often buggy so VMs can get hung, etc).
        #
        # We've been disabling this in virt-manager for a while, but lets
        # do it here too for consistency.
        if (self.os.is_x86() and
            self.conn.check_support(self.conn.SUPPORT_CONN_PM_DISABLE)):
            if self.pm.suspend_to_mem is None:
                self.pm.suspend_to_mem = False
            if self.pm.suspend_to_disk is None:
                self.pm.suspend_to_disk = False

    def _add_implied_controllers(self):
        has_spapr_scsi = False
        has_virtio_scsi = False
        has_any_scsi = False
        for dev in self.get_devices("controller"):
            if dev.type == "scsi":
                has_any_scsi = True
                if dev.address.type == "spapr-vio":
                    has_spapr_scsi = True
                if dev.model == "virtio":
                    has_virtio_scsi = True

        # Add spapr-vio controller if needed
        if not has_spapr_scsi:
            for dev in self.get_devices("disk"):
                if dev.address.type == "spapr-vio":
                    ctrl = VirtualController(self.conn)
                    ctrl.type = "scsi"
                    ctrl.address.set_addrstr("spapr-vio")
                    self.add_device(ctrl)
                    break

        # Add virtio-scsi controller if needed
        if (self.os.is_arm_machvirt() and
            not has_any_scsi and
            not has_virtio_scsi):
            for dev in self.get_devices("disk"):
                if dev.bus == "scsi":
                    ctrl = VirtualController(self.conn)
                    ctrl.type = "scsi"
                    ctrl.model = "virtio-scsi"
                    self.add_device(ctrl)
                    break


    def _check_address_multi(self):
        addresses = {}
        for d in self.get_all_devices():
            if d.address.type != d.address.ADDRESS_TYPE_PCI:
                continue
            if None in [d.address.domain, d.address.bus, d.address.slot]:
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

        if (self.os.is_arm_vexpress() and
            self.os.dtb and
            self._os_object.supports_virtiommio() and
            self.conn.check_support(support.SUPPORT_CONN_VIRTIO_MMIO)):
            return True

        return False

    def _set_disk_defaults(self):
        disks = self.get_devices("disk")

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
                  self._supports_virtio(self._os_object.supports_virtiodisk())):
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

    def _set_net_defaults(self):
        net_model = None
        if not self.os.is_hvm():
            net_model = None
        elif self._supports_virtio(self._os_object.supports_virtionet()):
            net_model = "virtio"
        else:
            net_model = self._os_object.default_netmodel()

        if net_model:
            for net in self.get_devices("interface"):
                if not net.model:
                    net.model = net_model

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
        def _set_type(gfx):
            gtype = self.default_graphics_type
            logging.debug("Using default_graphics=%s", gtype)
            if (gtype == "spice" and not
                (self.conn.caps.host.cpu.arch in ["i686", "x86_64"] and
                 self.conn.check_support(
                     self.conn.SUPPORT_CONN_GRAPHICS_SPICE))):
                logging.debug("spice requested but HV doesn't support it. "
                              "Using vnc.")
                gtype = "vnc"

            gfx.type = gtype

        for dev in self.get_devices("graphics"):
            if dev.type == "default":
                _set_type(dev)

            if (dev.type == "spice" and
                not self.conn.is_remote() and
                self.conn.check_support(
                    self.conn.SUPPORT_CONN_SPICE_COMPRESSION)):
                logging.debug("Local connection, disabling spice image "
                    "compression.")
                if dev.image_compression is None:
                    dev.image_compression = "off"

            if (dev.type == "spice" and dev.gl and
                not self.conn.check_support(self.conn.SUPPORT_CONN_SPICE_GL)):
                raise ValueError(_("Host does not support spice GL"))

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
        if not self.os.is_hvm():
            return
        if not (self.os.is_x86() or
                self.os.is_arm_machvirt):
            return

        self.add_device(VirtualAudio(self.conn))

    def _add_spice_usbredir(self):
        if self.skip_default_usbredir:
            return
        if self.get_devices("redirdev"):
            return
        if not self.os.is_x86():
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

    def has_gl(self):
        for gfx in self.get_devices("graphics"):
            if gfx.gl:
                return True

    def _set_video_defaults(self):
        if self.has_spice():
            self._add_spice_channels()
            self._add_spice_sound()
            self._add_spice_usbredir()

        video_model = self._os_object.default_videomodel(self)
        if self.os.is_arm_machvirt():
            video_model = "virtio"

        for video in self.get_devices("video"):
            if video.model == video.MODEL_DEFAULT:
                video.model = video_model
                if video.model == 'virtio' and self.has_gl():
                    video.accel3d = True

    def _set_panic_defaults(self):
        for panic in self.get_devices("panic"):
            if panic.model == VirtualPanicDevice.MODEL_DEFAULT:
                panic.model = VirtualPanicDevice.get_default_model(self.os)
