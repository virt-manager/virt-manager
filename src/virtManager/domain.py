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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import gobject
import libvirt
import libxml2
import os
import sys
import logging


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
        self._update_status()
        self.xml = None

    def get_xml(self):
        if self.xml is None:
            self.xml = self.vm.XMLDesc(0)
        return self.xml

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
        id = self.get_id()
        if id < 0:
            return "-"
        return str(id)

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
        os_type = self.get_xml_string("/domain/os/type")
        # XXX libvirt bug - doesn't work for inactive guests
        #os_type = self.vm.OSType()
        logging.debug("OS Type: %s" % os_type)
        if os_type == "hvm":
            return True
        return False

    def is_vcpu_hotplug_capable(self):
        # Read only connections aren't allowed to change it
        if self.connection.is_read_only():
            return False
        # Running paravirt guests can change it, or any inactive guest
        if self.vm.OSType() == "linux" or self.get_id() < 0:
            return True
        # Everyone else is out of luck
        return False

    def is_memory_hotplug_capable(self):
        # Read only connections aren't allowed to change it
        if self.connection.is_read_only():
            return False
        # Running paravirt guests can change it, or any inactive guest
        if self.vm.OSType() == "linux" or self.get_id() < 0:
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

    def tick(self, now):
        # Clear cached XML
        self.xml = None
        hostInfo = self.connection.get_host_info()
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

        newStats = { "timestamp": now,
                     "cpuTime": cpuTime,
                     "cpuTimeAbs": cpuTimeAbs,
                     "cpuTimePercent": pcentCpuTime,
                     "currMem": info[2],
                     "currMemPercent": pcentCurrMem,
                     "vcpuCount": info[3],
                     "maxMem": info[1],
                     "maxMemPercent": pcentMaxMem,
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

    def network_traffic(self):
        return 1

    def network_traffic_percentage(self):
        return 1

    def disk_usage(self):
        return 1

    def disk_usage_percentage(self):
        return 1

    def vcpu_count(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["vcpuCount"]

    def vcpu_max_count(self):
        cpus = self.get_xml_string("/domain/vcpu")
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

    def network_traffic_vector(self):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length()+1):
            vector.append(0)
        return vector

    def disk_usage_vector(self):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length()+1):
            vector.append(0)
        return vector

    def shutdown(self):
        self.vm.shutdown()
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

    def save(self, file, ignore1=None):
        self.vm.save(file)
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

    def get_xml_string(self, path):
        xml = self.get_xml()
        doc = None
        try:
            doc = libxml2.parseDoc(xml)
        except:
            return None
        ctx = doc.xpathNewContext()
        try:
            ret = ctx.xpathEval(path)
            tty = None
            if len(ret) == 1:
                tty = ret[0].content
            ctx.xpathFreeContext()
            doc.freeDoc()
            return tty
        except:
            ctx.xpathFreeContext()
            doc.freeDoc()
            return None

    def get_serial_console_tty(self):
        return self.get_xml_string("/domain/devices/console/@tty")

    def is_serial_console_tty_accessible(self):
        tty = self.get_serial_console_tty()
        if tty == None:
            return False
        return os.access(tty, os.R_OK | os.W_OK)

    def get_graphics_console(self):
        type = self.get_xml_string("/domain/devices/graphics/@type")
        port = None
        if type == "vnc":
            port = self.get_xml_string("/domain/devices/graphics[@type='vnc']/@port")
            if port == None:
                port = 5900 + self.get_id()
            else:
                port = int(port)
            return [type, "127.0.0.1", port]
        return [type, None, None]

    def get_disk_devices(self):
        xml = self.get_xml()
        doc = None
        try:
            doc = libxml2.parseDoc(xml)
        except:
            return []
        ctx = doc.xpathNewContext()
        disks = []
        try:
            ret = ctx.xpathEval("/domain/devices/disk")
            for node in ret:
                type = node.prop("type")
                srcpath = None
                devdst = None
                for child in node.children:
                    if child.name == "source":
                        if type == "file":
                            srcpath = child.prop("file")
                        elif type == "block":
                            srcpath = child.prop("dev")
                    elif child.name == "target":
                        devdst = child.prop("dev")

                if srcpath == None:
                    raise RuntimeError("missing source path")
                if devdst == None:
                    raise RuntimeError("missing destination device")

                devtype = node.prop("device")
                if devtype == None:
                    devtype = "disk"
                disks.append([type, srcpath, devtype, devdst])

        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()
        return disks

    def add_disk_device(self, xml):
        self.vm.attachDevice(xml)

    def get_network_devices(self):
        xml = self.get_xml()
        doc = None
        try:
            doc = libxml2.parseDoc(xml)
        except:
            return []
        ctx = doc.xpathNewContext()
        nics = []
        try:
            ret = ctx.xpathEval("/domain/devices/interface")

            n = 0
            for node in ret:
                type = node.prop("type")
                devmac = None
                source = None
                target = "eth%d" % n
                n = n + 1
                for child in node.children:
                    if child.name == "source":
                        if type == "bridge":
                            source = child.prop("bridge")
                        elif type == "ethernet":
                            source = child.prop("dev")
                        elif type == "network":
                            source = child.prop("network")
                        elif type == "user":
                            source = None
                        else:
                            source = None
                    elif child.name == "mac":
                        devmac = child.prop("address")

                nics.append([type, source, target, devmac])
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()
        return nics

    def add_device(self, xml):
        if self.is_active():
            self.vm.attachDevice(xml)

        vmxml = self.vm.XMLDesc(0)

        index = vmxml.find("</devices>")
        newxml = vmxml[0:index] + xml + vmxml[index:]

        logging.debug("Redefine with " + newxml)

        self.get_connection().define_domain(newxml)

    def remove_device(self, xml):
        if self.is_active():
            self.vm.detachDevice(xml)

        # XXX remove from defined XML. Eek !

    def set_vcpu_count(self, vcpus):
        vcpus = int(vcpus)
        self.vm.setVcpus(vcpus)

    def set_memory(self, memory):
        memory = int(memory)
        if (memory > self.maximum_memory()):
            logging.warning("Requested memory " + str(memory) + " over maximum " + str(self.maximum_memory()))
            memory = self.maximum_memory()
        self.vm.setMemory(memory)

    def set_max_memory(self, memory):
        memory = int(memory)
        self.vm.setMaxMemory(memory)

gobject.type_register(vmmDomain)
