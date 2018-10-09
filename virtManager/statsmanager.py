# Copyright (C) 2018 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import re
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
        self._enable_mem_stats = False
        self._enable_cpu_stats = False
        self._enable_net_stats = False
        self._enable_disk_stats = False

        self._net_stats_supported = True
        self._disk_stats_supported = True
        self._disk_stats_lxc_supported = True
        self._mem_stats_supported = True
        self._mem_stats_period_is_set = False

        self._on_config_sample_network_traffic_changed()
        self._on_config_sample_disk_io_changed()
        self._on_config_sample_mem_stats_changed()
        self._on_config_sample_cpu_stats_changed()

        self.add_gsettings_handle(
            self.config.on_stats_enable_cpu_poll_changed(
                self._on_config_sample_cpu_stats_changed))
        self.add_gsettings_handle(
            self.config.on_stats_enable_net_poll_changed(
                self._on_config_sample_network_traffic_changed))
        self.add_gsettings_handle(
            self.config.on_stats_enable_disk_poll_changed(
                self._on_config_sample_disk_io_changed))
        self.add_gsettings_handle(
            self.config.on_stats_enable_memory_poll_changed(
                self._on_config_sample_mem_stats_changed))


    def _cleanup(self):
        self._newStatsDict = {}

    def _on_config_sample_network_traffic_changed(self, ignore=None):
        self._enable_net_stats = self.config.get_stats_enable_net_poll()
    def _on_config_sample_disk_io_changed(self, ignore=None):
        self._enable_disk_stats = self.config.get_stats_enable_disk_poll()
    def _on_config_sample_mem_stats_changed(self, ignore=None):
        self._enable_mem_stats = self.config.get_stats_enable_memory_poll()
    def _on_config_sample_cpu_stats_changed(self, ignore=None):
        self._enable_cpu_stats = self.config.get_stats_enable_cpu_poll()


    ######################
    # CPU stats handling #
    ######################

    def _old_cpu_stats_helper(self, vm):
        info = vm.get_backend().info()
        state = info[0]
        guestcpus = info[3]
        cpuTimeAbs = info[4]
        return state, guestcpus, cpuTimeAbs

    def _sample_cpu_stats(self, now, vm, allstats):
        if not self._enable_cpu_stats:
            return 0, 0, 0, 0

        prevCpuTime = 0
        prevTimestamp = 0
        cpuTime = 0
        pcentHostCpu = 0
        pcentGuestCpu = 0

        if len(vm.stats) > 0:
            prevTimestamp = vm.stats[0]["timestamp"]
            prevCpuTime = vm.stats[0]["cpuTimeAbs"]

        if allstats:
            state = allstats.get("state.state", 0)
            guestcpus = allstats.get("vcpu.current", 0)
            cpuTimeAbs = allstats.get("cpu.time", 0)
        else:
            state, guestcpus, cpuTimeAbs = self._old_cpu_stats_helper(vm)

        is_offline = (state in [libvirt.VIR_DOMAIN_SHUTOFF,
                                libvirt.VIR_DOMAIN_CRASHED])
        if is_offline:
            guestcpus = 0
            cpuTimeAbs = 0

        cpuTime = cpuTimeAbs - prevCpuTime
        if not is_offline:
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


    ######################
    # net stats handling #
    ######################

    def _old_net_stats_helper(self, vm, dev):
        try:
            io = vm.get_backend().interfaceStats(dev)
            if io:
                rx = io[0]
                tx = io[4]
                return rx, tx
        except libvirt.libvirtError as err:
            if util.is_error_nosupport(err):
                logging.debug("conn does not support interfaceStats")
                self._net_stats_supported = False
                return 0, 0

            logging.debug("Error in interfaceStats for '%s' dev '%s': %s",
                          vm.get_name(), dev, err)
            if vm.is_active():
                logging.debug("Adding %s to skip list", dev)
                vm.stats_net_skip.append(dev)
            else:
                logging.debug("Aren't running, don't add to skiplist")

        return 0, 0

    def _sample_net_stats(self, vm, allstats):
        rx = 0
        tx = 0
        if (not self._net_stats_supported or
            not self._enable_net_stats or
            not vm.is_active()):
            vm.stats_net_skip = []
            return rx, tx

        if allstats:
            for key in allstats.keys():
                if re.match(r"net.[0-9]+.rx.bytes", key):
                    rx += allstats[key]
                if re.match(r"net.[0-9]+.tx.bytes", key):
                    tx += allstats[key]
            return rx, tx

        for iface in vm.get_interface_devices_norefresh():
            dev = iface.target_dev
            if not dev:
                continue
            if dev in vm.stats_net_skip:
                continue

            devrx, devtx = self._old_net_stats_helper(vm, dev)
            rx += devrx
            tx += devtx

        return rx, tx


    #######################
    # disk stats handling #
    #######################

    def _old_disk_stats_helper(self, vm, dev):
        try:
            io = vm.get_backend().blockStats(dev)
            if io:
                rd = io[1]
                wr = io[3]
                return rd, wr
        except libvirt.libvirtError as err:
            if util.is_error_nosupport(err):
                logging.debug("conn does not support blockStats")
                self._disk_stats_supported = False
                return 0, 0

            logging.debug("Error in blockStats for '%s' dev '%s': %s",
                          vm.get_name(), dev, err)
            if vm.is_active():
                logging.debug("Adding %s to skip list", dev)
                vm.stats_disk_skip.append(dev)
            else:
                logging.debug("Aren't running, don't add to skiplist")

        return 0, 0

    def _sample_disk_stats(self, vm, allstats):
        rd = 0
        wr = 0
        if (not self._disk_stats_supported or
            not self._enable_disk_stats or
            not vm.is_active()):
            vm.stats_disk_skip = []
            return rd, wr

        if allstats:
            for key in allstats.keys():
                if re.match(r"block.[0-9]+.rd.bytes", key):
                    rd += allstats[key]
                if re.match(r"block.[0-9]+.wr.bytes", key):
                    wr += allstats[key]
            return rd, wr

        # LXC has a special blockStats method
        if vm.conn.is_lxc() and self._disk_stats_lxc_supported:
            try:
                io = vm.get_backend().blockStats('')
                if io:
                    rd = io[1]
                    wr = io[3]
                    return rd, wr
            except libvirt.libvirtError as e:
                logging.debug("LXC style disk stats not supported: %s", e)
                self._disk_stats_lxc_supported = False

        for disk in vm.get_disk_devices_norefresh():
            dev = disk.target
            if not dev:
                continue
            if dev in vm.stats_disk_skip:
                continue

            diskrd, diskwr = self._old_disk_stats_helper(vm, dev)
            rd += diskrd
            wr += diskwr

        return rd, wr


    #########################
    # memory stats handling #
    #########################

    def _set_mem_stats_period(self, vm):
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

    def _old_mem_stats_helper(self, vm):
        totalmem = 1
        curmem = 0
        try:
            stats = vm.get_backend().memoryStats()
            totalmem = stats.get("actual", 1)
            curmem = max(0, totalmem - stats.get("unused", totalmem))
        except libvirt.libvirtError as err:
            if util.is_error_nosupport(err):
                logging.debug("conn does not support memoryStats")
                self._mem_stats_supported = False
            else:
                logging.debug("Error reading mem stats: %s", err)

        return totalmem, curmem

    def _sample_mem_stats(self, vm, allstats):
        if (not self._mem_stats_supported or
            not self._enable_mem_stats or
            not vm.is_active()):
            self._mem_stats_period_is_set = False
            return 0, 0

        if self._mem_stats_period_is_set is False:
            self._set_mem_stats_period(vm)
            self._mem_stats_period_is_set = True

        if allstats:
            totalmem = allstats.get("balloon.current", 1)
            curmem = max(0,
                    totalmem - allstats.get("balloon.unused", totalmem))
        else:
            totalmem, curmem = self._old_mem_stats_helper(vm)

        pcentCurrMem = (curmem / float(totalmem)) * 100
        pcentCurrMem = max(0.0, min(pcentCurrMem, 100.0))

        return pcentCurrMem, curmem


    #####################
    # allstats handling #
    #####################

    def _get_all_stats(self, con):
        if not self._all_stats_supported:
            return []

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
                logging.debug("conn does not support getAllDomainStats()")
                self._all_stats_supported = False
            else:
                logging.debug("Error call getAllDomainStats(): %s", err)
        return stats

    def refresh_vms_stats(self, conn, vm_list):
        for vm in vm_list:
            now = time.time()

            domallstats = None
            for _domstat in self._get_all_stats(conn):
                if vm.get_name() == _domstat[0].name():
                    domallstats = _domstat[1]
                    break

            cpuTime, cpuTimeAbs, pcentHostCpu, pcentGuestCpu = \
                self._sample_cpu_stats(now, vm, domallstats)
            pcentCurrMem, curmem = self._sample_mem_stats(vm, domallstats)
            rdBytes, wrBytes = self._sample_disk_stats(vm, domallstats)
            rxBytes, txBytes = self._sample_net_stats(vm, domallstats)

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
        # this should happen only during initialization of vm when
        # caches are primed
        if not self._newStatsDict.get(vm):
            self.refresh_vms_stats(vm.conn, [vm])

        return self._newStatsDict.get(vm)
