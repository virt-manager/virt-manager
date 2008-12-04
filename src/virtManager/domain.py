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
import libxml2
import os
import logging
import virtinst.util as util

class vmmDomain(gobject.GObject):
    __gsignals__ = {
        "status-changed": (gobject.SIGNAL_RUN_FIRST,
                           gobject.TYPE_NONE,
                           [int]),
        "resources-sampled": (gobject.SIGNAL_RUN_FIRST,
                              gobject.TYPE_NONE,
                              []),
        }

    def __init__(self, config, connection, vm, uuid):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.vm = vm
        self.uuid = uuid
        self.lastStatus = None
        self.record = []
        self.maxRecord = { "diskRdRate" : 10.0,
                           "diskWrRate" : 10.0,
                           "netTxRate"  : 10.0,
                           "netRxRate"  : 10.0,
                         }

        self._update_status()
        self.xml = None

        self._network_traffic = None
        self.config.on_vmlist_network_traffic_visible_changed(self.toggle_sample_network_traffic)
        self.toggle_sample_network_traffic()

        self._disk_io = None
        self.config.on_vmlist_disk_io_visible_changed(self.toggle_sample_disk_io)
        self.toggle_sample_disk_io()

    def get_xml(self):
        if self.xml is None:
            self.xml = self.vm.XMLDesc(0)
        return self.xml

    def release_handle(self):
        del(self.vm)
        self.vm = None

    def set_handle(self, vm):
        self.vm = vm

    def is_active(self):
        if self.vm.ID() == -1:
            return False
        else:
            return True

    def get_connection(self):
        return self.connection

    def get_id(self):
        return self.vm.ID()

    def get_id_pretty(self):
        i = self.get_id()
        if i < 0:
            return "-"
        return str(i)

    def get_name(self):
        return self.vm.name()

    def get_uuid(self):
        return self.uuid

    def is_read_only(self):
        if self.connection.is_read_only():
            return True
        if self.is_management_domain():
            return True
        return False

    def is_management_domain(self):
        if self.vm.ID() == 0:
            return True
        return False

    def is_hvm(self):
        os_type = util.get_xml_path(self.get_xml(), "/domain/os/type")
        # XXX libvirt bug - doesn't work for inactive guests
        #os_type = self.vm.OSType()
        logging.debug("OS Type: %s" % os_type)
        if os_type == "hvm":
            return True
        return False

    def get_type(self):
        return util.get_xml_path(self.get_xml(), "/domain/@type")

    def is_vcpu_hotplug_capable(self):
        # Read only connections aren't allowed to change it
        if self.connection.is_read_only():
            return False
        # Running paravirt guests can change it, or any inactive guest
        if self.vm.OSType() == "linux" \
           or self.status() not in [libvirt.VIR_DOMAIN_RUNNING,\
                                    libvirt.VIR_DOMAIN_PAUSED]:
            return True
        # Everyone else is out of luck
        return False

    def is_memory_hotplug_capable(self):
        # Read only connections aren't allowed to change it
        if self.connection.is_read_only():
            return False
        # Running paravirt guests can change it, or any inactive guest
        if self.vm.OSType() == "linux" \
           or self.status() not in [libvirt.VIR_DOMAIN_RUNNING,\
                                    libvirt.VIR_DOMAIN_PAUSED]:
            return True
        # Everyone else is out of luck
        return False

    def _normalize_status(self, status):
        if status == libvirt.VIR_DOMAIN_NOSTATE:
            return libvirt.VIR_DOMAIN_RUNNING
        elif status == libvirt.VIR_DOMAIN_BLOCKED:
            return libvirt.VIR_DOMAIN_RUNNING
        return status

    def _update_status(self, status=None):
        if status == None:
            info = self.vm.info()
            status = info[0]
        status = self._normalize_status(status)

        if status != self.lastStatus:
            self.lastStatus = status
            self.emit("status-changed", status)

    def _sample_network_traffic_dummy(self):
        return 0, 0

    def _sample_network_traffic(self):
        rx = 0
        tx = 0
        for netdev in self.get_network_devices():
            try:
                io = self.vm.interfaceStats(netdev[2])
                if io:
                    rx += io[0]
                    tx += io[4]
            except libvirt.libvirtError, err:
                logging.error("Error reading interface stats %s" % err)
        return rx, tx

    def _sample_disk_io_dummy(self):
        return 0, 0

    def _sample_disk_io(self):
        rd = 0
        wr = 0
        for disk in self.get_disk_devices():
            try:
                io = self.vm.blockStats(disk[3])
                if io:
                    rd += io[1]
                    wr += io[3]
            except libvirt.libvirtError, err:
                logging.error("Error reading block stats %s" % err)
        return rd, wr

    def _get_cur_rate(self, what):
        if len(self.record) > 1:
            ret = float(self.record[0][what] - self.record[1][what]) / \
                      float(self.record[0]["timestamp"] - self.record[1]["timestamp"])
        else:
            ret = 0.0
        return max(ret, 0,0) # avoid negative values at poweroff

    def _set_max_rate(self, what):
        if self.record[0][what] > self.maxRecord[what]:
            self.maxRecord[what] = self.record[0][what]

    def tick(self, now):
        if self.connection.get_state() != self.connection.STATE_ACTIVE:
            return
        # Clear cached XML
        self.xml = None
        info = self.vm.info()
        expected = self.config.get_stats_history_length()
        current = len(self.record)
        if current > expected:
            del self.record[expected:current]

        prevCpuTime = 0
        prevTimestamp = 0
        if len(self.record) > 0:
            prevTimestamp = self.record[0]["timestamp"]
            prevCpuTime = self.record[0]["cpuTimeAbs"]

        cpuTime = 0
        cpuTimeAbs = 0
        pcentCpuTime = 0
        if not(info[0] in [libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED]):
            cpuTime = info[4] - prevCpuTime
            cpuTimeAbs = info[4]

            pcentCpuTime = (cpuTime) * 100.0 / ((now - prevTimestamp)*1000.0*1000.0*1000.0*self.connection.host_active_processor_count())
            # Due to timing diffs between getting wall time & getting
            # the domain's time, its possible to go a tiny bit over
            # 100% utilization. This freaks out users of the data, so
            # we hard limit it.
            if pcentCpuTime > 100.0:
                pcentCpuTime = 100.0
            # Enforce >= 0 just in case
            if pcentCpuTime < 0.0:
                pcentCpuTime = 0.0

        # Xen reports complete crap for Dom0 max memory
        # (ie MAX_LONG) so lets clamp it to the actual
        # physical RAM in machine which is the effective
        # real world limit
        # XXX need to skip this for non-Xen
        if self.get_id() == 0:
            info[1] = self.connection.host_memory_size()

        pcentCurrMem = info[2] * 100.0 / self.connection.host_memory_size()
        pcentMaxMem = info[1] * 100.0 / self.connection.host_memory_size()

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

        self.record.insert(0, newStats)
        nSamples = 5
        #nSamples = len(self.record)
        if nSamples > len(self.record):
            nSamples = len(self.record)

        startCpuTime = self.record[nSamples-1]["cpuTimeAbs"]
        startTimestamp = self.record[nSamples-1]["timestamp"]

        if startTimestamp == now:
            self.record[0]["cpuTimeMovingAvg"] = self.record[0]["cpuTimeAbs"]
            self.record[0]["cpuTimeMovingAvgPercent"] = 0
        else:
            self.record[0]["cpuTimeMovingAvg"] = (self.record[0]["cpuTimeAbs"]-startCpuTime) / nSamples
            self.record[0]["cpuTimeMovingAvgPercent"] = (self.record[0]["cpuTimeAbs"]-startCpuTime) * 100.0 / ((now-startTimestamp)*1000.0*1000.0*1000.0 * self.connection.host_active_processor_count())

        for r in [ "diskRd", "diskWr", "netRx", "netTx" ]:
            self.record[0][r + "Rate"] = self._get_cur_rate(r + "KB")
            self._set_max_rate(r + "Rate")

        self._update_status(info[0])
        self.emit("resources-sampled")


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
            return "0.00 MB"
        return self.get_memory_pretty()


    def get_memory(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["currMem"]

    def get_memory_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["currMemPercent"]

    def get_cputime(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["cpuTime"]

    def get_memory_pretty(self):
        mem = self.get_memory()
        if mem > (1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.2f MB" % (mem/1024.0)


    def maximum_memory(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["maxMem"]

    def maximum_memory_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["maxMemPercent"]

    def maximum_memory_pretty(self):
        mem = self.maximum_memory()
        if mem > (1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.2f MB" % (mem/1024.0)


    def cpu_time(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["cpuTime"]

    def cpu_time_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["cpuTimePercent"]

    def cpu_time_pretty(self):
        return "%2.2f %%" % self.cpu_time_percentage()

    def network_rx_rate(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["netRxRate"]

    def network_tx_rate(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["netTxRate"]

    def network_traffic_rate(self):
        return self.network_tx_rate() + self.network_rx_rate()

    def disk_read_rate(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["diskRdRate"]

    def disk_write_rate(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["diskWrRate"]

    def disk_io_rate(self):
        return self.disk_read_rate() + self.disk_write_rate()

    def vcpu_count(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["vcpuCount"]

    def vcpu_max_count(self):
        cpus = util.get_xml_path(self.get_xml(), "/domain/vcpu")
        return int(cpus)

    def cpu_time_vector(self):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["cpuTimePercent"]/100.0)
            else:
                vector.append(0)
        return vector

    def cpu_time_vector_limit(self, limit):
        cpudata = self.cpu_time_vector()
        if len(cpudata) > limit:
            cpudata = cpudata[0:limit]
        return cpudata

    def cpu_time_moving_avg_vector(self):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["cpuTimeMovingAvgPercent"]/100.0)
            else:
                vector.append(0)
        return vector

    def current_memory_vector(self):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["currMemPercent"]/100.0)
            else:
                vector.append(0)
        return vector

    def in_out_vector_limit(self, data, limit):
        l = len(data)/2
        end = [l, limit][l > limit]
        if l > limit:
            data = data[0:end] + data[l:l+end]
        d = map(lambda x,y: (x + y)/2, data[0:end], data[end:end*2]) 
        return d

    def network_traffic_vector(self):
        vector = []
        stats = self.record
        ceil = float(max(self.maxRecord["netRxRate"], self.maxRecord["netTxRate"]))
        for n in [ "netRxRate", "netTxRate" ]:
            for i in range(self.config.get_stats_history_length()+1):
                if i < len(stats):
                    vector.append(float(stats[i][n])/ceil)
                else:
                    vector.append(0.0)
        return vector

    def network_traffic_vector_limit(self, limit):
        return self.in_out_vector_limit(self.network_traffic_vector(), limit)

    def disk_io_vector(self):
        vector = []
        stats = self.record
        ceil = float(max(self.maxRecord["diskRdRate"], self.maxRecord["diskWrRate"]))
        for n in [ "diskRdRate", "diskWrRate" ]:
            for i in range(self.config.get_stats_history_length()+1):
                if i < len(stats):
                    vector.append(float(stats[i][n])/ceil)
                else:
                    vector.append(0.0)
        return vector

    def disk_io_vector_limit(self, limit):
        return self.in_out_vector_limit(self.disk_io_vector(), limit)

    def shutdown(self):
        self.vm.shutdown()
        self._update_status()

    def reboot(self):
        self.vm.reboot(0)
        self._update_status()

    def startup(self):
        self.vm.create()
        self._update_status()

    def suspend(self):
        self.vm.suspend()
        self._update_status()

    def delete(self):
        self.vm.undefine()

    def resume(self):
        self.vm.resume()
        self._update_status()

    def save(self, filename, ignore1=None, background=True):
        if background:
            conn = libvirt.open(self.connection.uri)
            vm = conn.lookupByID(self.get_id())
        else:
            vm = self.vm

        vm.save(filename)
        self._update_status()

    def destroy(self):
        self.vm.destroy()

    def status(self):
        return self.lastStatus

    def run_status(self):
        if self.lastStatus == libvirt.VIR_DOMAIN_RUNNING:
            return _("Running")
        elif self.lastStatus == libvirt.VIR_DOMAIN_PAUSED:
            return _("Paused")
        elif self.lastStatus == libvirt.VIR_DOMAIN_SHUTDOWN:
            return _("Shutdown")
        elif self.lastStatus == libvirt.VIR_DOMAIN_SHUTOFF:
            return _("Shutoff")
        elif self.lastStatus == libvirt.VIR_DOMAIN_CRASHED:
            return _("Crashed")
        else:
            raise RuntimeError(_("Unknown status code"))

    def run_status_icon(self):
        return self.config.get_vm_status_icon(self.status())

    def _is_serial_console_tty_accessible(self, path):
        # pty serial scheme doesn't work over remote
        if self.connection.is_remote():
            return False

        if path == None:
            return False
        return os.access(path, os.R_OK | os.W_OK)

    def get_serial_devs(self):
        def _parse_serial_consoles(ctx):
            # [ Name, device type, source path
            serial_list = []
            devs = ctx.xpathEval("/domain/devices/serial")
            for node in devs:
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

                serial_list.append([name, dev_type, source_path])

            return serial_list
        return self._parse_device_xml(_parse_serial_consoles)

    def get_graphics_console(self):
        self.xml = None
        typ = util.get_xml_path(self.get_xml(),
                                "/domain/devices/graphics/@type")
        port = None
        if typ == "vnc":
            port = util.get_xml_path(self.get_xml(),
                                     "/domain/devices/graphics[@type='vnc']/@port")
            if port is not None:
                port = int(port)

        transport, username = self.connection.get_transport()
        if transport is None:
            # Force use of 127.0.0.1, because some (broken) systems don't 
            # reliably resolve 'localhost' into 127.0.0.1, either returning
            # the public IP, or an IPv6 addr. Neither work since QEMU only
            # listens on 127.0.0.1 for VNC.
            return [typ, "127.0.0.1", port, None, None]
        else:
            return [typ, self.connection.get_hostname(), port, transport, username]


    def get_disk_devices(self):
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
                        if typ == "file":
                            srcpath = child.prop("file")
                        elif typ == "block":
                            srcpath = child.prop("dev")
                        elif typ == None:
                            typ = "-"
                    elif child.name == "target":
                        devdst = child.prop("dev")
                        bus = child.prop("bus")
                    elif child.name == "readonly":
                        readonly = True
                    elif child.name == "sharable":
                        sharable = True

                if srcpath == None:
                    if devtype == "cdrom" or devtype == "floppy":
                        srcpath = "-"
                        typ = "block"
                    else:
                        raise RuntimeError("missing source path")
                if devdst == None:
                    raise RuntimeError("missing destination device")

                disks.append([typ, srcpath, devtype, devdst, readonly, \
                              sharable, bus])

            return disks

        return self._parse_device_xml(_parse_disk_devs)

    def get_disk_xml(self, target):
        """Returns device xml in string form for passed disk target"""
        xml = self.get_xml()
        doc = None
        ctx = None
        try:
            doc = libxml2.parseDoc(xml)
            ctx = doc.xpathNewContext()
            disk_fragment = ctx.xpathEval("/domain/devices/disk[target/@dev='%s']" % target)
            if len(disk_fragment) == 0:
                raise RuntimeError("Attmpted to parse disk device %s, but %s does not exist" % (target,target))
            if len(disk_fragment) > 1:
                raise RuntimeError("Found multiple disk devices named %s. This domain's XML is malformed." % target)
            result = disk_fragment[0].serialize()
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()
        return result

    def get_network_devices(self):
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
                    nics.append([typ, source, target, devmac, model])
            return nics

        return self._parse_device_xml(_parse_network_devs)

    def get_input_devices(self):
        def _parse_input_devs(ctx):
            inputs = []
            ret = ctx.xpathEval("/domain/devices/input")

            for node in ret:
                typ = node.prop("type")
                bus = node.prop("bus")
                # XXX Replace 'None' with device model when libvirt supports
                # that
                inputs.append([typ, bus, None, typ + ":" + bus])
            return inputs

        return self._parse_device_xml(_parse_input_devs)

    def get_graphics_devices(self):
        def _parse_graphics_devs(ctx):
            graphics = []
            ret = ctx.xpathEval("/domain/devices/graphics[1]")
            for node in ret:
                typ = node.prop("type")
                if typ == "vnc":
                    listen = node.prop("listen")
                    port = node.prop("port")
                    keymap = node.prop("keymap")
                    graphics.append([typ, listen, port, typ, keymap])
                else:
                    graphics.append([typ, None, None, typ, None])
            return graphics

        return self._parse_device_xml(_parse_graphics_devs)

    def get_sound_devices(self):
        def _parse_sound_devs(ctx):
            sound = []
            ret = ctx.xpathEval("/domain/devices/sound")
            for node in ret:
                sound.append([None, None, None, node.prop("model")])
            return sound

        return self._parse_device_xml(_parse_sound_devs)

    def get_char_devices(self):
        def _parse_char_devs(ctx):
            chars = []
            devs  = []
            devs = ctx.xpathEval("/domain/devices/console")
            devs.extend(ctx.xpathEval("/domain/devices/parallel"))
            devs.extend(ctx.xpathEval("/domain/devices/serial"))

            # Since there is only one 'console' device ever in the xml
            # find its port (if present) and path
            cons_port = None
            cons_dev = None
            list_cons = True

            for node in devs:
                char_type = node.name
                dev_type = node.prop("type")
                target_port = None
                source_path = None

                for child in node.children:
                    if child.name == "target":
                        target_port = child.prop("port")
                    if child.name == "source":
                        source_path = child.prop("path")

                if not source_path:
                    source_path = node.prop("tty")

                dev = [char_type, dev_type, target_port,
                       "%s:%s" % (char_type, target_port), source_path, False]

                if node.name == "console":
                    cons_port = target_port
                    cons_dev = dev
                    continue
                elif node.name == "serial" and cons_port \
                   and target_port == cons_port:
                    # Console is just a dupe of this serial device
                    dev[5] = True
                    list_cons = False

                chars.append(dev)

            if cons_dev and list_cons:
                chars.append(cons_dev)

            return chars

        return self._parse_device_xml(_parse_char_devs)

    def _parse_device_xml(self, parse_function):
        doc = None
        ctx = None
        ret = []
        try:
            try:
                doc = libxml2.parseDoc(self.get_xml())
                ctx = doc.xpathNewContext()
                ret = parse_function(ctx)
            except Exception, e:
                raise RuntimeError(_("Error parsing domain xml: %s") % str(e))
        finally:
            if ctx:
                ctx.xpathFreeContext()
            if doc:
                doc.freeDoc()
        return ret

    def _add_xml_device(self, xml, devxml):
        """Add device 'devxml' to devices section of 'xml', return result"""
        index = xml.find("</devices>")
        return xml[0:index] + devxml + xml[index:]

    def _remove_xml_device(self, xml, devxml):
        """Remove device 'devxml' from devices section of 'xml, return
           result"""
        doc = None
        try:
            doc = libxml2.parseDoc(xml)
        except:
            return
        ctx = doc.xpathNewContext()
        try:
            dev_doc = libxml2.parseDoc(devxml)
        except:
            raise RuntimeError("Device XML would not parse")
        dev_ctx = dev_doc.xpathNewContext()
        ret = None

        try:
            dev = dev_ctx.xpathEval("//*")
            dev_type = dev[0].name
            if dev_type=="interface":
                address = dev_ctx.xpathEval("/interface/mac/@address")
                if len(address) > 0 and address[0].content != None:
                    logging.debug("The mac address appears to be %s" % address[0].content)
                    ret = ctx.xpathEval("/domain/devices/interface[mac/@address='%s']" % address[0].content)

            elif dev_type=="disk":
                path = dev_ctx.xpathEval("/disk/target/@dev")
                if len(path) > 0 and path[0].content != None:
                    logging.debug("Looking for path %s" % path[0].content)
                    ret = ctx.xpathEval("/domain/devices/disk[target/@dev='%s']" % path[0].content)

            elif dev_type=="input":
                typ = dev_ctx.xpathEval("/input/@type")
                bus = dev_ctx.xpathEval("/input/@bus")
                if (len(typ) > 0 and typ[0].content != None and
                    len(bus) > 0 and bus[0].content != None):
                    logging.debug("Looking for type %s bus %s" % (typ[0].content, bus[0].content))
                    ret = ctx.xpathEval("/domain/devices/input[@type='%s' and @bus='%s']" % (typ[0].content, bus[0].content))

            elif dev_type=="graphics":
                typ = dev_ctx.xpathEval("/graphics/@type")
                if len(typ) > 0 and typ[0].content != None:
                    logging.debug("Looking for type %s" % typ[0].content)
                    ret = ctx.xpathEval("/domain/devices/graphics[@type='%s']" % typ[0].content)

            elif dev_type == "sound":
                model = dev_ctx.xpathEval("/sound/@model")
                if len(model) > 0 and model[0].content != None:
                    logging.debug("Looking for type %s" % model[0].content)
                    ret = ctx.xpathEval("/domain/devices/sound[@model='%s']" % model[0].content)

            elif dev_type == "parallel" or dev_type == "console" or \
                 dev_type == "serial":
                port = dev_ctx.xpathEval("/%s/target/@port" % dev_type)
                if port and len(port) > 0 and port[0].content != None:
                    logging.debug("Looking for %s w/ port %s" % (dev_type,
                                                                 port))
                    ret = ctx.xpathEval("/domain/devices/%s[target/@port='%s']" % (dev_type, port[0].content))

                    # If serial and console are both present, console is
                    # probably (always?) just a dup of the 'primary' serial
                    # device. Try and find an associated console device with
                    # the same port and remove that as well, otherwise the
                    # removal doesn't go through on libvirt <= 0.4.4
                    if dev_type == "serial":
                        cons_ret = ctx.xpathEval("/domain/devices/console[target/@port='%s']" % port[0].content)
                        if cons_ret and len(cons_ret) > 0:
                            logging.debug("Also removing console device "
                                          "associated with serial dev.")
                            cons_ret[0].unlinkNode()
                            cons_ret[0].freeNode()
                        else:
                            logging.debug("No console device found associated "
                                          "with passed serial devices")

            else:
                raise RuntimeError, _("Unknown device type '%s'" % dev_type)

            # Take variable 'ret', unlink it, and define the altered xml
            if ret and len(ret) > 0:
                ret[0].unlinkNode()
                ret[0].freeNode()
                newxml = doc.serialize()
                return newxml
            else:
                logging.debug("Didn't find the specified device to remove. "
                              "Passed xml was: %s" % devxml)
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()
            if dev_doc != None:
                dev_doc.freeDoc()

    def attach_device(self, xml):
        """Hotplug device to running guest"""
        if self.is_active():
            self.vm.attachDevice(xml)

    def detach_device(self, xml):
        """Hotunplug device from running guest"""
        if self.is_active():
            self.vm.detachDevice(xml)

    def add_device(self, xml):
        """Redefine guest with appended device"""
        vmxml = self.vm.XMLDesc(0)

        newxml = self._add_xml_device(vmxml, xml)

        logging.debug("Redefine with " + newxml)
        self.get_connection().define_domain(newxml)

        # Invalidate cached XML
        self.xml = None

    def remove_device(self, devxml):
        xml = self.vm.XMLDesc(0)

        newxml = self._remove_xml_device(xml, devxml)

        logging.debug("Redefine with " + newxml)
        self.get_connection().define_domain(newxml)

        # Invalidate cached XML
        self.xml = None

    def _change_cdrom(self, newdev, origdev):
        # If vm is shutoff, remove device, and redefine with media
        vmxml = self.vm.XMLDesc(0)
        if not self.is_active():
            tmpxml = self._remove_xml_device(vmxml, origdev)
            finalxml = self._add_xml_device(tmpxml, newdev)
            logging.debug("change cdrom: redefining xml with:\n%s" % finalxml)
            self.get_connection().define_domain(finalxml)
        else:
            self.attach_device(newdev)

    def connect_cdrom_device(self, _type, source, target):
        xml = self.get_disk_xml(target)
        doc = None
        ctx = None
        try:
            doc = libxml2.parseDoc(xml)
            ctx = doc.xpathNewContext()
            disk_fragment = ctx.xpathEval("/disk")
            driver_fragment = ctx.xpathEval("/disk/driver")
            origdisk = disk_fragment[0].serialize()
            disk_fragment[0].setProp("type", _type)
            elem = disk_fragment[0].newChild(None, "source", None)
            if _type == "file":
                elem.setProp("file", source)
                if driver_fragment:
                    driver_fragment[0].setProp("name", _type)
            else:
                elem.setProp("dev", source)
                if driver_fragment:
                    driver_fragment[0].setProp("name", "phy")
            result = disk_fragment[0].serialize()
            logging.debug("connect_cdrom_device produced the following XML: %s" % result)
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()
        self._change_cdrom(result, origdisk)

    def disconnect_cdrom_device(self, target):
        xml = self.get_disk_xml(target)
        doc = None
        ctx = None
        try:
            doc = libxml2.parseDoc(xml)
            ctx = doc.xpathNewContext()
            disk_fragment = ctx.xpathEval("/disk")
            origdisk = disk_fragment[0].serialize()
            sourcenode = None
            for child in disk_fragment[0].children:
                if child.name == "source":
                    sourcenode = child
                    break
                else:
                    continue
            sourcenode.unlinkNode()
            sourcenode.freeNode()
            result = disk_fragment[0].serialize()
            logging.debug("disconnect_cdrom_device produced the following XML: %s" % result)
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()
        self._change_cdrom(result, origdisk)

    def set_vcpu_count(self, vcpus):
        vcpus = int(vcpus)
        self.vm.setVcpus(vcpus)

    def set_memory(self, memory):
        memory = int(memory)
        # capture updated information due to failing to get proper maxmem setting
        # if both current & max allocation are set simultaneously
        maxmem = self.vm.info()
        if (memory > maxmem[1]):
            logging.warning("Requested memory " + str(memory) + " over maximum " + str(self.maximum_memory()))
            memory = self.maximum_memory()
        self.vm.setMemory(memory)

    def set_max_memory(self, memory):
        memory = int(memory)
        self.vm.setMaxMemory(memory)

    def get_autostart(self):
        return self.vm.autostart()

    def set_autostart(self, val):
        if self.get_autostart() != val:
            self.vm.setAutostart(val)

    def get_boot_device(self):
        xml = self.get_xml()
        doc = None
        try:
            doc = libxml2.parseDoc(xml)
        except:
            return []
        ctx = doc.xpathNewContext()
        dev = None
        try:
            ret = ctx.xpathEval("/domain/os/boot[1]")
            for node in ret:
                dev = node.prop("dev")
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()
        return dev

    def set_boot_device(self, boot_type):
        logging.debug("Setting boot device to type: %s" % boot_type)
        xml = self.get_xml()
        doc = None
        try:
            doc = libxml2.parseDoc(xml)
        except:
            return []
        ctx = doc.xpathNewContext()
        try:
            ret = ctx.xpathEval("/domain/os/boot[1]")
            if len(ret) > 0:
                ret[0].unlinkNode()
                ret[0].freeNode()
            emptyxml=doc.serialize()
            index = emptyxml.find("</os>")
            newxml = emptyxml[0:index] + \
                     "<boot dev=\"" + boot_type + "\"/>\n" + \
                     emptyxml[index:]
            logging.debug("New boot device, redefining with: " + newxml)
            self.get_connection().define_domain(newxml)
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()

        # Invalidate cached xml
        self.xml = None

    def toggle_sample_network_traffic(self, ignore1=None, ignore2=None, ignore3=None, ignore4=None):
        if self.config.is_vmlist_network_traffic_visible():
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

    def toggle_sample_disk_io(self, ignore1=None, ignore2=None, ignore3=None, ignore4=None):
        if self.config.is_vmlist_disk_io_visible():
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


    def migrate(self, dictcon):
        flags = 0
        if self.lastStatus == libvirt.VIR_DOMAIN_RUNNING:
            flags = libvirt.VIR_MIGRATE_LIVE
        self.vm.migrate(self.connection.vmm, flags, None, dictcon.get_short_hostname(), 0)

gobject.type_register(vmmDomain)
