# Copyright (C) 2018 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import time

import libvirt

from virtinst import util

from .baseclass import vmmGObject


class vmmStatsManager(vmmGObject):
    """
    Class for polling statistics
    """
    def __init__(self):
        vmmGObject.__init__(self)
        self._newStatsDict = {}
        self._all_stats_supported = True

    def _cleanup(self):
        self._newStatsDict = {}

    @staticmethod
    def _sample_cpu_stats_helper(vm, stats):
        state = 0
        guestcpus = 0
        cpuTimeAbs = 0
        if stats:
            state = stats.get("state.state", 0)
            if not (state in [libvirt.VIR_DOMAIN_SHUTOFF,
                                libvirt.VIR_DOMAIN_CRASHED]):
                guestcpus = stats.get("vcpu.current", 0)
                cpuTimeAbs = stats.get("cpu.time", 0)
        else:
            info = vm.get_backend().info()
            state = info[0]
            if not (state in [libvirt.VIR_DOMAIN_SHUTOFF,
                                libvirt.VIR_DOMAIN_CRASHED]):
                guestcpus = info[3]
                cpuTimeAbs = info[4]

        return state, guestcpus, cpuTimeAbs

    def _sample_cpu_stats(self, now, vm, stats=None):
        if not vm.enable_cpu_stats:
            return 0, 0, 0, 0

        prevCpuTime = 0
        prevTimestamp = 0
        cpuTime = 0
        cpuTimeAbs = 0
        pcentHostCpu = 0
        pcentGuestCpu = 0

        if len(vm.stats) > 0:
            prevTimestamp = vm.stats[0]["timestamp"]
            prevCpuTime = vm.stats[0]["cpuTimeAbs"]

        state, guestcpus, cpuTimeAbs = self._sample_cpu_stats_helper(vm, stats)
        cpuTime = cpuTimeAbs - prevCpuTime

        if state not in [libvirt.VIR_DOMAIN_SHUTOFF,
                            libvirt.VIR_DOMAIN_CRASHED]:
            hostcpus = vm.conn.host_active_processor_count()

            pcentbase = (((cpuTime) * 100.0) /
                         ((now - prevTimestamp) * 1000.0 * 1000.0 * 1000.0))
            pcentHostCpu = pcentbase / hostcpus
            # Under RHEL-5.9 using a XEN HV guestcpus can be 0 during shutdown
            # so play safe and check it.
            pcentGuestCpu = guestcpus > 0 and pcentbase / guestcpus or 0

        pcentHostCpu = max(0.0, min(100.0, pcentHostCpu))
        pcentGuestCpu = max(0.0, min(100.0, pcentGuestCpu))

        return cpuTime, cpuTimeAbs, pcentHostCpu, pcentGuestCpu

    @staticmethod
    def _sample_network_traffic_helper(vm, stats, i, dev=None):
        rx = 0
        tx = 0
        if stats:
            rx = stats.get("net." + str(i) + ".rx.bytes", 0)
            tx = stats.get("net." + str(i) + ".tx.bytes", 0)
        else:
            try:
                io = vm.get_backend().interfaceStats(dev)
                if io:
                    rx = io[0]
                    tx = io[4]
            except libvirt.libvirtError as err:
                if util.is_error_nosupport(err):
                    logging.debug("Net stats not supported: %s", err)
                    vm.stats_net_supported = False
                else:
                    logging.error("Error reading net stats for "
                                  "'%s' dev '%s': %s",
                                  vm.get_name(), dev, err)
                    if vm.is_active():
                        logging.debug("Adding %s to skip list", dev)
                        vm.stats_net_skip.append(dev)
                    else:
                        logging.debug("Aren't running, don't add to skiplist")

        return rx, tx

    def _sample_network_traffic(self, vm, stats=None):
        rx = 0
        tx = 0
        if (not vm.stats_net_supported or
            not vm.enable_net_poll or
            not vm.is_active()):
            vm.stats_net_skip = []
            return rx, tx

        for i, netdev in enumerate(vm.get_interface_devices_norefresh()):
            dev = netdev.target_dev
            if not dev:
                continue

            if dev in vm.stats_net_skip:
                continue

            devrx, devtx = self._sample_network_traffic_helper(vm, stats, i, dev)
            rx += devrx
            tx += devtx

        return rx, tx

    @staticmethod
    def _sample_disk_io_helper(vm, stats, i, dev=None):
        rd = 0
        wr = 0
        if stats:
            rd = stats.get("block." + str(i) + ".rd.bytes", 0)
            wr = stats.get("block." + str(i) + ".wr.bytes", 0)
        else:
            try:
                io = vm.get_backend().blockStats(dev)
                if io:
                    rd = io[1]
                    wr = io[3]
            except libvirt.libvirtError as err:
                if util.is_error_nosupport(err):
                    logging.debug("Disk stats not supported: %s", err)
                    vm.stats_disk_supported = False
                else:
                    logging.error("Error reading disk stats for "
                                  "'%s' dev '%s': %s",
                                  vm.get_name(), dev, err)
                    if vm.is_active():
                        logging.debug("Adding %s to skip list", dev)
                        vm.stats_disk_skip.append(dev)
                    else:
                        logging.debug("Aren't running, don't add to skiplist")

        return rd, wr

    def _sample_disk_io(self, vm, stats=None):
        rd = 0
        wr = 0
        if (not vm.stats_disk_supported or
            not vm.enable_disk_poll or
            not vm.is_active()):
            vm.stats_disk_skip = []
            return rd, wr

        # Some drivers support this method for getting all usage at once
        if not vm.summary_disk_stats_skip:
            rd, wr = self._sample_disk_io_helper(vm, stats, 0)
            return rd, wr

        # did not work, iterate over all disks
        for i, disk in enumerate(vm.get_disk_devices_norefresh()):
            dev = disk.target
            if not dev:
                continue

            if dev in vm.stats_disk_skip:
                continue

            diskrd, diskwr = self._sample_disk_io_helper(vm, stats, i, dev)
            rd += diskrd
            wr += diskwr

        return rd, wr

    @staticmethod
    def _set_mem_stats_period(vm):
        # QEMU requires to explicitly enable memory stats polling per VM
        # if we want fine grained memory stats
        if not vm.conn.check_support(
                vm.conn.SUPPORT_CONN_MEM_STATS_PERIOD):
            return

        # Only works for virtio balloon
        if not any([b for b in vm.get_xmlobj().devices.memballoon if
                    b.model == "virtio"]):
            return

        try:
            secs = 5
            vm.get_backend().setMemoryStatsPeriod(secs,
                libvirt.VIR_DOMAIN_AFFECT_LIVE)
        except Exception as e:
            logging.debug("Error setting memstats period: %s", e)

    @staticmethod
    def _sample_mem_stats_helper(vm, stats):
        if stats:
            # @stats are available if new API call is supported
            totalmem = stats.get("balloon.current", 0)
            curmem = stats.get("balloon.rss", 0)
        else:
            # Legacy call
            try:
                stats = vm.get_backend().memoryStats()
                totalmem = stats.get("actual", 0)
                curmem = stats.get("rss", 0)

                if "unused" in stats:
                    curmem = max(0, totalmem - stats.get("unused", totalmem))
            except libvirt.libvirtError as err:
                logging.error("Error reading mem stats: %s", err)

        return totalmem, curmem

    def _sample_mem_stats(self, vm, stats=None):
        if (not vm.mem_stats_supported or
            not vm.enable_mem_stats or
            not vm.is_active()):
            vm.mem_stats_period_is_set = False
            return 0, 0

        if vm.mem_stats_period_is_set is False:
            self._set_mem_stats_period(vm)
            vm.mem_stats_period_is_set = True

        totalmem, curmem = self._sample_mem_stats_helper(vm, stats)

        if "unused" in stats:
            curmem = max(0, totalmem - stats.get("unused", totalmem))

        pcentCurrMem = (curmem / float(totalmem)) * 100
        pcentCurrMem = max(0.0, min(pcentCurrMem, 100.0))

        return pcentCurrMem, curmem

    def _get_all_stats(self, con):
        stats = []
        try:
            stats = con.get_backend().getAllDomainStats(
                libvirt.VIR_DOMAIN_STATS_STATE |
                libvirt.VIR_DOMAIN_STATS_CPU_TOTAL |
                libvirt.VIR_DOMAIN_STATS_VCPU |
                libvirt.VIR_DOMAIN_STATS_BALLOON |
                libvirt.VIR_DOMAIN_STATS_BLOCK |
                libvirt.VIR_DOMAIN_STATS_INTERFACE,
                0)
        except libvirt.libvirtError as err:
            if util.is_error_nosupport(err):
                logging.debug("Method getAllDomainStats() not supported: %s", err)
                self._all_stats_supported = False
            else:
                logging.error("Error loading statistics: %s", err)
        return stats

    def refresh_vms_stats(self, con, vm_list):
        for vm in vm_list:
            stats = None
            now = time.time()
            if self._all_stats_supported:
                stats = self._get_all_stats(con)
            if stats:
                # using new API
                for domstat in stats:
                    if vm.get_backend().UUID() == domstat[0].UUID():
                        cpuTime, cpuTimeAbs, pcentHostCpu, pcentGuestCpu = \
                            self._sample_cpu_stats(now, vm, domstat[1])
                        pcentCurrMem, curmem = self._sample_mem_stats(vm, domstat[1])
                        rdBytes, wrBytes = self._sample_disk_io(vm, domstat[1])
                        rxBytes, txBytes = self._sample_network_traffic(vm, domstat[1])
                        # this if statement is true only once, so we can break out
                        # of the cycle
                        break
            else:
                # legacy method of gathering stats
                cpuTime, cpuTimeAbs, pcentHostCpu, pcentGuestCpu = \
                    self._sample_cpu_stats(now, vm)
                pcentCurrMem, curmem = self._sample_mem_stats(vm)
                rdBytes, wrBytes = self._sample_disk_io(vm)
                rxBytes, txBytes = self._sample_network_traffic(vm)

            newStats = {
                "timestamp": now,
                "cpuTime": cpuTime,
                "cpuTimeAbs": cpuTimeAbs,
                "cpuHostPercent": pcentHostCpu,
                "cpuGuestPercent": pcentGuestCpu,
                "curmem": curmem,
                "currMemPercent": pcentCurrMem,
                "diskRdKiB": rdBytes // 1024,
                "diskWrKiB": wrBytes // 1024,
                "netRxKiB": rxBytes // 1024,
                "netTxKiB": txBytes // 1024,
            }

            self._newStatsDict[vm] = newStats

    def get_vm_stats(self, vm):
        if not self._all_stats_supported:
            return None

        # this should happen only during initialization of vm when
        # caches are primed
        if not self._newStatsDict.get(vm):
            self.refresh_vms_stats(vm.conn, [vm])

        return self._newStatsDict.get(vm)
