#
# Copyright (C) 2006, 2013, 2014 Red Hat, Inc.
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

import logging
import os
import time
import threading

import libvirt

from gi.repository import GObject

from virtinst import DomainCapabilities
from virtinst import DomainSnapshot
from virtinst import Guest
from virtinst import util
from virtinst import VirtualController
from virtinst import VirtualDisk

from .libvirtobject import vmmLibvirtObject

if not hasattr(libvirt, "VIR_DOMAIN_PMSUSPENDED"):
    setattr(libvirt, "VIR_DOMAIN_PMSUSPENDED", 7)

vm_status_icons = {
    libvirt.VIR_DOMAIN_BLOCKED: "state_running",
    libvirt.VIR_DOMAIN_CRASHED: "state_shutoff",
    libvirt.VIR_DOMAIN_PAUSED: "state_paused",
    libvirt.VIR_DOMAIN_RUNNING: "state_running",
    libvirt.VIR_DOMAIN_SHUTDOWN: "state_shutoff",
    libvirt.VIR_DOMAIN_SHUTOFF: "state_shutoff",
    libvirt.VIR_DOMAIN_NOSTATE: "state_running",
    libvirt.VIR_DOMAIN_PMSUSPENDED: "state_paused",
}


class _SENTINEL(object):
    pass


def compare_device(origdev, newdev, idx):
    devprops = {
        "disk":          ["target", "bus"],
        "interface":     ["macaddr", "vmmindex"],
        "input":         ["bus", "type", "vmmindex"],
        "sound":         ["model", "vmmindex"],
        "video":         ["model", "vmmindex"],
        "watchdog":      ["vmmindex"],
        "hostdev":       ["type", "managed", "vmmindex",
                            "product", "vendor",
                            "function", "domain", "slot"],
        "serial":        ["type", "target_port"],
        "parallel":      ["type", "target_port"],
        "console":       ["type", "target_type", "target_port"],
        "graphics":      ["type", "vmmindex"],
        "controller":    ["type", "index"],
        "channel":       ["type", "target_name"],
        "filesystem":    ["target", "vmmindex"],
        "smartcard":     ["mode", "vmmindex"],
        "redirdev":      ["bus", "type", "vmmindex"],
        "tpm":           ["type", "vmmindex"],
        "rng":           ["type", "vmmindex"],
        "panic":         ["type", "vmmindex"],
    }

    if id(origdev) == id(newdev):
        return True

    if not isinstance(origdev, type(newdev)):
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


def _find_device(guest, origdev):
    devlist = guest.get_devices(origdev.virtual_device_type)
    for idx, dev in enumerate(devlist):
        if compare_device(origdev, dev, idx):
            return dev

    return None


def start_job_progress_thread(vm, meter, progtext):
    current_thread = threading.currentThread()

    def jobinfo_cb():
        while True:
            time.sleep(.5)

            if not current_thread.isAlive():
                return False

            try:
                jobinfo = vm.job_info()
                data_total      = float(jobinfo[3])
                # data_processed  = float(jobinfo[4])
                data_remaining  = float(jobinfo[5])

                # data_total is 0 if the job hasn't started yet
                if not data_total:
                    continue

                if not meter.started:
                    meter.start(size=data_total,
                                text=progtext)

                progress = data_total - data_remaining
                meter.update(progress)
            except Exception:
                logging.exception("Error calling jobinfo")
                return False

        return True

    if vm.getjobinfo_supported:
        t = threading.Thread(target=jobinfo_cb,
                             name="job progress reporting",
                             args=())
        t.daemon = True
        t.start()


class vmmInspectionData(object):
    def __init__(self):
        self.os_type = None
        self.distro = None
        self.major_version = None
        self.minor_version = None
        self.hostname = None
        self.product_name = None
        self.product_variant = None
        self.icon = None
        self.applications = None
        self.error = False


class vmmDomainSnapshot(vmmLibvirtObject):
    """
    Class wrapping a virDomainSnapshot object
    """
    def __init__(self, conn, backend):
        vmmLibvirtObject.__init__(self, conn, backend, backend.getName(),
                                  DomainSnapshot)


    ##########################
    # Required class methods #
    ##########################

    def _backend_get_name(self):
        return self._backend.getName()

    def _conn_tick_poll_param(self):
        return None
    def class_name(self):
        return "snapshot"

    def _XMLDesc(self, flags):
        return self._backend.getXMLDesc(flags=flags)
    def _get_backend_status(self):
        return self._STATUS_ACTIVE

    def tick(self, stats_update=True):
        ignore = stats_update
    def _init_libvirt_state(self):
        self.ensure_latest_xml()


    ###########
    # Actions #
    ###########

    def delete(self, force=True):
        ignore = force
        self._backend.delete()

    def run_status(self):
        status = DomainSnapshot.state_str_to_int(self.get_xmlobj().state)
        return vmmDomain.pretty_run_status(status)
    def run_status_icon_name(self):
        status = DomainSnapshot.state_str_to_int(self.get_xmlobj().state)
        if status not in vm_status_icons:
            logging.debug("Unknown status %d, using NOSTATE", status)
            status = libvirt.VIR_DOMAIN_NOSTATE
        return vm_status_icons[status]

    def is_current(self):
        return self._backend.isCurrent()
    def is_external(self):
        if self.get_xmlobj().memory_type == "external":
            return True
        for disk in self.get_xmlobj().disks:
            if disk.snapshot == "external":
                return True
        return False


class vmmDomain(vmmLibvirtObject):
    """
    Class wrapping virDomain libvirt objects. Is also extended to be
    backed by a virtinst.Guest object for new VM 'customize before install'
    """
    __gsignals__ = {
        "resources-sampled": (GObject.SignalFlags.RUN_FIRST, None, []),
        "inspection-changed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "pre-startup": (GObject.SignalFlags.RUN_FIRST, None, [object]),
    }

    @staticmethod
    def pretty_run_status(status, has_saved=False):
        if status == libvirt.VIR_DOMAIN_RUNNING:
            return _("Running")
        elif status == libvirt.VIR_DOMAIN_PAUSED:
            return _("Paused")
        elif status == libvirt.VIR_DOMAIN_SHUTDOWN:
            return _("Shutting Down")
        elif status == libvirt.VIR_DOMAIN_SHUTOFF:
            if has_saved:
                return _("Saved")
            else:
                return _("Shutoff")
        elif status == libvirt.VIR_DOMAIN_CRASHED:
            return _("Crashed")
        elif status == libvirt.VIR_DOMAIN_PMSUSPENDED:
            return _("Suspended")

        logging.debug("Unknown status %s, returning 'Unknown'", status)
        return _("Unknown")

    @staticmethod
    def pretty_status_reason(status, reason):
        def key(x, y):
            return getattr(libvirt, "VIR_DOMAIN_" + x, y)
        reasons = {
            libvirt.VIR_DOMAIN_RUNNING: {
                key("RUNNING_BOOTED", 1):             _("Booted"),
                key("RUNNING_MIGRATED", 2):           _("Migrated"),
                key("RUNNING_RESTORED", 3):           _("Restored"),
                key("RUNNING_FROM_SNAPSHOT", 4):      _("From snapshot"),
                key("RUNNING_UNPAUSED", 5):           _("Unpaused"),
                key("RUNNING_MIGRATION_CANCELED", 6): _("Migration canceled"),
                key("RUNNING_SAVE_CANCELED", 7):      _("Save canceled"),
                key("RUNNING_WAKEUP", 8):             _("Event wakeup"),
                key("RUNNING_CRASHED", 9):            _("Crashed"),
            },
            libvirt.VIR_DOMAIN_PAUSED: {
                key("PAUSED_USER", 1):                _("User"),
                key("PAUSED_MIGRATION", 2):           _("Migrating"),
                key("PAUSED_SAVE", 3):                _("Saving"),
                key("PAUSED_DUMP", 4):                _("Dumping"),
                key("PAUSED_IOERROR", 5):             _("I/O error"),
                key("PAUSED_WATCHDOG", 6):            _("Watchdog"),
                key("PAUSED_FROM_SNAPSHOT", 7):       _("From snapshot"),
                key("PAUSED_SHUTTING_DOWN", 8):       _("Shutting down"),
                key("PAUSED_SNAPSHOT", 9):            _("Creating snapshot"),
                key("PAUSED_CRASHED", 10):            _("Crashed"),
            },
            libvirt.VIR_DOMAIN_SHUTDOWN: {
                key("SHUTDOWN_USER", 1):              _("User"),
            },
            libvirt.VIR_DOMAIN_SHUTOFF: {
                key("SHUTOFF_SHUTDOWN", 1):           _("Shut Down"),
                key("SHUTOFF_DESTROYED", 2):          _("Destroyed"),
                key("SHUTOFF_CRASHED", 3):            _("Crashed"),
                key("SHUTOFF_MIGRATED", 4):           _("Migrated"),
                key("SHUTOFF_SAVED", 5):              _("Saved"),
                key("SHUTOFF_FAILED", 6):             _("Failed"),
                key("SHUTOFF_FROM_SNAPSHOT", 7):      _("From snapshot"),
            },
            libvirt.VIR_DOMAIN_CRASHED: {
                key("CRASHED_PANICKED", 1):           _("Panicked"),
            }
        }
        return reasons.get(status) and reasons[status].get(reason)

    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, Guest)

        self.cloning = False

        self._stats = []
        self._stats_rates = {
            "diskRdRate":   10.0,
            "diskWrRate":   10.0,
            "netTxRate":    10.0,
            "netRxRate":    10.0,
        }

        self._install_abort = False
        self._id = None
        self._uuid = None
        self._has_managed_save = None
        self._snapshot_list = None
        self._autostart = None
        self._domain_caps = None
        self._status_reason = None

        self.managedsave_supported = False
        self.remote_console_supported = False
        self.title_supported = False
        self.mem_stats_supported = False
        self.domain_state_supported = False

        self._enable_mem_stats = False
        self._enable_cpu_stats = False
        self._mem_stats_period_is_set = False

        self._enable_net_poll = False
        self._stats_net_supported = True
        self._stats_net_skip = []

        self._enable_disk_poll = False
        self._stats_disk_supported = True
        self._stats_disk_skip = []
        self._summary_disk_stats_skip = False

        self.inspection = vmmInspectionData()

    def _cleanup(self):
        for snap in self._snapshot_list or []:
            snap.cleanup()
        self._snapshot_list = None

    def _init_libvirt_state(self):
        self.managedsave_supported = self.conn.check_support(
            self.conn.SUPPORT_DOMAIN_MANAGED_SAVE, self._backend)
        self.remote_console_supported = self.conn.check_support(
            self.conn.SUPPORT_DOMAIN_CONSOLE_STREAM, self._backend)
        self.title_supported = self.conn.check_support(
            self.conn.SUPPORT_DOMAIN_GET_METADATA, self._backend)
        self.mem_stats_supported = self.conn.check_support(
            self.conn.SUPPORT_DOMAIN_MEMORY_STATS, self._backend)
        self.domain_state_supported = self.conn.check_support(
            self.conn.SUPPORT_DOMAIN_STATE, self._backend)

        # Determine available XML flags (older libvirt versions will error
        # out if passed SECURE_XML, INACTIVE_XML, etc)
        (self._inactive_xml_flags,
         self._active_xml_flags) = self.conn.get_dom_flags(self._backend)

        # This needs to come before initial stats tick
        self._on_config_sample_network_traffic_changed()
        self._on_config_sample_disk_io_changed()
        self._on_config_sample_mem_stats_changed()
        self._on_config_sample_cpu_stats_changed()

        # Prime caches
        info = self._backend.info()
        self._refresh_status(newstatus=info[0])
        self._tick_stats(info)
        self.has_managed_save()
        self.snapshots_supported()

        # Hook up listeners that need to be cleaned up
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

        if (self.get_name() == "Domain-0" and
            self.get_uuid() == "00000000-0000-0000-0000-000000000000"):
            # We don't want virt-manager to track Domain-0 since it
            # doesn't work with our UI. Raising an error will ensures it
            # is blacklisted.
            raise RuntimeError("Can't track Domain-0 as a vmmDomain")

        self.connect("pre-startup", self._prestartup_nodedev_check)

    def _prestartup_nodedev_check(self, src, ret):
        ignore = src
        error = _("There is more than one '%s' device attached to "
                  "your host, and we can't determine which one to "
                  "use for your guest.\n"
                  "To fix this, remove and reattach the USB device "
                  "to your guest using the 'Add Hardware' wizard.")

        for hostdev in self.get_hostdev_devices():
            devtype = hostdev.type

            if devtype != "usb":
                continue

            vendor = hostdev.vendor
            product = hostdev.product
            bus = hostdev.bus
            device = hostdev.device

            if vendor and product:
                count = self.conn.get_nodedev_count("usb_device",
                                                      vendor,
                                                      product)
                if count > 1 and not (bus and device):
                    prettyname = "%s %s" % (vendor, product)
                    ret.append(error % prettyname)


    ###########################
    # Misc API getter methods #
    ###########################

    def reports_stats(self):
        return True
    def _using_events(self):
        return self.conn.using_domain_events

    def get_id(self):
        if self._id is None:
            self._id = self._backend.ID()
        return self._id

    def status(self):
        return self._normalize_status(self._get_status())

    def status_reason(self):
        if self._status_reason is None:
            self._status_reason = 1
            if self.domain_state_supported:
                self._status_reason = self._backend.state()[1]
        return self._status_reason

    def get_cloning(self):
        return self.cloning
    def set_cloning(self, val):
        self.cloning = bool(val)

    # If manual shutdown or destroy specified, make sure we don't continue
    # install process
    def get_install_abort(self):
        return bool(self._install_abort)

    def stable_defaults(self):
        return self.get_xmlobj().stable_defaults()

    def has_spicevmc_type_redirdev(self):
        devs = self.get_redirdev_devices()
        for dev in devs:
            if dev.type == "spicevmc":
                return True
        return False

    def get_id_pretty(self):
        i = self.get_id()
        if i < 0:
            return "-"
        return str(i)

    def has_nvram(self):
        return bool(self.get_xmlobj().os.loader_ro is True and
                    self.get_xmlobj().os.loader_type == "pflash")

    def is_persistent(self):
        return bool(self._backend.isPersistent())

    ##################
    # Support checks #
    ##################

    def _get_getvcpus_supported(self):
        return self.conn.check_support(
            self.conn.SUPPORT_DOMAIN_GETVCPUS, self._backend)
    getvcpus_supported = property(_get_getvcpus_supported)

    def _get_getjobinfo_supported(self):
        return self.conn.check_support(
            self.conn.SUPPORT_DOMAIN_JOB_INFO, self._backend)
    getjobinfo_supported = property(_get_getjobinfo_supported)

    def snapshots_supported(self):
        if not self.conn.check_support(
                self.conn.SUPPORT_DOMAIN_LIST_SNAPSHOTS, self._backend):
            return _("Libvirt connection does not support snapshots.")

        if self.list_snapshots():
            return

        # Check if our disks are all qcow2
        seen_qcow2 = False
        for disk in self.get_disk_devices(refresh_if_nec=False):
            if disk.read_only:
                continue
            if not disk.path:
                continue
            if disk.driver_type == "qcow2":
                seen_qcow2 = True
                continue
            return _("Snapshots are only supported if all writeable disks "
                     "images allocated to the guest are qcow2 format.")
        if not seen_qcow2:
            return _("Snapshots require at least one writeable qcow2 disk "
                     "image allocated to the guest.")

    def get_domain_capabilities(self):
        if not self._domain_caps:
            self._domain_caps = DomainCapabilities.build_from_guest(
                self.get_xmlobj())
        return self._domain_caps


    #############################
    # Internal XML handling API #
    #############################

    def _invalidate_xml(self):
        vmmLibvirtObject._invalidate_xml(self)
        self._id = None
        self._status_reason = None
        self._has_managed_save = None

    def _lookup_device_to_define(self, xmlobj, origdev, for_hotplug):
        if for_hotplug:
            return origdev

        dev = _find_device(xmlobj, origdev)
        if dev:
            return dev

        # If we are removing multiple dev from an active VM, a double
        # attempt may result in a lookup failure. If device is present
        # in the active XML, assume all is good.
        if _find_device(self.get_xmlobj(), origdev):
            logging.debug("Device in active config but not inactive config.")
            return

        raise RuntimeError(_("Could not find specified device in the "
                             "inactive VM configuration: %s") % repr(origdev))

    def _copy_nvram_file(self, new_name):
        """
        We need to do this copy magic because there is no Libvirt storage API
        to rename storage volume.
        """
        old_nvram = VirtualDisk(self.conn.get_backend())
        old_nvram.path = self.get_xmlobj().os.nvram

        nvram_dir = os.path.dirname(old_nvram.path)
        new_nvram_path = os.path.join(nvram_dir, "%s_VARS.fd" % new_name)
        new_nvram = VirtualDisk(self.conn.get_backend())

        nvram_install = VirtualDisk.build_vol_install(
                self.conn.get_backend(), os.path.basename(new_nvram_path),
                old_nvram.get_parent_pool(), old_nvram.get_size(), False)
        nvram_install.input_vol = old_nvram.get_vol_object()
        nvram_install.sync_input_vol(only_format=True)

        new_nvram.set_vol_install(nvram_install)
        new_nvram.validate()
        new_nvram.setup()

        return new_nvram, old_nvram


    ##############################
    # Persistent XML change APIs #
    ##############################

    def rename_domain(self, new_name):
        new_nvram = None
        old_nvram = None
        if self.has_nvram():
            new_nvram, old_nvram = self._copy_nvram_file(new_name)

        try:
            self.define_name(new_name)
        except Exception as error:
            if new_nvram:
                try:
                    new_nvram.get_vol_object().delete(0)
                except Exception as warn:
                    logging.debug("rename failed and new nvram was not "
                                  "removed: '%s'", warn)
            raise error

        if new_nvram:
            try:
                old_nvram.get_vol_object().delete(0)
            except Exception as warn:
                logging.debug("old nvram file was not removed: '%s'", warn)

            self.define_overview(nvram=new_nvram.path)

    # Device Add/Remove
    def add_device(self, devobj):
        """
        Redefine guest with appended device XML 'devxml'
        """
        xmlobj = self._make_xmlobj_to_define()
        xmlobj.add_device(devobj)
        self._redefine_xmlobj(xmlobj)

    def remove_device(self, devobj):
        """
        Remove passed device from the inactive guest XML
        """
        # HACK: If serial and console are both present, they both need
        # to be removed at the same time
        con = None
        if hasattr(devobj, "virtmanager_console_dup"):
            con = getattr(devobj, "virtmanager_console_dup")

        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, False)
        if not editdev:
            return

        if con:
            rmcon = _find_device(xmlobj, con)
            if rmcon:
                xmlobj.remove_device(rmcon)
        xmlobj.remove_device(editdev)

        self._redefine_xmlobj(xmlobj)

    def define_cpu(self, vcpus=_SENTINEL, maxvcpus=_SENTINEL,
            model=_SENTINEL, sockets=_SENTINEL,
            cores=_SENTINEL, threads=_SENTINEL):
        guest = self._make_xmlobj_to_define()

        if vcpus != _SENTINEL:
            guest.curvcpus = int(vcpus)
        if maxvcpus != _SENTINEL:
            guest.vcpus = int(maxvcpus)

        if sockets != _SENTINEL:
            guest.cpu.sockets = sockets
            guest.cpu.cores = cores
            guest.cpu.threads = threads

        if model != _SENTINEL:
            if model in guest.cpu.SPECIAL_MODES:
                guest.cpu.set_special_mode(model)
            else:
                guest.cpu.model = model
        self._redefine_xmlobj(guest)

    def define_memory(self, memory=_SENTINEL, maxmem=_SENTINEL):
        guest = self._make_xmlobj_to_define()

        if memory != _SENTINEL:
            guest.memory = int(memory)
        if maxmem != _SENTINEL:
            guest.maxmemory = int(maxmem)
        self._redefine_xmlobj(guest)

    def define_overview(self, machine=_SENTINEL, description=_SENTINEL,
            title=_SENTINEL, idmap_list=_SENTINEL, loader=_SENTINEL,
            nvram=_SENTINEL):
        guest = self._make_xmlobj_to_define()
        if machine != _SENTINEL:
            guest.os.machine = machine
            self._domain_caps = None
        if description != _SENTINEL:
            guest.description = description or None
        if title != _SENTINEL:
            guest.title = title or None

        if loader != _SENTINEL:
            if loader is None:
                # Implies seabios, aka the default, so clear everything
                guest.os.loader = None
                guest.os.loader_ro = None
                guest.os.loader_type = None
                guest.os.nvram = None
                guest.os.nvram_template = None
            else:
                # Implies UEFI
                guest.os.loader = loader
                guest.os.loader_type = "pflash"
                guest.os.loader_ro = True
                guest.check_uefi_secure()

        if nvram != _SENTINEL:
            guest.os.nvram = nvram

        if idmap_list != _SENTINEL:
            if idmap_list is not None:
                # pylint: disable=unpacking-non-sequence
                (uid_target, uid_count, gid_target, gid_count) = idmap_list
                guest.idmap.uid_start = 0
                guest.idmap.uid_target = uid_target
                guest.idmap.uid_count = uid_count
                guest.idmap.gid_start = 0
                guest.idmap.gid_target = gid_target
                guest.idmap.gid_count = gid_count
            else:
                guest.idmap.clear()

        self._redefine_xmlobj(guest)

    def define_boot(self, boot_order=_SENTINEL, boot_menu=_SENTINEL,
            kernel=_SENTINEL, initrd=_SENTINEL, dtb=_SENTINEL,
            kernel_args=_SENTINEL, init=_SENTINEL, initargs=_SENTINEL):

        guest = self._make_xmlobj_to_define()
        def _change_boot_order():
            boot_dev_order = []
            devmap = dict((dev.vmmidstr, dev) for dev in
                          self.get_bootable_devices())
            for b in boot_order:
                if b in devmap:
                    boot_dev_order.append(devmap[b])

            # Unset the traditional boot order
            guest.os.bootorder = []

            # Unset device boot order
            for dev in guest.get_all_devices():
                dev.boot.order = None

            count = 1
            for origdev in boot_dev_order:
                dev = self._lookup_device_to_define(guest, origdev, False)
                if not dev:
                    continue
                dev.boot.order = count
                count += 1

        if boot_order != _SENTINEL:
            if self.can_use_device_boot_order():
                _change_boot_order()
            else:
                guest.os.bootorder = boot_order

        if boot_menu != _SENTINEL:
            guest.os.enable_bootmenu = bool(boot_menu)
        if init != _SENTINEL:
            guest.os.init = init
            guest.os.set_initargs_string(initargs)

        if kernel != _SENTINEL:
            guest.os.kernel = kernel or None
        if initrd != _SENTINEL:
            guest.os.initrd = initrd or None
        if dtb != _SENTINEL:
            guest.os.dtb = dtb or None
        if kernel_args != _SENTINEL:
            guest.os.kernel_args = kernel_args or None

        self._redefine_xmlobj(guest)


    ######################
    # Device XML editing #
    ######################

    def define_disk(self, devobj, do_hotplug,
            path=_SENTINEL, readonly=_SENTINEL, serial=_SENTINEL,
            shareable=_SENTINEL, removable=_SENTINEL, cache=_SENTINEL,
            io=_SENTINEL, driver_type=_SENTINEL, bus=_SENTINEL, addrstr=_SENTINEL,
            sgio=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        def _change_bus():
            oldprefix = editdev.get_target_prefix()[0]
            oldbus = editdev.bus
            editdev.bus = bus

            if oldbus == bus:
                return

            editdev.address.clear()
            editdev.address.set_addrstr(addrstr)

            if oldprefix == editdev.get_target_prefix()[0]:
                return

            used = []
            disks = (self.get_disk_devices() +
                     self.get_disk_devices(inactive=True))
            for d in disks:
                used.append(d.target)

            if editdev.target:
                used.remove(editdev.target)

            editdev.target = None
            editdev.generate_target(used)

        if path != _SENTINEL:
            editdev.path = path
            if not do_hotplug:
                editdev.sync_path_props()

        if readonly != _SENTINEL:
            editdev.read_only = readonly
        if shareable != _SENTINEL:
            editdev.shareable = shareable
        if removable != _SENTINEL:
            editdev.removable = removable

        if cache != _SENTINEL:
            editdev.driver_cache = cache or None
        if io != _SENTINEL:
            editdev.driver_io = io or None
        if driver_type != _SENTINEL:
            editdev.driver_type = driver_type or None
        if serial != _SENTINEL:
            editdev.serial = serial or None

        if sgio != _SENTINEL:
            editdev.sgio = sgio or None

        if bus != _SENTINEL:
            _change_bus()

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)

    def define_network(self, devobj, do_hotplug,
            ntype=_SENTINEL, source=_SENTINEL,
            mode=_SENTINEL, model=_SENTINEL, addrstr=_SENTINEL,
            vtype=_SENTINEL, managerid=_SENTINEL, typeid=_SENTINEL,
            typeidversion=_SENTINEL, instanceid=_SENTINEL,
            portgroup=_SENTINEL, macaddr=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        if ntype != _SENTINEL:
            editdev.source = None

            editdev.type = ntype
            editdev.source = source
            editdev.source_mode = mode or None
            editdev.portgroup = portgroup or None

        if model != _SENTINEL:
            if editdev.model != model:
                editdev.address.clear()
                editdev.address.set_addrstr(addrstr)
            editdev.model = model

        if vtype != _SENTINEL:
            editdev.virtualport.type = vtype or None
            editdev.virtualport.managerid = managerid or None
            editdev.virtualport.typeid = typeid or None
            editdev.virtualport.typeidversion = typeidversion or None
            editdev.virtualport.instanceid = instanceid or None

        if macaddr != _SENTINEL:
            editdev.macaddr = macaddr

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)

    def define_graphics(self, devobj, do_hotplug,
            listen=_SENTINEL, addr=_SENTINEL, port=_SENTINEL, tlsport=_SENTINEL,
            passwd=_SENTINEL, keymap=_SENTINEL, gtype=_SENTINEL,
            gl=_SENTINEL, rendernode=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        if addr != _SENTINEL:
            editdev.listen = addr
        if port != _SENTINEL:
            editdev.port = port
        if tlsport != _SENTINEL:
            editdev.tlsPort = tlsport
        if passwd != _SENTINEL:
            editdev.passwd = passwd
        if keymap != _SENTINEL:
            editdev.keymap = keymap
        if gtype != _SENTINEL:
            editdev.type = gtype
        if gl != _SENTINEL:
            editdev.gl = gl
        if rendernode != _SENTINEL:
            editdev.rendernode = rendernode
        if listen != _SENTINEL:
            listentype = editdev.get_first_listen_type()
            if listen == 'none':
                editdev.set_listen_none()
            elif listentype and listentype == 'none':
                editdev.remove_all_listens()

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)

    def define_sound(self, devobj, do_hotplug, model=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        if model != _SENTINEL:
            if editdev.model != model:
                editdev.address.clear()
            editdev.model = model

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)

    def define_video(self, devobj, do_hotplug, model=_SENTINEL, accel3d=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        if model != _SENTINEL and model != editdev.model:
            editdev.model = model
            editdev.address.clear()

            # Clear out heads/ram values so they reset to default. If
            # we ever allow editing these values in the UI we should
            # drop this
            editdev.vram = None
            editdev.heads = None
            editdev.ram = None
            editdev.vgamem = None
            editdev.accel3d = None

        if accel3d != _SENTINEL:
            editdev.accel3d = accel3d

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)

    def define_watchdog(self, devobj, do_hotplug,
            model=_SENTINEL, action=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        if model != _SENTINEL:
            if editdev.model != model:
                editdev.address.clear()
            editdev.model = model

        if action != _SENTINEL:
            editdev.action = action

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)

    def define_smartcard(self, devobj, do_hotplug, model=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        if model != _SENTINEL:
            editdev.mode = model
            editdev.type = editdev.TYPE_DEFAULT

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)

    def define_controller(self, devobj, do_hotplug, model=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        def _change_model():
            if editdev.type == "usb":
                ctrls = xmlobj.get_devices("controller")
                ctrls = [x for x in ctrls if (x.type ==
                         VirtualController.TYPE_USB)]
                for dev in ctrls:
                    xmlobj.remove_device(dev)

                if model == "ich9-ehci1":
                    for dev in VirtualController.get_usb2_controllers(
                            xmlobj.conn):
                        xmlobj.add_device(dev)
                else:
                    dev = VirtualController(xmlobj.conn)
                    dev.type = "usb"
                    dev.model = model
                    xmlobj.add_device(dev)

            else:
                editdev.model = model
                editdev.address.clear()
                self.hotplug(device=editdev)

        if model != _SENTINEL:
            _change_model()

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)

    def define_filesystem(self, devobj, do_hotplug, newdev=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        if newdev != _SENTINEL:
            # pylint: disable=maybe-no-member
            editdev.type = newdev.type
            editdev.accessmode = newdev.accessmode
            editdev.wrpolicy = newdev.wrpolicy
            editdev.driver = newdev.driver
            editdev.format = newdev.format
            editdev.readonly = newdev.readonly
            editdev.units = newdev.units
            editdev.source = newdev.source
            editdev.target = newdev.target

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)


    def define_hostdev(self, devobj, do_hotplug, rom_bar=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        if rom_bar != _SENTINEL:
            editdev.rom_bar = rom_bar

        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)


    ####################
    # Hotplug routines #
    ####################

    def attach_device(self, devobj):
        """
        Hotplug device to running guest
        """
        if not self.is_active():
            return

        devxml = devobj.get_xml_config()
        logging.debug("attach_device with xml=\n%s", devxml)
        self._backend.attachDevice(devxml)

    def detach_device(self, devobj):
        """
        Hotunplug device from running guest
        """
        if not self.is_active():
            return

        devxml = devobj.get_xml_config()
        logging.debug("detach_device with xml=\n%s", devxml)
        self._backend.detachDevice(devxml)

    def _update_device(self, devobj, flags=None):
        if flags is None:
            flags = getattr(libvirt, "VIR_DOMAIN_DEVICE_MODIFY_LIVE", 1)

        xml = devobj.get_xml_config()
        logging.debug("update_device with xml=\n%s", xml)
        self._backend.updateDeviceFlags(xml, flags)

    def hotplug(self, vcpus=_SENTINEL, memory=_SENTINEL, maxmem=_SENTINEL,
            description=_SENTINEL, title=_SENTINEL, device=_SENTINEL):
        if not self.is_active():
            return

        def _hotplug_memory(val):
            if val != self.get_memory():
                self._backend.setMemory(val)
        def _hotplug_maxmem(val):
            if val != self.maximum_memory():
                self._backend.setMaxMemory(val)

        def _hotplug_metadata(val, mtype):
            flags = (libvirt.VIR_DOMAIN_AFFECT_LIVE |
                     libvirt.VIR_DOMAIN_AFFECT_CONFIG)
            self._backend.setMetadata(mtype, val, None, None, flags)

        if vcpus != _SENTINEL:
            vcpus = int(vcpus)
            if vcpus != self.vcpu_count():
                self._backend.setVcpus(vcpus)

        if memory != _SENTINEL:
            logging.info("Hotplugging curmem=%s maxmem=%s for VM '%s'",
                         memory, maxmem, self.get_name())

            actual_cur = self.get_memory()
            if memory:
                if maxmem < actual_cur:
                    # Set current first to avoid error
                    _hotplug_memory(memory)
                    _hotplug_maxmem(maxmem)
                else:
                    _hotplug_maxmem(maxmem)
                    _hotplug_memory(memory)
            else:
                _hotplug_maxmem(maxmem)

        if description != _SENTINEL:
            _hotplug_metadata(description,
                libvirt.VIR_DOMAIN_METADATA_DESCRIPTION)
        if title != _SENTINEL:
            _hotplug_metadata(title, libvirt.VIR_DOMAIN_METADATA_TITLE)

        if device != _SENTINEL:
            self._update_device(device)


    ########################
    # Libvirt API wrappers #
    ########################

    def _conn_tick_poll_param(self):
        return "pollvm"
    def class_name(self):
        return "domain"

    def _define(self, xml):
        self.conn.define_domain(xml)
    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _get_backend_status(self):
        return self._backend.info()[0]

    def get_autostart(self):
        if self._autostart is None:
            self._autostart = self._backend.autostart()
        return self._autostart
    def set_autostart(self, val):
        self._backend.setAutostart(val)

        # Recache value
        self._autostart = None
        self.get_autostart()

    def job_info(self):
        return self._backend.jobInfo()
    def abort_job(self):
        self._backend.abortJob()

    def open_console(self, devname, stream, flags=0):
        return self._backend.openConsole(devname, stream, flags)

    def open_graphics_fd(self):
        flags = 0

        # Ugly workaround for VNC bug where the display cannot be opened
        # if the listen type is "none".  This bug was fixed in QEMU-2.9.0.
        graphics = self.get_graphics_devices()[0]
        if (graphics.type == "vnc" and
                graphics.get_first_listen_type() == "none" and
                not self.conn.SUPPORT_CONN_VNC_NONE_AUTH):
            flags = libvirt.VIR_DOMAIN_OPEN_GRAPHICS_SKIPAUTH

        return self._backend.openGraphicsFD(0, flags)

    def refresh_snapshots(self):
        self._snapshot_list = None

    def list_snapshots(self):
        if self._snapshot_list is None:
            newlist = []
            for rawsnap in self._backend.listAllSnapshots():
                obj = vmmDomainSnapshot(self.conn, rawsnap)
                obj.init_libvirt_state()
                newlist.append(obj)
            self._snapshot_list = newlist
        return self._snapshot_list[:]

    @vmmLibvirtObject.lifecycle_action
    def revert_to_snapshot(self, snap):
        self._backend.revertToSnapshot(snap.get_backend())

    def create_snapshot(self, xml, redefine=False):
        flags = 0
        if redefine:
            flags = (flags | libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REDEFINE)

        if not redefine:
            logging.debug("Creating snapshot flags=%s xml=\n%s", flags, xml)
        self._backend.snapshotCreateXML(xml, flags)


    ########################
    # XML Parsing routines #
    ########################

    def is_container(self):
        return self.get_xmlobj().os.is_container()
    def is_xenpv(self):
        return self.get_xmlobj().os.is_xenpv()
    def is_hvm(self):
        return self.get_xmlobj().os.is_hvm()

    def get_uuid(self):
        if self._uuid is None:
            self._uuid = self._backend.UUIDString()
        return self._uuid
    def get_abi_type(self):
        return self.get_xmlobj().os.os_type
    def get_hv_type(self):
        return self.get_xmlobj().type
    def get_pretty_hv_type(self):
        return self.conn.pretty_hv(self.get_abi_type(), self.get_hv_type())
    def get_arch(self):
        return self.get_xmlobj().os.arch
    def get_init(self):
        import pipes
        init = self.get_xmlobj().os.init
        initargs = " ".join(
            [pipes.quote(i.val) for i in self.get_xmlobj().os.initargs])
        return init, initargs

    def get_emulator(self):
        return self.get_xmlobj().emulator
    def get_machtype(self):
        return self.get_xmlobj().os.machine
    def get_idmap(self):
        return self.get_xmlobj().idmap

    def get_name_or_title(self):
        title = self.get_title()
        if title:
            return title
        return self.get_name()

    def get_title(self):
        return self.get_xmlobj().title
    def get_description(self):
        return self.get_xmlobj().description

    def get_memory(self):
        return int(self.get_xmlobj().memory)
    def maximum_memory(self):
        return int(self.get_xmlobj().maxmemory)

    def vcpu_count(self):
        return int(self.get_xmlobj().curvcpus or self.get_xmlobj().vcpus)
    def vcpu_max_count(self):
        return int(self.get_xmlobj().vcpus)

    def get_cpu_config(self):
        return self.get_xmlobj().cpu

    def _convert_old_boot_order(self):
        boot_order = self._get_old_boot_order()
        ret = []
        disk = None
        cdrom = None
        floppy = None
        net = None

        for d in self.get_disk_devices():
            if not cdrom and d.device == "cdrom":
                cdrom = d
            if not floppy and d.device == "floppy":
                floppy = d
            if not disk and d.device not in ["cdrom", "floppy"]:
                disk = d
            if cdrom and disk and floppy:
                break

        for n in self.get_network_devices():
            net = n
            break

        for b in boot_order:
            if b == "network" and net:
                ret.append(net.vmmidstr)
            if b == "hd" and disk:
                ret.append(disk.vmmidstr)
            if b == "cdrom" and cdrom:
                ret.append(cdrom.vmmidstr)
            if b == "fd" and floppy:
                ret.append(floppy.vmmidstr)
        return ret

    def _get_device_boot_order(self):
        devs = self.get_bootable_devices()
        order = []
        for dev in devs:
            if not dev.boot.order:
                continue
            order.append((dev.vmmidstr, dev.boot.order))

        if not order:
            # No devices individually marked bootable, convert traditional
            # boot XML to fine grained, for the UI.
            return self._convert_old_boot_order()

        order.sort(key=lambda p: p[1])
        return [p[0] for p in order]

    def _get_old_boot_order(self):
        return self.get_xmlobj().os.bootorder
    def get_boot_order(self):
        if self.can_use_device_boot_order():
            return self._get_device_boot_order()
        return self._get_old_boot_order()
    def get_boot_menu(self):
        guest = self.get_xmlobj()
        return bool(guest.os.enable_bootmenu)
    def get_boot_kernel_info(self):
        guest = self.get_xmlobj()
        return (guest.os.kernel, guest.os.initrd,
                guest.os.dtb, guest.os.kernel_args)

    # XML Device listing

    def get_serial_devs(self):
        devs = self.get_char_devices()
        devlist = []

        devlist += [x for x in devs if x.virtual_device_type == "serial"]
        devlist += [x for x in devs if x.virtual_device_type == "console"]
        return devlist

    def _build_device_list(self, device_type,
                           refresh_if_nec=True, inactive=False):
        guest = self.get_xmlobj(refresh_if_nec=refresh_if_nec,
                                inactive=inactive)
        devs = guest.get_devices(device_type)

        for idx, dev in enumerate(devs):
            dev.vmmindex = idx
            dev.vmmidstr = dev.virtual_device_type + ("%.3d" % idx)

        return devs

    def get_network_devices(self, refresh_if_nec=True):
        return self._build_device_list("interface", refresh_if_nec)
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
    def get_controller_devices(self):
        return self._build_device_list("controller")
    def get_filesystem_devices(self):
        return self._build_device_list("filesystem")
    def get_smartcard_devices(self):
        return self._build_device_list("smartcard")
    def get_redirdev_devices(self):
        return self._build_device_list("redirdev")
    def get_tpm_devices(self):
        return self._build_device_list("tpm")
    def get_rng_devices(self):
        return self._build_device_list("rng")
    def get_panic_devices(self):
        return self._build_device_list("panic")

    def get_disk_devices(self, refresh_if_nec=True, inactive=False):
        devs = self._build_device_list("disk", refresh_if_nec, inactive)

        # Iterate through all disks and calculate what number they are
        # HACK: We are making a variable in VirtualDisk to store the index
        idx_mapping = {}
        for dev in devs:
            devtype = dev.device
            bus = dev.bus
            key = devtype + (bus or "")

            if key not in idx_mapping:
                idx_mapping[key] = 1

            dev.disk_bus_index = idx_mapping[key]
            idx_mapping[key] += 1

        return devs

    def get_char_devices(self):
        devs = []
        serials     = self._build_device_list("serial")
        parallels   = self._build_device_list("parallel")
        consoles    = self._build_device_list("console")
        channels    = self._build_device_list("channel")

        for devicelist in [serials, parallels, consoles, channels]:
            devs.extend(devicelist)

        # Don't display <console> if it's just a duplicate of <serial>
        if (len(consoles) > 0 and len(serials) > 0):
            con = consoles[0]
            ser = serials[0]

            if (con.type == ser.type and
                con.target_type is None or con.target_type == "serial"):
                ser.virtmanager_console_dup = con
                devs.remove(con)

        return devs

    def can_use_device_boot_order(self):
        # Return 'True' if guest can use new style boot device ordering
        return self.conn.check_support(
            self.conn.SUPPORT_CONN_DEVICE_BOOTORDER)

    def get_bootable_devices(self):
        devs = self.get_disk_devices()
        devs += self.get_network_devices()
        devs += self.get_hostdev_devices()

        # redirdev can also be marked bootable, but it should be rarely
        # used and clutters the UI
        return devs


    ############################
    # Domain lifecycle methods #
    ############################

    # All these methods are usually run asynchronously from threads, so
    # let's be extra careful and have anything which might touch UI
    # or GObject.props invoked in an idle callback

    @vmmLibvirtObject.lifecycle_action
    def shutdown(self):
        self._install_abort = True
        self._backend.shutdown()

    @vmmLibvirtObject.lifecycle_action
    def reboot(self):
        self._install_abort = True
        self._backend.reboot(0)

    @vmmLibvirtObject.lifecycle_action
    def destroy(self):
        self._install_abort = True
        self._backend.destroy()

    @vmmLibvirtObject.lifecycle_action
    def reset(self):
        self._install_abort = True
        self._backend.reset(0)

    @vmmLibvirtObject.lifecycle_action
    def startup(self):
        if self.get_cloning():
            raise RuntimeError(_("Cannot start guest while cloning "
                                 "operation in progress"))

        pre_startup_ret = []
        self.emit("pre-startup", pre_startup_ret)

        for error in pre_startup_ret:
            raise RuntimeError(error)

        self._backend.create()

    @vmmLibvirtObject.lifecycle_action
    def suspend(self):
        self._backend.suspend()

    @vmmLibvirtObject.lifecycle_action
    def delete(self, force=True):
        """
        @force: True if we are deleting domain, False if we are renaming domain

        If the domain is renamed we need to keep the nvram file.
        """
        flags = 0
        if force:
            flags |= getattr(libvirt,
                             "VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA", 0)
            flags |= getattr(libvirt, "VIR_DOMAIN_UNDEFINE_MANAGED_SAVE", 0)
            if self.has_nvram():
                flags |= getattr(libvirt, "VIR_DOMAIN_UNDEFINE_NVRAM", 0)
        else:
            if self.has_nvram():
                flags |= getattr(libvirt, "VIR_DOMAIN_UNDEFINE_KEEP_NVRAM", 0)
        try:
            self._backend.undefineFlags(flags)
        except libvirt.libvirtError:
            logging.exception("libvirt undefineFlags failed, "
                              "falling back to old style")
            self._backend.undefine()

    @vmmLibvirtObject.lifecycle_action
    def resume(self):
        if self.get_cloning():
            raise RuntimeError(_("Cannot resume guest while cloning "
                                 "operation in progress"))
        self._backend.resume()

    @vmmLibvirtObject.lifecycle_action
    def save(self, meter=None):
        self._install_abort = True

        if meter:
            start_job_progress_thread(self, meter, _("Saving domain to disk"))

        self._backend.managedSave(0)

    def has_managed_save(self):
        if not self.managedsave_supported:
            return False

        if self._has_managed_save is None:
            try:
                self._has_managed_save = self._backend.hasManagedSaveImage(0)
            except libvirt.libvirtError as e:
                if not util.exception_is_libvirt_error(e, "VIR_ERR_NO_DOMAIN"):
                    raise
                return False

        return self._has_managed_save

    def remove_saved_image(self):
        if not self.has_managed_save():
            return
        self._backend.managedSaveRemove(0)
        self._has_managed_save = None


    def migrate(self, destconn, dest_uri=None,
            tunnel=False, unsafe=False, temporary=False, meter=None):
        self._install_abort = True

        flags = 0
        flags |= libvirt.VIR_MIGRATE_LIVE

        if not temporary:
            flags |= libvirt.VIR_MIGRATE_PERSIST_DEST
            flags |= libvirt.VIR_MIGRATE_UNDEFINE_SOURCE

        if tunnel:
            flags |= libvirt.VIR_MIGRATE_PEER2PEER
            flags |= libvirt.VIR_MIGRATE_TUNNELLED

        if unsafe:
            flags |= libvirt.VIR_MIGRATE_UNSAFE

        libvirt_destconn = destconn.get_backend().get_conn_for_api_arg()
        logging.debug("Migrating: conn=%s flags=%s uri=%s tunnel=%s "
            "unsafe=%s temporary=%s",
            destconn, flags, dest_uri, tunnel, unsafe, temporary)

        if meter:
            start_job_progress_thread(self, meter, _("Migrating domain"))

        params = {}
        if dest_uri and not tunnel:
            params[libvirt.VIR_MIGRATE_PARAM_URI] = dest_uri

        if tunnel:
            self._backend.migrateToURI3(dest_uri, params, flags)
        else:
            self._backend.migrate3(libvirt_destconn, params, flags)

        # Don't schedule any conn update, migrate dialog handles it for us


    #################
    # Stats helpers #
    #################

    def _sample_cpu_stats(self, info, now):
        if not self._enable_cpu_stats:
            return 0, 0, 0, 0
        if not info:
            info = self._backend.info()

        prevCpuTime = 0
        prevTimestamp = 0
        cpuTime = 0
        cpuTimeAbs = 0
        pcentHostCpu = 0
        pcentGuestCpu = 0

        if len(self._stats) > 0:
            prevTimestamp = self._stats[0]["timestamp"]
            prevCpuTime = self._stats[0]["cpuTimeAbs"]

        if not (info[0] in [libvirt.VIR_DOMAIN_SHUTOFF,
                            libvirt.VIR_DOMAIN_CRASHED]):
            guestcpus = info[3]
            cpuTime = info[4] - prevCpuTime
            cpuTimeAbs = info[4]
            hostcpus = self.conn.host_active_processor_count()

            pcentbase = (((cpuTime) * 100.0) /
                         ((now - prevTimestamp) * 1000.0 * 1000.0 * 1000.0))
            pcentHostCpu = pcentbase / hostcpus
            # Under RHEL-5.9 using a XEN HV guestcpus can be 0 during shutdown
            # so play safe and check it.
            pcentGuestCpu = guestcpus > 0 and pcentbase / guestcpus or 0

        pcentHostCpu = max(0.0, min(100.0, pcentHostCpu))
        pcentGuestCpu = max(0.0, min(100.0, pcentGuestCpu))

        return cpuTime, cpuTimeAbs, pcentHostCpu, pcentGuestCpu

    def _get_cur_rate(self, what):
        if len(self._stats) > 1:
            ret = (float(self._stats[0][what] -
                         self._stats[1][what]) /
                   float(self._stats[0]["timestamp"] -
                         self._stats[1]["timestamp"]))
        else:
            ret = 0.0
        return max(ret, 0, 0)  # avoid negative values at poweroff

    def _set_max_rate(self, record, what):
        if record[what] > self._stats_rates[what]:
            self._stats_rates[what] = record[what]
    def _get_max_rate(self, name1, name2):
        return float(max(self._stats_rates[name1], self._stats_rates[name2]))

    def _get_record_helper(self, record_name):
        if len(self._stats) == 0:
            return 0
        return self._stats[0][record_name]

    def _vector_helper(self, record_name, limit, ceil=100.0):
        vector = []
        statslen = self.config.get_stats_history_length() + 1
        if limit is not None:
            statslen = min(statslen, limit)

        for i in range(statslen):
            if i < len(self._stats):
                vector.append(self._stats[i][record_name] / ceil)
            else:
                vector.append(0)

        return vector

    def _in_out_vector_helper(self, name1, name2, limit, ceil):
        if ceil is None:
            ceil = self._get_max_rate(name1, name2)

        return (self._vector_helper(name1, limit, ceil=ceil),
                self._vector_helper(name2, limit, ceil=ceil))


    ###################
    # Stats accessors #
    ###################

    def stats_memory(self):
        return self._get_record_helper("curmem")
    def cpu_time(self):
        return self._get_record_helper("cpuTime")
    def host_cpu_time_percentage(self):
        return self._get_record_helper("cpuHostPercent")
    def guest_cpu_time_percentage(self):
        return self._get_record_helper("cpuGuestPercent")
    def network_rx_rate(self):
        return self._get_record_helper("netRxRate")
    def network_tx_rate(self):
        return self._get_record_helper("netTxRate")
    def disk_read_rate(self):
        return self._get_record_helper("diskRdRate")
    def disk_write_rate(self):
        return self._get_record_helper("diskWrRate")

    def network_traffic_rate(self):
        return self.network_tx_rate() + self.network_rx_rate()
    def network_traffic_max_rate(self):
        return self._get_max_rate("netRxRate", "netTxRate")
    def disk_io_rate(self):
        return self.disk_read_rate() + self.disk_write_rate()
    def disk_io_max_rate(self):
        return self._get_max_rate("diskRdRate", "diskWrRate")

    def host_cpu_time_vector(self, limit=None):
        return self._vector_helper("cpuHostPercent", limit)
    def guest_cpu_time_vector(self, limit=None):
        return self._vector_helper("cpuGuestPercent", limit)
    def stats_memory_vector(self, limit=None):
        return self._vector_helper("currMemPercent", limit)
    def network_traffic_vectors(self, limit=None, ceil=None):
        return self._in_out_vector_helper(
            "netRxRate", "netTxRate", limit, ceil)
    def disk_io_vectors(self, limit=None, ceil=None):
        return self._in_out_vector_helper(
            "diskRdRate", "diskWrRate", limit, ceil)


    ###################
    # Status helpers ##
    ###################

    def _normalize_status(self, status):
        if status == libvirt.VIR_DOMAIN_NOSTATE:
            return libvirt.VIR_DOMAIN_RUNNING
        elif status == libvirt.VIR_DOMAIN_BLOCKED:
            return libvirt.VIR_DOMAIN_RUNNING
        return status

    def is_active(self):
        return not self.is_shutoff()
    def is_shutoff(self):
        return self.status() == libvirt.VIR_DOMAIN_SHUTOFF
    def is_crashed(self):
        return self.status() == libvirt.VIR_DOMAIN_CRASHED
    def is_stoppable(self):
        return self.status() in [libvirt.VIR_DOMAIN_RUNNING,
                                 libvirt.VIR_DOMAIN_PAUSED,
                                 libvirt.VIR_DOMAIN_CRASHED,
                                 libvirt.VIR_DOMAIN_PMSUSPENDED]
    def is_destroyable(self):
        return (self.is_stoppable() or
                self.status() in [libvirt.VIR_DOMAIN_CRASHED])
    def is_runable(self):
        return self.is_shutoff()
    def is_pauseable(self):
        return self.status() in [libvirt.VIR_DOMAIN_RUNNING]
    def is_unpauseable(self):
        return self.status() in [libvirt.VIR_DOMAIN_PAUSED]
    def is_paused(self):
        return self.status() in [libvirt.VIR_DOMAIN_PAUSED]
    def is_clonable(self):
        return self.status() in [libvirt.VIR_DOMAIN_SHUTOFF,
                                 libvirt.VIR_DOMAIN_PAUSED,
                                 libvirt.VIR_DOMAIN_PMSUSPENDED]

    def run_status(self):
        return self.pretty_run_status(self.status(), self.has_managed_save())

    def run_status_reason(self):
        return self.pretty_status_reason(self.status(), self.status_reason())

    def run_status_icon_name(self):
        status = self.status()
        if status not in vm_status_icons:
            logging.debug("Unknown status %s, using NOSTATE", status)
            status = libvirt.VIR_DOMAIN_NOSTATE
        return vm_status_icons[status]

    def inspection_data_updated(self):
        self.idle_emit("inspection-changed")


    ##################
    # config helpers #
    ##################

    def on_console_scaling_changed(self, *args, **kwargs):
        return self.config.listen_pervm(self.get_uuid(), "/scaling",
                                        *args, **kwargs)
    def set_console_scaling(self, value):
        self.config.set_pervm(self.get_uuid(), "/scaling", value)
    def get_console_scaling(self):
        ret = self.config.get_pervm(self.get_uuid(), "/scaling")
        if ret == -1:
            return self.config.get_console_scaling()
        return ret

    def on_console_resizeguest_changed(self, *args, **kwargs):
        return self.config.listen_pervm(self.get_uuid(), "/resize-guest",
                                        *args, **kwargs)
    def set_console_resizeguest(self, value):
        self.config.set_pervm(self.get_uuid(), "/resize-guest", value)
    def get_console_resizeguest(self):
        ret = self.config.get_pervm(self.get_uuid(), "/resize-guest")
        if ret == -1:
            return self.config.get_console_resizeguest()
        return ret

    def set_details_window_size(self, w, h):
        self.config.set_pervm(self.get_uuid(), "/vm-window-size", (w, h))
    def get_details_window_size(self):
        ret = self.config.get_pervm(self.get_uuid(), "/vm-window-size")
        return ret

    def get_console_password(self):
        return self.config.get_pervm(self.get_uuid(), "/console-password")
    def set_console_password(self, username, keyid):
        return self.config.set_pervm(self.get_uuid(), "/console-password",
                                     (username, keyid))
    def del_console_password(self):
        return self.config.set_pervm(self.get_uuid(), "/console-password",
                                     ("", -1))


    def _on_config_sample_network_traffic_changed(self, ignore=None):
        self._enable_net_poll = self.config.get_stats_enable_net_poll()
    def _on_config_sample_disk_io_changed(self, ignore=None):
        self._enable_disk_poll = self.config.get_stats_enable_disk_poll()
    def _on_config_sample_mem_stats_changed(self, ignore=None):
        self._enable_mem_stats = self.config.get_stats_enable_memory_poll()
    def _on_config_sample_cpu_stats_changed(self, ignore=None):
        self._enable_cpu_stats = self.config.get_stats_enable_cpu_poll()

    def get_cache_dir(self):
        ret = os.path.join(self.conn.get_cache_dir(), self.get_uuid())
        if not os.path.exists(ret):
            os.makedirs(ret, 0o755)
        return ret


    ###################
    # Polling helpers #
    ###################

    def _sample_network_traffic(self):
        rx = 0
        tx = 0
        if (not self._stats_net_supported or
            not self._enable_net_poll or
            not self.is_active()):
            self._stats_net_skip = []
            return rx, tx

        for netdev in self.get_network_devices(refresh_if_nec=False):
            dev = netdev.target_dev
            if not dev:
                continue

            if dev in self._stats_net_skip:
                continue

            try:
                io = self._backend.interfaceStats(dev)
                if io:
                    rx += io[0]
                    tx += io[4]
            except libvirt.libvirtError as err:
                if util.is_error_nosupport(err):
                    logging.debug("Net stats not supported: %s", err)
                    self._stats_net_supported = False
                else:
                    logging.error("Error reading net stats for "
                                  "'%s' dev '%s': %s",
                                  self.get_name(), dev, err)
                    if self.is_active():
                        logging.debug("Adding %s to skip list", dev)
                        self._stats_net_skip.append(dev)
                    else:
                        logging.debug("Aren't running, don't add to skiplist")

        return rx, tx

    def _sample_disk_io(self):
        rd = 0
        wr = 0
        if (not self._stats_disk_supported or
            not self._enable_disk_poll or
            not self.is_active()):
            self._stats_disk_skip = []
            return rd, wr

        # Some drivers support this method for getting all usage at once
        if not self._summary_disk_stats_skip:
            try:
                io = self._backend.blockStats('')
                if io:
                    rd = io[1]
                    wr = io[3]
                    return rd, wr
            except libvirt.libvirtError:
                self._summary_disk_stats_skip = True

        # did not work, iterate over all disks
        for disk in self.get_disk_devices(refresh_if_nec=False):
            dev = disk.target
            if not dev:
                continue

            if dev in self._stats_disk_skip:
                continue

            try:
                io = self._backend.blockStats(dev)
                if io:
                    rd += io[1]
                    wr += io[3]
            except libvirt.libvirtError as err:
                if util.is_error_nosupport(err):
                    logging.debug("Disk stats not supported: %s", err)
                    self._stats_disk_supported = False
                else:
                    logging.error("Error reading disk stats for "
                                  "'%s' dev '%s': %s",
                                  self.get_name(), dev, err)
                    if self.is_active():
                        logging.debug("Adding %s to skip list", dev)
                        self._stats_disk_skip.append(dev)
                    else:
                        logging.debug("Aren't running, don't add to skiplist")

        return rd, wr

    def _set_mem_stats_period(self):
        # QEMU requires we explicitly enable memory stats polling per VM
        # if we wan't fine grained memory stats
        if not self.conn.check_support(
                self.conn.SUPPORT_CONN_MEM_STATS_PERIOD):
            return

        # Only works for virtio balloon
        if not any([b for b in self.get_xmlobj().get_devices("memballoon") if
                    b.model == "virtio"]):
            return

        try:
            secs = 5
            self._backend.setMemoryStatsPeriod(secs,
                libvirt.VIR_DOMAIN_AFFECT_LIVE)
        except Exception as e:
            logging.debug("Error setting memstats period: %s", e)

    def _sample_mem_stats(self):
        if (not self.mem_stats_supported or
            not self._enable_mem_stats or
            not self.is_active()):
            self._mem_stats_period_is_set = False
            return 0, 0

        if self._mem_stats_period_is_set is False:
            self._set_mem_stats_period()
            self._mem_stats_period_is_set = True

        curmem = 0
        totalmem = 1
        try:
            stats = self._backend.memoryStats()
            totalmem = stats.get("actual", 1)
            curmem = stats.get("rss", 0)

            if "unused" in stats:
                curmem = max(0, totalmem - stats.get("unused", totalmem))
        except libvirt.libvirtError as err:
            logging.error("Error reading mem stats: %s", err)

        pcentCurrMem = (curmem // float(totalmem)) * 100
        pcentCurrMem = max(0.0, min(pcentCurrMem, 100.0))

        return pcentCurrMem, curmem


    def tick(self, stats_update=True):
        if (not self._using_events() and
            not stats_update):
            return

        info = []
        dosignal = False
        if not self._using_events():
            # For domains it's pretty important that we are always using
            # the latest XML, but other objects probably don't want to do
            # this since it could be a performance hit.
            self._invalidate_xml()
            info = self._backend.info()
            dosignal = self._refresh_status(newstatus=info[0], cansignal=False)

        if stats_update:
            self._tick_stats(info)
        if dosignal:
            self.idle_emit("state-changed")
        if stats_update:
            self.idle_emit("resources-sampled")

    def _tick_stats(self, info):
        expected = self.config.get_stats_history_length()
        current = len(self._stats)
        if current > expected:
            del self._stats[expected:current]

        now = time.time()
        (cpuTime, cpuTimeAbs,
         pcentHostCpu, pcentGuestCpu) = self._sample_cpu_stats(info, now)
        pcentCurrMem, curmem = self._sample_mem_stats()
        rdBytes, wrBytes = self._sample_disk_io()
        rxBytes, txBytes = self._sample_network_traffic()

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

        for r in ["diskRd", "diskWr", "netRx", "netTx"]:
            newStats[r + "Rate"] = self._get_cur_rate(r + "KiB")
            self._set_max_rate(newStats, r + "Rate")

        self._stats.insert(0, newStats)


########################
# Libvirt domain class #
########################

class vmmDomainVirtinst(vmmDomain):
    """
    Domain object backed by a virtinst Guest object.

    Used for launching a details window for customizing a VM before install.
    """
    def __init__(self, conn, backend, key):
        vmmDomain.__init__(self, conn, backend, key)
        self._orig_xml = None

        # This encodes all the virtinst defaults up front, so the customize
        # dialog actually shows disk buses, cache values, default devices, etc.
        backend.set_install_defaults()

        self.title_supported = True
        self._refresh_status()
        logging.debug("%s initialized with XML=\n%s", self, self._XMLDesc(0))

    def get_name(self):
        return self._backend.name
    def get_uuid(self):
        return self._backend.uuid
    def get_id(self):
        return -1
    def has_managed_save(self):
        return False

    def snapshots_supported(self):
        return False

    def get_autostart(self):
        return self._backend.autostart
    def set_autostart(self, val):
        self._backend.autostart = bool(val)
        self.emit("state-changed")

    def _using_events(self):
        return False
    def _get_backend_status(self):
        return libvirt.VIR_DOMAIN_SHUTOFF
    def _init_libvirt_state(self):
        pass

    def tick(self, stats_update=True):
        ignore = stats_update


    ################
    # XML handling #
    ################

    def define_name(self, newname):
        # We need to overwrite this, since the implementation for libvirt
        # needs to do some crazy stuff.
        xmlobj = self._make_xmlobj_to_define()
        xmlobj.name = str(newname)
        self._redefine_xmlobj(xmlobj)

    def _XMLDesc(self, flags):
        ignore = flags
        return self._backend.get_xml_config()

    def _define(self, xml):
        ignore = xml
        self.emit("state-changed")

    def _invalidate_xml(self):
        vmmDomain._invalidate_xml(self)
        self._orig_xml = None

    def _make_xmlobj_to_define(self):
        if not self._orig_xml:
            self._orig_xml = self._backend.get_xml_config()
        return self._backend

    def _redefine_xmlobj(self, xmlobj, origxml=None):
        vmmDomain._redefine_xmlobj(self, xmlobj, origxml=self._orig_xml)
