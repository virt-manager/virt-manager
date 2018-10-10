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


class _VMStatsRecord(object):
    """
    Tracks a set of VM stats for a single timestamp
    """
    def __init__(self, timestamp,
                 cpuTime, cpuTimeAbs,
                 cpuHostPercent, cpuGuestPercent,
                 curmem, currMemPercent,
                 diskRdBytes, diskWrBytes,
                 netRxBytes, netTxBytes):
        self.timestamp = timestamp
        self.cpuTime = cpuTime
        self.cpuTimeAbs = cpuTimeAbs
        self.cpuHostPercent = cpuHostPercent
        self.cpuGuestPercent = cpuGuestPercent
        self.curmem = curmem
        self.currMemPercent = currMemPercent
        self.diskRdKiB = diskRdBytes // 1024
        self.diskWrKiB = diskWrBytes // 1024
        self.netRxKiB = netRxBytes // 1024
        self.netTxKiB = netTxBytes // 1024

        # These are set in _VMStatsList.append_stats
        self.diskRdRate = None
        self.diskWrRate = None
        self.netRxRate = None
        self.netTxRate = None


class _VMStatsList(vmmGObject):
    """
    Tracks a list of VMStatsRecords for a single VM
    """
    def __init__(self):
        vmmGObject.__init__(self)
        self._stats = []

        self.diskRdMaxRate = 10.0
        self.diskWrMaxRate = 10.0
        self.netRxMaxRate = 10.0
        self.netTxMaxRate = 10.0

        self.mem_stats_period_is_set = False
        self.stats_disk_skip = []
        self.stats_net_skip = []

    def _cleanup(self):
        pass

    def append_stats(self, newstats):
        expected = self.config.get_stats_history_length()
        current = len(self._stats)
        if current > expected:
            del(self._stats[expected:current])

        def _calculate_rate(record_name):
            ret = 0.0
            if self._stats:
                oldstats = self._stats[0]
                ratediff = (getattr(newstats, record_name) -
                            getattr(oldstats, record_name))
                timediff = newstats.timestamp - oldstats.timestamp
                ret = float(ratediff) / float(timediff)
            return max(ret, 0.0)

        newstats.diskRdRate = _calculate_rate("diskRdKiB")
        newstats.diskWrRate = _calculate_rate("diskWrKiB")
        newstats.netRxRate = _calculate_rate("netRxKiB")
        newstats.netTxRate = _calculate_rate("netTxKiB")

        self.diskRdMaxRate = max(newstats.diskRdRate, self.diskRdMaxRate)
        self.diskWrMaxRate = max(newstats.diskWrRate, self.diskWrMaxRate)
        self.netRxMaxRate = max(newstats.netRxRate, self.netRxMaxRate)
        self.netTxMaxRate = max(newstats.netTxRate, self.netTxMaxRate)

        self._stats.insert(0, newstats)

    def get_record(self, record_name):
        if not self._stats:
            return 0
        return getattr(self._stats[0], record_name)

    def get_vector(self, record_name, limit, ceil=100.0):
        vector = []
        statslen = self.config.get_stats_history_length() + 1
        if limit is not None:
            statslen = min(statslen, limit)

        for i in range(statslen):
            if i < len(self._stats):
                vector.append(getattr(self._stats[i], record_name) / ceil)
            else:
                vector.append(0)
        return vector

    def get_in_out_vector(self, name1, name2, limit, ceil):
        if ceil is None:
            ceil = max(self.get_record(name1), self.get_record(name2), 10.0)
        return (self.get_vector(name1, limit, ceil=ceil),
                self.get_vector(name2, limit, ceil=ceil))


class vmmStatsManager(vmmGObject):
    """
    Class for polling statistics
    """
    def __init__(self):
        vmmGObject.__init__(self)
        self._vm_stats = {}
        self._latest_all_stats = {}

        self._all_stats_supported = True
        self._net_stats_supported = True
        self._disk_stats_supported = True
        self._disk_stats_lxc_supported = True
        self._mem_stats_supported = True


    def _cleanup(self):
        self._latest_all_stats = None


    ######################
    # CPU stats handling #
    ######################

    def _old_cpu_stats_helper(self, vm):
        info = vm.get_backend().info()
        state = info[0]
        guestcpus = info[3]
        cpuTimeAbs = info[4]
        return state, guestcpus, cpuTimeAbs

    def _sample_cpu_stats(self, vm, allstats):
        timestamp = time.time()
        if (not vm.is_active() or
            not self.config.get_stats_enable_cpu_poll()):
            return 0, 0, 0, 0, timestamp

        cpuTime = 0
        cpuHostPercent = 0
        cpuGuestPercent = 0
        prevTimestamp = self.get_vm_statslist(vm).get_record("timestamp")
        prevCpuTime = self.get_vm_statslist(vm).get_record("cpuTimeAbs")

        if allstats:
            state = allstats.get("state.state", 0)
            guestcpus = allstats.get("vcpu.current", 0)
            cpuTimeAbs = allstats.get("cpu.time", 0)
            timestamp = allstats.get("virt-manager.timestamp")
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

            pcentbase = (
                    ((cpuTime) * 100.0) /
                    ((timestamp - prevTimestamp) * 1000.0 * 1000.0 * 1000.0))
            cpuHostPercent = pcentbase / hostcpus
            # Under RHEL-5.9 using a XEN HV guestcpus can be 0 during shutdown
            # so play safe and check it.
            cpuGuestPercent = guestcpus > 0 and pcentbase / guestcpus or 0

        cpuHostPercent = max(0.0, min(100.0, cpuHostPercent))
        cpuGuestPercent = max(0.0, min(100.0, cpuGuestPercent))

        return cpuTime, cpuTimeAbs, cpuHostPercent, cpuGuestPercent, timestamp


    ######################
    # net stats handling #
    ######################

    def _old_net_stats_helper(self, vm, dev):
        statslist = self.get_vm_statslist(vm)
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
                statslist.stats_net_skip.append(dev)
            else:
                logging.debug("Aren't running, don't add to skiplist")

        return 0, 0

    def _sample_net_stats(self, vm, allstats):
        rx = 0
        tx = 0
        statslist = self.get_vm_statslist(vm)
        if (not self._net_stats_supported or
            not vm.is_active() or
            not self.config.get_stats_enable_net_poll()):
            statslist.stats_net_skip = []
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
            if dev in statslist.stats_net_skip:
                continue

            devrx, devtx = self._old_net_stats_helper(vm, dev)
            rx += devrx
            tx += devtx

        return rx, tx


    #######################
    # disk stats handling #
    #######################

    def _old_disk_stats_helper(self, vm, dev):
        statslist = self.get_vm_statslist(vm)
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
                statslist.stats_disk_skip.append(dev)
            else:
                logging.debug("Aren't running, don't add to skiplist")

        return 0, 0

    def _sample_disk_stats(self, vm, allstats):
        rd = 0
        wr = 0
        statslist = self.get_vm_statslist(vm)
        if (not self._disk_stats_supported or
            not vm.is_active() or
            not self.config.get_stats_enable_disk_poll()):
            statslist.stats_disk_skip = []
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
            if dev in statslist.stats_disk_skip:
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
        statslist = self.get_vm_statslist(vm)
        if (not self._mem_stats_supported or
            not vm.is_active() or
            not self.config.get_stats_enable_memory_poll()):
            statslist.mem_stats_period_is_set = False
            return 0, 0

        if statslist.mem_stats_period_is_set is False:
            self._set_mem_stats_period(vm)
            statslist.mem_stats_period_is_set = True

        if allstats:
            totalmem = allstats.get("balloon.current", 1)
            curmem = max(0,
                    totalmem - allstats.get("balloon.unused", totalmem))
        else:
            totalmem, curmem = self._old_mem_stats_helper(vm)

        currMemPercent = (curmem / float(totalmem)) * 100
        currMemPercent = max(0.0, min(currMemPercent, 100.0))

        return currMemPercent, curmem


    ####################
    # alltats handling #
    ####################

    def _get_all_stats(self, conn):
        if not self._all_stats_supported:
            return {}

        statflags = 0
        if self.config.get_stats_enable_cpu_poll():
            statflags |= libvirt.VIR_DOMAIN_STATS_STATE
            statflags |= libvirt.VIR_DOMAIN_STATS_CPU_TOTAL
            statflags |= libvirt.VIR_DOMAIN_STATS_VCPU
        if self.config.get_stats_enable_memory_poll():
            statflags |= libvirt.VIR_DOMAIN_STATS_BALLOON
        if self.config.get_stats_enable_disk_poll():
            statflags |= libvirt.VIR_DOMAIN_STATS_BLOCK
        if self.config.get_stats_enable_net_poll():
            statflags |= libvirt.VIR_DOMAIN_STATS_INTERFACE
        if statflags == 0:
            return {}

        ret = {}
        try:
            timestamp = time.time()
            rawallstats = conn.get_backend().getAllDomainStats(statflags, 0)

            # Reformat the output to be a bit more friendly
            for dom, domallstats in rawallstats:
                domallstats["virt-manager.timestamp"] = timestamp
                ret[dom.UUIDString()] = domallstats
        except libvirt.libvirtError as err:
            if util.is_error_nosupport(err):
                logging.debug("conn does not support getAllDomainStats()")
                self._all_stats_supported = False
            else:
                logging.debug("Error call getAllDomainStats(): %s", err)
        return ret


    ##############
    # Public API #
    ##############

    def refresh_vm_stats(self, vm):
        domallstats = self._latest_all_stats.get(vm.get_uuid(), None)

        (cpuTime, cpuTimeAbs, cpuHostPercent, cpuGuestPercent, timestamp) = \
                self._sample_cpu_stats(vm, domallstats)
        currMemPercent, curmem = self._sample_mem_stats(vm, domallstats)
        diskRdBytes, diskWrBytes = self._sample_disk_stats(vm, domallstats)
        netRxBytes, netTxBytes = self._sample_net_stats(vm, domallstats)

        newstats = _VMStatsRecord(
                timestamp, cpuTime, cpuTimeAbs,
                cpuHostPercent, cpuGuestPercent,
                curmem, currMemPercent,
                diskRdBytes, diskWrBytes,
                netRxBytes, netTxBytes)
        self.get_vm_statslist(vm).append_stats(newstats)

    def cache_all_stats(self, conn):
        self._latest_all_stats = self._get_all_stats(conn)

    def get_vm_statslist(self, vm):
        if vm.get_connkey() not in self._vm_stats:
            self._vm_stats[vm.get_connkey()] = _VMStatsList()
        return self._vm_stats[vm.get_connkey()]
