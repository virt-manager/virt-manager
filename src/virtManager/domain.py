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
import os
import logging
import time
import difflib

from virtManager import util
import virtinst.util as vutil
import virtinst

def safeint(val, fmt="%.3d"):
    try:
        int(val)
    except:
        return str(val)
    return fmt % int(val)

class vmmDomain(gobject.GObject):
    __gsignals__ = {
        "status-changed": (gobject.SIGNAL_RUN_FIRST,
                           gobject.TYPE_NONE,
                           [int]),
        "resources-sampled": (gobject.SIGNAL_RUN_FIRST,
                              gobject.TYPE_NONE,
                              []),
        "config-changed": (gobject.SIGNAL_RUN_FIRST,
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

        self._xml = None
        self._orig_inactive_xml = None
        self._valid_xml = False

        self._network_traffic = None
        self._disk_io = None

        self._update_status()

        self.config.on_stats_enable_net_poll_changed(self.toggle_sample_network_traffic)
        self.config.on_stats_enable_disk_poll_changed(self.toggle_sample_disk_io)

        self._stats_net_supported = True
        self._stats_disk_supported = True

        self.toggle_sample_network_traffic()
        self.toggle_sample_disk_io()

        # Determine available XML flags (older libvirt versions will error
        # out if passed SECURE_XML, INACTIVE_XML, etc)
        self.connection.set_dom_flags(vm)

    def get_xml(self):
        """
        Get domain xml. If cached xml is invalid, update.
        """
        return self._xml_fetch_helper(refresh_if_necc=True)

    def get_xml_no_refresh(self):
        """
        Fetch XML, but don't force a refresh. Useful to prevent updating
        xml in the tick loop when it's not that important (disk/net stats)
        """
        return self._xml_fetch_helper(refresh_if_necc=False)

    def get_xml_to_define(self):
        # FIXME: This isn't sufficient, since we pull stuff like disk targets
        #        from the active XML. This all needs proper fixing in the long
        #        term.
        if self.is_active():
            return self._get_inactive_xml()
        else:
            self._invalidate_xml()
            return self.get_xml()

    def refresh_xml(self):
        self._update_xml()

    def _xml_fetch_helper(self, refresh_if_necc):
        # Helper to fetch xml with various options
        if self._xml is None:
            self._update_xml()
        elif refresh_if_necc and self._valid_xml:
            self._update_xml()

        return self._xml

    def _update_xml(self):
        # Force an xml update. Signal 'config-changed' if domain xml has
        # changed since last refresh

        flags = libvirt.VIR_DOMAIN_XML_SECURE
        if not self.connection.has_dom_flags(flags):
            flags = 0

        origxml = self._xml
        self._xml = self.vm.XMLDesc(flags)
        self._valid_xml = True

        if origxml != self._xml:
            # 'tick' to make sure we have the latest time
            self.tick(time.time())
            gobject.idle_add(util.idle_emit, self, "config-changed")

    def _invalidate_xml(self):
        # Mark cached xml as invalid
        self._valid_xml = False

    def _get_inactive_xml(self):
        # FIXME: We only allow the user to change the inactive xml once.
        #        We should eventually allow them to continually change it,
        #        possibly see the inactive config? and not choke if they try
        #        to remove a device twice.
        if self._orig_inactive_xml is None:
            self._refresh_inactive_xml()
        return self._orig_inactive_xml

    def _refresh_inactive_xml(self):
        flags = (libvirt.VIR_DOMAIN_XML_INACTIVE |
                 libvirt.VIR_DOMAIN_XML_SECURE)
        if not self.connection.has_dom_flags(flags):
            flags = libvirt.VIR_DOMAIN_XML_INACTIVE

            if not self.connection.has_dom_flags:
                flags = 0

        self._orig_inactive_xml = self.vm.XMLDesc(flags)

    def redefine(self, xml_func, *args):
        """
        Helper function for altering a redefining VM xml

        @param xml_func: Function to alter the running XML. Takes the
                         original XML as its first argument.
        @param args: Extra arguments to pass to xml_func
        """
        origxml = self.get_xml_to_define()
        # Sanitize origxml to be similar to what we will get back
        origxml = util.xml_parse_wrapper(origxml, lambda d, c: d.serialize())

        newxml = xml_func(origxml, *args)

        if origxml == newxml:
            logging.debug("Redefinition requested, but new xml was not"
                          " different")

        else:
            diff = "".join(difflib.unified_diff(origxml.splitlines(1),
                                                newxml.splitlines(1),
                                                fromfile="Original XML",
                                                tofile="New XML"))
            logging.debug("Redefining '%s' with XML diff:\n%s",
                          self.get_name(), diff)

        self.get_connection().define_domain(newxml)

        # Invalidate cached XML
        self._invalidate_xml()

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
        if self.get_abi_type() == "hvm":
            return True
        return False

    def get_abi_type(self):
        # FIXME: This should be static, not parse xml everytime
        return str(vutil.get_xml_path(self.get_xml(),
                                      "/domain/os/type")).lower()

    def get_hv_type(self):
        # FIXME: This should be static, not parse xml everytime
        return str(vutil.get_xml_path(self.get_xml(), "/domain/@type")).lower()

    def get_pretty_hv_type(self):
        return util.pretty_hv(self.get_abi_type(), self.get_hv_type())

    def get_arch(self):
        return vutil.get_xml_path(self.get_xml(), "/domain/os/type/@arch")

    def get_emulator(self):
        return vutil.get_xml_path(self.get_xml(), "/domain/devices/emulator")

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
            if self.lastStatus in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                                    libvirt.VIR_DOMAIN_SHUTOFF,
                                    libvirt.VIR_DOMAIN_CRASHED ]:
                # Domain just started. Invalidate inactive xml
                self._orig_inactive_xml = None
            self.lastStatus = status
            gobject.idle_add(util.idle_emit, self, "status-changed", status)

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

            try:
                io = self.vm.interfaceStats(dev)
                if io:
                    rx += io[0]
                    tx += io[4]
            except libvirt.libvirtError, err:
                if err.get_error_code() == libvirt.VIR_ERR_NO_SUPPORT:
                    logging.debug("Net stats not supported: %s" % err)
                    self._stats_net_supported = False
                else:
                    logging.error("Error reading net stats for "
                                  "'%s' dev '%s': %s" %
                                  (self.get_name(), dev, err))
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

            try:
                io = self.vm.blockStats(dev)
                if io:
                    rd += io[1]
                    wr += io[3]
            except libvirt.libvirtError, err:
                if err.get_error_code() == libvirt.VIR_ERR_NO_SUPPORT:
                    logging.debug("Disk stats not supported: %s" % err)
                    self._stats_disk_supported = False
                else:
                    logging.error("Error reading disk stats for "
                                  "'%s' dev '%s': %s" %
                                  (self.get_name(), dev, err))
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

    def tick(self, now):
        if self.connection.get_state() != self.connection.STATE_ACTIVE:
            return

        # Invalidate cached xml
        self._invalidate_xml()

        info = self.vm.info()
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
        gobject.idle_add(util.idle_emit, self, "resources-sampled")


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
        if mem > (10*1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.0f MB" % (mem/1024.0)


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
        if mem > (10*1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.0f MB" % (mem/1024.0)


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

    def vcpu_pinning(self):
        cpuset = vutil.get_xml_path(self.get_xml(), "/domain/vcpu/@cpuset")
        # We need to set it to empty string not to show None in the entry
        if cpuset is None:
            cpuset = ""
        return cpuset

    def vcpu_max_count(self):
        cpus = vutil.get_xml_path(self.get_xml(), "/domain/vcpu")
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

    def save(self, filename, background=True):
        if background:
            conn = util.dup_conn(self.config, self.connection)
            vm = conn.lookupByID(self.get_id())
        else:
            vm = self.vm

        vm.save(filename)
        self._update_status()

    def destroy(self):
        self.vm.destroy()

    def status(self):
        return self.lastStatus

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
        if self.lastStatus == libvirt.VIR_DOMAIN_RUNNING:
            return _("Running")
        elif self.lastStatus == libvirt.VIR_DOMAIN_PAUSED:
            return _("Paused")
        elif self.lastStatus == libvirt.VIR_DOMAIN_SHUTDOWN:
            return _("Shuting Down")
        elif self.lastStatus == libvirt.VIR_DOMAIN_SHUTOFF:
            return _("Shutoff")
        elif self.lastStatus == libvirt.VIR_DOMAIN_CRASHED:
            return _("Crashed")
        else:
            raise RuntimeError(_("Unknown status code"))

    def run_status_icon(self):
        return self.config.get_vm_status_icon(self.status())
    def run_status_icon_large(self):
        return self.config.get_vm_status_icon_large(self.status())

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
        typ = vutil.get_xml_path(self.get_xml(),
                                "/domain/devices/graphics/@type")
        port = None
        if typ == "vnc":
            port = vutil.get_xml_path(self.get_xml(),
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


    # ----------------
    # get_X_devices functions: return a list of lists. Each sublist represents
    # a device, of the format:
    # [ device_type, unique_attribute(s), hw column label, attr1, attr2, ... ]
    # ----------------

    def get_disk_devices(self, refresh_if_necc=True):
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
                    elif child.name == "shareable":
                        sharable = True

                if srcpath == None:
                    if devtype == "cdrom" or devtype == "floppy":
                        srcpath = "-"
                        typ = "block"
                    else:
                        raise RuntimeError("missing source path")
                if devdst == None:
                    raise RuntimeError("missing destination device")

                # [ devicetype, unique, device target, source path,
                #   disk device type, disk type, readonly?, sharable?,
                #   bus type ]
                disks.append(["disk", devdst, devdst, srcpath, devtype, typ,
                              readonly, sharable, bus])

            return disks

        return self._parse_device_xml(_parse_disk_devs, refresh_if_necc)

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

                # [device type, unique, graphics type, listen addr, port,
                #  keymap ]
                graphics.append(["graphics", typ, typ, listen, port, keymap])
            return graphics

        return self._parse_device_xml(_parse_graphics_devs)

    def get_sound_devices(self):
        def _parse_sound_devs(ctx):
            sound = []
            ret = ctx.xpathEval("/domain/devices/sound")
            for node in ret:
                model = node.prop("model")

                # [device type, unique, sound model]
                sound.append(["sound", model, model])
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

            for node in devs:
                char_type = node.name
                dev_type = node.prop("type")
                target_port = None
                source_path = None

                for child in node.children or []:
                    if child.name == "target":
                        target_port = child.prop("port")
                    if child.name == "source":
                        source_path = child.prop("path")

                if not source_path:
                    source_path = node.prop("tty")

                # [device type, unique, display string, target_port,
                #  char device type, source_path, is_console_dup_of_serial?
                dev = [char_type, target_port,
                       "%s:%s" % (char_type, target_port), target_port,
                       dev_type, source_path, False]

                if node.name == "console":
                    cons_port = target_port
                    cons_dev = dev
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

                unique = [model, ram, heads]
                row = ["video", unique, model, ram, heads]
                vids.append(row)

            return vids
        return self._parse_device_xml(_parse_video_devs)

    def get_hostdev_devices(self):
        def _parse_hostdev_devs(ctx):
            hostdevs = []
            devs = ctx.xpathEval("/domain/devices/hostdev")

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

                # [device type, unique, hwlist label, hostdev mode,
                #  hostdev type, source desc label]
                hostdevs.append(["hostdev", unique, hwlabel, mode, typ,
                                 srclabel])

            return hostdevs
        return self._parse_device_xml(_parse_hostdev_devs)


    def _parse_device_xml(self, parse_function, refresh_if_necc=True):
        def parse_wrap_func(doc, ctx):
            return parse_function(ctx)

        if refresh_if_necc:
            xml = self.get_xml()
        else:
            xml = self.get_xml_no_refresh()

        return util.xml_parse_wrapper(xml, parse_wrap_func)

    def _add_xml_device(self, xml, devxml):
        """
        Add device 'devxml' to devices section of 'xml', return result
        """
        index = xml.find("</devices>")
        return xml[0:index] + devxml + xml[index:]

    def get_device_xml(self, dev_type, dev_id_info):
        vmxml = self.get_xml()

        def dev_xml_serialize(doc, ctx):
            nodes = self._get_device_xml_helper(ctx, dev_type, dev_id_info)
            if nodes:
                return nodes[0].serialize()

        return util.xml_parse_wrapper(vmxml, dev_xml_serialize)

    def _get_device_xml_helper(self, ctx, dev_type, dev_id_info):
        """Does all the work of looking up the device in the VM xml"""

        if dev_type=="interface":
            ret = ctx.xpathEval("/domain/devices/interface[mac/@address='%s']" % dev_id_info)

        elif dev_type=="disk":
            ret = ctx.xpathEval("/domain/devices/disk[target/@dev='%s']" % \
                                dev_id_info)

        elif dev_type=="input":
            typ, bus = dev_id_info
            ret = ctx.xpathEval("/domain/devices/input[@type='%s' and @bus='%s']" % (typ, bus))

        elif dev_type=="graphics":
            ret = ctx.xpathEval("/domain/devices/graphics[@type='%s']" % \
                                dev_id_info)

        elif dev_type == "sound":
            ret = ctx.xpathEval("/domain/devices/sound[@model='%s']" % \
                                dev_id_info)

        elif dev_type == "parallel" or dev_type == "console" or \
             dev_type == "serial":
            ret = ctx.xpathEval("/domain/devices/%s[target/@port='%s']" % (dev_type, dev_id_info))

            # If serial and console are both present, console is
            # probably (always?) just a dup of the 'primary' serial
            # device. Try and find an associated console device with
            # the same port and remove that as well, otherwise the
            # removal doesn't go through on libvirt <= 0.4.4
            if dev_type == "serial":
                cons_ret = ctx.xpathEval("/domain/devices/console[target/@port='%s']" % dev_id_info)
                if cons_ret and len(cons_ret) > 0:
                    ret.append(cons_ret[0])

        elif dev_type == "hostdev":
            # This whole process is a little funky, since we need a decent
            # amount of info to determine which specific hostdev to remove

            xmlbase = "/domain/devices/hostdev[@type='%s' and " % \
                      dev_id_info["type"]
            xpath = ""
            ret = []

            addr = dev_id_info.get("address")
            vend = dev_id_info.get("vendor")
            prod = dev_id_info.get("product")
            if addr:
                bus = addr.get("bus")
                dev = addr.get("device")
                slot = addr.get("slot")
                funct = addr.get("function")
                dom = addr.get("domain")

                if bus and dev:
                    # USB by bus and dev
                    xpath = (xmlbase + "source/address/@bus='%s' and "
                                       "source/address/@device='%s']" %
                                       (bus, dev))
                elif bus and slot and funct and dom:
                    # PCI by bus,slot,funct,dom
                    xpath = (xmlbase + "source/address/@bus='%s' and "
                                       "source/address/@slot='%s' and "
                                       "source/address/@function='%s' and "
                                       "source/address/@domain='%s']" %
                                       (bus, slot, funct, dom))

            elif vend.get("id") and prod.get("id"):
                # USB by vendor and product
                xpath = (xmlbase + "source/vendor/@id='%s' and "
                                   "source/product/@id='%s']" %
                                   (vend.get("id"), prod.get("id")))

            if xpath:
                # Log this, since we could hit issues with unexpected
                # xml parameters in the future
                logging.debug("Hostdev xpath string: %s" % xpath)
                ret = ctx.xpathEval(xpath)

        elif dev_type == "video":
            model, ram, heads = dev_id_info
            xpath = "/domain/devices/video"

            xpath += "[model/@type='%s'" % model
            if ram:
                xpath += " and model/@vram='%s'" % ram
            if heads:
                xpath += " and model/@heads='%s'" % heads
            xpath += "][1]"

            ret = ctx.xpathEval(xpath)

        else:
            raise RuntimeError, _("Unknown device type '%s'" % dev_type)

        return ret

    def _remove_xml_device(self, vmxml, dev_type, dev_id_info):
        """
        Remove device 'devxml' from devices section of 'xml, return result
        """

        def unlink_dev_node(doc, ctx):
            ret = self._get_device_xml_helper(ctx, dev_type, dev_id_info)

            if ret and len(ret) > 0:
                if len(ret) > 1 and ret[0].name == "serial" and \
                   ret[1].name == "console":
                    ret[1].unlinkNode()
                    ret[1].freeNode()

                ret[0].unlinkNode()
                ret[0].freeNode()
                newxml = doc.serialize()
                return newxml
            else:
                raise ValueError(_("Didn't find the specified device to "
                                   "remove. Device was: %s %s" % \
                                   (dev_type, str(dev_id_info))))

        return util.xml_parse_wrapper(vmxml, unlink_dev_node)

    def attach_device(self, xml):
        """Hotplug device to running guest"""
        if self.is_active():
            self.vm.attachDevice(xml)

    def detach_device(self, xml):
        """Hotunplug device from running guest"""
        if self.is_active():
            self.vm.detachDevice(xml)

    def add_device(self, devxml):
        """Redefine guest with appended device"""
        self.redefine(self._add_xml_device, devxml)

    def remove_device(self, dev_type, dev_id_info):
        self.redefine(self._remove_xml_device, dev_type, dev_id_info)

    def _change_cdrom(self, newdev, dev_id_info):
        # If vm is shutoff, remove device, and redefine with media
        if not self.is_active():
            def change_cdrom_helper(origxml, newdev, dev_id_info):
                tmpxml = self._remove_xml_device(origxml, "disk", dev_id_info)
                return self._add_xml_device(tmpxml, newdev)

            self.redefine(change_cdrom_helper, newdev, dev_id_info)
        else:
            self.attach_device(newdev)

    def connect_cdrom_device(self, _type, source, dev_id_info):
        xml = self.get_device_xml("disk", dev_id_info)

        def cdrom_xml_connect(doc, ctx):
            disk_fragment = ctx.xpathEval("/disk")[0]
            driver_fragment = ctx.xpathEval("/disk/driver")
            disk_fragment.setProp("type", _type)
            elem = disk_fragment.newChild(None, "source", None)

            if _type == "file":
                elem.setProp("file", source)
                driver_name = _type
            else:
                elem.setProp("dev", source)
                driver_name = "phy"

            if driver_fragment:
                driver_fragment = driver_fragment[0]
                orig_name = driver_fragment.prop("name")

                # For Xen, the driver name is dependent on the storage type
                # (file or phys).
                if orig_name and orig_name in [ "file", "phy" ]:
                    driver_fragment.setProp("name", driver_name)

            return disk_fragment.serialize()

        result = util.xml_parse_wrapper(xml, cdrom_xml_connect)
        logging.debug("connect_cdrom produced: %s" % result)
        self._change_cdrom(result, dev_id_info)

    def disconnect_cdrom_device(self, dev_id_info):
        xml = self.get_device_xml("disk", dev_id_info)

        def cdrom_xml_disconnect(doc, ctx):
            disk_fragment = ctx.xpathEval("/disk")[0]
            sourcenode = None

            for child in disk_fragment.children:
                if child.name == "source":
                    sourcenode = child
                    break
                else:
                    continue

            sourcenode.unlinkNode()
            sourcenode.freeNode()
            return disk_fragment.serialize()

        result = util.xml_parse_wrapper(xml, cdrom_xml_disconnect)
        logging.debug("eject_cdrom produced: %s" % result)
        self._change_cdrom(result, dev_id_info)

    def hotplug_vcpu(self, vcpus):
        self.vm.setVcpus(int(vcpus))

    def hotplug_vcpus(self, vcpus):
        vcpus = int(vcpus)
        if vcpus != self.vcpu_count():
            self.vm.setVcpus(vcpus)

    def get_cpuset_syntax_error(self, val):
        # We need to allow None value and empty string so we can't get
        # rid of this function
        if len(val) == 0:
            return None

        guest = virtinst.Guest(connection = self.get_connection().vmm)
        guest.cpuset = val

    def define_vcpus(self, vcpus, cpuset=None):
        vcpus = int(vcpus)

        def set_node(doc, ctx, vcpus, cpumask, xpath):
            node = ctx.xpathEval(xpath)
            node = (node and node[0] or None)

            if node:
                node.setContent(str(vcpus))

                # If cpuset mask is not valid, don't change it
                # If cpuset mask is None, we don't want to use cpuset
                if cpumask is None or (cpumask is not None
                    and len(cpumask) == 0):
                    node.unsetProp("cpuset")
                elif not self.get_cpuset_syntax_error(cpumask):
                    node.setProp("cpuset", cpumask)
            return doc.serialize()

        def change_vcpu_xml(xml, vcpus, cpuset):
            return util.xml_parse_wrapper(xml, set_node, vcpus, cpuset,
                                          "/domain/vcpu[1]")

        self.redefine(change_vcpu_xml, vcpus, cpuset)

    def hotplug_memory(self, memory):
        if memory != self.get_memory():
            self.vm.setMemory(memory)

    def hotplug_maxmem(self, maxmem):
        if maxmem != self.maximum_memory():
            self.vm.setMaxMemory(maxmem)

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

        self.redefine(change_mem_xml, memory, maxmem)

    def get_autostart(self):
        return self.vm.autostart()

    def set_autostart(self, val):
        if self.get_autostart() != val:
            self.vm.setAutostart(val)

    def get_boot_device(self):
        xml = self.get_xml()

        def get_boot_xml(doc, ctx):
            ret = ctx.xpathEval("/domain/os/boot[1]")
            for node in ret:
                dev = node.prop("dev")
            return dev

        return util.xml_parse_wrapper(xml, get_boot_xml)

    def set_boot_device(self, boot_type):
        logging.debug("Setting boot device to type: %s" % boot_type)

        def set_boot_xml(doc, ctx):
            node = ctx.xpathEval("/domain/os/boot[1]")
            node = (node and node[0] or None)

            if node and node.prop("dev"):
                node.setProp("dev", boot_type)

            return doc.serialize()

        self.redefine(util.xml_parse_wrapper, set_boot_xml)

    def get_seclabel(self):
        xml = self.get_xml()
        model = vutil.get_xml_path(xml, "/domain/seclabel/@model")
        t     = vutil.get_xml_path(self.get_xml(), "/domain/seclabel/@type")
        label = vutil.get_xml_path(self.get_xml(), "/domain/seclabel/label")

        return [model, t or "dynamic", label or ""]

    def define_seclabel(self, model, t, label):
        logging.debug("Changing seclabel with model=%s t=%s label=%s" %
                      (model, t, label))

        def change_label(doc, ctx):
            secnode = ctx.xpathEval("/domain/seclabel")
            secnode = (secnode and secnode[0] or None)

            if not model:
                if secnode:
                    secnode.unlinkNode()

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

        self.redefine(util.xml_parse_wrapper,
                      change_label)

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


    def migrate(self, destconn):
        flags = 0
        if self.lastStatus == libvirt.VIR_DOMAIN_RUNNING:
            flags = libvirt.VIR_MIGRATE_LIVE

        newxml = self.get_xml()

        self.vm.migrate(destconn.vmm, flags, None, None, 0)

        destconn.define_domain(newxml)

gobject.type_register(vmmDomain)
