
import libvirt
import gtk.gdk
from time import time

class vmmStats:
    def __init__(self, config, connection):
        self.config = config
        self.connection = connection
        self.record = {}

        self.hostinfo = self.connection.get_host_info()
        self.connection.connect("vm-added", self._vm_added)
        self.connection.connect("vm-removed", self._vm_removed)


    def _vm_added(self, connection, uri, vmuuid, name):
        self.record[vmuuid] = []

    def _vm_removed(self, connection, uri, vmuuid):
        del self.record[vmuuid]

    def update(self, vmuuid, vm):
        now = time()

        self.hostinfo = self.connection.get_host_info()
        info = vm.info()

        expected = self.config.get_stats_history_length()
        current = len(self.record[vmuuid])
        if current > expected:
            del self.record[vmuuid][expected:current]

        prevCpuTime = 0
        prevTimestamp = 0
        if len(self.record[vmuuid]) > 0:
            prevTimestamp = self.record[vmuuid][0]["timestamp"]
            prevCpuTime = self.record[vmuuid][0]["cpuTimeAbs"]

        pcentCpuTime = (info[4]-prevCpuTime) * 100 / ((now - prevTimestamp)*1000*1000*1000*self.host_active_processor_count())

        pcentCurrMem = info[2] * 100 / self.host_memory_size()
        pcentMaxMem = info[1] * 100 / self.host_memory_size()

        newStats = { "timestamp": now,
                     "status": info[0],
                     "cpuTime": (info[4]-prevCpuTime),
                     "cpuTimeAbs": info[4],
                     "cpuTimePercent": pcentCpuTime,
                     "currMem": info[2],
                     "currMemPercent": pcentCurrMem,
                     "maxMem": info[1],
                     "maxMemPercent": pcentMaxMem,
                     }

        self.record[vmuuid].insert(0, newStats)

        nSamples = 5
        #nSamples = len(self.record[vmuuid])
        if nSamples > len(self.record[vmuuid]):
            nSamples = len(self.record[vmuuid])

        startCpuTime = self.record[vmuuid][nSamples-1]["cpuTimeAbs"]
        startTimestamp = self.record[vmuuid][nSamples-1]["timestamp"]

        if startTimestamp == now:
            self.record[vmuuid][0]["cpuTimeMovingAvg"] = self.record[vmuuid][0]["cpuTimeAbs"]
            self.record[vmuuid][0]["cpuTimeMovingAvgPercent"] = 0
        else:
            self.record[vmuuid][0]["cpuTimeMovingAvg"] = (self.record[vmuuid][0]["cpuTimeAbs"]-startCpuTime) / nSamples
            self.record[vmuuid][0]["cpuTimeMovingAvgPercent"] = (self.record[vmuuid][0]["cpuTimeAbs"]-startCpuTime) * 100 / ((now-startTimestamp)*1000*1000*1000 * self.host_active_processor_count())


    def current_memory(self, vmuuid):
        if len(self.record[vmuuid]) == 0:
            return 0
        return self.record[vmuuid][0]["currMem"]

    def current_memory_percentage(self, vmuuid):
        if len(self.record[vmuuid]) == 0:
            return 0
        return self.record[vmuuid][0]["currMemPercent"]

    def maximum_memory(self, vmuuid):
        if len(self.record[vmuuid]) == 0:
            return 0
        return self.record[vmuuid][0]["maxMem"]

    def maximum_memory_percentage(self, vmuuid):
        if len(self.record[vmuuid]) == 0:
            return 0
        return self.record[vmuuid][0]["maxMemPercent"]

    def cpu_time(self, vmuuid):
        if len(self.record[vmuuid]) == 0:
            return 0
        return self.record[vmuuid][0]["cpuTime"]

    def cpu_time_percentage(self, vmuuid):
        if len(self.record[vmuuid]) == 0:
            return 0
        return self.record[vmuuid][0]["cpuTimePercent"]

    def network_traffic(self, vmuuid):
        return 1

    def network_traffic_percentage(self, vmuuid):
        return 1

    def disk_usage(self, vmuuid):
        return 1

    def disk_usage_percentage(self, vmuuid):
        return 1

    def cpu_time_vector(self, vmuuid):
        vector = []
        stats = self.record[vmuuid]
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["cpuTimePercent"])
            else:
                vector.append(0)
        return vector

    def cpu_time_moving_avg_vector(self, vmuuid):
        vector = []
        stats = self.record[vmuuid]
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["cpuTimeMovingAvgPercent"])
            else:
                vector.append(0)
        return vector

    def current_memory_vector(self, vmuuid):
        vector = []
        stats = self.record[vmuuid]
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["currMemPercent"])
            else:
                vector.append(0)
        return vector

    def network_traffic_vector(self, vmuuid):
        vector = []
        stats = self.record[vmuuid]
        for i in range(self.config.get_stats_history_length()+1):
            vector.append(1)
        return vector

    def disk_usage_vector(self, vmuuid):
        vector = []
        stats = self.record[vmuuid]
        for i in range(self.config.get_stats_history_length()+1):
            vector.append(1)
        return vector

    def host_memory_size(self):
        return self.hostinfo[1]*1024

    def host_active_processor_count(self):
        return self.hostinfo[2]

    def host_maximum_processor_count(self):
        return self.hostinfo[4] * self.hostinfo[5] * self.hostinfo[6] * self.hostinfo[7]

    def run_status(self, vmuuid):
        if len(self.record[vmuuid]) == 0:
            return "Shutoff"
        status = self.record[vmuuid][0]["status"]
        if status == libvirt.VIR_DOMAIN_NOSTATE:
            return "Idle"
        elif status == libvirt.VIR_DOMAIN_RUNNING:
            return "Running"
        elif status == libvirt.VIR_DOMAIN_BLOCKED:
            return "Blocked"
        elif status == libvirt.VIR_DOMAIN_PAUSED:
            return "Paused"
        elif status == libvirt.VIR_DOMAIN_SHUTDOWN:
            return "Shutdown"
        elif status == libvirt.VIR_DOMAIN_SHUTOFF:
            return "Shutoff"
        elif status == libvirt.VIR_DOMAIN_CRASHED:
            return "Crashed"
        else:
            raise "Unknown status code"

    def run_status_icon(self, name):
        status = self.run_status(name)
        return self.config.get_vm_status_icon(status.lower())
