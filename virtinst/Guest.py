#
# Common code for all guests
#
# Copyright 2006-2009  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

import os
import time
import logging
import signal

import urlgrabber.progress as progress
import libvirt
import libxml2

import _util
import CapabilitiesParser
import VirtualGraphics
import support
import XMLBuilderDomain
import virtinst
from XMLBuilderDomain import _xml_property
import DistroInstaller
from VirtualDevice import VirtualDevice
from VirtualDisk import VirtualDisk
from VirtualInputDevice import VirtualInputDevice
from VirtualCharDevice import VirtualCharDevice
from VirtualController import VirtualControllerUSB
from Clock import Clock
from Seclabel import Seclabel
from CPU import CPU
from DomainNumatune import DomainNumatune
from DomainFeatures import DomainFeatures

import osdict


class Guest(XMLBuilderDomain.XMLBuilderDomain):

    # OS Dictionary static variables and methods
    _DEFAULTS = osdict.DEFAULTS
    _OS_TYPES = osdict.OS_TYPES

    _default_os_type = None

    @staticmethod
    def pretty_os_list():
        """
        Return a strip representation of OS list for printing
        """
        ret = ""
        for t in Guest.list_os_types():
            for v in Guest.list_os_variants(t):
                ret += "%-20s : %s\n" % (v, Guest.get_os_variant_label(t, v))
        return ret

    @staticmethod
    def list_os_types(supported=False, filtervars=None):
        """
        @param filtervars: List of only variants we want to show by default
        """
        vals = osdict.sort_helper(Guest._OS_TYPES)
        for t in vals[:]:
            if not Guest.list_os_variants(t, supported=supported,
                                          filtervars=filtervars):
                vals.remove(t)
        return vals

    @staticmethod
    def list_os_variants(type, sortpref=None, supported=False, filtervars=None):
        """
        Return a list of sorted os variants for the passed distro type

        @param sortpref: An option list of osdict 'distro' tags to
        prioritize in the returned list, e.g. passing ["fedora"] will make
        the sorted list have all fedora distros first
        @param filtervars: List of only variants we want to show by default
        """
        vals = osdict.sort_helper(Guest._OS_TYPES[type]["variants"],
                                  sortpref)
        ret = []
        for v in vals:
            if filtervars:
                if v not in filtervars:
                    continue
            elif supported:
                if not osdict.lookup_osdict_key(None, None,
                                                type, v, "supported"):
                    continue

            ret.append(v)
        return ret

    @staticmethod
    def get_os_type_label(type):
        return Guest._OS_TYPES[type]["label"]

    @staticmethod
    def get_os_variant_label(type, variant):
        return Guest._OS_TYPES[type]["variants"][variant]["label"]

    @staticmethod
    def cpuset_str_to_tuple(conn, cpuset):
        return DomainNumatune.cpuset_str_to_tuple(conn, cpuset)

    @staticmethod
    def generate_cpuset(conn, mem):
        """
        Generates a cpu pinning string based on host NUMA configuration.

        If host doesn't have a suitable NUMA configuration, a RuntimeError
        is thrown.
        """
        caps = CapabilitiesParser.parse(conn.getCapabilities())

        if caps.host.topology is None:
            raise RuntimeError(_("No topology section in capabilities xml."))

        cells = caps.host.topology.cells
        if len(cells) <= 1:
            raise RuntimeError(_("Capabilities only show <= 1 cell. "
                                 "Not NUMA capable"))

        # Capabilities tells us about the available memory 'cells' on the
        # system. Each 'cell' has associated 'cpu's.
        #
        # Use getCellsFreeMemory to determine which 'cell' has the smallest
        # amount of memory which fits the requested VM memory amount, then
        # pin the VM to that 'cell's associated 'cpu's

        cell_mem = conn.getCellsFreeMemory(0, len(cells))
        cell_id = -1
        mem = mem * 1024
        for i in range(len(cells)):
            if cell_mem[i] < mem:
                # Cell doesn't have enough mem to fit, skip it
                continue

            if len(cells[i].cpus) == 0:
                # No cpus to use for the cell
                continue

            # Find smallest cell that fits
            if cell_id < 0 or cell_mem[i] < cell_mem[cell_id]:
                cell_id = i

        if cell_id < 0:
            raise RuntimeError(_("Could not find any usable NUMA "
                                 "cell/cpu combinations."))

        # Build cpuset string
        cpustr = ""
        for cpu in cells[cell_id].cpus:
            if cpustr != "":
                cpustr += ","
            cpustr += str(cpu.id)

        return cpustr

    def __init__(self, type=None, connection=None, hypervisorURI=None,
                 installer=None, parsexml=None, caps=None, conn=None):

        # Set up the connection, since it is fundamental for other init
        conn = conn or connection
        if conn == None:
            logging.debug("No conn passed to Guest, opening URI '%s'" %
                          hypervisorURI)
            conn = self._open_uri(hypervisorURI)

        if conn == None:
            raise RuntimeError(_("Unable to connect to hypervisor, aborting "
                                 "installation!"))

        self._name = None
        self._uuid = None
        self._memory = None
        self._maxmemory = None
        self._hugepage = None
        self._vcpus = 1
        self._maxvcpus = 1
        self._cpuset = None
        self._autostart = False
        self._clock = None
        self._seclabel = None
        self._description = None
        self._features = None
        self._replace = None
        self._emulator = None
        self._installer = installer

        self._os_type = None
        self._os_variant = None
        self._os_autodetect = False

        # DEPRECATED: Public device lists unaltered by install process
        self.disks = []
        self.nics = []
        self.sound_devs = []
        self.hostdevs = []

        # General device list. Only access through API calls (even internally)
        self._devices = []

        # Device list to use/alter during install process. Don't access
        # directly, use internal APIs
        self._install_devices = []

        # The libvirt virDomain object we 'Create'
        self.domain = None
        self._consolechild = None

        self._default_input_device = None
        self._default_console_device = None

        caps = caps or (self._installer and self._installer._get_caps())
        XMLBuilderDomain.XMLBuilderDomain.__init__(self, conn, parsexml,
                                                   caps=caps)
        if self._is_parse():
            return

        if not self.installer:
            i = DistroInstaller.DistroInstaller(type=type,
                                                conn=conn,
                                                os_type=self._default_os_type,
                                                caps=self._get_caps())
            self.installer = i

        # Add default devices (if applicable)
        inp = self._get_default_input_device()
        if inp:
            self.add_device(inp)
        self._default_input_device = inp

        con = self._get_default_console_device()
        con.virtinst_default = True
        self.add_device(con)
        self._default_console_device = con

        # Need to do this after all parameter init
        self._features = DomainFeatures(self.conn)
        self._clock = Clock(self.conn)
        self._seclabel = Seclabel(self.conn)
        self._cpu = CPU(self.conn)
        self._numatune = DomainNumatune(self.conn)

    def _open_uri(self, uri):
        # This is here so test suite can overwrite it, to make sure
        # Guest is never opening anything
        return libvirt.open(uri)

    ######################
    # Property accessors #
    ######################

    def get_installer(self):
        return self._installer
    def set_installer(self, val):
        self._installer = val
    installer = property(get_installer, set_installer)

    def get_clock(self):
        return self._clock
    clock = property(get_clock)
    def get_seclabel(self):
        return self._seclabel
    seclabel = property(get_seclabel)
    def get_cpu(self):
        return self._cpu
    cpu = property(get_cpu)
    def get_numatune(self):
        return self._numatune
    numatune = property(get_numatune)

    def _get_features(self):
        return self._features
    features = property(_get_features)

    # Domain name of the guest
    def get_name(self):
        return self._name
    def set_name(self, val):
        _util.validate_name(_("Guest"), val, lencheck=True)

        do_fail = False
        if self.replace != True:
            try:
                self.conn.lookupByName(val)
                do_fail = True
            except:
                # Name not found
                pass

        if do_fail:
            raise ValueError(_("Guest name '%s' is already in use.") % val)

        self._name = val
    name = _xml_property(get_name, set_name,
                         xpath="./name")

    # Memory allocated to the guest.  Should be given in MB
    def get_memory(self):
        return self._memory
    def set_memory(self, val):
        if (type(val) is not type(1) or val <= 0):
            raise ValueError(_("Memory value must be an integer greater "
                               "than 0"))
        self._memory = val

        if self.maxmemory is None or self.maxmemory < val:
            self.maxmemory = val
    def _xml_memory_value(self):
        return int(self.memory) * 1024
    memory = _xml_property(get_memory, set_memory,
                           xpath="./currentMemory",
                           get_converter=lambda s, x: int(x) / 1024,
                           set_converter=lambda s, x: int(x) * 1024)

    # Memory allocated to the guest.  Should be given in MB
    def get_maxmemory(self):
        return self._maxmemory
    def set_maxmemory(self, val):
        if (type(val) is not type(1) or val <= 0):
            raise ValueError(_("Max Memory value must be an integer greater "
                               "than 0"))
        self._maxmemory = val
    def _xml_maxmemory_value(self):
        return int(self.maxmemory) * 1024
    maxmemory = _xml_property(get_maxmemory, set_maxmemory,
                              xpath="./memory",
                              get_converter=lambda s, x: int(x) / 1024,
                              set_converter=lambda s, x: int(x) * 1024)
    def get_hugepage(self):
        return self._hugepage
    def set_hugepage(self, val):
        if val is None:
            return val
        self._hugepage = bool(val)
    hugepage = _xml_property(get_hugepage, set_hugepage,
                             xpath="./memoryBacking/hugepages", is_bool=True)

    # UUID for the guest
    def get_uuid(self):
        return self._uuid
    def set_uuid(self, val):
        val = _util.validate_uuid(val)
        self._uuid = val
    uuid = _xml_property(get_uuid, set_uuid,
                         xpath="./uuid")

    def __validate_cpus(self, val):
        maxvcpus = _util.get_max_vcpus(self.conn, self.type)
        val = int(val)
        if val < 1:
            raise ValueError(_("Number of vcpus must be a positive integer."))
        if val > maxvcpus:
            raise ValueError(_("Number of vcpus must be no greater than %d "
                               "for this vm type.") % maxvcpus)
        return val

    # number of vcpus for the guest
    def get_vcpus(self):
        return self._vcpus
    def set_vcpus(self, val):
        val = self.__validate_cpus(val)
        self._vcpus = val

        # Don't force set maxvcpus unless already specified
        if self.maxvcpus is not None and self.maxvcpus < val:
            self.maxvcpus = val
    def _vcpus_get_converter(self, val):
        # If no current VCPUs, return maxvcpus
        if not val:
            val = self.maxvcpus
        return int(val)
    vcpus = _xml_property(get_vcpus, set_vcpus,
                          xpath="./vcpu/@current",
                          get_converter=_vcpus_get_converter)

    def _get_maxvcpus(self):
        return self._maxvcpus
    def _set_maxvcpus(self, val):
        val = self.__validate_cpus(val)
        self._maxvcpus = val
    maxvcpus = _xml_property(_get_maxvcpus, _set_maxvcpus,
                             xpath="./vcpu",
                             get_converter=lambda s, x: int(x))

    # set phy-cpus for the guest
    def get_cpuset(self):
        return self._cpuset
    def set_cpuset(self, val):
        if val is None or val == "":
            self._cpuset = None
            return

        DomainNumatune.validate_cpuset(self.conn, val)
        self._cpuset = val
    cpuset = _xml_property(get_cpuset, set_cpuset,
                           xpath="./vcpu/@cpuset")

    def get_graphics_dev(self):
        gdevs = self.get_devices(VirtualDevice.VIRTUAL_DEV_GRAPHICS)
        return (gdevs and gdevs[0] or None)
    def set_graphics_dev(self, val):
        gdev = self.graphics_dev
        if val:
            self.add_device(val)
        if gdev:
            self.remove_device(gdev)
    graphics_dev = property(get_graphics_dev, set_graphics_dev)

    # GAH! - installer.os_type = "hvm" or "xen" (aka xen paravirt)
    #        guest.os_type     = "Solaris", "Windows", "Linux"
    # FIXME: We should really rename this property to something else,
    #        change it throughout the codebase for readability sake, but
    #        maintain back compat.
    def get_os_type(self):
        return self._os_type
    def set_os_type(self, val):
        if type(val) is not str:
            raise ValueError(_("OS type must be a string."))
        val = val.lower()

        if val in self._OS_TYPES:
            if self._os_type != val:
                # Invalidate variant, since it may not apply to the new os type
                self._os_type = val
                self._os_variant = None
        else:
            raise ValueError(_("OS type '%s' does not exist in our "
                                "dictionary") % val)

    os_type = property(get_os_type, set_os_type)

    def get_os_variant(self):
        return self._os_variant
    def set_os_variant(self, val):
        if type(val) is not str:
            raise ValueError(_("OS variant must be a string."))
        val = val.lower()

        if self.os_type:
            if val in self._OS_TYPES[self.os_type]["variants"]:
                self._os_variant = val
            else:
                raise ValueError(_("OS variant '%(var)s' does not exist in "
                                   "our dictionary for OS type '%(ty)s'") %
                                   {'var' : val, 'ty' : self._os_type})
        else:
            found = False
            for ostype in self.list_os_types():
                if (val in self._OS_TYPES[ostype]["variants"] and
                    not self._OS_TYPES[ostype]["variants"][val].get("skip")):
                    logging.debug("Setting os type to '%s' for variant '%s'",
                                  ostype, val)
                    self.os_type = ostype
                    self._os_variant = val
                    found = True

            if not found:
                raise ValueError(_("Unknown OS variant '%s'" % val))

    os_variant = property(get_os_variant, set_os_variant)

    def set_os_autodetect(self, val):
        self._os_autodetect = bool(val)
    def get_os_autodetect(self):
        return self._os_autodetect
    os_autodetect = property(get_os_autodetect, set_os_autodetect)

    # Get the current variants 'distro' tag: 'rhel', 'fedora', etc.
    def get_os_distro(self):
        return self._lookup_osdict_key("distro")
    os_distro = property(get_os_distro)

    def get_autostart(self):
        return self._autostart
    def set_autostart(self, val):
        self._autostart = bool(val)
    autostart = property(get_autostart, set_autostart,
                         doc="Have domain autostart when the host boots.")

    def _get_description(self):
        return self._description
    def _set_description(self, val):
        self._description = val
    description = _xml_property(_get_description, _set_description,
                                xpath="./description")

    def _get_emulator(self):
        return self._emulator
    def _set_emulator(self, val):
        self._emulator = val
    emulator = _xml_property(_get_emulator, _set_emulator,
                             xpath="./devices/emulator")

    def _get_replace(self):
        return self._replace
    def _set_replace(self, val):
        self._replace = bool(val)
    replace = property(_get_replace, _set_replace,
                       doc=_("Whether we should overwrite an existing guest "
                             "with the same name."))

    #########################
    # DEPRECATED PROPERTIES #
    #########################

    # Deprecated: Should set graphics_dev.keymap directly
    def get_keymap(self):
        if self.graphics_dev is None:
            return None
        return self.graphics_dev.keymap
    def set_keymap(self, val):
        if self.graphics_dev is not None:
            self.graphics_dev.keymap = val
    keymap = property(get_keymap, set_keymap)

    # Deprecated: Should set guest.graphics_dev = VirtualGraphics(...)
    def get_graphics(self):
        if self.graphics_dev is None:
            return { "enabled" : False }
        return { "enabled" : True, "type" : self.graphics_dev, \
                 "keymap"  : self.graphics_dev.keymap}
    def set_graphics(self, val):

        # val can be:
        #   a dictionary with keys:  enabled, type, port, keymap
        #   a tuple of the form   : (enabled, type, port, keymap)
        #                            last 2 optional
        #                         : "vnc", "sdl", or false
        port = None
        gtype = None
        enabled = False
        keymap = None
        gdev = None
        if type(val) == dict:
            if "enabled" not in val:
                raise ValueError(_("Must specify whether graphics are enabled"))

            enabled = val["enabled"]
            if "type" in val:
                gtype = val["type"]
                if "opts" in val:
                    port = val["opts"]

        elif type(val) == tuple:
            if len(val) >= 1:
                enabled = val[0]
            if len(val) >= 2:
                gtype = val[1]
            if len(val) >= 3:
                port = val[2]
            if len(val) >= 4:
                keymap = val[3]

        else:
            if val in ("vnc", "sdl"):
                gtype = val
                enabled = True
            else:
                enabled = val

        if enabled not in (True, False):
            raise ValueError(_("Graphics enabled must be True or False"))

        if enabled:
            gdev = VirtualGraphics.VirtualGraphics(type=gtype)
            if port:
                gdev.port = port
            if keymap:
                gdev.keymap = keymap
        self.graphics_dev = gdev

    graphics = property(get_graphics, set_graphics)

    # Hypervisor name (qemu, xen, kvm, etc.)
    # Deprecated: should be pulled directly from the installer
    def get_type(self):
        return self._installer.type
    def set_type(self, val):
        self._installer.type = val
    type = property(get_type, set_type)

    # Deprecated: should be pulled directly from the installer
    def get_arch(self):
        return self.installer.arch
    def set_arch(self, val):
        self.installer.arch = val
    arch = property(get_arch, set_arch)

    # Deprecated: Should be called from the installer directly
    def get_location(self):
        return self._installer.location
    def set_location(self, val):
        self._installer.location = val
    location = property(get_location, set_location)

    # Deprecated: Should be called from the installer directly
    def get_scratchdir(self):
        return self._installer.scratchdir
    scratchdir = property(get_scratchdir)

    # Deprecated: Should be called from the installer directly
    def get_boot(self):
        return self._installer.boot
    def set_boot(self, val):
        self._installer.boot = val
    boot = property(get_boot, set_boot)

    # Deprecated: Should be called from the installer directly
    def get_extraargs(self):
        return self._installer.extraargs
    def set_extraargs(self, val):
        self._installer.extraargs = val
    extraargs = property(get_extraargs, set_extraargs)

    # Deprecated: Should set the installer values directly
    def get_cdrom(self):
        return self._installer.location
    def set_cdrom(self, val):
        self._installer.location = val
        self._installer.cdrom = True
    cdrom = property(get_cdrom, set_cdrom)


    ########################################
    # Device Add/Remove Public API methods #
    ########################################

    def _dev_build_list(self, devtype, devlist=None):
        if not devlist:
            devlist = self._devices

        newlist = []
        for i in devlist:
            if i.virtual_device_type == devtype:
                newlist.append(i)
        return newlist

    def add_device(self, dev):
        """
        Add the passed device to the guest's device list.

        @param dev: VirtualDevice instance to attach to guest
        """
        if not isinstance(dev, VirtualDevice):
            raise ValueError(_("Must pass a VirtualDevice instance."))

        if self._is_parse():
            xml = dev.get_xml_config()
            node = libxml2.parseDoc(xml).children
            dev.set_xml_node(node)
            self._add_child_node("./devices", node)

        return self._add_device(dev)

    def _add_device(self, dev):
        devtype = dev.virtual_device_type

        # If user adds a device conflicting with a default assigned device
        # remove the default
        if (dev.virtual_device_type == VirtualDevice.VIRTUAL_DEV_INPUT and
            self._default_input_device):
            if self._default_input_device in self.get_all_devices():
                self.remove_device(self._default_input_device)
            self._default_input_device = None

        if (dev.virtual_device_type in [VirtualDevice.VIRTUAL_DEV_CONSOLE,
                                        VirtualDevice.VIRTUAL_DEV_SERIAL] and
            self._default_console_device):
            if self._default_console_device in self.get_all_devices():
                self.remove_device(self._default_console_device)
            self._default_console_device = None

        # Actually add the device
        if   devtype == VirtualDevice.VIRTUAL_DEV_DISK:
            self.disks.append(dev)
        elif devtype == VirtualDevice.VIRTUAL_DEV_NET:
            self.nics.append(dev)
        elif devtype == VirtualDevice.VIRTUAL_DEV_AUDIO:
            self.sound_devs.append(dev)
        elif devtype == VirtualDevice.VIRTUAL_DEV_HOSTDEV:
            self.hostdevs.append(dev)
        else:
            self._devices.append(dev)


    def get_devices(self, devtype):
        """
        Return a list of devices of type 'devtype' that will installed on
        the guest.

        @param devtype: Device type to search for (one of
                        VirtualDevice.virtual_device_types)
        """
        if   devtype == VirtualDevice.VIRTUAL_DEV_DISK:
            devlist = self.disks[:]
        elif devtype == VirtualDevice.VIRTUAL_DEV_NET:
            devlist = self.nics[:]
        elif devtype == VirtualDevice.VIRTUAL_DEV_AUDIO:
            devlist = self.sound_devs[:]
        elif devtype == VirtualDevice.VIRTUAL_DEV_HOSTDEV:
            devlist = self.hostdevs[:]
        else:
            devlist = self._dev_build_list(devtype)

        devlist.extend(self._install_devices)
        return self._dev_build_list(devtype, devlist)

    def get_all_devices(self):
        """
        Return a list of all devices being installed with the guest
        """
        retlist = []
        for devtype in VirtualDevice.virtual_device_types:
            retlist.extend(self.get_devices(devtype))
        return retlist

    def remove_device(self, dev):
        """
        Remove the passed device from the guest's device list

        @param dev: VirtualDevice instance
        """
        found = False
        for devlist in [self.disks, self.nics, self.sound_devs, self.hostdevs,
                        self._devices, self._install_devices]:
            if found:
                break

            if dev in devlist:
                devlist.remove(dev)
                found = True
                break

        if not found:
            raise ValueError(_("Did not find device %s") % str(dev))

        if self._is_parse():
            xpath = dev.get_xml_node_path()
            if xpath:
                self._remove_child_xpath(xpath)


    ################################
    # Private xml building methods #
    ################################

    def _parsexml(self, xml, node):
        XMLBuilderDomain.XMLBuilderDomain._parsexml(self, xml, node)

        device_mappings = {
            "disk"      : virtinst.VirtualDisk,
            "interface" : virtinst.VirtualNetworkInterface,
            "sound"     : virtinst.VirtualAudio,
            "hostdev"   : virtinst.VirtualHostDevice,
            "input"     : virtinst.VirtualInputDevice,
            "serial"    : virtinst.VirtualCharDevice,
            "parallel"  : virtinst.VirtualCharDevice,
            "console"   : virtinst.VirtualCharDevice,
            "channel"   : virtinst.VirtualCharDevice,
            "graphics"  : virtinst.VirtualGraphics,
            "video"     : virtinst.VirtualVideoDevice,
            "watchdog"  : virtinst.VirtualWatchdog,
            "controller": virtinst.VirtualController,
            "filesystem": virtinst.VirtualFilesystem,
            "smartcard" : virtinst.VirtualSmartCardDevice,
            "redirdev"  : virtinst.VirtualRedirDevice,
            "memballoon": virtinst.VirtualMemballoon,
        }

        # Hand off all child element parsing to relevant classes
        caps = self._get_caps()
        for node in self._xml_node.children:
            if node.name != "devices":
                continue

            children = filter(lambda x: (x.name in device_mappings and
                                         x.parent == node),
                              node.children)
            for devnode in children:
                objclass = device_mappings.get(devnode.name)

                if objclass == virtinst.VirtualCharDevice:
                    dev = objclass(self.conn, devnode.name,
                                   parsexmlnode=devnode, caps=caps)
                else:
                    dev = objclass(conn=self.conn,
                                   parsexmlnode=devnode, caps=caps)
                self._add_device(dev)

        self._installer = virtinst.Installer.Installer(self.conn,
                                                   parsexmlnode=self._xml_node,
                                                   caps=caps)
        self._features = DomainFeatures(self.conn,
                                        parsexmlnode=self._xml_node,
                                        caps=caps)
        self._clock = Clock(self.conn, parsexmlnode=self._xml_node, caps=caps)
        self._seclabel = Seclabel(self.conn, parsexmlnode=self._xml_node,
                                  caps=caps)
        self._cpu = CPU(self.conn, parsexmlnode=self._xml_node, caps=caps)
        self._numatune = DomainNumatune(self.conn,
                                        parsexmlnode=self._xml_node, caps=caps)

    def _get_default_input_device(self):
        """
        Return a VirtualInputDevice.
        """
        if self.installer and self.installer.is_container():
            return None
        dev = VirtualInputDevice(self.conn)
        return dev

    def _get_default_console_device(self):
        """
        Only implemented for FullVirtGuest
        """
        dev = VirtualCharDevice.get_dev_instance(self.conn,
                                                 VirtualCharDevice.DEV_CONSOLE,
                                                 VirtualCharDevice.CHAR_PTY)
        return dev

    def _get_device_xml(self, devs, install=True):

        def do_remove_media(d):
            # Keep cdrom around, but with no media attached,
            # But only if we are a distro that doesn't have a multi
            # stage install (aka not Windows)
            return (d.virtual_device_type == VirtualDevice.VIRTUAL_DEV_DISK and
                    d.device == VirtualDisk.DEVICE_CDROM
                    and d.transient
                    and not install and
                    not self.get_continue_inst())

        def do_skip_disk(d):
            # Skip transient labeled non-media disks
            return (d.virtual_device_type == VirtualDevice.VIRTUAL_DEV_DISK and
                    d.device == VirtualDisk.DEVICE_DISK
                    and d.transient
                    and not install)

        # Wrapper for building disk XML, handling transient CDROMs
        def get_dev_xml(dev):
            origpath = None
            try:
                if do_skip_disk(dev):
                    return ""

                if do_remove_media(dev):
                    origpath = dev.path
                    dev.path = None

                return dev.get_xml_config()
            finally:
                if origpath:
                    dev.path = origpath
        def get_vscsi_ctrl_xml():
            vscsi_class = virtinst.VirtualController.get_class_for_type(
                          virtinst.VirtualController.CONTROLLER_TYPE_SCSI)
            ctrl = vscsi_class(self.conn)
            ctrl.set_address("spapr-vio")
            return ctrl.get_xml_config()

        xml = self._get_emulator_xml()
        # Build XML
        for dev in devs:
            xml = _util.xml_append(xml, get_dev_xml(dev))
            if (dev.address.type == "spapr-vio" and
                  dev.virtual_device_type == virtinst.VirtualDevice.VIRTUAL_DEV_DISK):
                xml = _util.xml_append(xml, get_vscsi_ctrl_xml())

        return xml

    def _get_emulator_xml(self):
        emulator = self.emulator
        if self.installer.is_xenpv():
            return ""

        if (not self.emulator and
            self.installer.is_hvm() and
            self.type == "xen"):
            if self._get_caps().host.arch in ("x86_64"):
                emulator = "/usr/lib64/xen/bin/qemu-dm"
            else:
                emulator = "/usr/lib/xen/bin/qemu-dm"

        emu_xml = ""
        if emulator is not None:
            emu_xml = "    <emulator>%s</emulator>" % emulator

        return emu_xml

    def _get_features_xml(self, features):
        """
        Return features (pae, acpi, apic) xml
        """
        if self.installer and self.installer.is_container():
            return ""
        return features.get_xml_config()

    def _get_cpu_xml(self):
        """
        Return <cpu> XML
        """
        self.cpu.set_topology_defaults(self.vcpus)
        return self.cpu.get_xml_config()

    def _get_clock_xml(self):
        """
        Return <clock/> xml
        """
        return self.clock.get_xml_config()

    def _get_seclabel_xml(self):
        """
        Return <seclabel> XML
        """
        xml = ""
        if self.seclabel:
            xml = self.seclabel.get_xml_config()

        return xml

    def _get_osblob(self, install):
        """
        Return os, features, and clock xml (Implemented in subclass)
        """
        xml = ""

        osxml = self.installer.get_xml_config(self, install)
        if not osxml:
            return None

        xml = _util.xml_append(xml,
                               self.installer.get_xml_config(self, install))
        return xml

    def _get_vcpu_xml(self):
        curvcpus_supported = virtinst.support.check_conn_support(
                                    self.conn,
                                    virtinst.support.SUPPORT_CONN_MAXVCPUS_XML)
        cpuset = ""
        if self.cpuset is not None:
            cpuset = " cpuset='%s'" % self.cpuset

        maxv = self.maxvcpus
        curv = self.vcpus

        curxml = ""
        if maxv != curv and curvcpus_supported:
            curxml = " current='%s'" % curv
        else:
            maxv = curv

        return "  <vcpu%s%s>%s</vcpu>" % (cpuset, curxml, maxv)

    ############################
    # Install Helper functions #
    ############################

    def _prepare_install(self, meter, dry=False):
        self._install_devices = []
        ignore = dry

        # Fetch install media, prepare installer devices
        self._installer.prepare(guest=self,
                                meter=meter)

        # Initialize install device list
        for dev in self._installer.install_devices:
            self._install_devices.append(dev)

    def _cleanup_install(self):
        self._installer.cleanup()

    def _create_devices(self, progresscb):
        """
        Ensure that devices are setup
        """
        for dev in self.get_all_devices():
            dev.setup_dev(self.conn, progresscb)

    ##############
    # Public API #
    ##############

    def _get_xml_config(self, install=True, disk_boot=False):
        """
        Return the full Guest xml configuration.

        @param install: Whether we want the 'OS install' configuration or
                        the 'post-install' configuration. (Some Installers,
                        like the LiveCDInstaller may not have an 'install'
                        config.)
        @type install: C{bool}
        @param disk_boot: Whether we should boot off the harddisk, regardless
                          of our position in the install process (this is
                          used for 2 stage installs, where the second stage
                          boots off the disk. You probably don't need to touch
                          this.)
        @type disk_boot: C{bool}
        """
        # We do a shallow copy of the device list here, and set the defaults.
        # This way, default changes aren't persistent, and we don't need
        # to worry about when to call set_defaults
        origdevs = self.get_all_devices()
        devs = []
        for dev in origdevs:
            devs.append(dev.copy())
        tmpfeat = self.features.copy()

        def get_transient_devices(devtype):
            return self._dev_build_list(devtype, devs)
        def remove_transient_device(device):
            devs.remove(device)

        # Set device defaults so we can validly generate XML
        self._set_defaults(get_transient_devices,
                           remove_transient_device,
                           tmpfeat)

        if install:
            action = "destroy"
        else:
            action = "restart"

        osblob_install = install
        if disk_boot:
            osblob_install = False

        osblob = self._get_osblob(osblob_install)
        if osblob_install and not self.installer.has_install_phase():
            return None

        desc_xml = ""
        if self.description is not None:
            desc = str(self.description)
            desc_xml = ("  <description>%s</description>" %
                        _util.xml_escape(desc))

        xml = ""
        add = lambda x: _util.xml_append(xml, x)

        xml = add("<domain type='%s'>" % self.type)
        xml = add("  <name>%s</name>" % self.name)
        xml = add("  <uuid>%s</uuid>" % self.uuid)
        xml = add(desc_xml)
        xml = add("  <memory>%s</memory>" % (self.maxmemory * 1024))
        xml = add("  <currentMemory>%s</currentMemory>" % (self.memory * 1024))

        # <blkiotune>
        # <memtune>
        if self.hugepage is True:
            xml = add("  <memoryBacking>")
            xml = add("    <hugepages/>")
            xml = add("  </memoryBacking>")

        xml = add(self._get_vcpu_xml())
        # <cputune>
        xml = add(self.numatune.get_xml_config())
        # <sysinfo>
        # XXX: <bootloader> goes here, not in installer XML
        xml = add("  %s" % osblob)
        xml = add(self._get_features_xml(tmpfeat))
        xml = add(self._get_cpu_xml())
        xml = add(self._get_clock_xml())
        xml = add("  <on_poweroff>destroy</on_poweroff>")
        xml = add("  <on_reboot>%s</on_reboot>" % action)
        xml = add("  <on_crash>%s</on_crash>" % action)
        xml = add("  <devices>")
        xml = add(self._get_device_xml(devs, install))
        xml = add("  </devices>")
        xml = add(self._get_seclabel_xml())
        xml = add("</domain>\n")

        return xml

    def post_install_check(self):
        """
        Back compat mapping to installer post_install_check
        """
        return self.installer.post_install_check(self)

    def get_continue_inst(self):
        """
        Return True if this guest requires a call to 'continue_install',
        which means the OS requires a 2 stage install (windows)
        """
        # If we are doing an 'import' or 'liveCD' install, there is
        # no true install process, so continue install has no meaning
        if not self.installer.has_install_phase():
            return False

        return self._lookup_osdict_key("continue")

    def validate_parms(self):
        """
        Do some pre-install domain validation
        """
        if self.domain is not None:
            raise RuntimeError(_("Domain has already been started!"))

        if self.name is None or self.memory is None:
            raise RuntimeError(_("Name and memory must be specified for "
                                 "all guests!"))

        if _util.vm_uuid_collision(self.conn, self.uuid):
            raise RuntimeError(_("The UUID you entered is already in "
                                 "use by another guest!"))

    def connect_console(self, consolecb, wait=True):
        """
        Launched the passed console callback for the already defined
        domain. If domain isn't running, return an error.
        """
        (self.domain,
         self._consolechild) = self._wait_and_connect_console(consolecb)

        # If we connected the console, wait for it to finish
        self._waitpid_console(self._consolechild, wait)

    def terminate_console(self):
        """
        Kill guest console if it is open (and actually exists), otherwise
        do nothing
        """
        if self._consolechild:
            try:
                os.kill(self._consolechild, signal.SIGKILL)
            except:
                pass

    def domain_is_shutdown(self):
        """
        Return True if the created domain object is shutdown
        """
        dom = self.domain
        if not dom:
            return False

        dominfo = dom.info()

        state    = dominfo[0]
        cpu_time = dominfo[4]

        if state == libvirt.VIR_DOMAIN_SHUTOFF:
            return True

        # If 'wait' was specified, the dom object we have was looked up
        # before initially shutting down, which seems to bogus up the
        # info data (all 0's). So, if it is bogus, assume the domain is
        # shutdown. We will catch the error later.
        return state == libvirt.VIR_DOMAIN_NOSTATE and cpu_time == 0

    def domain_is_crashed(self):
        """
        Return True if the created domain object is in a crashed state
        """
        if not self.domain:
            return False

        dominfo = self.domain.info()
        state = dominfo[0]

        return state == libvirt.VIR_DOMAIN_CRASHED

    ##########################
    # Actual install methods #
    ##########################

    def remove_original_vm(self, force=None):
        """
        Remove the existing VM with the same name if requested, or error
        if there is a collision.
        """
        if force == None:
            force = self.replace

        vm = None
        try:
            vm = self.conn.lookupByName(self.name)
        except libvirt.libvirtError:
            pass

        if vm is None:
            return

        if not force:
            raise RuntimeError(_("Domain named %s already exists!") %
                               self.name)

        try:
            logging.debug("Explicitly replacing guest '%s'", self.name)
            if vm.ID() != -1:
                logging.info("Destroying guest '%s'", self.name)
                vm.destroy()

            logging.info("Undefining guest '%s'", self.name)
            vm.undefine()
        except libvirt.libvirtError, e:
            raise RuntimeError(_("Could not remove old vm '%s': %s") %
                               (self.name, str(e)))

    def start_install(self, consolecb=None, meter=None, removeOld=None,
                      wait=True, dry=False, return_xml=False, noboot=False):
        """
        Begin the guest install (stage1).
        @param return_xml: Don't create the guest, just return generated XML
        """
        is_initial = True

        self.validate_parms()
        self._consolechild = None

        self._prepare_install(meter, dry)
        try:
            # Create devices if required (disk images, etc.)
            if not dry:
                self._create_devices(meter)

            start_xml, final_xml = self._build_xml(is_initial)
            if return_xml:
                return (start_xml, final_xml)
            if dry:
                return

            # Remove existing VM if requested
            self.remove_original_vm(removeOld)

            self.domain = self._create_guest(consolecb, meter, wait,
                                             start_xml, final_xml, is_initial,
                                             noboot)

            # Set domain autostart flag if requested
            self._flag_autostart()

            return self.domain
        finally:
            self._cleanup_install()

    def continue_install(self, consolecb=None, meter=None, wait=True,
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

        return self._create_guest(consolecb, meter, wait,
                                  start_xml, final_xml, is_initial, False)

    def _build_meter(self, meter, is_initial):
        if is_initial:
            meter_label = _("Creating domain...")
        else:
            meter_label = _("Starting domain...")

        if meter == None:
            meter = progress.BaseMeter()
        meter.start(size=None, text=meter_label)

        return meter

    def _build_xml(self, is_initial):
        log_label = is_initial and "install" or "continue"
        disk_boot = not is_initial

        start_xml = self.get_xml_config(install=True, disk_boot=disk_boot)
        final_xml = self.get_xml_config(install=False)

        logging.debug("Generated %s XML: %s",
                      log_label,
                      (start_xml and ("\n" + start_xml) or "None required"))
        logging.debug("Generated boot XML: \n%s", final_xml)

        return start_xml, final_xml

    def _create_guest(self, consolecb, meter, wait,
                      start_xml, final_xml, is_initial, noboot):
        """
        Actually do the XML logging, guest defining/creating, console
        launching and waiting

        @param is_initial: If running initial guest creation, else we
                           are continuing the install
        @param noboot: Don't boot guest if no install phase
        """
        meter = self._build_meter(meter, is_initial)
        doboot = not noboot or self.installer.has_install_phase()
        if not doboot:
            consolecb = None

        if is_initial and doboot:
            dom = self.conn.createLinux(start_xml or final_xml, 0)
        else:
            dom = self.conn.defineXML(start_xml or final_xml)
            if doboot:
                dom.create()

        self.domain = dom
        meter.end(0)

        if doboot:
            logging.debug("Started guest, connecting to console if requested")
            (self.domain,
             self._consolechild) = self._wait_and_connect_console(consolecb)

        self.domain = self.conn.defineXML(final_xml)
        if is_initial:
            try:
                logging.debug("XML fetched from libvirt object:\n%s",
                              dom.XMLDesc(0))
            except Exception, e:
                logging.debug("Error fetching XML from libvirt object: %s", e)

        # if we connected the console, wait for it to finish
        self._waitpid_console(self._consolechild, wait)

        return self.conn.lookupByName(self.name)


    def _wait_and_connect_console(self, consolecb):
        """
        Wait for domain to appear and be running, then connect to
        the console if necessary
        """
        child = None
        dom = _wait_for_domain(self.conn, self.name)

        if dom is None:
            raise RuntimeError(_("Domain has not existed.  You should be "
                                 "able to find more information in the logs"))
        elif dom.ID() == -1:
            raise RuntimeError(_("Domain has not run yet.  You should be "
                                 "able to find more information in the logs"))

        if consolecb:
            child = consolecb(dom)

        return dom, child

    def _waitpid_console(self, console_child, do_wait):
        """
        Wait for console to close if it was launched
        """
        if not console_child or not do_wait:
            return

        try:
            os.waitpid(console_child, 0)
        except OSError, (err_no, msg):
            logging.debug("waitpid: %s: %s", err_no, msg)

        # ensure there's time for the domain to finish destroying if the
        # install has finished or the guest crashed
        time.sleep(1)

    def _flag_autostart(self):
        """
        Set the autostart flag for self.domain if the user requested it
        """
        if not self.autostart:
            return

        try:
            self.domain.setAutostart(True)
        except libvirt.libvirtError, e:
            if support.is_error_nosupport(e):
                logging.warn("Could not set autostart flag: libvirt "
                             "connection does not support autostart.")
            else:
                raise e


    ###################
    # Device defaults #
    ###################

    def set_defaults(self):
        """
        Public function to set guest defaults. Things like preferred
        disk bus (unless one is specified). These changes are persistent.
        The install process will call a non-persistent version, so calling
        this manually isn't required.
        """
        self._set_defaults(self.get_devices, self.remove_device,
                           self.features)

    def _set_hvm_defaults(self, devlist_func, features):
        disktype = VirtualDevice.VIRTUAL_DEV_DISK
        nettype = VirtualDevice.VIRTUAL_DEV_NET
        disk_bus  = self._lookup_device_param(disktype, "bus")
        net_model = self._lookup_device_param(nettype, "model")

        # Only overwrite params if they weren't already specified
        for net in devlist_func(nettype):
            if net_model and not net.model:
                net.model = net_model

        for disk in devlist_func(disktype):
            if (disk_bus and not disk.bus and
                disk.device == VirtualDisk.DEVICE_DISK):
                disk.bus = disk_bus

        if self.clock.offset == None:
            self.clock.offset = self._lookup_osdict_key("clock")

        if features["acpi"] is None:
            features["acpi"] = self._lookup_osdict_key("acpi")
        if features["apic"] is None:
            features["apic"] = self._lookup_osdict_key("apic")
        if features["pae"] is None and self._get_caps():
            features["pae"] = self._get_caps().support_pae()

        if (self.installer.machine == None and
            self._get_caps().host.arch == "ppc64"):
            self.installer.machine = "pseries"

    def _set_pv_defaults(self, devlist_func, remove_func):
        # Default file backed PV guests to tap driver
        for d in devlist_func(VirtualDevice.VIRTUAL_DEV_DISK):
            if (d.type == VirtualDisk.TYPE_FILE
                and _util.is_blktap_capable()
                and d.driver_name == None):
                d.driver_name = VirtualDisk.DRIVER_TAP

        for d in devlist_func(VirtualDevice.VIRTUAL_DEV_INPUT):
            if d.type == d.INPUT_TYPE_DEFAULT:
                d.type = d.INPUT_TYPE_MOUSE
            if d.bus == d.INPUT_BUS_DEFAULT:
                d.bus = d.INPUT_BUS_XEN

        for d in devlist_func(VirtualDevice.VIRTUAL_DEV_CONSOLE):
            if hasattr(d, "virtinst_default"):
                remove_func(d)

    def add_usb_ich9_controllers(self):
        ctrl = VirtualControllerUSB(self.conn,
                                    model="ich9-ehci1")
        self.add_device(ctrl)

        ctrl = VirtualControllerUSB(self.conn,
                                    model="ich9-uhci1")
        ctrl.get_master().startport = 0
        self.add_device(ctrl)

        ctrl = VirtualControllerUSB(self.conn,
                                    model="ich9-uhci2")
        ctrl.get_master().startport = 2
        self.add_device(ctrl)

        ctrl = VirtualControllerUSB(self.conn,
                                    model="ich9-uhci3")
        ctrl.get_master().startport = 4
        self.add_device(ctrl)

    def _set_defaults(self, devlist_func, remove_func, features):
        if self.installer.is_hvm():
            self._set_hvm_defaults(devlist_func, features)
        if self.installer.is_xenpv():
            self._set_pv_defaults(devlist_func, remove_func)

        soundtype = VirtualDevice.VIRTUAL_DEV_AUDIO
        videotype = VirtualDevice.VIRTUAL_DEV_VIDEO
        inputtype = VirtualDevice.VIRTUAL_DEV_INPUT
        gfxtype = VirtualDevice.VIRTUAL_DEV_GRAPHICS
        channeltype = VirtualDevice.VIRTUAL_DEV_CHANNEL

        # Set default input values
        input_type = self._lookup_device_param(inputtype, "type")
        input_bus = self._lookup_device_param(inputtype, "bus")
        for inp in devlist_func(inputtype):
            if (inp.type == inp.INPUT_TYPE_DEFAULT and
                inp.bus  == inp.INPUT_BUS_DEFAULT):
                inp.type = input_type
                inp.bus  = input_bus

        # Generate disk targets, and set preferred disk bus
        used_targets = []
        for disk in devlist_func(VirtualDevice.VIRTUAL_DEV_DISK):
            if not disk.bus:
                if disk.device == disk.DEVICE_FLOPPY:
                    disk.bus = "fdc"
                else:
                    if self.installer.is_hvm():
                        if (self.installer.type == "kvm" and
                            self.installer.machine == "pseries"):
                            disk.bus = "scsi"
                        else:
                            disk.bus = "ide"
                    elif self.installer.is_xenpv():
                        disk.bus = "xen"
            if disk.target:
                used_targets.append(disk.target)
            else:
                used_targets.append(disk.generate_target(used_targets))

        # Set sound device model
        sound_model  = self._lookup_device_param(soundtype, "model")
        for sound in devlist_func(soundtype):
            if sound.model == sound.MODEL_DEFAULT:
                sound.model = sound_model

        # Set video device model
        # QXL device (only if we use spice) - safe even if guest is VGA only
        def has_spice():
            for gfx in devlist_func(gfxtype):
                if gfx.type == gfx.TYPE_SPICE:
                    return True
        if has_spice():
            video_model  = "qxl"
        else:
            video_model  = self._lookup_device_param(videotype, "model_type")

        for video in devlist_func(videotype):
            if video.model_type == video.MODEL_DEFAULT:
                video.model_type = video_model

        # Spice agent channel (only if we use spice)
        def has_spice_agent():
            for chn in devlist_func(channeltype):
                if chn.char_type == chn.CHAR_SPICEVMC:
                    return True

        if (has_spice() and
            not has_spice_agent() and
            support.check_conn_support(self.conn,
                                       support.SUPPORT_CONN_HV_CHAR_SPICEVMC)):
            agentdev = VirtualCharDevice.get_dev_instance(self.conn,
                                            VirtualCharDevice.DEV_CHANNEL,
                                            VirtualCharDevice.CHAR_SPICEVMC)
            self.add_device(agentdev)

        # Generate UUID
        if self.uuid is None:
            self.uuid = _util.generate_uuid(self.conn)


    ###################################
    # Guest Dictionary Helper methods #
    ###################################

    def _is_rhel6(self):
        emulator = self.emulator or ""

        return (self.type in ["qemu", "kvm"] and
                emulator.startswith("/usr/libexec/qemu"))

    def _lookup_osdict_key(self, key):
        """
        Using self.os_type and self.os_variant to find key in OSTYPES
        @returns: dict value, or None if os_type/variant wasn't set
        """
        return osdict.lookup_osdict_key(self.conn, self.type,
                                        self.os_type, self.os_variant,
                                        key)

    def _lookup_device_param(self, device_key, param):
        """
        Check the OS dictionary for the prefered device setting for passed
        device type and param (bus, model, etc.)
        """
        try:
            support._set_rhel6(self._is_rhel6())
            return osdict.lookup_device_param(self.conn, self.type,
                                              self.os_type, self.os_variant,
                                              device_key, param)
        finally:
            support._set_rhel6(False)


def _wait_for_domain(conn, name):
    # sleep in .25 second increments until either a) we get running
    # domain ID or b) it's been 5 seconds.  this is so that
    # we can try to gracefully handle domain restarting failures
    dom = None
    for ignore in range(1, int(5 / .25)): # 5 seconds, .25 second sleeps
        try:
            dom = conn.lookupByName(name)
            if dom and dom.ID() != -1:
                break
        except libvirt.libvirtError, e:
            logging.debug("No guest running yet: " + str(e))
            dom = None
        time.sleep(0.25)

    return dom

# Back compat class to avoid ABI break
XenGuest = Guest
Guest.get_config_xml = Guest.get_xml_config
