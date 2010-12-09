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

import virtinst
from virtManager import util
import virtinst.util as vutil
import virtinst.support as support

from virtManager.libvirtobject import vmmLibvirtObject

def compare_device(origdev, newdev, idx):
    devprops = {
        "disk"      : ["target", "bus"],
        "interface" : ["macaddr", "vmmindex"],
        "input"     : ["bus", "type", "vmmindex"],
        "sound"     : ["model", "vmmindex"],
        "video"     : ["model_type", "vmmindex"],
        "watchdog"  : ["vmmindex"],
        "hostdev"   : ["vendor", "product", "bus", "device",
                       "type", "function", "domain", "slot", "managed"],
        "serial"    : ["char_type", "target_port"],
        "parallel"  : ["char_type", "target_port"],
        "console"   : ["char_type", "target_type", "target_port"],
        "graphics"  : ["type", "vmmindex"],
    }

    if id(origdev) == id(newdev):
        return True

    if type(origdev) is not type(newdev):
        return False

    for devprop in devprops[origdev.virtual_device_type]:
        origval = getattr(origdev, devprop)
        if devprop == "vmmindex":
            newval = idx
        else:
            newval = getattr(newdev, devprop)

        if origval != newval:
            return False

    return True

def find_device(guest, origdev):
    devlist = guest.get_devices(origdev.virtual_device_type)
    for idx in range(len(devlist)):
        dev = devlist[idx]
        if compare_device(origdev, dev, idx):
            return dev

    return None

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

    def __init__(self, connection, backend, uuid):
        vmmLibvirtObject.__init__(self, connection)

        self._backend = backend
        self.uuid = uuid
        self.cloning = False

        self.record = []
        self.maxRecord = {
            "diskRdRate" : 10.0,
            "diskWrRate" : 10.0,
            "netTxRate"  : 10.0,
            "netRxRate"  : 10.0,
        }

        self._install_abort = False
        self._startup_vcpus = None

        self.managedsave_supported = False

        self._guest_to_define = None

        self._network_traffic = None
        self._stats_net_supported = True
        self._stats_net_skip = []

        self._disk_io = None
        self._stats_disk_supported = True
        self._stats_disk_skip = []

    # Info accessors
    def get_name(self):
        raise NotImplementedError()
    def get_id(self):
        raise NotImplementedError()
    def status(self):
        raise NotImplementedError()

    def get_memory_percentage(self):
        raise NotImplementedError()
    def maximum_memory_percentage(self):
        raise NotImplementedError()
    def cpu_time(self):
        raise NotImplementedError()
    def cpu_time_percentage(self):
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

    def get_cloning(self):
        return self.cloning
    def set_cloning(self, val):
        self.cloning = bool(val)

    # If manual shutdown or destroy specified, make sure we don't continue
    # install process
    def set_install_abort(self, val):
        self._install_abort = bool(val)
    def get_install_abort(self):
        return bool(self._install_abort)

    # Device/XML hotplug API
    def set_autostart(self, val):
        raise NotImplementedError()

    def attach_device(self, devobj):
        raise NotImplementedError()
    def detach_device(self, devobj):
        raise NotImplementedError()

    def hotplug_storage_media(self, devobj, newpath):
        raise NotImplementedError()

    def hotplug_vcpus(self, vcpus):
        raise NotImplementedError()

    def hotplug_both_mem(self, memory, maxmem):
        raise NotImplementedError()

    def _get_guest(self, inactive=False, refresh_if_necc=True):
        raise NotImplementedError()

    def _invalidate_xml(self):
        vmmLibvirtObject._invalidate_xml(self)
        self._guest_to_define = None

    def _get_guest_to_define(self):
        if not self._guest_to_define:
            self._guest_to_define = self._get_guest(inactive=True)
        return self._guest_to_define

    def _redefine_guest(self, cb):
        guest = self._get_guest_to_define()
        return cb(guest)

    def _redefine_device(self, cb, origdev):
        defguest = self._get_guest_to_define()
        dev = find_device(defguest, origdev)
        if dev:
            return cb(dev)

        # If we are removing multiple dev from an active VM, a double
        # attempt may result in a lookup failure. If device is present
        # in the active XML, assume all is good.
        if find_device(self._get_guest(), origdev):
            return

        raise RuntimeError(_("Could not find specified device in the "
                             "inactive VM configuration: %s") % repr(origdev))

    def redefine_cached(self):
        if not self._guest_to_define:
            logging.debug("No cached XML to define, skipping.")
            return

        guest = self._get_guest_to_define()
        xml = guest.get_xml_config(install=False)
        self._redefine_xml(xml)

    # virtinst.Guest XML persistent change Impls
    def add_device(self, devobj):
        """
        Redefine guest with appended device XML 'devxml'
        """
        def change(guest):
            guest.add_device(devobj)
        ret = self._redefine_guest(change)
        self.redefine_cached()
        return ret

    def remove_device(self, devobj):
        """
        Remove passed device from the inactive guest XML
        """
        # HACK: If serial and console are both present, they both need
        # to be removed at the same time
        con = None
        if hasattr(devobj, "virtmanager_console_dup"):
            con = getattr(devobj, "virtmanager_console_dup")

        def change(guest):
            def rmdev(editdev):
                if con:
                    rmcon = find_device(guest, con)
                    if rmcon:
                        guest.remove_device(rmcon)

                guest.remove_device(editdev)
            return self._redefine_device(rmdev, devobj)

        ret = self._redefine_guest(change)
        self.redefine_cached()
        return ret

    def define_vcpus(self, vcpus):
        def change(guest):
            guest.vcpus = int(vcpus)
        return self._redefine_guest(change)
    def define_cpuset(self, cpuset):
        def change(guest):
            guest.cpuset = cpuset
        return self._redefine_guest(change)

    def define_both_mem(self, memory, maxmem):
        def change(guest):
            guest.memory = int(int(memory) / 1024)
            guest.maxmemory = int(int(maxmem) / 1024)
        return self._redefine_guest(change)

    def define_seclabel(self, model, t, label):
        def change(guest):
            seclabel = guest.seclabel
            seclabel.model = model or None
            if not model:
                return

            seclabel.type = t
            if label:
                seclabel.label = label

        return self._redefine_guest(change)

    def define_acpi(self, newvalue):
        def change(guest):
            guest.features["acpi"] = bool(newvalue)
        return self._redefine_guest(change)
    def define_apic(self, newvalue):
        def change(guest):
            guest.features["apic"] = bool(newvalue)
        return self._redefine_guest(change)

    def define_clock(self, newvalue):
        def change(guest):
            guest.clock.offset = newvalue
        return self._redefine_guest(change)

    def define_description(self, newvalue):
        def change(guest):
            guest.description = newvalue or None
        return self._redefine_guest(change)

    def set_boot_device(self, boot_list):
        def change(guest):
            guest.installer.bootconfig.bootorder = boot_list
        return self._redefine_guest(change)

    # virtinst.VirtualDevice XML persistent change Impls
    def define_storage_media(self, devobj, newpath):
        def change(editdev):
            editdev.path = newpath
        return self._redefine_device(change, devobj)
    def define_disk_readonly(self, devobj, do_readonly):
        def change(editdev):
            editdev.read_only = do_readonly
        return self._redefine_device(change, devobj)
    def define_disk_shareable(self, devobj, do_shareable):
        def change(editdev):
            editdev.shareable = do_shareable
        return self._redefine_device(change, devobj)
    def define_disk_cache(self, devobj, new_cache):
        def change(editdev):
            editdev.driver_cache = new_cache or None
        return self._redefine_device(change, devobj)

    def define_network_model(self, devobj, newmodel):
        def change(editdev):
            editdev.model = newmodel
        return self._redefine_device(change, devobj)

    def define_sound_model(self, devobj, newmodel):
        def change(editdev):
            editdev.model = newmodel
        return self._redefine_device(change, devobj)

    def define_video_model(self, devobj, newmodel):
        def change(editdev):
            editdev.model_type = newmodel
        return self._redefine_device(change, devobj)

    def define_watchdog_model(self, devobj, newval):
        def change(editdev):
            editdev.model = newval
        return self._redefine_device(change, devobj)
    def define_watchdog_action(self, devobj, newval):
        def change(editdev):
            editdev.action = newval
        return self._redefine_device(change, devobj)

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

    def hasSavedImage(self):
        return False

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

    def get_memory(self):
        return int(vutil.get_xml_path(self.get_xml(), "/domain/currentMemory"))

    def maximum_memory(self):
        return int(vutil.get_xml_path(self.get_xml(), "/domain/memory"))

    def vcpu_count(self):
        return int(vutil.get_xml_path(self.get_xml(), "/domain/vcpu"))

    def vcpu_max_count(self):
        if self._startup_vcpus == None:
            self._startup_vcpus = int(vutil.get_xml_path(self.get_xml(),
                                      "/domain/vcpu"))
        return int(self._startup_vcpus)

    def vcpu_pinning(self):
        cpuset = vutil.get_xml_path(self.get_xml(), "/domain/vcpu/@cpuset")
        # We need to set it to empty string not to show None in the entry
        if cpuset is None:
            cpuset = ""
        return cpuset

    def get_boot_device(self):
        xml = self.get_xml()

        def get_boot_xml(doc, ctx):
            ignore = doc
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
        devs = self.get_char_devices()
        devlist = []

        serials  = filter(lambda x: x.virtual_device_type == "serial", devs)
        consoles = filter(lambda x: x.virtual_device_type == "console", devs)

        for dev in serials:
            devlist.append(["Serial %s" % (dev.index + 1), dev.char_type,
                            dev.source_path, dev.index])

        for dev in consoles:
            devlist.append(["Text Console %s" % (dev.index + 1),
                            dev.char_type, dev.source_path, dev.index])

        return devlist

    def get_graphics_console(self):
        gdevs = self.get_graphics_devices()
        connhost = self.connection.get_uri_hostname()
        transport, username = self.connection.get_transport()
        vncport = None
        gport = None
        gtype = None
        if gdevs:
            gport = gdevs[0].port
            gtype = gdevs[0].type

        if gtype == 'vnc':
            vncport = int(gport)

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
        if gtype == 'vnc':
            vncuri = str(gtype) + "://"
            if username:
                vncuri = vncuri + str(username) + '@'
            vncuri += str(connhost) + ":" + str(vncport)

        return [gtype, connhost, vncport, transport, username, connport,
                vncuri]


    def _build_device_list(self, device_type,
                           refresh_if_necc=True, inactive=False):
        guest = self._get_guest(refresh_if_necc=refresh_if_necc,
                                inactive=inactive)
        devs = guest.get_devices(device_type)

        count = 0
        for dev in devs:
            dev.vmmindex = count
            count += 1

        return devs

    def get_network_devices(self, refresh_if_necc=True):
        return self._build_device_list("interface", refresh_if_necc)
    def get_video_devices(self):
        return self._build_device_list("video")
    def get_hostdev_devices(self):
        return self._build_device_list("hostdev")
    def get_watchdog_devices(self):
        return self._build_device_list("watchdog")
    def get_input_devices(self):
        return self._build_device_list("input")
    def get_graphics_devices(self):
        return self._build_device_list("graphics")
    def get_sound_devices(self):
        return self._build_device_list("sound")

    def get_disk_devices(self, refresh_if_necc=True, inactive=False):
        devs = self._build_device_list("disk", refresh_if_necc, inactive)

        # Iterate through all disks and calculate what number they are
        # HACK: We are making a variable in VirtualDisk to store the index
        idx_mapping = {}
        for dev in devs:
            devtype = dev.device
            bus = dev.bus
            key = devtype + (bus or "")

            if not idx_mapping.has_key(key):
                idx_mapping[key] = 1

            dev.disk_bus_index = idx_mapping[key]
            idx_mapping[key] += 1

        return devs

    def get_char_devices(self):
        devs = []
        serials     = self._build_device_list("serial")
        parallels   = self._build_device_list("parallel")
        consoles    = self._build_device_list("console")

        for devicelist in [serials, parallels, consoles]:
            devs.extend(devicelist)

        # Don't display <console> if it's just a duplicate of <serial>
        if (len(consoles) > 0 and len(serials) > 0):
            con = consoles[0]
            ser = serials[0]

            if (con.char_type == ser.char_type and
                con.target_type is None or con.target_type == "serial"):
                ser.virtmanager_console_dup = con
                devs.remove(con)

        return devs

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

        if pcentCurrMem > 100:
            pcentCurrMem = 100.0
        if pcentMaxMem > 100:
            pcentMaxMem = 100.0

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

    def _get_cur_rate(self, what):
        if len(self.record) > 1:
            ret = (float(self.record[0][what] -
                         self.record[1][what]) /
                   float(self.record[0]["timestamp"] -
                         self.record[1]["timestamp"]))
        else:
            ret = 0.0
        return max(ret, 0, 0) # avoid negative values at poweroff

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
        d = map(lambda x, y: (x + y) / 2, data[0:end], data[end:end * 2])
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

    def __init__(self, connection, backend, uuid):
        vmmDomainBase.__init__(self, connection, backend, uuid)

        self.lastStatus = libvirt.VIR_DOMAIN_SHUTOFF

        self.config.on_stats_enable_net_poll_changed(
                                            self.toggle_sample_network_traffic)
        self.config.on_stats_enable_disk_poll_changed(
                                            self.toggle_sample_disk_io)

        self.getvcpus_supported = support.check_domain_support(self._backend,
                                            support.SUPPORT_DOMAIN_GETVCPUS)
        self.managedsave_supported = self.connection.get_dom_managedsave_supported(self._backend)
        self.getjobinfo_supported = support.check_domain_support(self._backend,
                                            support.SUPPORT_DOMAIN_JOB_INFO)

        self.toggle_sample_network_traffic()
        self.toggle_sample_disk_io()

        self.reboot_listener = None
        self._guest = None
        self._reparse_xml()

        # Determine available XML flags (older libvirt versions will error
        # out if passed SECURE_XML, INACTIVE_XML, etc)
        (self._inactive_xml_flags,
         self._active_xml_flags) = self.connection.get_dom_flags(
                                                            self._backend)

        # Hook up our own status listeners
        self._update_status()
        self.connect("status-changed", self._update_start_vcpus)
        self.connect("config-changed", self._reparse_xml)

    ##########################
    # Internal virDomain API #
    ##########################

    def _define(self, newxml):
        self.get_connection().define_domain(newxml)

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)

    def support_downtime(self):
        return support.check_domain_support(self._backend,
                        support.SUPPORT_DOMAIN_MIGRATE_DOWNTIME)

    def get_info(self):
        return self._backend.info()

    def status(self):
        return self.lastStatus

    def _get_record_helper(self, record_name):
        if len(self.record) == 0:
            return 0
        return self.record[0][record_name]

    def get_memory_percentage(self):
        return self._get_record_helper("currMemPercent")
    def maximum_memory_percentage(self):
        return self._get_record_helper("maxMemPercent")
    def cpu_time(self):
        return self._get_record_helper("cpuTime")
    def cpu_time_percentage(self):
        return self._get_record_helper("cpuTimePercent")
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
        self.set_install_abort(True)
        self._unregister_reboot_listener()
        self._backend.shutdown()
        self._update_status()

    def reboot(self):
        self.set_install_abort(True)
        self._backend.reboot(0)
        self._update_status()

    def startup(self):
        if self.get_cloning():
            raise RuntimeError(_("Cannot start guest while cloning "
                                 "operation in progress"))
        self._backend.create()
        self._update_status()

    def suspend(self):
        self._backend.suspend()
        self._update_status()

    def delete(self):
        self._backend.undefine()

    def resume(self):
        if self.get_cloning():
            raise RuntimeError(_("Cannot resume guest while cloning "
                                 "operation in progress"))

        self._backend.resume()
        self._update_status()

    def hasSavedImage(self):
        if not self.managedsave_supported:
            return False
        return self._backend.hasManagedSaveImage(0)

    def save(self, filename=None):
        self.set_install_abort(True)
        if not self.managedsave_supported:
            self._backend.save(filename)
        else:
            self._backend.managedSave(0)
        self._update_status()

    def destroy(self):
        self.set_install_abort(True)
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

    def abort_job(self):
        self._backend.abortJob()

    def migrate_set_max_downtime(self, max_downtime, flag=0):
        self._backend.migrateSetMaxDowntime(max_downtime, flag)

    def migrate(self, destconn, interface=None, rate=0,
                live=False, secure=False):
        newname = None

        flags = 0
        if self.status() == libvirt.VIR_DOMAIN_RUNNING and live:
            flags |= libvirt.VIR_MIGRATE_LIVE

        if secure:
            flags |= libvirt.VIR_MIGRATE_PEER2PEER
            flags |= libvirt.VIR_MIGRATE_TUNNELLED

        newxml = self.get_xml(inactive=True)

        logging.debug("Migrating: conn=%s flags=%s dname=%s uri=%s rate=%s" %
                      (destconn.vmm, flags, newname, interface, rate))
        self._backend.migrate(destconn.vmm, flags, newname, interface, rate)
        destconn.define_domain(newxml)

    # Genertc backend APIs
    def get_name(self):
        return self._backend.name()
    def get_id(self):
        return self._backend.ID()

    # Hotplug routines
    def attach_device(self, devobj):
        """
        Hotplug device to running guest
        """
        if not self.is_active():
            return

        devxml = devobj.get_xml_config()
        self._backend.attachDevice(devxml)

    def detach_device(self, devobj):
        """
        Hotunplug device from running guest
        """
        if not self.is_active():
            return

        xml = devobj.get_xml_config()
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

    def hotplug_storage_media(self, devobj, newpath):
        devobj.path = newpath
        self.attach_device(devobj)

    ####################
    # End internal API #
    ####################

    ###########################
    # XML/Config Altering API #
    ###########################

    def _get_domain_xml(self, inactive=False, refresh_if_necc=True):
        return vmmLibvirtObject.get_xml(self,
                                        inactive=inactive,
                                        refresh_if_necc=refresh_if_necc)

    def get_xml(self, inactive=False, refresh_if_necc=True):
        guest = self._get_guest(inactive=inactive,
                                refresh_if_necc=refresh_if_necc)
        return guest.get_xml_config(install=False)

    def _get_guest(self, inactive=False, refresh_if_necc=True):
        xml = self._get_domain_xml(inactive, refresh_if_necc)

        if self.is_active() or inactive:
            # We don't cache guest for 'inactive' XML while guest is running,
            # so just return it
            return self._build_guest(xml)

        return self._guest

    def _build_guest(self, xml):
        return virtinst.Guest(connection=self.connection.vmm,
                              parsexml=xml,
                              caps=self.connection.get_capabilities())

    def _reparse_xml(self, ignore=None):
        self._guest = self._build_guest(self._get_domain_xml())

    ########################
    # End XML Altering API #
    ########################

    def _update_start_vcpus(self, ignore, oldstatus, status):
        ignore = status

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

            # Send 'config-changed' before a status-update, so users
            # are operating with fresh XML
            self.refresh_xml()

            util.safe_idle_add(util.idle_emit, self, "status-changed",
                               oldstatus, status)

    ##################
    # Stats handling #
    ##################

    def toggle_sample_network_traffic(self, ignore1=None, ignore2=None,
                                      ignore3=None, ignore4=None):
        if not self.config.get_stats_enable_net_poll():
            self._network_traffic = lambda: (0, 0)
            return

        if len(self.record) > 1:
            # resample the current value before calculating the rate in
            # self.tick() otherwise we'd get a huge spike when switching
            # from 0 to bytes_transfered_so_far
            rxBytes, txBytes = self._sample_network_traffic()
            self.record[0]["netRxKB"] = rxBytes / 1024
            self.record[0]["netTxKB"] = txBytes / 1024
        self._network_traffic = self._sample_network_traffic

    def toggle_sample_disk_io(self, ignore1=None, ignore2=None,
                              ignore3=None, ignore4=None):
        if not self.config.get_stats_enable_disk_poll():
            self._disk_io = lambda: (0, 0)
            return

        if len(self.record) > 1:
            # resample the current value before calculating the rate in
            # self.tick() otherwise we'd get a huge spike when switching
            # from 0 to bytes_transfered_so_far
            rdBytes, wrBytes = self._sample_disk_io()
            self.record[0]["diskRdKB"] = rdBytes / 1024
            self.record[0]["diskWrKB"] = wrBytes / 1024
        self._disk_io = self._sample_disk_io


    def _sample_network_traffic(self):
        rx = 0
        tx = 0
        if not self._stats_net_supported or not self.is_active():
            return rx, tx

        for netdev in self.get_network_devices(refresh_if_necc=False):
            dev = netdev.target_dev
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

    def _sample_disk_io(self):
        rd = 0
        wr = 0
        if not self._stats_disk_supported or not self.is_active():
            return rd, wr

        for disk in self.get_disk_devices(refresh_if_necc=False):
            dev = disk.target
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
                     "currMemPercent": pcentCurrMem,
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
    def __init__(self, connection, backend, uuid):
        vmmDomainBase.__init__(self, connection, backend, uuid)

        self._orig_xml = None

    def get_name(self):
        return self._backend.name
    def get_id(self):
        return -1
    def status(self):
        return libvirt.VIR_DOMAIN_SHUTOFF

    def get_xml(self, inactive=False, refresh_if_necc=True):
        ignore = inactive
        ignore = refresh_if_necc

        xml = self._backend.get_xml_config(install=False)
        if not self._orig_xml:
            self._orig_xml = xml
        return xml

    # Internal XML implementations
    def _get_guest(self, inactive=False, refresh_if_necc=True):
        # Make sure XML is up2date
        self.get_xml()
        return self._backend

    def _define(self, newxml):
        ignore = newxml
        self._orig_xml = None
        util.safe_idle_add(util.idle_emit, self, "config-changed")

    def _redefine_xml(self, newxml):
        # We need to cache origxml in order to have something to diff against
        origxml = self._orig_xml or self.get_xml(inactive=True)
        return self._redefine_helper(origxml, newxml)

    def refresh_xml(self, forcesignal=False):
        # No caching, so no refresh needed
        return

    def get_autostart(self):
        return self._backend.autostart

    # Stats stubs
    def get_memory_percentage(self):
        return 0
    def maximum_memory_percentage(self):
        return 0
    def cpu_time(self):
        return 0
    def cpu_time_percentage(self):
        return 0
    def network_rx_rate(self):
        return 0
    def network_tx_rate(self):
        return 0
    def disk_read_rate(self):
        return 0
    def disk_write_rate(self):
        return 0

    # Device/XML hotplug implementations
    def set_autostart(self, val):
        self._backend.autostart = bool(val)
        util.safe_idle_add(util.idle_emit, self, "config-changed")

    def attach_device(self, devobj):
        return
    def detach_device(self, devobj):
        return
    def hotplug_storage_media(self, devobj, newpath):
        return
    def hotplug_vcpus(self, vcpus):
        raise NotImplementedError()
    def hotplug_both_mem(self, memory, maxmem):
        raise NotImplementedError()

vmmLibvirtObject.type_register(vmmDomainVirtinst)
vmmLibvirtObject.type_register(vmmDomainBase)
vmmLibvirtObject.type_register(vmmDomain)
