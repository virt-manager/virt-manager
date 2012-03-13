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

import logging
import time
import threading

import libvirt
import virtinst
from virtinst.VirtualCharDevice import VirtualCharSpicevmcDevice
import virtinst.support as support

from virtManager import util
from virtManager.libvirtobject import vmmLibvirtObject

def compare_device(origdev, newdev, idx):
    devprops = {
        "disk"      : ["target", "bus"],
        "interface" : ["macaddr", "vmmindex"],
        "input"     : ["bus", "type", "vmmindex"],
        "sound"     : ["model", "vmmindex"],
        "video"     : ["model_type", "vmmindex"],
        "watchdog"  : ["vmmindex"],
        "hostdev"   : ["type", "managed", "vmmindex",
                       "product", "vendor",
                       "function", "domain", "slot"],
        "serial"    : ["char_type", "target_port"],
        "parallel"  : ["char_type", "target_port"],
        "console"   : ["char_type", "target_type", "target_port"],
        "graphics"  : ["type", "vmmindex"],
        "controller" : ["type", "index"],
        "channel"   : ["char_type", "target_name"],
        "filesystem" : ["target" , "vmmindex"],
        "smartcard" : ["mode" , "vmmindex"],
        "redirdev" : ["bus" , "type", "vmmindex"],
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
                #data_processed  = float(jobinfo[4])
                data_remaining  = float(jobinfo[5])

                # data_total is 0 if the job hasn't started yet
                if not data_total:
                    continue

                if not meter.started:
                    meter.start(size=data_total,
                                text=progtext)

                progress = data_total - data_remaining
                meter.update(progress)
            except:
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
        self.type = None
        self.distro = None
        self.major_version = None
        self.minor_version = None
        self.hostname = None
        self.product_name = None
        self.product_variant = None
        self.icon = None
        self.applications = None

class vmmDomain(vmmLibvirtObject):
    """
    Class wrapping virDomain libvirt objects. Is also extended to be
    backed by a virtinst.Guest object for new VM 'customize before install'
    """
    def __init__(self, conn, backend, uuid):
        vmmLibvirtObject.__init__(self, conn)

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
        self.reboot_listener = None
        self._startup_vcpus = None
        self._is_management_domain = None
        self._id = None
        self._name = None

        self._inactive_xml_flags = 0
        self._active_xml_flags = 0

        self.lastStatus = libvirt.VIR_DOMAIN_SHUTOFF

        self._getvcpus_supported = None
        self._getjobinfo_supported = None
        self.managedsave_supported = False
        self.remote_console_supported = False

        self._guest = None
        self._guest_to_define = None

        self._enable_net_poll = False
        self._stats_net_supported = True
        self._stats_net_skip = []

        self._enable_disk_poll = False
        self._stats_disk_supported = True
        self._stats_disk_skip = []

        self.inspection = vmmInspectionData()

        if isinstance(self._backend, virtinst.Guest):
            return

        self._libvirt_init()

    def _get_getvcpus_supported(self):
        if self._getvcpus_supported is None:
            self._getvcpus_supported = True
            try:
                self._backend.vcpus()
            except libvirt.libvirtError, err:
                if support.is_error_nosupport(err):
                    self._getvcpus_supported = False
        return self._getvcpus_supported
    getvcpus_supported = property(_get_getvcpus_supported)

    def _get_getjobinfo_supported(self):
        if self._getjobinfo_supported is None:
            self._getjobinfo_supported = support.check_domain_support(
                                            self._backend,
                                            support.SUPPORT_DOMAIN_JOB_INFO)
        return self._getjobinfo_supported
    getjobinfo_supported = property(_get_getjobinfo_supported)

    def _libvirt_init(self):
        """
        Initialization to do if backed by a libvirt virDomain
        """
        self._reparse_xml()

        self.managedsave_supported = self.conn.get_dom_managedsave_supported(self._backend)

        self.remote_console_supported = support.check_domain_support(
                                        self._backend,
                                        support.SUPPORT_DOMAIN_CONSOLE_STREAM)

        # Determine available XML flags (older libvirt versions will error
        # out if passed SECURE_XML, INACTIVE_XML, etc)
        (self._inactive_xml_flags,
         self._active_xml_flags) = self.conn.get_dom_flags(self._backend)

        self.toggle_sample_network_traffic()
        self.toggle_sample_disk_io()

        self.force_update_status()

        # Hook up listeners that need to be cleaned up
        self.add_gconf_handle(
            self.config.on_stats_enable_net_poll_changed(
                                        self.toggle_sample_network_traffic))
        self.add_gconf_handle(
            self.config.on_stats_enable_disk_poll_changed(
                                        self.toggle_sample_disk_io))

        self.connect("status-changed", self._update_start_vcpus)
        self.connect("config-changed", self._reparse_xml)


    ###########################
    # Misc API getter methods #
    ###########################

    def get_name(self):
        if self._name == None:
            self._name = self._backend.name()
        return self._name

    def get_id(self):
        if self._id == None:
            self._id = self._backend.ID()
        return self._id

    def status(self):
        return self.lastStatus

    def change_name_backend(self, newbackend):
        # Used for changing the domain object after a rename
        self._backend = newbackend

    def get_cloning(self):
        return self.cloning
    def set_cloning(self, val):
        self.cloning = bool(val)

    # If manual shutdown or destroy specified, make sure we don't continue
    # install process
    def get_install_abort(self):
        return bool(self._install_abort)

    def rhel6_defaults(self):
        return self.conn.rhel6_defaults(self.get_emulator())

    def is_read_only(self):
        if self.conn.is_read_only():
            return True
        if self.is_management_domain():
            return True
        return False

    def is_management_domain(self):
        if self._is_management_domain == None:
            self._is_management_domain = (self.get_id() == 0)
        return self._is_management_domain

    def get_id_pretty(self):
        i = self.get_id()
        if i < 0:
            return "-"
        return str(i)

    #############################
    # Internal XML handling API #
    #############################

    def _invalidate_xml(self):
        vmmLibvirtObject._invalidate_xml(self)
        self._guest_to_define = None
        self._name = None
        self._id = None

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
            logging.debug("Device in active config but not inactive config.")
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

        if inactive:
            # If inactive XML requested, always return a fresh guest even
            # the current Guest is inactive XML (like when the domain is
            # stopped). Callers that request inactive are basically expecting
            # a new copy.
            return self._build_guest(xml)

        return self._guest

    def _build_guest(self, xml):
        return virtinst.Guest(conn=self.conn.vmm,
                              parsexml=xml,
                              caps=self.conn.get_capabilities())

    def _reparse_xml(self, ignore=None):
        self._guest = self._build_guest(self._get_domain_xml())


    ##############################
    # Persistent XML change APIs #
    ##############################

    # Rename

    def define_name(self, newname):
        # Do this, so that _guest_to_define has original inactive XML
        self._invalidate_xml()

        guest = self._get_guest_to_define()
        if guest.name == newname:
            return

        if self.is_active():
            raise RuntimeError(_("Cannot rename an active guest"))

        logging.debug("Changing guest name to '%s'", newname)
        origxml = guest.get_xml_config()
        guest.name = newname
        newxml = guest.get_xml_config()

        try:
            self.conn.rename_vm(self, origxml, newxml)
        finally:
            self._invalidate_xml()

        self.emit("config-changed")

    # Device Add/Remove

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

    # CPU define methods

    def define_vcpus(self, vcpus, maxvcpus):
        def change(guest):
            guest.vcpus = int(vcpus)
            guest.maxvcpus = int(maxvcpus)
        return self._redefine_guest(change)
    def define_cpuset(self, cpuset):
        def change(guest):
            guest.cpuset = cpuset
        return self._redefine_guest(change)

    def define_cpu_topology(self, sockets, cores, threads):
        def change(guest):
            cpu = guest.cpu
            cpu.sockets = sockets
            cpu.cores = cores
            cpu.threads = threads
        return self._redefine_guest(change)
    def define_cpu(self, model, vendor, from_host, featurelist):
        def change(guest):
            if from_host:
                guest.cpu.copy_host_cpu()
            elif guest.cpu.model != model:
                # Since we don't expose this in the UI, have host value trump
                # caps value
                guest.cpu.vendor = vendor

            guest.cpu.model = model or None

            origfeatures = guest.cpu.features
            def set_feature(fname, fpol):
                for f in origfeatures:
                    if f.name != fname:
                        continue
                    if f.policy != fpol:
                        if fpol == "default":
                            guest.cpu.remove_feature(f)
                        else:
                            f.policy = fpol
                    return

                if fpol != "default":
                    guest.cpu.add_feature(fname, fpol)

            # Sync feature lists
            for fname, fpol in featurelist:
                set_feature(fname, fpol)

        return self._redefine_guest(change)

    # Mem define methods

    def define_both_mem(self, memory, maxmem):
        def change(guest):
            guest.memory = int(int(memory) / 1024)
            guest.maxmemory = int(int(maxmem) / 1024)
        return self._redefine_guest(change)

    # Security define methods

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

    # Machine config define methods

    def define_acpi(self, newvalue):
        def change(guest):
            guest.features["acpi"] = newvalue
        return self._redefine_guest(change)
    def define_apic(self, newvalue):
        def change(guest):
            guest.features["apic"] = newvalue
        return self._redefine_guest(change)

    def define_clock(self, newvalue):
        def change(guest):
            guest.clock.offset = newvalue
        return self._redefine_guest(change)

    def define_machtype(self, newvalue):
        def change(guest):
            guest.installer.machine = newvalue
        return self._redefine_guest(change)

    def define_description(self, newvalue):
        def change(guest):
            guest.description = newvalue or None
        return self._redefine_guest(change)

    # Boot define methods

    def set_boot_device(self, boot_list):
        def change(guest):
            guest.installer.bootconfig.bootorder = boot_list
        return self._redefine_guest(change)
    def set_boot_menu(self, newval):
        def change(guest):
            guest.installer.bootconfig.enable_bootmenu = bool(newval)
        return self._redefine_guest(change)
    def set_boot_kernel(self, kernel, initrd, args):
        def change(guest):
            guest.installer.bootconfig.kernel = kernel or None
            guest.installer.bootconfig.initrd = initrd or None
            guest.installer.bootconfig.kernel_args = args or None
        return self._redefine_guest(change)
    def set_boot_init(self, init):
        def change(guest):
            guest.installer.init = init
        return self._redefine_guest(change)

    # Disk define methods

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
    def define_disk_io(self, devobj, val):
        def change(editdev):
            editdev.driver_io = val or None
        return self._redefine_device(change, devobj)
    def define_disk_driver_type(self, devobj, new_driver_type):
        def change(editdev):
            editdev.driver_type = new_driver_type or None
        return self._redefine_device(change, devobj)
    def define_disk_bus(self, devobj, newval, addr):
        def change(editdev):
            oldprefix = editdev.get_target_prefix()[0]
            oldbus = editdev.bus
            editdev.bus = newval

            if oldbus == newval:
                return

            editdev.address.clear()
            editdev.set_address(addr)

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
        return self._redefine_device(change, devobj)
    def define_disk_serial(self, devobj, val):
        def change(editdev):
            if val != editdev.serial:
                editdev.serial = val or None
        return self._redefine_device(change, devobj)

    # Network define methods

    def define_network_source(self, devobj, newtype, newsource, newmode):
        def change(editdev):
            if not newtype:
                return
            editdev.source = None

            editdev.type = newtype
            editdev.source = newsource
            editdev.source_mode = newmode or None
        return self._redefine_device(change, devobj)
    def define_network_model(self, devobj, newmodel, addr):
        def change(editdev):
            if editdev.model != newmodel:
                editdev.address.clear()
                editdev.set_address(addr)
            editdev.model = newmodel
        return self._redefine_device(change, devobj)

    def define_virtualport(self, devobj, newtype, newmanagerid,
                           newtypeid, newtypeidversion, newinstanceid):
        def change(editdev):
            editdev.virtualport.type = newtype or None
            editdev.virtualport.managerid = newmanagerid or None
            editdev.virtualport.typeid = newtypeid or None
            editdev.virtualport.typeidversion = newtypeidversion or None
            editdev.virtualport.instanceid = newinstanceid or None
        return self._redefine_device(change, devobj)

    # Graphics define methods

    def define_graphics_password(self, devobj, newval):
        def change(editdev):
            editdev.passwd = newval or None
        return self._redefine_device(change, devobj)
    def define_graphics_keymap(self, devobj, newval):
        def change(editdev):
            editdev.keymap = newval
        return self._redefine_device(change, devobj)
    def define_graphics_type(self, devobj, newval, apply_spice_defaults):
        def handle_spice():
            if not apply_spice_defaults:
                return

            guest = self._get_guest_to_define()
            is_spice = (newval == virtinst.VirtualGraphics.TYPE_SPICE)

            if is_spice:
                guest.add_device(VirtualCharSpicevmcDevice(guest.conn))
            else:
                channels = guest.get_devices("channel")
                channels = filter(lambda x:
                            (x.char_type ==
                             virtinst.VirtualCharDevice.CHAR_SPICEVMC),
                           channels)
                for dev in channels:
                    guest.remove_device(dev)

        def change(editdev):
            editdev.type = newval
            handle_spice()

        return self._redefine_device(change, devobj)

    # Sound define methods

    def define_sound_model(self, devobj, newmodel):
        def change(editdev):
            if editdev.model != newmodel:
                editdev.address.clear()
            editdev.model = newmodel
        return self._redefine_device(change, devobj)

    # Vide define methods

    def define_video_model(self, devobj, newmodel):
        def change(editdev):
            if newmodel == editdev.model_type:
                return

            editdev.model_type = newmodel
            editdev.address.clear()

            # Clear out heads/ram values so they reset to default. If
            # we ever allow editing these values in the UI we should
            # drop this
            editdev.vram = None
            editdev.heads = None

        return self._redefine_device(change, devobj)

    # Watchdog define methods

    def define_watchdog_model(self, devobj, newval):
        def change(editdev):
            if editdev.model != newval:
                editdev.address.clear()
            editdev.model = newval
        return self._redefine_device(change, devobj)
    def define_watchdog_action(self, devobj, newval):
        def change(editdev):
            editdev.action = newval
        return self._redefine_device(change, devobj)

    # Smartcard define methods

    def define_smartcard_mode(self, devobj, newmodel):
        def change(editdev):
            editdev.mode = newmodel
        return self._redefine_device(change, devobj)

    # Controller define methods

    def define_controller_model(self, devobj, newmodel):
        def change(editdev):
            ignore = editdev

            guest = self._get_guest_to_define()
            ctrls = guest.get_devices("controller")
            ctrls = filter(lambda x: (x.type ==
                           virtinst.VirtualController.CONTROLLER_TYPE_USB),
                           ctrls)
            for dev in ctrls:
                guest.remove_device(dev)

            if newmodel == "ich9-ehci1":
                guest.add_usb_ich9_controllers()

        return self._redefine_device(change, devobj)



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
        self._backend.attachDevice(devxml)

    def detach_device(self, devobj):
        """
        Hotunplug device from running guest
        """
        if not self.is_active():
            return

        xml = devobj.get_xml_config()
        self._backend.detachDevice(xml)

    def update_device(self, devobj, flags=1):
        if not self.is_active():
            return

        # Default flag is VIR_DOMAIN_DEVICE_MODIFY_LIVE
        xml = devobj.get_xml_config()
        self._backend.updateDeviceFlags(xml, flags)

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
        logging.info("Hotplugging curmem=%s maxmem=%s for VM '%s'",
                     memory, maxmem, self.get_name())

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

    def hotplug_graphics_password(self, devobj, newval):
        devobj.passwd = newval or None
        self.update_device(devobj)


    ########################
    # Libvirt API wrappers #
    ########################

    def _define(self, newxml):
        self.conn.define_domain(newxml)
    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)

    def pin_vcpu(self, vcpu_num, pinlist):
        self._backend.pinVcpu(vcpu_num, pinlist)
    def vcpu_info(self):
        if self.is_active() and self.getvcpus_supported:
            return self._backend.vcpus()
        return [[], []]

    def get_autostart(self):
        return self._backend.autostart()
    def set_autostart(self, val):
        if self.get_autostart() == val:
            return
        self._backend.setAutostart(val)

    def job_info(self):
        return self._backend.jobInfo()
    def abort_job(self):
        self._backend.abortJob()

    def open_console(self, devname, stream, flags=0):
        return self._backend.openConsole(devname, stream, flags)

    ########################
    # XML Parsing routines #
    ########################

    def is_container(self):
        return self._get_guest().installer.is_container()
    def is_xenpv(self):
        return self._get_guest().installer.is_xenpv()
    def is_hvm(self):
        return self._get_guest().installer.is_hvm()

    def get_uuid(self):
        return self.uuid
    def get_abi_type(self):
        return self._get_guest().installer.os_type
    def get_hv_type(self):
        return self._get_guest().installer.type
    def get_pretty_hv_type(self):
        return util.pretty_hv(self.get_abi_type(), self.get_hv_type())
    def get_arch(self):
        return self._get_guest().installer.arch
    def get_init(self):
        return self._get_guest().installer.init
    def get_emulator(self):
        return self._get_guest().emulator
    def get_acpi(self):
        return self._get_guest().features["acpi"]
    def get_apic(self):
        return self._get_guest().features["apic"]
    def get_clock(self):
        return self._get_guest().clock.offset
    def get_machtype(self):
        return self._get_guest().installer.machine

    def get_description(self):
        # Always show the inactive <description>, let's us fake hotplug
        # for a field that's strictly metadata
        return self._get_guest(inactive=True).description

    def get_memory(self):
        return int(self._get_guest().memory * 1024)
    def maximum_memory(self):
        return int(self._get_guest().maxmemory * 1024)

    def vcpu_count(self):
        return int(self._get_guest().vcpus)
    def vcpu_max_count(self):
        guest = self._get_guest()
        has_xml_max = (guest.vcpus != guest.maxvcpus)
        if has_xml_max or not self.is_active():
            return guest.maxvcpus

        if self._startup_vcpus == None:
            self._startup_vcpus = int(self.vcpu_count())
        return int(self._startup_vcpus)

    def vcpu_pinning(self):
        return self._get_guest().cpuset or ""
    def get_cpu_config(self):
        return self._get_guest().cpu

    def get_boot_device(self):
        return self._get_guest().installer.bootconfig.bootorder
    def get_boot_menu(self):
        guest = self._get_guest()
        return bool(guest.installer.bootconfig.enable_bootmenu)
    def get_boot_kernel_info(self):
        guest = self._get_guest()
        kernel = guest.installer.bootconfig.kernel
        initrd = guest.installer.bootconfig.initrd
        args = guest.installer.bootconfig.kernel_args

        return (kernel, initrd, args)

    def get_seclabel(self):
        model = self._get_guest().seclabel.model
        t     = self._get_guest().seclabel.type or "dynamic"
        label = self._get_guest().seclabel.label or ""

        return [model, t, label]

    # XML Device listing

    def get_serial_devs(self):
        devs = self.get_char_devices()
        devlist = []

        devlist += filter(lambda x: x.virtual_device_type == "serial", devs)
        devlist += filter(lambda x: x.virtual_device_type == "console", devs)
        return devlist

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
    def get_controller_devices(self):
        return self._build_device_list("controller")
    def get_filesystem_devices(self):
        return self._build_device_list("filesystem")
    def get_smartcard_devices(self):
        return self._build_device_list("smartcard")
    def get_redirdev_devices(self):
        return self._build_device_list("redirdev")

    def get_disk_devices(self, refresh_if_necc=True, inactive=False):
        devs = self._build_device_list("disk", refresh_if_necc, inactive)

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

            if (con.char_type == ser.char_type and
                con.target_type is None or con.target_type == "serial"):
                ser.virtmanager_console_dup = con
                devs.remove(con)

        return devs


    ############################
    # Domain lifecycle methods #
    ############################

    # All these methods are usually run asynchronously from threads, so
    # let's be extra careful and have anything which might touch UI
    # or gobject props invoked in an idle callback

    def _unregister_reboot_listener(self):
        if self.reboot_listener == None:
            return

        try:
            self.idle_add(self.disconnect, self.reboot_listener)
            self.reboot_listener = None
        except:
            pass

    def manual_reboot(self):
        """
        Attempt a manual reboot by invoking 'shutdown', then listen
        for a state change and restart the VM
        """
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

        def add_reboot():
            self.reboot_listener = self.connect_opt_out("status-changed",
                                                    reboot_listener, self)
        self.idle_add(add_reboot)

    def shutdown(self):
        self._install_abort = True
        self._unregister_reboot_listener()
        self._backend.shutdown()
        self.idle_add(self.force_update_status)

    def reboot(self):
        self._install_abort = True
        self._backend.reboot(0)
        self.idle_add(self.force_update_status)

    def destroy(self):
        self._install_abort = True
        self._unregister_reboot_listener()
        self._backend.destroy()
        self.idle_add(self.force_update_status)

    def startup(self):
        if self.get_cloning():
            raise RuntimeError(_("Cannot start guest while cloning "
                                 "operation in progress"))
        self._backend.create()
        self.idle_add(self.force_update_status)

    def suspend(self):
        self._backend.suspend()
        self.idle_add(self.force_update_status)

    def delete(self):
        if self.hasSavedImage():
            try:
                self._backend.managedSaveRemove(0)
            except:
                logging.exception("Failed to remove managed save state")
        self._backend.undefine()

    def resume(self):
        if self.get_cloning():
            raise RuntimeError(_("Cannot resume guest while cloning "
                                 "operation in progress"))

        self._backend.resume()
        self.idle_add(self.force_update_status)

    def hasSavedImage(self):
        if not self.managedsave_supported:
            return False
        return self._backend.hasManagedSaveImage(0)

    def save(self, filename=None, meter=None):
        self._install_abort = True

        if meter:
            start_job_progress_thread(self, meter, _("Saving domain to disk"))

        if not self.managedsave_supported:
            self._backend.save(filename)
        else:
            self._backend.managedSave(0)

        self.idle_add(self.force_update_status)


    def support_downtime(self):
        return support.check_domain_support(self._backend,
                        support.SUPPORT_DOMAIN_MIGRATE_DOWNTIME)

    def migrate_set_max_downtime(self, max_downtime, flag=0):
        self._backend.migrateSetMaxDowntime(max_downtime, flag)

    def migrate(self, destconn, interface=None, rate=0,
                live=False, secure=False, meter=None):
        self._install_abort = True

        newname = None

        flags = 0
        if self.status() == libvirt.VIR_DOMAIN_RUNNING and live:
            flags |= libvirt.VIR_MIGRATE_LIVE

        if secure:
            flags |= libvirt.VIR_MIGRATE_PEER2PEER
            flags |= libvirt.VIR_MIGRATE_TUNNELLED

        logging.debug("Migrating: conn=%s flags=%s dname=%s uri=%s rate=%s",
                      destconn.vmm, flags, newname, interface, rate)

        if meter:
            start_job_progress_thread(self, meter, _("Migrating domain"))

        self._backend.migrate(destconn.vmm, flags, newname, interface, rate)

        def define_cb():
            newxml = self.get_xml(inactive=True)
            destconn.define_domain(newxml)
        self.idle_add(define_cb)


    ###################
    # Stats helpers ###
    ###################

    def _sample_mem_stats(self, info):
        curmem = info[2]
        if not self.is_active():
            curmem = 0

        pcentCurrMem = curmem * 100.0 / self.conn.host_memory_size()
        pcentCurrMem = max(0.0, min(pcentCurrMem, 100.0))

        return pcentCurrMem, curmem

    def _sample_cpu_stats(self, info, now):
        prevCpuTime = 0
        prevTimestamp = 0
        cpuTime = 0
        cpuTimeAbs = 0
        pcentHostCpu = 0
        pcentGuestCpu = 0

        if len(self.record) > 0:
            prevTimestamp = self.record[0]["timestamp"]
            prevCpuTime = self.record[0]["cpuTimeAbs"]

        if not (info[0] in [libvirt.VIR_DOMAIN_SHUTOFF,
                            libvirt.VIR_DOMAIN_CRASHED]):
            guestcpus = info[3]
            cpuTime = info[4] - prevCpuTime
            cpuTimeAbs = info[4]
            hostcpus = self.conn.host_active_processor_count()

            pcentbase = (((cpuTime) * 100.0) /
                         ((now - prevTimestamp) * 1000.0 * 1000.0 * 1000.0))
            pcentHostCpu = pcentbase / hostcpus
            pcentGuestCpu = pcentbase / guestcpus

        pcentHostCpu = max(0.0, min(100.0, pcentHostCpu))
        pcentGuestCpu = max(0.0, min(100.0, pcentGuestCpu))

        return cpuTime, cpuTimeAbs, pcentHostCpu, pcentGuestCpu

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
    def _get_max_rate(self, name1, name2):
        return float(max(self.maxRecord[name1], self.maxRecord[name2]))

    def _get_record_helper(self, record_name):
        if len(self.record) == 0:
            return 0
        return self.record[0][record_name]

    def _vector_helper(self, record_name):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length() + 1):
            if i < len(stats):
                vector.append(stats[i][record_name] / 100.0)
            else:
                vector.append(0)
        return vector

    def _in_out_vector_helper(self, name1, name2, ceil):
        vector = []
        stats = self.record
        if ceil is None:
            ceil = self._get_max_rate(name1, name2)
        maxlen = self.config.get_stats_history_length()

        for n in [name1, name2]:
            for i in range(maxlen + 1):
                if i < len(stats):
                    vector.append(float(stats[i][n]) / ceil)
                else:
                    vector.append(0.0)
        return vector

    def in_out_vector_limit(self, data, limit):
        l = len(data) / 2
        end = min(l, limit)
        if l > limit:
            data = data[0:end] + data[l:l + end]

        return map(lambda x, y: (x + y) / 2, data[0:end], data[end:end * 2])

    def toggle_sample_network_traffic(self, ignore1=None, ignore2=None,
                                      ignore3=None, ignore4=None):
        self._enable_net_poll = self.config.get_stats_enable_net_poll()

        if self._enable_net_poll and len(self.record) > 1:
            # resample the current value before calculating the rate in
            # self.tick() otherwise we'd get a huge spike when switching
            # from 0 to bytes_transfered_so_far
            rxBytes, txBytes = self._sample_network_traffic()
            self.record[0]["netRxKB"] = rxBytes / 1024
            self.record[0]["netTxKB"] = txBytes / 1024

    def toggle_sample_disk_io(self, ignore1=None, ignore2=None,
                              ignore3=None, ignore4=None):
        self._enable_disk_poll = self.config.get_stats_enable_disk_poll()

        if self._enable_disk_poll and len(self.record) > 1:
            # resample the current value before calculating the rate in
            # self.tick() otherwise we'd get a huge spike when switching
            # from 0 to bytes_transfered_so_far
            rdBytes, wrBytes = self._sample_disk_io()
            self.record[0]["diskRdKB"] = rdBytes / 1024
            self.record[0]["diskWrKB"] = wrBytes / 1024


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

    def get_memory_pretty(self):
        return util.pretty_mem(self.get_memory())
    def maximum_memory_pretty(self):
        return util.pretty_mem(self.maximum_memory())

    def network_traffic_rate(self):
        return self.network_tx_rate() + self.network_rx_rate()
    def network_traffic_max_rate(self):
        return self._get_max_rate("netRxRate", "netTxRate")
    def disk_io_rate(self):
        return self.disk_read_rate() + self.disk_write_rate()
    def disk_io_max_rate(self):
        return self._get_max_rate("diskRdRate", "diskWrRate")

    def host_cpu_time_vector(self):
        return self._vector_helper("cpuHostPercent")
    def guest_cpu_time_vector(self):
        return self._vector_helper("cpuGuestPercent")
    def stats_memory_vector(self):
        return self._vector_helper("currMemPercent")
    def network_traffic_vector(self, ceil=None):
        return self._in_out_vector_helper("netRxRate", "netTxRate", ceil)
    def disk_io_vector(self, ceil=None):
        return self._in_out_vector_helper("diskRdRate", "diskWrRate", ceil)

    def host_cpu_time_vector_limit(self, limit):
        cpudata = self.host_cpu_time_vector()
        if len(cpudata) > limit:
            cpudata = cpudata[0:limit]
        return cpudata
    def guest_cpu_time_vector_limit(self, limit):
        cpudata = self.guest_cpu_time_vector()
        if len(cpudata) > limit:
            cpudata = cpudata[0:limit]
        return cpudata
    def network_traffic_vector_limit(self, limit, ceil=None):
        return self.in_out_vector_limit(self.network_traffic_vector(ceil),
                                        limit)
    def disk_io_vector_limit(self, limit, ceil=None):
        return self.in_out_vector_limit(self.disk_io_vector(ceil), limit)


    ###################
    # Status helpers ##
    ###################

    def _update_start_vcpus(self, ignore, oldstatus, status):
        ignore = status

        if oldstatus not in [libvirt.VIR_DOMAIN_SHUTDOWN,
                             libvirt.VIR_DOMAIN_SHUTOFF,
                             libvirt.VIR_DOMAIN_CRASHED]:
            return

        # Want to track the startup vcpu amount, which is the
        # cap of how many VCPUs can be added
        self._startup_vcpus = None
        self.vcpu_max_count()

    def run_status(self):
        if self.status() == libvirt.VIR_DOMAIN_RUNNING:
            return _("Running")
        elif self.status() == libvirt.VIR_DOMAIN_PAUSED:
            return _("Paused")
        elif self.status() == libvirt.VIR_DOMAIN_SHUTDOWN:
            return _("Shutting Down")
        elif self.status() == libvirt.VIR_DOMAIN_SHUTOFF:
            if self.hasSavedImage():
                return _("Saved")
            else:
                return _("Shutoff")
        elif self.status() == libvirt.VIR_DOMAIN_CRASHED:
            return _("Crashed")

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

    def run_status_icon_name(self):
        status_icons = {
            libvirt.VIR_DOMAIN_BLOCKED: "state_running",
            libvirt.VIR_DOMAIN_CRASHED: "state_shutoff",
            libvirt.VIR_DOMAIN_PAUSED: "state_paused",
            libvirt.VIR_DOMAIN_RUNNING: "state_running",
            libvirt.VIR_DOMAIN_SHUTDOWN: "state_shutoff",
            libvirt.VIR_DOMAIN_SHUTOFF: "state_shutoff",
            libvirt.VIR_DOMAIN_NOSTATE: "state_running",
        }

        return status_icons[self.status()]

    def force_update_status(self):
        """
        Fetch current domain state and clear status cache
        """
        try:
            info = self._backend.info()
        except libvirt.libvirtError, e:
            if (hasattr(libvirt, "VIR_ERR_NO_DOMAIN") and
                e.get_error_code() == getattr(libvirt, "VIR_ERR_NO_DOMAIN")):
                # Possibly a transient domain that was removed on shutdown
                return
            raise

        self._update_status(info[0])

    def _update_status(self, status):
        """
        Internal helper to change cached status to 'status' and signal
        clients if we actually changed state
        """
        status = self._normalize_status(status)

        if status == self.lastStatus:
            return

        oldstatus = self.lastStatus
        self.lastStatus = status

        # Send 'config-changed' before a status-update, so users
        # are operating with fresh XML
        self.refresh_xml()

        self.idle_emit("status-changed", oldstatus, status)


    #################
    # GConf helpers #
    #################

    def set_console_scaling(self, value):
        self.config.set_pervm(self.conn.get_uri(), self.uuid,
                              self.config.set_console_scaling, value)
    def get_console_scaling(self):
        return self.config.get_pervm(self.conn.get_uri(), self.uuid,
                                     self.config.get_console_scaling)
    def on_console_scaling_changed(self, cb):
        return self.config.listen_pervm(self.conn.get_uri(), self.uuid,
                                        self.config.on_console_scaling_changed,
                                        cb)

    def set_details_window_size(self, w, h):
        self.config.set_pervm(self.conn.get_uri(), self.uuid,
                              self.config.set_details_window_size, (w, h))
    def get_details_window_size(self):
        return self.config.get_pervm(self.conn.get_uri(), self.uuid,
                                     self.config.get_details_window_size)

    def inspection_data_updated(self):
        self.idle_emit("inspection-changed")


    ###################
    # Polling helpers #
    ###################

    def _sample_network_traffic(self):
        rx = 0
        tx = 0
        if (not self._stats_net_supported or
            not self._enable_net_poll or
            not self.is_active()):
            return rx, tx

        for netdev in self.get_network_devices(refresh_if_necc=False):
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
            except libvirt.libvirtError, err:
                if support.is_error_nosupport(err):
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
            return rd, wr

        for disk in self.get_disk_devices(refresh_if_necc=False):
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
            except libvirt.libvirtError, err:
                if support.is_error_nosupport(err):
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

    def tick(self, now=None):
        if self.conn.get_state() != self.conn.STATE_ACTIVE:
            return

        if now is None:
            now = time.time()

        # Invalidate cached values
        self._invalidate_xml()

        info = self._backend.info()
        expected = self.config.get_stats_history_length()
        current = len(self.record)
        if current > expected:
            del self.record[expected:current]

        # Xen reports complete crap for Dom0 max memory
        # (ie MAX_LONG) so lets clamp it to the actual
        # physical RAM in machine which is the effective
        # real world limit
        if (self.conn.is_xen() and
            self.is_management_domain()):
            info[1] = self.conn.host_memory_size()

        (cpuTime, cpuTimeAbs,
         pcentHostCpu, pcentGuestCpu) = self._sample_cpu_stats(info, now)
        pcentCurrMem, curmem = self._sample_mem_stats(info)
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
            "diskRdKB": rdBytes / 1024,
            "diskWrKB": wrBytes / 1024,
            "netRxKB": rxBytes / 1024,
            "netTxKB": txBytes / 1024,
        }

        for r in ["diskRd", "diskWr", "netRx", "netTx"]:
            newStats[r + "Rate"] = self._get_cur_rate(r + "KB")
            self._set_max_rate(newStats, r + "Rate")

        self.record.insert(0, newStats)
        self._update_status(info[0])
        self.idle_emit("resources-sampled")


########################
# Libvirt domain class #
########################

class vmmDomainVirtinst(vmmDomain):
    """
    Domain object backed by a virtinst Guest object.

    Used for launching a details window for customizing a VM before install.
    """
    def __init__(self, conn, backend, uuid):
        vmmDomain.__init__(self, conn, backend, uuid)

        self._orig_xml = None

    def get_name(self):
        return self._backend.name
    def get_id(self):
        return -1
    def hasSavedImage(self):
        return False

    def _XMLDesc(self, flags):
        raise RuntimeError("Shouldn't be called")

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
        self.emit("config-changed")

    def _redefine_xml(self, newxml):
        # We need to cache origxml in order to have something to diff against
        origxml = self._orig_xml or self.get_xml(inactive=True)
        return self._redefine_helper(origxml, newxml)

    def refresh_xml(self, forcesignal=False):
        # No caching, so no refresh needed
        return

    def get_autostart(self):
        return self._backend.autostart
    def set_autostart(self, val):
        self._backend.autostart = bool(val)
        self.emit("config-changed")

    def define_name(self, newname):
        def change(guest):
            guest.name = str(newname)
        return self._redefine_guest(change)

vmmLibvirtObject.type_register(vmmDomain)
vmmDomain.signal_new(vmmDomain, "status-changed", [int, int])
vmmDomain.signal_new(vmmDomain, "resources-sampled", [])
vmmDomain.signal_new(vmmDomain, "inspection-changed", [])

vmmLibvirtObject.type_register(vmmDomainVirtinst)
