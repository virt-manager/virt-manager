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

    def get_connection(self):
        return self.connection

    def get_id(self):
        return self.vm.ID()

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
        if len(self.record) == 0:
            return 0
        return self.record[0]["currMem"]

    def current_memory_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["currMemPercent"]

    def maximum_memory(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["maxMem"]

    def maximum_memory_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["maxMemPercent"]

    def cpu_time(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["cpuTime"]

    def cpu_time_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["cpuTimePercent"]

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

    def cpu_time_vector(self):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["cpuTimePercent"]/100.0)
            else:
                vector.append(0)
        return vector

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

    def suspend(self):
        self.vm.suspend()
        self._update_status()

    def resume(self):
        self.vm.resume()
        self._update_status()

    def save(self, file):
        self.vm.save(file)
        self._update_status()

    def status(self):
        return self.lastStatus

    def run_status(self):
        if self.lastStatus == libvirt.VIR_DOMAIN_RUNNING:
            return "Running"
        elif self.lastStatus == libvirt.VIR_DOMAIN_PAUSED:
            return "Paused"
        elif self.lastStatus == libvirt.VIR_DOMAIN_SHUTDOWN:
            return "Shutdown"
        elif self.lastStatus == libvirt.VIR_DOMAIN_SHUTOFF:
            return "Shutoff"
        elif self.lastStatus == libvirt.VIR_DOMAIN_CRASHED:
            return "Crashed"
        else:
            raise "Unknown status code"

    def run_status_icon(self):
        status = self.run_status()
        return self.config.get_vm_status_icon(status.lower())

    def get_console_info(self):
        # XXX don't hardcode me! need to really extract info from
        # the libvirt XML as & when the display device info gets
        # added
        return ["vnc", "localhost", 5900 + self.get_id()]

    def set_vcpu_count(self, vcpus):
        print "If this was implemented, it would set this domain to have " + `vcpus` + " virtual cpus."

    def set_memory(self, memory):
        if(memory > self.maximum_memory()):
            print "XXX add proper error handling here. You may not set vm memory larger than the maximum set for the vm."
        self.vm.setMemory(memory)
        return self.vm.info()[2]

gobject.type_register(vmmDomain)
