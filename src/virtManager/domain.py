#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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
#

import gobject
import libvirt
import logging
import difflib

import virtinst
from virtManager import util
import virtinst.util as vutil
import virtinst.support as support
from virtinst import VirtualDevice

from virtManager.libvirtobject import vmmLibvirtObject

def safeint(val, fmt="%.3d"):
    try:
        int(val)
    except:
        return str(val)
    return fmt % int(val)

def disk_type_to_xen_driver_name(disk_type):
    if disk_type == "block":
        return "phy"
    elif disk_type == "file":
        return "file"

    return "file"

def disk_type_to_target_prop(disk_type):
    if disk_type == "file":
        return "file"
    elif disk_type == "block":
        return "dev"
    elif disk_type == "dir":
        return "dir"
    return "file"

class vmmDomainBase(vmmLibvirtObject):
    """
    Base class for vmmDomain objects. Provides common set up and methods
    for domain backends (libvirt virDomain, virtinst Guest)
    """
    __gsignals__ = {
        "status-changed": (gobject.SIGNAL_RUN_FIRST,
                           gobject.TYPE_NONE,
                           [int, int]),
        "resources-sampled": (gobject.SIGNAL_RUN_FIRST,
                              gobject.TYPE_NONE,
                              []),
        }

    def __init__(self, config, connection, backend, uuid):
        vmmLibvirtObject.__init__(self, config, connection)

        self._backend = backend
        self.uuid = uuid

        self._startup_vcpus = None

        self._network_traffic = None
        self._disk_io = None

        self._stats_net_supported = True
        self._stats_net_skip = []

        self._stats_disk_supported = True
        self._stats_disk_skip = []

    # Info accessors
    def get_name(self):
        raise NotImplementedError()
    def get_id(self):
        raise NotImplementedError()
    def status(self):
        raise NotImplementedError()

    def get_memory(self):
        raise NotImplementedError()
    def get_memory_percentage(self):
        raise NotImplementedError()
    def maximum_memory(self):
        raise NotImplementedError()
    def maximum_memory_percentage(self):
        raise NotImplementedError()
    def cpu_time(self):
        raise NotImplementedError()
    def cpu_time_percentage(self):
        raise NotImplementedError()
    def vcpu_count(self):
        raise NotImplementedError()
    def network_rx_rate(self):
        raise NotImplementedError()
    def network_tx_rate(self):
        raise NotImplementedError()
    def disk_read_rate(self):
        raise NotImplementedError()
    def disk_write_rate(self):
        raise NotImplementedError()

    def get_autostart(self):
        raise NotImplementedError()

    # Device/XML altering API
    def set_autostart(self, val):
        raise NotImplementedError()

    def attach_device(self, devobj, devxml=None):
        raise NotImplementedError()
    def detach_device(self, devtype, dev_id_info):
        raise NotImplementedError()

    def add_device(self, devobj):
        raise NotImplementedError()
    def remove_device(self, dev_type, dev_id_info):
        raise NotImplementedError()

    def define_storage_media(self, dev_id_info, newpath, _type=None):
        raise NotImplementedError()
    def hotplug_storage_media(self, dev_id_info, newpath, _type=None):
        raise NotImplementedError()

    def define_vcpus(self, vcpus):
        raise NotImplementedError()
    def hotplug_vcpus(self, vcpus):
        raise NotImplementedError()
    def define_cpuset(self, cpuset):
        raise NotImplementedError()

    def define_both_mem(self, memory, maxmem):
        raise NotImplementedError()
    def hotplug_both_mem(self, memory, maxmem):
        raise NotImplementedError()

    def define_seclabel(self, model, t, label):
        raise NotImplementedError()

    def set_boot_device(self, boot_list):
        raise NotImplementedError()

    def define_acpi(self, newvalue):
        raise NotImplementedError()
    def define_apic(self, newvalue):
        raise NotImplementedError()
    def define_clock(self, newvalue):
        raise NotImplementedError()
    def define_description(self, newvalue):
        raise NotImplementedError()

    def define_disk_readonly(self, dev_id_info, do_readonly):
        raise NotImplementedError()
    def define_disk_shareable(self, dev_id_info, do_shareable):
        raise NotImplementedError()

    def define_network_model(self, dev_id_info, newmodel):
        raise NotImplementedError()

    def define_sound_model(self, dev_id_info, newmodel):
        raise NotImplementedError()

    def define_video_model(self, dev_id_info, newmodel):
        raise NotImplementedError()

    def define_watchdog_model(self, dev_id_info, newmodel):
        raise NotImplementedError()
    def define_watchdog_action(self, dev_id_info, newmodel):
        raise NotImplementedError()

    ########################
    # XML Parsing routines #
    ########################
    def get_uuid(self):
        return self.uuid

    def set_handle(self, vm):
        self._backend = vm
    def release_handle(self):
        del(self._backend)
        self._backend = None
    def get_handle(self):
        return self._backend

    def is_read_only(self):
        if self.connection.is_read_only():
            return True
        if self.is_management_domain():
            return True
        return False

    def is_management_domain(self):
        if self.get_id() == 0:
            return True
        return False

    def is_hvm(self):
        if self.get_abi_type() == "hvm":
            return True
        return False

    def is_active(self):
        if self.get_id() == -1:
            return False
        else:
            return True

    def get_id_pretty(self):
        i = self.get_id()
        if i < 0:
            return "-"
        return str(i)

    def get_abi_type(self):
        return str(vutil.get_xml_path(self.get_xml(),
                                      "/domain/os/type")).lower()

    def get_hv_type(self):
        return str(vutil.get_xml_path(self.get_xml(), "/domain/@type")).lower()

    def get_pretty_hv_type(self):
        return util.pretty_hv(self.get_abi_type(), self.get_hv_type())

    def get_arch(self):
        return vutil.get_xml_path(self.get_xml(), "/domain/os/type/@arch")

    def get_emulator(self):
        return vutil.get_xml_path(self.get_xml(), "/domain/devices/emulator")

    def get_acpi(self):
        return bool(vutil.get_xml_path(self.get_xml(),
                                       "count(/domain/features/acpi)"))

    def get_apic(self):
        return bool(vutil.get_xml_path(self.get_xml(),
                                       "count(/domain/features/apic)"))

    def get_clock(self):
        return vutil.get_xml_path(self.get_xml(), "/domain/clock/@offset")

    def get_description(self):
        return vutil.get_xml_path(self.get_xml(), "/domain/description")

    def vcpu_pinning(self):
        cpuset = vutil.get_xml_path(self.get_xml(), "/domain/vcpu/@cpuset")
        # We need to set it to empty string not to show None in the entry
        if cpuset is None:
            cpuset = ""
        return cpuset

    def vcpu_max_count(self):
        if self._startup_vcpus == None:
            self._startup_vcpus = int(vutil.get_xml_path(self.get_xml(),
                                      "/domain/vcpu"))
        return int(self._startup_vcpus)

    def get_boot_device(self):
        xml = self.get_xml()

        def get_boot_xml(doc, ctx):
            ret = ctx.xpathEval("/domain/os/boot")
            devs = []
            for node in ret:
                dev = node.prop("dev")
                if dev:
                    devs.append(dev)
            return devs

        return util.xml_parse_wrapper(xml, get_boot_xml)

    def get_seclabel(self):
        xml = self.get_xml()
        model = vutil.get_xml_path(xml, "/domain/seclabel/@model")
        t     = vutil.get_xml_path(self.get_xml(), "/domain/seclabel/@type")
        label = vutil.get_xml_path(self.get_xml(), "/domain/seclabel/label")

        return [model, t or "dynamic", label or ""]

    # Device listing

    def get_serial_devs(self):
        def _parse_serial_consoles(ctx):
            # [ Name, device type, source path
            serial_list = []
            sdevs = ctx.xpathEval("/domain/devices/serial")
            cdevs = ctx.xpathEval("/domain/devices/console")
            for node in sdevs:
                name = "Serial "
                dev_type = node.prop("type")
                source_path = None

                for child in node.children:
                    if child.name == "target":
                        target_port = child.prop("port")
                        if target_port:
                            name += str(target_port)
                    if child.name == "source":
                        source_path = child.prop("path")

                serial_list.append([name, dev_type, source_path, target_port])

            for node in cdevs:
                name = "Serial Console"
                dev_type = "pty"
                source_path = None
                target_port = -1
                inuse = False

                for child in node.children:
                    if child.name == "source":
                        source_path = child.prop("path")

                    if child.name == "target":
                        target_port = child.prop("port")

                if target_port != -1:
                    for dev in serial_list:
                        if target_port == dev[3]:
                            inuse = True
                            break

                if not inuse:
                    serial_list.append([name, dev_type, source_path,
                                       target_port])

            return serial_list
        return self._parse_device_xml(_parse_serial_consoles)

    def get_graphics_console(self):
        gtype = vutil.get_xml_path(self.get_xml(),
                                  "/domain/devices/graphics/@type")
        vncport = vutil.get_xml_path(self.get_xml(),
                               "/domain/devices/graphics[@type='vnc']/@port")

        if gtype != "vnc":
            vncport = None
        else:
            vncport = int(vncport)

        connhost = self.connection.get_uri_hostname()
        transport, username = self.connection.get_transport()

        if connhost == None:
            # Force use of 127.0.0.1, because some (broken) systems don't
            # reliably resolve 'localhost' into 127.0.0.1, either returning
            # the public IP, or an IPv6 addr. Neither work since QEMU only
            # listens on 127.0.0.1 for VNC.
            connhost = "127.0.0.1"

        # Parse URI port
        connport = None
        if connhost.count(":"):
            connhost, connport = connhost.split(":", 1)

        # Build VNC uri for debugging
        vncuri = None
        if gtype:
            vncuri = str(gtype) + "://"
            if username:
                vncuri = vncuri + str(username) + '@'
            vncuri += str(connhost) + ":" + str(vncport)

        return [gtype, connhost, vncport, transport, username, connport,
                vncuri]


    # ----------------
    # get_X_devices functions: return a list of lists. Each sublist represents
    # a device, of the format:
    # [ device_type, unique_attribute(s), hw column label, attr1, attr2, ... ]
    # ----------------

    def get_disk_devices(self, refresh_if_necc=True, inactive=False):
        def _parse_disk_devs(ctx):
            disks = []
            ret = ctx.xpathEval("/domain/devices/disk")
            for node in ret:
                typ = node.prop("type")
                srcpath = None
                devdst = None
                bus = None
                readonly = False
                sharable = False
                devtype = node.prop("device")
                if devtype == None:
                    devtype = "disk"
                for child in node.children:
                    if child.name == "source":
                        propname = disk_type_to_target_prop(typ)
                        srcpath = child.prop(propname)
                    elif child.name == "target":
                        devdst = child.prop("dev")
                        bus = child.prop("bus")
                    elif child.name == "readonly":
                        readonly = True
                    elif child.name == "shareable":
                        sharable = True

                if srcpath == None:
                    if devtype == "cdrom" or devtype == "floppy":
                        typ = "block"

                # [ devicetype, unique, device target, source path,
                #   disk device type, disk type, readonly?, sharable?,
                #   bus type, disk idx ]
                disks.append(["disk", devdst, devdst, srcpath, devtype, typ,
                              readonly, sharable, bus, 0])

            # Iterate through all disks and calculate what number they are
            idx_mapping = {}
            for disk in disks:
                devtype = disk[4]
                bus = disk[8]
                key = devtype + (bus or "")

                if not idx_mapping.has_key(key):
                    idx_mapping[key] = 1

                disk[9] = idx_mapping[key]
                idx_mapping[key] += 1

            return disks

        return self._parse_device_xml(_parse_disk_devs, refresh_if_necc,
                                      inactive)

    def get_network_devices(self, refresh_if_necc=True):
        def _parse_network_devs(ctx):
            nics = []
            ret = ctx.xpathEval("/domain/devices/interface")

            for node in ret:
                typ = node.prop("type")
                devmac = None
                source = None
                target = None
                model = None
                for child in node.children:
                    if child.name == "source":
                        if typ == "bridge":
                            source = child.prop("bridge")
                        elif typ == "ethernet":
                            source = child.prop("dev")
                        elif typ == "network":
                            source = child.prop("network")
                        elif typ == "user":
                            source = None
                        else:
                            source = None
                    elif child.name == "mac":
                        devmac = child.prop("address")
                    elif child.name == "target":
                        target = child.prop("dev")
                    elif child.name == "model":
                        model = child.prop("type")
                # XXX Hack - ignore devs without a MAC, since we
                # need mac for uniqueness. Some reason XenD doesn't
                # always complete kill the NIC record
                if devmac != None:
                    # [device type, unique, mac addr, source, target dev,
                    #  net type, net model]
                    nics.append(["interface", devmac, devmac, source, target,
                                 typ, model])
            return nics

        return self._parse_device_xml(_parse_network_devs, refresh_if_necc)

    def get_input_devices(self):
        def _parse_input_devs(ctx):
            inputs = []
            ret = ctx.xpathEval("/domain/devices/input")

            for node in ret:
                typ = node.prop("type")
                bus = node.prop("bus")

                # [device type, unique, display string, bus type, input type]
                inputs.append(["input", (typ, bus), typ + ":" + bus, bus, typ])
            return inputs

        return self._parse_device_xml(_parse_input_devs)

    def get_graphics_devices(self):
        def _parse_graphics_devs(ctx):
            graphics = []
            count = 0
            ret = ctx.xpathEval("/domain/devices/graphics")

            for node in ret:
                typ = node.prop("type")
                listen = None
                port = None
                keymap = None
                if typ == "vnc":
                    listen = node.prop("listen")
                    port = node.prop("port")
                    keymap = node.prop("keymap")

                unique = count
                count += 1

                # [device type, unique, graphics type, listen addr, port,
                #  keymap ]
                graphics.append(["graphics", unique, typ, listen, port, keymap])
            return graphics

        return self._parse_device_xml(_parse_graphics_devs)

    def get_sound_devices(self):
        def _parse_sound_devs(ctx):
            sound = []
            count = 0
            ret = ctx.xpathEval("/domain/devices/sound")

            for node in ret:
                model = node.prop("model")

                unique = count
                count += 1

                # [device type, unique, sound model]
                sound.append(["sound", unique, model])
            return sound

        return self._parse_device_xml(_parse_sound_devs)

    def get_char_devices(self):
        def _parse_char_devs(ctx):
            chars = []
            devs  = []
            devs.extend(ctx.xpathEval("/domain/devices/console"))
            devs.extend(ctx.xpathEval("/domain/devices/parallel"))
            devs.extend(ctx.xpathEval("/domain/devices/serial"))

            # Since there is only one 'console' device ever in the xml
            # find its port (if present) and path
            cons_port = None
            cons_dev = None
            list_cons = True
            count_dict = {}

            for node in devs:
                char_type = node.name
                dev_type = node.prop("type")
                target_port = None
                source_path = None

                for child in node.children or []:
                    if child.name == "source":
                        source_path = child.prop("path")

                if not source_path:
                    source_path = node.prop("tty")

                # Rather than parse the target port, just calculate it
                # ourselves. This helps device removal when customizing
                # installs
                if count_dict.get(char_type) == None:
                    count_dict[char_type] = -1
                count_dict[char_type] += 1
                target_port = str(count_dict[char_type])

                # [device type, unique, display string, target_port,
                #  char device type, source_path, is_console_dup_of_serial?
                dev = [char_type, target_port,
                       "%s:%s" % (char_type, target_port), target_port,
                       dev_type, source_path, False]

                if node.name == "console":
                    cons_port = target_port
                    cons_dev = dev
                    dev[6] = True
                    continue
                elif node.name == "serial" and cons_port \
                   and target_port == cons_port:
                    # Console is just a dupe of this serial device
                    dev[6] = True
                    list_cons = False

                chars.append(dev)

            if cons_dev and list_cons:
                chars.append(cons_dev)

            return chars

        return self._parse_device_xml(_parse_char_devs)

    def get_video_devices(self):
        def _parse_video_devs(ctx):
            vids = []
            devs = ctx.xpathEval("/domain/devices/video")
            count = 0

            for dev in devs:
                model = None
                ram   = None
                heads = None

                for node in dev.children or []:
                    if node.name == "model":
                        model = node.prop("type")
                        ram = node.prop("vram")
                        heads = node.prop("heads")

                        if ram:
                            ram = safeint(ram, "%d")

                unique = count
                count += 1

                row = ["video", unique, model, ram, heads]
                vids.append(row)

            return vids
        return self._parse_device_xml(_parse_video_devs)

    def get_hostdev_devices(self):
        def _parse_hostdev_devs(ctx):
            hostdevs = []
            devs = ctx.xpathEval("/domain/devices/hostdev")
            count = 0

            for dev in devs:
                vendor  = None
                product = None
                addrbus = None
                addrdev = None
                unique = {}

                # String shown in the devices details section
                srclabel = ""
                # String shown in the VMs hardware list
                hwlabel = ""

                def dehex(val):
                    if val.startswith("0x"):
                        val = val[2:]
                    return val

                def set_uniq(baseent, propname, node):
                    val = node.prop(propname)
                    if not unique.has_key(baseent):
                        unique[baseent] = {}
                    unique[baseent][propname] = val
                    return val

                mode = dev.prop("mode")
                typ  = dev.prop("type")
                unique["type"] = typ

                hwlabel = typ.upper()
                srclabel = typ.upper()

                for node in dev.children:
                    if node.name == "source":
                        for child in node.children:
                            if child.name == "address":
                                addrbus = set_uniq("address", "bus", child)

                                # For USB
                                addrdev = set_uniq("address", "device", child)

                                # For PCI
                                addrdom = set_uniq("address", "domain", child)
                                addrslt = set_uniq("address", "slot", child)
                                addrfun = set_uniq("address", "function", child)
                            elif child.name == "vendor":
                                vendor = set_uniq("vendor", "id", child)
                            elif child.name == "product":
                                product = set_uniq("product", "id", child)

                if vendor and product:
                    # USB by vendor + product
                    devstr = " %s:%s" % (dehex(vendor), dehex(product))
                    srclabel += devstr
                    hwlabel += devstr

                elif addrbus and addrdev:
                    # USB by bus + dev
                    srclabel += " Bus %s Device %s" % \
                                (safeint(addrbus), safeint(addrdev))
                    hwlabel += " %s:%s" % (safeint(addrbus), safeint(addrdev))

                elif addrbus and addrslt and addrfun and addrdom:
                    # PCI by bus:slot:function
                    devstr = " %s:%s:%s.%s" % \
                              (dehex(addrdom), dehex(addrbus),
                               dehex(addrslt), dehex(addrfun))
                    srclabel += devstr
                    hwlabel += devstr

                else:
                    # If we can't determine source info, skip these
                    # device since we have no way to determine uniqueness
                    continue

                index = count
                count += 1

                # [device type, unique, hwlist label, hostdev mode,
                #  hostdev type, source desc label]
                hostdevs.append(["hostdev", index, hwlabel, mode, typ,
                                 srclabel, unique])

            return hostdevs
        return self._parse_device_xml(_parse_hostdev_devs)

    def get_watchdog_devices(self):
        def _parse_devs(ctx):
            vids = []
            devs = ctx.xpathEval("/domain/devices/watchdog")
            count = 0

            for dev in devs:
                model = dev.prop("model")
                action = dev.prop("action")

                unique = count
                count += 1

                row = ["watchdog", unique, model, action]
                vids.append(row)

            return vids
        return self._parse_device_xml(_parse_devs)

    def _parse_device_xml(self, parse_function, refresh_if_necc=True,
                          inactive=False):
        def parse_wrap_func(doc, ctx):
            return parse_function(ctx)

        if inactive:
            xml = self._get_inactive_xml()
        elif refresh_if_necc:
            xml = self.get_xml()
        else:
            xml = self._get_xml_no_refresh()

        return util.xml_parse_wrapper(xml, parse_wrap_func)

    def _get_device_xml(self, dev_type, dev_id_info):
        vmxml = self.get_xml()

        def dev_xml_serialize(doc, ctx):
            nodes = self._get_device_xml_nodes(ctx, dev_type, dev_id_info)
            if nodes:
                return nodes[0].serialize()

        return util.xml_parse_wrapper(vmxml, dev_xml_serialize)

    def _get_device_xml_xpath(self, dev_type, dev_id_info):
        """
        Generate the XPath needed to lookup the passed device info
        """
        xpath = None

        if dev_type=="interface":
            xpath = ("/domain/devices/interface[mac/@address='%s'][1]" %
                     dev_id_info)

        elif dev_type=="disk":
            xpath = "/domain/devices/disk[target/@dev='%s'][1]" % dev_id_info

        elif dev_type=="input":
            typ, bus = dev_id_info
            xpath = ("/domain/devices/input[@type='%s' and @bus='%s'][1]" %
                     (typ, bus))

        elif dev_type=="graphics":
            xpath = "/domain/devices/graphics[%s]" % (int(dev_id_info) + 1)

        elif dev_type == "sound":
            xpath = "/domain/devices/sound[%s]" % (int(dev_id_info) + 1)

        elif (dev_type == "parallel" or
              dev_type == "console" or
              dev_type == "serial"):
            xpath = ("/domain/devices/%s[target/@port='%s'][1]" %
                     (dev_type, dev_id_info))

        elif dev_type == "hostdev":
            xpath = "/domain/devices/hostdev[%s]" % (int(dev_id_info) + 1)

        elif dev_type == "video":
            xpath = "/domain/devices/video[%s]" % (int(dev_id_info) + 1)

        elif dev_type == "watchdog":
            xpath = "/domain/devices/watchdog[%s]" % (int(dev_id_info) + 1)

        else:
            raise RuntimeError(_("Unknown device type '%s'") % dev_type)

        if not xpath:
            raise RuntimeError(_("Couldn't build xpath for device %s:%s") %
                               (dev_type, dev_id_info))

        return xpath

    def _get_device_xml_nodes(self, ctx, dev_type, dev_id_info):
        """
        Return nodes needed to alter/remove the desired device
        """
        xpath = self._get_device_xml_xpath(dev_type, dev_id_info)

        ret = ctx.xpathEval(xpath)

        # If serial and console are both present, console is
        # probably (always?) just a dup of the 'primary' serial
        # device. Try and find an associated console device with
        # the same port and remove that as well, otherwise the
        # removal doesn't go through on libvirt <= 0.4.4
        if dev_type == "serial":
            con = ctx.xpathEval("/domain/devices/console[target/@port='%s'][1]"
                                % dev_id_info)
            if con and len(con) > 0 and ret:
                ret.append(con[0])

        if not ret or len(ret) <= 0:
            raise RuntimeError(_("Could not find device %s") % xpath)

        return ret


    # Stats accessors
    def _normalize_status(self, status):
        if status == libvirt.VIR_DOMAIN_NOSTATE:
            return libvirt.VIR_DOMAIN_RUNNING
        elif status == libvirt.VIR_DOMAIN_BLOCKED:
            return libvirt.VIR_DOMAIN_RUNNING
        return status

    def _sample_mem_stats(self, info):
        pcentCurrMem = info[2] * 100.0 / self.connection.host_memory_size()
        pcentMaxMem = info[1] * 100.0 / self.connection.host_memory_size()
        return pcentCurrMem, pcentMaxMem

    def _sample_cpu_stats(self, info, now):
        prevCpuTime = 0
        prevTimestamp = 0
        if len(self.record) > 0:
            prevTimestamp = self.record[0]["timestamp"]
            prevCpuTime = self.record[0]["cpuTimeAbs"]

        cpuTime = 0
        cpuTimeAbs = 0
        pcentCpuTime = 0
        if not (info[0] in [libvirt.VIR_DOMAIN_SHUTOFF,
                            libvirt.VIR_DOMAIN_CRASHED]):
            cpuTime = info[4] - prevCpuTime
            cpuTimeAbs = info[4]

            pcentCpuTime = ((cpuTime) * 100.0 /
                            (((now - prevTimestamp)*1000.0*1000.0*1000.0) *
                               self.connection.host_active_processor_count()))
            # Due to timing diffs between getting wall time & getting
            # the domain's time, its possible to go a tiny bit over
            # 100% utilization. This freaks out users of the data, so
            # we hard limit it.
            if pcentCpuTime > 100.0:
                pcentCpuTime = 100.0
            # Enforce >= 0 just in case
            if pcentCpuTime < 0.0:
                pcentCpuTime = 0.0

        return cpuTime, cpuTimeAbs, pcentCpuTime

    def _sample_network_traffic_dummy(self):
        return 0, 0

    def _sample_network_traffic(self):
        rx = 0
        tx = 0
        if not self._stats_net_supported or not self.is_active():
            return rx, tx

        for netdev in self.get_network_devices(refresh_if_necc=False):
            dev = netdev[4]
            if not dev:
                continue

            if dev in self._stats_net_skip:
                continue

            try:
                io = self.interfaceStats(dev)
                if io:
                    rx += io[0]
                    tx += io[4]
            except libvirt.libvirtError, err:
                if support.is_error_nosupport(err):
                    logging.debug("Net stats not supported: %s" % err)
                    self._stats_net_supported = False
                else:
                    logging.error("Error reading net stats for "
                                  "'%s' dev '%s': %s" %
                                  (self.get_name(), dev, err))
                    logging.debug("Adding %s to skip list." % dev)
                    self._stats_net_skip.append(dev)

        return rx, tx

    def _sample_disk_io_dummy(self):
        return 0, 0

    def _sample_disk_io(self):
        rd = 0
        wr = 0
        if not self._stats_disk_supported or not self.is_active():
            return rd, wr

        for disk in self.get_disk_devices(refresh_if_necc=False):
            dev = disk[2]
            if not dev:
                continue

            if dev in self._stats_disk_skip:
                continue

            try:
                io = self.blockStats(dev)
                if io:
                    rd += io[1]
                    wr += io[3]
            except libvirt.libvirtError, err:
                if support.is_error_nosupport(err):
                    logging.debug("Disk stats not supported: %s" % err)
                    self._stats_disk_supported = False
                else:
                    logging.error("Error reading disk stats for "
                                  "'%s' dev '%s': %s" %
                                  (self.get_name(), dev, err))
                    logging.debug("Adding %s to skip list." % dev)
                    self._stats_disk_skip.append(dev)

        return rd, wr

    def _get_cur_rate(self, what):
        if len(self.record) > 1:
            ret = float(self.record[0][what] - self.record[1][what]) / \
                      float(self.record[0]["timestamp"] - self.record[1]["timestamp"])
        else:
            ret = 0.0
        return max(ret, 0,0) # avoid negative values at poweroff

    def _set_max_rate(self, record, what):
        if record[what] > self.maxRecord[what]:
            self.maxRecord[what] = record[what]

    def current_memory(self):
        if self.get_id() == -1:
            return 0
        return self.get_memory()

    def current_memory_percentage(self):
        if self.get_id() == -1:
            return 0
        return self.get_memory_percentage()

    def current_memory_pretty(self):
        if self.get_id() == -1:
            return "0 MB"
        return self.get_memory_pretty()

    def get_memory_pretty(self):
        mem = self.get_memory()
        if mem > (10*1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.0f MB" % (mem/1024.0)

    def maximum_memory_pretty(self):
        mem = self.maximum_memory()
        if mem > (10*1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.0f MB" % (mem/1024.0)

    def cpu_time_pretty(self):
        return "%2.2f %%" % self.cpu_time_percentage()

    def network_traffic_rate(self):
        return self.network_tx_rate() + self.network_rx_rate()

    def disk_io_rate(self):
        return self.disk_read_rate() + self.disk_write_rate()

    def _vector_helper(self, record_name):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length() + 1):
            if i < len(stats):
                vector.append(stats[i][record_name] / 100.0)
            else:
                vector.append(0)
        return vector

    def _in_out_vector_helper(self, name1, name2):
        vector = []
        stats = self.record
        ceil = float(max(self.maxRecord[name1], self.maxRecord[name2]))
        maxlen = self.config.get_stats_history_length()
        for n in [ name1, name2 ]:
            for i in range(maxlen + 1):
                if i < len(stats):
                    vector.append(float(stats[i][n])/ceil)
                else:
                    vector.append(0.0)
        return vector

    def in_out_vector_limit(self, data, limit):
        l = len(data)/2
        end = [l, limit][l > limit]
        if l > limit:
            data = data[0:end] + data[l:l+end]
        d = map(lambda x,y: (x + y)/2, data[0:end], data[end:end*2])
        return d

    def cpu_time_vector(self):
        return self._vector_helper("cpuTimePercent")
    def cpu_time_moving_avg_vector(self):
        return self._vector_helper("cpuTimeMovingAvgPercent")
    def current_memory_vector(self):
        return self._vector_helper("currMemPercent")
    def network_traffic_vector(self):
        return self._in_out_vector_helper("netRxRate", "netTxRate")
    def disk_io_vector(self):
        return self._in_out_vector_helper("diskRdRate", "diskWrRate")

    def cpu_time_vector_limit(self, limit):
        cpudata = self.cpu_time_vector()
        if len(cpudata) > limit:
            cpudata = cpudata[0:limit]
        return cpudata
    def network_traffic_vector_limit(self, limit):
        return self.in_out_vector_limit(self.network_traffic_vector(), limit)
    def disk_io_vector_limit(self, limit):
        return self.in_out_vector_limit(self.disk_io_vector(), limit)

    def is_shutoff(self):
        return self.status() == libvirt.VIR_DOMAIN_SHUTOFF

    def is_crashed(self):
        return self.status() == libvirt.VIR_DOMAIN_CRASHED

    def is_stoppable(self):
        return self.status() in [libvirt.VIR_DOMAIN_RUNNING,
                                 libvirt.VIR_DOMAIN_PAUSED]

    def is_destroyable(self):
        return (self.is_stoppable() or
                self.status() in [libvirt.VIR_DOMAIN_CRASHED])

    def is_runable(self):
        return self.status() in [libvirt.VIR_DOMAIN_SHUTOFF,
                                 libvirt.VIR_DOMAIN_CRASHED]

    def is_pauseable(self):
        return self.status() in [libvirt.VIR_DOMAIN_RUNNING]

    def is_unpauseable(self):
        return self.status() in [libvirt.VIR_DOMAIN_PAUSED]

    def is_paused(self):
        return self.status() in [libvirt.VIR_DOMAIN_PAUSED]

    def run_status(self):
        if self.status() == libvirt.VIR_DOMAIN_RUNNING:
            return _("Running")
        elif self.status() == libvirt.VIR_DOMAIN_PAUSED:
            return _("Paused")
        elif self.status() == libvirt.VIR_DOMAIN_SHUTDOWN:
            return _("Shutting Down")
        elif self.status() == libvirt.VIR_DOMAIN_SHUTOFF:
            return _("Shutoff")
        elif self.status() == libvirt.VIR_DOMAIN_CRASHED:
            return _("Crashed")

    def run_status_icon(self):
        return self.config.get_vm_status_icon(self.status())
    def run_status_icon_large(self):
        return self.config.get_vm_status_icon_large(self.status())

    def toggle_sample_network_traffic(self, ignore1=None, ignore2=None,
                                      ignore3=None, ignore4=None):
        if self.config.get_stats_enable_net_poll():
            if len(self.record) > 1:
                # resample the current value before calculating the rate in
                # self.tick() otherwise we'd get a huge spike when switching
                # from 0 to bytes_transfered_so_far
                rxBytes, txBytes = self._sample_network_traffic()
                self.record[0]["netRxKB"] = rxBytes / 1024
                self.record[0]["netTxKB"] = txBytes / 1024
            self._network_traffic = self._sample_network_traffic
        else:
            self._network_traffic = self._sample_network_traffic_dummy

    def toggle_sample_disk_io(self, ignore1=None, ignore2=None,
                              ignore3=None, ignore4=None):
        if self.config.get_stats_enable_disk_poll():
            if len(self.record) > 1:
                # resample the current value before calculating the rate in
                # self.tick() otherwise we'd get a huge spike when switching
                # from 0 to bytes_transfered_so_far
                rdBytes, wrBytes = self._sample_disk_io()
                self.record[0]["diskRdKB"] = rdBytes / 1024
                self.record[0]["diskWrKB"] = wrBytes / 1024
            self._disk_io = self._sample_disk_io
        else:
            self._disk_io = self._sample_disk_io_dummy

    # GConf specific wranglings
    def set_console_scaling(self, value):
        self.config.set_pervm(self.connection.get_uri(), self.uuid,
                              self.config.set_console_scaling, value)
    def get_console_scaling(self):
        return self.config.get_pervm(self.connection.get_uri(), self.uuid,
                                     self.config.get_console_scaling)
    def on_console_scaling_changed(self, cb):
        self.config.listen_pervm(self.connection.get_uri(), self.uuid,
                                 self.config.on_console_scaling_changed, cb)

    def set_details_window_size(self, w, h):
        self.config.set_pervm(self.connection.get_uri(), self.uuid,
                              self.config.set_details_window_size, (w, h))
    def get_details_window_size(self):
        return self.config.get_pervm(self.connection.get_uri(), self.uuid,
                                     self.config.get_details_window_size)



########################
# Libvirt domain class #
########################

class vmmDomain(vmmDomainBase):
    """
    Domain class backed by a libvirt virDomain
    """

    def __init__(self, config, connection, backend, uuid):
        vmmDomainBase.__init__(self, config, connection, backend, uuid)

        self.lastStatus = libvirt.VIR_DOMAIN_SHUTOFF
        self.record = []
        self.maxRecord = { "diskRdRate" : 10.0,
                           "diskWrRate" : 10.0,
                           "netTxRate"  : 10.0,
                           "netRxRate"  : 10.0,
                         }

        self._update_status()

        self.config.on_stats_enable_net_poll_changed(
                                            self.toggle_sample_network_traffic)
        self.config.on_stats_enable_disk_poll_changed(
                                            self.toggle_sample_disk_io)

        self.getvcpus_supported = support.check_domain_support(self._backend,
                                            support.SUPPORT_DOMAIN_GETVCPUS)

        self.toggle_sample_network_traffic()
        self.toggle_sample_disk_io()

        self.reboot_listener = None

        # Determine available XML flags (older libvirt versions will error
        # out if passed SECURE_XML, INACTIVE_XML, etc)
        (self._inactive_xml_flags,
         self._active_xml_flags) = self.connection.get_dom_flags(
                                                            self._backend)

        # Hook up our own status listeners
        self.connect("status-changed", self._update_start_vcpus)

    ##########################
    # Internal virDomain API #
    ##########################

    def _define(self, newxml):
        self.get_connection().define_domain(newxml)

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)

    def get_info(self):
        return self._backend.info()

    def status(self):
        return self.lastStatus

    def _get_record_helper(self, record_name):
        if len(self.record) == 0:
            return 0
        return self.record[0][record_name]

    def get_memory(self):
        return self._get_record_helper("currMem")
    def get_memory_percentage(self):
        return self._get_record_helper("currMemPercent")
    def maximum_memory(self):
        return self._get_record_helper("maxMem")
    def maximum_memory_percentage(self):
        return self._get_record_helper("maxMemPercent")
    def cpu_time(self):
        return self._get_record_helper("cpuTime")
    def cpu_time_percentage(self):
        return self._get_record_helper("cpuTimePercent")
    def vcpu_count(self):
        return self._get_record_helper("vcpuCount")
    def network_rx_rate(self):
        return self._get_record_helper("netRxRate")
    def network_tx_rate(self):
        return self._get_record_helper("netTxRate")
    def disk_read_rate(self):
        return self._get_record_helper("diskRdRate")
    def disk_write_rate(self):
        return self._get_record_helper("diskWrRate")

    def _unregister_reboot_listener(self):
        if self.reboot_listener == None:
            return

        try:
            self.disconnect(self.reboot_listener)
            self.reboot_listener = None
        except:
            pass

    def manual_reboot(self):
        # Attempt a manual reboot via 'shutdown' followed by startup
        def reboot_listener(vm, ignore1, ignore2, self):
            if vm.is_crashed():
                # Abandon reboot plans
                self.reboot_listener = None
                return True

            if not vm.is_shutoff():
                # Not shutoff, continue waiting
                return

            try:
                logging.debug("Fake reboot detected shutdown. Restarting VM")
                vm.startup()
            except:
                logging.exception("Fake reboot startup failed")

            self.reboot_listener = None
            return True

        self._unregister_reboot_listener()

        # Request a shutdown
        self.shutdown()

        self.reboot_listener = util.connect_opt_out(self, "status-changed",
                                                    reboot_listener, self)

    def shutdown(self):
        self._unregister_reboot_listener()
        self._backend.shutdown()
        self._update_status()

    def reboot(self):
        self._backend.reboot(0)
        self._update_status()

    def startup(self):
        self._backend.create()
        self._update_status()

    def suspend(self):
        self._backend.suspend()
        self._update_status()

    def delete(self):
        self._backend.undefine()

    def resume(self):
        self._backend.resume()
        self._update_status()

    def save(self, filename, background=True):
        if background:
            conn = util.dup_conn(self.config, self.connection)
            vm = conn.lookupByID(self.get_id())
        else:
            vm = self._backend

        vm.save(filename)
        self._update_status()

    def destroy(self):
        self._unregister_reboot_listener()
        self._backend.destroy()
        self._update_status()

    def interfaceStats(self, device):
        return self._backend.interfaceStats(device)

    def blockStats(self, device):
        return self._backend.blockStats(device)

    def pin_vcpu(self, vcpu_num, pinlist):
        self._backend.pinVcpu(vcpu_num, pinlist)

    def vcpu_info(self):
        if self.is_active() and self.getvcpus_supported:
            return self._backend.vcpus()
        return [[], []]

    def get_autostart(self):
        return self._backend.autostart()

    def set_autostart(self, val):
        if self.get_autostart() != val:
            self._backend.setAutostart(val)

    def migrate(self, destconn, interface=None, rate=0,
                live=False, secure=False):
        newname = None

        flags = 0
        if self.status() == libvirt.VIR_DOMAIN_RUNNING and live:
            flags |= libvirt.VIR_MIGRATE_LIVE

        if secure:
            flags |= libvirt.VIR_MIGRATE_PEER2PEER
            flags |= libvirt.VIR_MIGRATE_TUNNELLED

        newxml = self._get_xml_to_define()

        logging.debug("Migrating: conn=%s flags=%s dname=%s uri=%s rate=%s" %
                      (destconn.vmm, flags, newname, interface, rate))
        self._backend.migrate(destconn.vmm, flags, newname, interface, rate)
        destconn.define_domain(newxml)

    # Genertc backend APIs
    def get_name(self):
        return self._backend.name()
    def get_id(self):
        return self._backend.ID()

    def attach_device(self, devobj, devxml=None):
        """
        Hotplug device to running guest
        """
        if not self.is_active():
            return

        if not devxml:
            devxml = devobj.get_xml_config()

        self._backend.attachDevice(devxml)

    def detach_device(self, devtype, dev_id_info):
        """
        Hotunplug device from running guest
        """
        xml = self._get_device_xml(devtype, dev_id_info)
        if self.is_active():
            self._backend.detachDevice(xml)

    def hotplug_vcpus(self, vcpus):
        vcpus = int(vcpus)
        if vcpus != self.vcpu_count():
            self._backend.setVcpus(vcpus)

    def hotplug_memory(self, memory):
        if memory != self.get_memory():
            self._backend.setMemory(memory)

    def hotplug_maxmem(self, maxmem):
        if maxmem != self.maximum_memory():
            self._backend.setMaxMemory(maxmem)

    ####################
    # End internal API #
    ####################

    ###########################
    # XML/Config Altering API #
    ###########################

    def _check_device_is_present(self, dev_type, dev_id_info):
        """
        Return True if device is present in the inactive XML, False otherwise.
        If device can not be found in either the active or inactive XML,
        raise an exception (which should not be caught in any domain.py func)

        We need to make this check every time we are altering device props
        of the inactive XML. If the device can't be found, make no change
        and return success.
        """
        vmxml = self._get_inactive_xml()

        def find_dev(doc, ctx, dev_type, dev_id_info):
            ret = self._get_device_xml_nodes(ctx, dev_type, dev_id_info)
            return ret is not None

        try:
            util.xml_parse_wrapper(vmxml, find_dev, dev_type, dev_id_info)
            return True
        except Exception, e:
            # If we are removing multiple dev from an active VM, a double
            # attempt may result in a lookup failure. If device is present
            # in the active XML, assume all is good.
            try:
                util.xml_parse_wrapper(self.get_xml(), find_dev,
                                       dev_type, dev_id_info)
                return False
            except:
                raise e


    # Generic device Add/Remove
    def add_device(self, devobj):
        """
        Redefine guest with appended device XML 'devxml'
        """
        devxml = devobj.get_xml_config()
        def _add_xml_device(xml, devxml):
            index = xml.find("</devices>")
            return xml[0:index] + devxml + xml[index:]

        self._redefine(_add_xml_device, devxml)

    def remove_device(self, dev_type, dev_id_info):
        """
        Remove device of type 'dev_type' with unique info 'dev_id_info' from
        the inactive guest XML
        """
        if not self._check_device_is_present(dev_type, dev_id_info):
            return

        def _remove_xml_device(vmxml, dev_type, dev_id_info):

            def unlink_dev_node(doc, ctx):
                ret = self._get_device_xml_nodes(ctx, dev_type, dev_id_info)

                for node in ret:
                    node.unlinkNode()
                    node.freeNode()

                newxml = doc.serialize()
                return newxml

            return util.xml_parse_wrapper(vmxml, unlink_dev_node)

        self._redefine(_remove_xml_device, dev_type, dev_id_info)

    # Media change

    # Helper for connecting a new source path to an existing disk
    def _media_xml_connect(self, doc, ctx, dev_id_info, newpath, _type):
        disk_fragment = self._get_device_xml_nodes(ctx, "disk",
                                                   dev_id_info)[0]
        driver_fragment = None

        for child in disk_fragment.children or []:
            if child.name == "driver":
                driver_fragment = child

        disk_fragment.setProp("type", _type)
        elem = disk_fragment.newChild(None, "source", None)

        targetprop = disk_type_to_target_prop(_type)
        elem.setProp(targetprop, newpath)
        driver_name = disk_type_to_xen_driver_name(_type)

        if driver_fragment:
            orig_name = driver_fragment.prop("name")

            # For Xen, the driver name is dependent on the storage type
            # (file or phys).
            if orig_name and orig_name in [ "file", "phy" ]:
                driver_fragment.setProp("name", driver_name)

        return doc.serialize(), disk_fragment.serialize()

    # Helper for disconnecting a path from an existing disk
    def _media_xml_disconnect(self, doc, ctx, dev_id_info, newpath, _type):
        disk_fragment = self._get_device_xml_nodes(ctx, "disk",
                                                   dev_id_info)[0]
        sourcenode = None

        for child in disk_fragment.children:
            if child.name == "source":
                sourcenode = child
                break
            else:
                continue

        if sourcenode:
            sourcenode.unlinkNode()
            sourcenode.freeNode()

        return doc.serialize(), disk_fragment.serialize()

    def define_storage_media(self, dev_id_info, newpath, _type=None):
        if not self._check_device_is_present("disk", dev_id_info):
            return

        if not newpath:
            func = self._media_xml_disconnect
        else:
            func = self._media_xml_connect

        def change_storage_helper(origxml):
            vmxml, ignore = util.xml_parse_wrapper(origxml, func, dev_id_info,
                                                   newpath, _type)
            return vmxml
        self._redefine(change_storage_helper)

    def hotplug_storage_media(self, dev_id_info, newpath, _type=None):
        if not newpath:
            func = self._media_xml_disconnect
        else:
            func = self._media_xml_connect

        ignore, diskxml = util.xml_parse_wrapper(self.get_xml(), func,
                                                 dev_id_info, newpath, _type)

        self.attach_device(None, diskxml)

    # VCPU changing
    def define_vcpus(self, vcpus):
        vcpus = int(vcpus)

        def set_node(doc, ctx, vcpus, xpath):
            node = ctx.xpathEval(xpath)
            node = (node and node[0] or None)

            if node:
                node.setContent(str(vcpus))

            return doc.serialize()

        def change_vcpu_xml(xml, vcpus):
            return util.xml_parse_wrapper(xml, set_node, vcpus,
                                          "/domain/vcpu[1]")

        self._redefine(change_vcpu_xml, vcpus)

    def define_cpuset(self, cpuset):
        def set_node(doc, ctx, xpath):
            node = ctx.xpathEval(xpath)
            node = (node and node[0] or None)

            if node:
                if cpuset:
                    node.setProp("cpuset", cpuset)
                else:
                    node.unsetProp("cpuset")
            return doc.serialize()

        def change_cpuset_xml(xml):
            return util.xml_parse_wrapper(xml, set_node, "/domain/vcpu[1]")

        self._redefine(change_cpuset_xml)

    # Memory routines
    def hotplug_both_mem(self, memory, maxmem):
        logging.info("Hotplugging curmem=%s maxmem=%s for VM '%s'" %
                     (memory, maxmem, self.get_name()))

        if self.is_active():
            actual_cur = self.get_memory()
            if memory:
                if maxmem < actual_cur:
                    # Set current first to avoid error
                    self.hotplug_memory(memory)
                    self.hotplug_maxmem(maxmem)
                else:
                    self.hotplug_maxmem(maxmem)
                    self.hotplug_memory(memory)
            else:
                self.hotplug_maxmem(maxmem)

    def define_both_mem(self, memory, maxmem):
        def set_mem_node(doc, ctx, memval, xpath):
            node = ctx.xpathEval(xpath)
            node = (node and node[0] or None)

            if node:
                node.setContent(str(memval))
            return doc.serialize()

        def change_mem_xml(xml, memory, maxmem):
            if memory:
                xml = util.xml_parse_wrapper(xml, set_mem_node, memory,
                                             "/domain/currentMemory[1]")
            if maxmem:
                xml = util.xml_parse_wrapper(xml, set_mem_node, maxmem,
                                             "/domain/memory[1]")
            return xml

        self._redefine(change_mem_xml, memory, maxmem)

    # Boot device
    def set_boot_device(self, boot_list):
        logging.debug("Setting boot devices to: %s" % boot_list)

        def set_boot_xml(doc, ctx):
            nodes = ctx.xpathEval("/domain/os/boot")
            os_node = ctx.xpathEval("/domain/os")[0]
            mappings = map(lambda x, y: (x, y), nodes, boot_list)

            for node, boot_dev in mappings:
                if node:
                    if boot_dev:
                        node.setProp("dev", boot_dev)
                    else:
                        node.unlinkNode()
                        node.freeNode()
                else:
                    if boot_dev:
                        node = os_node.newChild(None, "boot", None)
                    node.setProp("dev", boot_dev)

            return doc.serialize()

        self._redefine(util.xml_parse_wrapper, set_boot_xml)

    # Security label
    def define_seclabel(self, model, t, label):
        logging.debug("Changing seclabel with model=%s t=%s label=%s" %
                      (model, t, label))

        def change_label(doc, ctx):
            secnode = ctx.xpathEval("/domain/seclabel")
            secnode = (secnode and secnode[0] or None)

            if not model:
                if secnode:
                    secnode.unlinkNode()
                    secnode.freeNode()

            elif not secnode:
                # Need to create new node
                domain = ctx.xpathEval("/domain")[0]
                seclabel = domain.newChild(None, "seclabel", None)
                seclabel.setProp("model", model)
                seclabel.setProp("type", t)
                seclabel.newChild(None, "label", label)

            else:
                # Change existing label info
                secnode.setProp("model", model)
                secnode.setProp("type", t)
                l = ctx.xpathEval("/domain/seclabel/label")
                if len(l) > 0:
                    l[0].setContent(label)
                else:
                    secnode.newChild(None, "label", label)

            return doc.serialize()

        self._redefine(util.xml_parse_wrapper, change_label)

    # Helper function for changing ACPI/APIC
    def _change_features_helper(self, xml, feature_name, do_enable):
        def change_feature(doc, ctx):
            feature_node = ctx.xpathEval("/domain/features")
            feature_node = (feature_node and feature_node[0] or None)

            if not feature_node:
                if do_enable:
                    domain_node = ctx.xpathEval("/domain")[0]
                    feature_node = domain_node.newChild(None, "features", None)

            if feature_node:
                node = ctx.xpathEval("/domain/features/%s" % feature_name)
                node = (node and node[0] or None)

                if node:
                    if not do_enable:
                        node.unlinkNode()
                        node.freeNode()
                else:
                    if do_enable:
                        feature_node.newChild(None, feature_name, None)

            return doc.serialize()

        return util.xml_parse_wrapper(xml, change_feature)

    # 'Overview' section settings
    def define_acpi(self, do_enable):
        if do_enable == self.get_acpi():
            return
        self._redefine(self._change_features_helper, "acpi", do_enable)

    def define_apic(self, do_enable):
        if do_enable == self.get_apic():
            return
        self._redefine(self._change_features_helper, "apic", do_enable)

    def define_clock(self, newclock):
        if newclock == self.get_clock():
            return

        def change_clock(doc, ctx, newclock):
            clock_node = ctx.xpathEval("/domain/clock")
            clock_node = (clock_node and clock_node[0] or None)

            if clock_node:
                clock_node.setProp("offset", newclock)

            return doc.serialize()

        return self._redefine(util.xml_parse_wrapper, change_clock, newclock)

    def define_description(self, newvalue):
        newvalue = vutil.xml_escape(newvalue)
        if newvalue == self.get_description():
            return

        def change_desc(doc, ctx, newdesc):
            desc_node = ctx.xpathEval("/domain/description")
            desc_node = (desc_node and desc_node[0] or None)
            dom_node = ctx.xpathEval("/domain")[0]

            if newdesc:
                if not desc_node:
                    desc_node = dom_node.newChild(None, "description", None)

                desc_node.setContent(newdesc)

            elif desc_node:
                desc_node.unlinkNode()
                desc_node.freeNode()

            return doc.serialize()

        return self._redefine(util.xml_parse_wrapper, change_desc, newvalue)

    def _change_disk_param(self, doc, ctx, dev_id_info, node_name, newvalue):
        disk_node = self._get_device_xml_nodes(ctx, "disk", dev_id_info)[0]

        found_node = None
        for child in disk_node.children:
            if child.name == node_name:
                found_node = child
                break
            child = child.next

        if bool(found_node) != newvalue:
            if not newvalue:
                found_node.unlinkNode()
                found_node.freeNode()
            else:
                disk_node.newChild(None, node_name, None)

        return doc.serialize()

    # Disk properties
    def define_disk_readonly(self, dev_id_info, do_readonly):
        if not self._check_device_is_present("disk", dev_id_info):
            return

        return self._redefine(util.xml_parse_wrapper, self._change_disk_param,
                             dev_id_info, "readonly", do_readonly)

    def define_disk_shareable(self, dev_id_info, do_shareable):
        if not self._check_device_is_present("disk", dev_id_info):
            return

        return self._redefine(util.xml_parse_wrapper, self._change_disk_param,
                             dev_id_info, "shareable", do_shareable)

    # Network properties
    def define_network_model(self, dev_id_info, newmodel):
        devtype = "interface"
        if not self._check_device_is_present(devtype, dev_id_info):
            return

        def change_model(doc, ctx):
            dev_node = self._get_device_xml_nodes(ctx, devtype, dev_id_info)[0]
            model_node = dev_node.xpathEval("./model")
            model_node = model_node and model_node[0] or None

            if not model_node:
                if newmodel:
                    model_node = dev_node.newChild(None, "model", None)

            if newmodel:
                model_node.setProp("type", newmodel)
            else:
                model_node.unlinkNode()
                model_node.freeNode()

            return doc.serialize()

        return self._redefine(util.xml_parse_wrapper, change_model)

    # Sound properties
    def define_sound_model(self, dev_id_info, newmodel):
        devtype = "sound"
        if not self._check_device_is_present(devtype, dev_id_info):
            return

        def change_model(doc, ctx):
            dev_node = self._get_device_xml_nodes(ctx, devtype, dev_id_info)[0]
            dev_node.setProp("model", newmodel)

            return doc.serialize()

        return self._redefine(util.xml_parse_wrapper, change_model)

    # Video properties
    def define_video_model(self, dev_id_info, newmodel):
        if not self._check_device_is_present("video", dev_id_info):
            return

        def change_model(doc, ctx, dev_id_info, newmodel):
            vid_node = self._get_device_xml_nodes(ctx, "video",
                                                  dev_id_info)[0]

            model_node = vid_node.xpathEval("./model")[0]
            model_node.setProp("type", newmodel)

            return doc.serialize()

        return self._redefine(util.xml_parse_wrapper, change_model,
                              dev_id_info, newmodel)

    def define_watchdog_model(self, dev_id_info, newval):
        devtype = "watchdog"
        if not self._check_device_is_present(devtype, dev_id_info):
            return

        def change(doc, ctx):
            dev_node = self._get_device_xml_nodes(ctx, devtype, dev_id_info)[0]
            if newval:
                dev_node.setProp("model", newval)

            return doc.serialize()

        return self._redefine(util.xml_parse_wrapper, change)

    def define_watchdog_action(self, dev_id_info, newval):
        devtype = "watchdog"
        if not self._check_device_is_present(devtype, dev_id_info):
            return

        def change(doc, ctx):
            dev_node = self._get_device_xml_nodes(ctx, devtype, dev_id_info)[0]
            if newval:
                dev_node.setProp("action", newval)

            return doc.serialize()

        return self._redefine(util.xml_parse_wrapper, change)

    ########################
    # End XML Altering API #
    ########################

    def _update_start_vcpus(self, ignore, status, oldstatus):
        if oldstatus not in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                              libvirt.VIR_DOMAIN_SHUTOFF,
                              libvirt.VIR_DOMAIN_CRASHED ]:
            return

        # Want to track the startup vcpu amount, which is the
        # cap of how many VCPUs can be added
        self._startup_vcpus = None
        self.vcpu_max_count()

    def _update_status(self, status=None):
        if status == None:
            info = self.get_info()
            status = info[0]
        status = self._normalize_status(status)

        if status != self.lastStatus:
            oldstatus = self.lastStatus
            self.lastStatus = status
            util.safe_idle_add(util.idle_emit, self, "status-changed",
                               oldstatus, status)


    def tick(self, now):
        if self.connection.get_state() != self.connection.STATE_ACTIVE:
            return

        # Invalidate cached xml
        self._invalidate_xml()

        info = self.get_info()
        expected = self.config.get_stats_history_length()
        current = len(self.record)
        if current > expected:
            del self.record[expected:current]

        # Xen reports complete crap for Dom0 max memory
        # (ie MAX_LONG) so lets clamp it to the actual
        # physical RAM in machine which is the effective
        # real world limit
        # XXX need to skip this for non-Xen
        if self.get_id() == 0:
            info[1] = self.connection.host_memory_size()

        cpuTime, cpuTimeAbs, pcentCpuTime = self._sample_cpu_stats(info, now)
        pcentCurrMem, pcentMaxMem = self._sample_mem_stats(info)
        rdBytes, wrBytes = self._disk_io()
        rxBytes, txBytes = self._network_traffic()

        newStats = { "timestamp": now,
                     "cpuTime": cpuTime,
                     "cpuTimeAbs": cpuTimeAbs,
                     "cpuTimePercent": pcentCpuTime,
                     "currMem": info[2],
                     "currMemPercent": pcentCurrMem,
                     "vcpuCount": info[3],
                     "maxMem": info[1],
                     "maxMemPercent": pcentMaxMem,
                     "diskRdKB": rdBytes / 1024,
                     "diskWrKB": wrBytes / 1024,
                     "netRxKB": rxBytes / 1024,
                     "netTxKB": txBytes / 1024,
                     }

        nSamples = 5
        if nSamples > len(self.record):
            nSamples = len(self.record)

        if nSamples == 0:
            avg = ["cpuTimeAbs"]
            percent = 0
        else:
            startCpuTime = self.record[nSamples-1]["cpuTimeAbs"]
            startTimestamp = self.record[nSamples-1]["timestamp"]

            avg = ((newStats["cpuTimeAbs"] - startCpuTime) / nSamples)
            percent = ((newStats["cpuTimeAbs"] - startCpuTime) * 100.0 /
                       (((now - startTimestamp) * 1000.0 * 1000.0 * 1000.0) *
                        self.connection.host_active_processor_count()))

        newStats["cpuTimeMovingAvg"] = avg
        newStats["cpuTimeMovingAvgPercent"] = percent

        for r in [ "diskRd", "diskWr", "netRx", "netTx" ]:
            newStats[r + "Rate"] = self._get_cur_rate(r + "KB")
            self._set_max_rate(newStats, r + "Rate")

        self.record.insert(0, newStats)
        self._update_status(info[0])
        util.safe_idle_add(util.idle_emit, self, "resources-sampled")


class vmmDomainVirtinst(vmmDomainBase):
    """
    Domain object backed by a virtinst Guest object.

    Used for launching a details window for customizing a VM before install.
    """
    def __init__(self, config, connection, backend, uuid):
        vmmDomainBase.__init__(self, config, connection, backend, uuid)

    def get_name(self):
        return self._backend.name
    def get_id(self):
        return -1
    def status(self):
        return libvirt.VIR_DOMAIN_SHUTOFF

    def get_xml(self):
        return self._backend.get_config_xml()
    def _get_inactive_xml(self):
        return self.get_xml()

    def refresh_xml(self):
        # No caching, so no refresh needed
        return

    def get_autostart(self):
        return self._backend.autostart

    def get_memory(self):
        return int(self._backend.memory * 1024.0)
    def get_memory_percentage(self):
        return 0
    def maximum_memory(self):
        return int(self._backend.maxmemory * 1024.0)
    def maximum_memory_percentage(self):
        return 0
    def cpu_time(self):
        return 0
    def cpu_time_percentage(self):
        return 0
    def vcpu_count(self):
        return self._backend.vcpus
    def network_rx_rate(self):
        return 0
    def network_tx_rate(self):
        return 0
    def disk_read_rate(self):
        return 0
    def disk_write_rate(self):
        return 0


    # Device/XML altering implementations
    def set_autostart(self, val):
        self._backend.autostart = bool(val)
        self.emit("config-changed")

    def attach_device(self, devobj, devxml=None):
        return
    def detach_device(self, devtype, dev_id_info):
        return

    def add_device(self, devobj):
        def add_dev():
            self._backend.add_device(devobj)
        self._redefine(add_dev)
    def remove_device(self, dev_type, dev_id_info):
        dev = self._get_device_xml_object(dev_type, dev_id_info)

        def rm_dev():
            self._backend.remove_device(dev)
        self._redefine(rm_dev)

    def define_storage_media(self, dev_id_info, newpath, _type=None):
        dev = self._get_device_xml_object(VirtualDevice.VIRTUAL_DEV_DISK,
                                          dev_id_info)

        def change_path():
            dev.path = newpath
        self._redefine(change_path)
    def hotplug_storage_media(self, dev_id_info, newpath, _type=None):
        return

    def define_vcpus(self, vcpus):
        def change_vcpu():
            self._backend.vcpus = int(vcpus)
        self._redefine(change_vcpu)
    def hotplug_vcpus(self, vcpus):
        return
    def define_cpuset(self, cpuset):
        def change_cpuset():
            self._backend.cpuset = cpuset
        self._redefine(change_cpuset)

    def define_both_mem(self, memory, maxmem):
        def change_mem():
            self._backend.memory = int(int(memory) / 1024)
            self._backend.maxmemory = int(int(maxmem) / 1024)
        self._redefine(change_mem)
    def hotplug_both_mem(self, memory, maxmem):
        return

    def define_seclabel(self, model, t, label):
        def change_seclabel():
            if not model:
                self._backend.seclabel = None
                return

            seclabel = virtinst.Seclabel(self.get_connection().vmm)
            seclabel.type = t
            seclabel.model = model
            if label:
                seclabel.label = label

            self._backend.seclabel = seclabel

        self._redefine(change_seclabel)

    def set_boot_device(self, boot_list):
        if not boot_list or boot_list == self.get_boot_device():
            return

        raise RuntimeError("Boot device is determined by the install media.")

    def define_acpi(self, newvalue):
        def change_acpi():
            self._backend.features["acpi"] = bool(newvalue)
        self._redefine(change_acpi)
    def define_apic(self, newvalue):
        def change_apic():
            self._backend.features["apic"] = bool(newvalue)
        self._redefine(change_apic)

    def define_clock(self, newvalue):
        def change_clock():
            self._backend.clock.offset = newvalue
        self._redefine(change_clock)

    def define_description(self, newvalue):
        def change_desc():
            self._backend.description = newvalue
        self._redefine(change_desc)

    def define_disk_readonly(self, dev_id_info, do_readonly):
        dev = self._get_device_xml_object(VirtualDevice.VIRTUAL_DEV_DISK,
                                          dev_id_info)

        def change_readonly():
            dev.read_only = do_readonly
        self._redefine(change_readonly)
    def define_disk_shareable(self, dev_id_info, do_shareable):
        dev = self._get_device_xml_object(VirtualDevice.VIRTUAL_DEV_DISK,
                                          dev_id_info)

        def change_shareable():
            dev.shareable = do_shareable
        self._redefine(change_shareable)

    def define_network_model(self, dev_id_info, newmodel):
        dev = self._get_device_xml_object(VirtualDevice.VIRTUAL_DEV_NET,
                                          dev_id_info)
        def change_model():
            dev.model = newmodel
        self._redefine(change_model)

    def define_sound_model(self, dev_id_info, newmodel):
        dev = self._get_device_xml_object(VirtualDevice.VIRTUAL_DEV_AUDIO,
                                          dev_id_info)
        def change_model():
            dev.model = newmodel
        self._redefine(change_model)

    def define_video_model(self, dev_id_info, newmodel):
        dev = self._get_device_xml_object(VirtualDevice.VIRTUAL_DEV_VIDEO,
                                          dev_id_info)

        def change_video_model():
            dev.model_type = newmodel
        self._redefine(change_video_model)

    def define_watchdog_model(self, dev_id_info, newval):
        devtype = VirtualDevice.VIRTUAL_DEV_WATCHDOG
        dev = self._get_device_xml_object(devtype, dev_id_info)
        def change():
            dev.model = newval

        self._redefine(change)

    def define_watchdog_action(self, dev_id_info, newval):
        devtype = VirtualDevice.VIRTUAL_DEV_WATCHDOG
        dev = self._get_device_xml_object(devtype, dev_id_info)
        def change():
            dev.action = newval

        self._redefine(change)

    # Helper functions
    def _redefine(self, alter_func):
        origxml = self.get_xml()

        # Make change
        alter_func()

        newxml = self.get_xml()

        if origxml == newxml:
            logging.debug("Redefinition request XML was no different,"
                          " redefining anyways")
        else:
            diff = "".join(difflib.unified_diff(origxml.splitlines(1),
                                                newxml.splitlines(1),
                                                fromfile="Original XML",
                                                tofile="New XML"))
            logging.debug("Redefining '%s' with XML diff:\n%s",
                          self.get_name(), diff)

        self.emit("config-changed")

    def _get_device_xml_object(self, dev_type, dev_id_info):
        """
        Find the virtinst device for the passed id info
        """
        def device_iter(try_func):
            devs = self._backend.get_devices(dev_type)
            for dev in devs:
                if try_func(dev):
                    return dev

        def count_func(count):
            devs = self._backend.get_devices(dev_type)
            tmpcount = -1
            for dev in devs:
                tmpcount += 1
                if count == tmpcount:
                    return dev
            return None

        found_func = None
        count = None

        if dev_type == VirtualDevice.VIRTUAL_DEV_NET:
            found_func = (lambda x: x.macaddr == dev_id_info)

        elif dev_type == VirtualDevice.VIRTUAL_DEV_DISK:
            found_func = (lambda x: x.target == dev_id_info)

        elif dev_type == VirtualDevice.VIRTUAL_DEV_INPUT:
            found_func = (lambda x: (x.type == dev_id_info[0] and
                                     x.bus  == dev_id_info[1]))

        elif dev_type == VirtualDevice.VIRTUAL_DEV_GRAPHICS:
            count = int(dev_id_info)

        elif dev_type == VirtualDevice.VIRTUAL_DEV_AUDIO:
            count = int(dev_id_info)

        elif (dev_type == VirtualDevice.VIRTUAL_DEV_PARALLEL or
              dev_type == VirtualDevice.VIRTUAL_DEV_SERIAL or
              dev_type == VirtualDevice.VIRTUAL_DEV_CONSOLE):
            count = int(dev_id_info)

        elif dev_type == VirtualDevice.VIRTUAL_DEV_HOSTDEV:
            count = int(dev_id_info)

        elif dev_type == VirtualDevice.VIRTUAL_DEV_VIDEO:
            count = int(dev_id_info)

        elif dev_type == VirtualDevice.VIRTUAL_DEV_WATCHDOG:
            count = int(dev_id_info)

        else:
            raise RuntimeError(_("Unknown device type '%s'") % dev_type)

        if count != None:
            # We are looking up devices by a simple index
            found_dev = count_func(count)
        else:
            found_dev = device_iter(found_func)

        if not found_dev:
            raise RuntimeError(_("Did not find selected device."))

        return found_dev

gobject.type_register(vmmDomainVirtinst)
gobject.type_register(vmmDomainBase)
gobject.type_register(vmmDomain)
