# Copyright (C) 2006, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os
import time
import threading

import libvirt

from virtinst import DomainCapabilities
from virtinst import DomainSnapshot
from virtinst import Guest
from virtinst import util
from virtinst import DeviceController
from virtinst import DeviceDisk

from .libvirtobject import vmmLibvirtObject
from .libvirtenummap import LibvirtEnumMap


class _SENTINEL(object):
    pass


def compare_device(origdev, newdev, idx):
    devprops = {
        "disk":          ["target", "bus"],
        "interface":     ["macaddr", "xmlindex"],
        "input":         ["bus", "type", "xmlindex"],
        "sound":         ["model", "xmlindex"],
        "video":         ["model", "xmlindex"],
        "watchdog":      ["xmlindex"],
        "hostdev":       ["type", "managed", "xmlindex",
                            "product", "vendor",
                            "function", "domain", "slot"],
        "serial":        ["type", "target_port"],
        "parallel":      ["type", "target_port"],
        "console":       ["type", "target_type", "target_port"],
        "graphics":      ["type", "xmlindex"],
        "controller":    ["type", "index"],
        "channel":       ["type", "target_name"],
        "filesystem":    ["target", "xmlindex"],
        "smartcard":     ["mode", "xmlindex"],
        "redirdev":      ["bus", "type", "xmlindex"],
        "tpm":           ["type", "xmlindex"],
        "rng":           ["type", "xmlindex"],
        "panic":         ["type", "xmlindex"],
    }

    if id(origdev) == id(newdev):
        return True

    if not isinstance(origdev, type(newdev)):
        return False

    for devprop in devprops[origdev.DEVICE_TYPE]:
        if devprop == "xmlindex":
            origval = origdev.get_xml_idx()
            newval = idx
        else:
            origval = getattr(origdev, devprop)
            newval = getattr(newdev, devprop)

        if origval != newval:
            return False

    return True


def _find_device(guest, origdev):
    devlist = getattr(guest.devices, origdev.DEVICE_TYPE)
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
        self.errorstr = None


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
        return LibvirtEnumMap.pretty_run_status(status, False)
    def run_status_icon_name(self):
        status = DomainSnapshot.state_str_to_int(self.get_xmlobj().state)
        if status not in LibvirtEnumMap.VM_STATUS_ICONS:
            logging.debug("Unknown status %d, using NOSTATE", status)
            status = libvirt.VIR_DOMAIN_NOSTATE
        return LibvirtEnumMap.VM_STATUS_ICONS[status]

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
        "resources-sampled": (vmmLibvirtObject.RUN_FIRST, None, []),
        "inspection-changed": (vmmLibvirtObject.RUN_FIRST, None, []),
        "pre-startup": (vmmLibvirtObject.RUN_FIRST, None, [object]),
    }

    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, Guest)

        self.cloning = False

        self._install_abort = False
        self._id = None
        self._uuid = None
        self._has_managed_save = None
        self._snapshot_list = None
        self._autostart = None
        self._domain_caps = None
        self._status_reason = None
        self._ip_cache = None

        self.managedsave_supported = False
        self._domain_state_supported = False

        self.inspection = vmmInspectionData()

    def _cleanup(self):
        for snap in self._snapshot_list or []:
            snap.cleanup()
        self._snapshot_list = None
        vmmLibvirtObject._cleanup(self)

    def _init_libvirt_state(self):
        self.managedsave_supported = self.conn.check_support(
            self.conn.SUPPORT_DOMAIN_MANAGED_SAVE, self._backend)
        self._domain_state_supported = self.conn.check_support(
            self.conn.SUPPORT_DOMAIN_STATE, self._backend)

        # Determine available XML flags (older libvirt versions will error
        # out if passed SECURE_XML, INACTIVE_XML, etc)
        (self._inactive_xml_flags,
         self._active_xml_flags) = self.conn.get_dom_flags(self._backend)

        # Prime caches
        info = self._backend.info()
        self._refresh_status(newstatus=info[0])
        self.has_managed_save()
        self.snapshots_supported()

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

        for hostdev in self.xmlobj.devices.hostdev:
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
            if self._domain_state_supported:
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

    def has_spicevmc_type_redirdev(self):
        devs = self.xmlobj.devices.redirdev
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
        for disk in self.get_disk_devices_norefresh():
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
        old_nvram = DeviceDisk(self.conn.get_backend())
        old_nvram.path = self.get_xmlobj().os.nvram

        nvram_dir = os.path.dirname(old_nvram.path)
        new_nvram_path = os.path.join(nvram_dir, "%s_VARS.fd" % new_name)
        new_nvram = DeviceDisk(self.conn.get_backend())

        nvram_install = DeviceDisk.build_vol_install(
                self.conn.get_backend(), os.path.basename(new_nvram_path),
                old_nvram.get_parent_pool(), old_nvram.get_size(), False)
        nvram_install.input_vol = old_nvram.get_vol_object()
        nvram_install.sync_input_vol(only_format=True)

        new_nvram.set_vol_install(nvram_install)
        new_nvram.validate()
        new_nvram.build_storage(None)

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
        # If serial and duplicate console are both present, they both need
        # to be removed at the same time
        con = None
        if self.serial_is_console_dup(devobj):
            con = self.xmlobj.devices.console[0]

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
                guest.cpu.set_special_mode(guest, model)
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
                guest.set_uefi_path(loader)

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

    def define_os(self, os_name=_SENTINEL):
        guest = self._make_xmlobj_to_define()

        if os_name != _SENTINEL:
            guest.set_os_name(os_name)

        self._redefine_xmlobj(guest)

    def define_boot(self, boot_order=_SENTINEL, boot_menu=_SENTINEL,
            kernel=_SENTINEL, initrd=_SENTINEL, dtb=_SENTINEL,
            kernel_args=_SENTINEL, init=_SENTINEL, initargs=_SENTINEL):

        guest = self._make_xmlobj_to_define()
        def _change_boot_order():
            boot_dev_order = []
            devmap = dict((dev.get_xml_id(), dev) for dev in
                          self.get_bootable_devices())
            for b in boot_order:
                if b in devmap:
                    boot_dev_order.append(devmap[b])

            # Unset the traditional boot order
            guest.os.bootorder = []

            # Unset device boot order
            for dev in guest.devices.get_all():
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
            io=_SENTINEL, discard=_SENTINEL, detect_zeroes=_SENTINEL,
            driver_type=_SENTINEL, bus=_SENTINEL, addrstr=_SENTINEL,
            sgio=_SENTINEL, managed_pr=_SENTINEL):
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
            disks = (self.xmlobj.devices.disk +
                     self.get_xmlobj(inactive=True).devices.disk)
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
        if discard != _SENTINEL:
            editdev.driver_discard = discard or None
        if detect_zeroes != _SENTINEL:
            editdev.driver_detect_zeroes = detect_zeroes or None
        if driver_type != _SENTINEL:
            editdev.driver_type = driver_type or None
        if serial != _SENTINEL:
            editdev.serial = serial or None

        if sgio != _SENTINEL:
            editdev.sgio = sgio or None

        if managed_pr != _SENTINEL:
            editdev.reservations_managed = "yes" if managed_pr else None

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
            portgroup=_SENTINEL, macaddr=_SENTINEL, linkstate=_SENTINEL):
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

        if linkstate != _SENTINEL:
            editdev.link_state = "up" if linkstate else "down"

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
            editdev.type = None
            editdev.type = editdev.default_type()

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
                ctrls = xmlobj.devices.controller
                ctrls = [x for x in ctrls if (x.type ==
                         DeviceController.TYPE_USB)]
                for dev in ctrls:
                    xmlobj.remove_device(dev)

                if model == "ich9-ehci1":
                    for dev in DeviceController.get_usb2_controllers(
                            xmlobj.conn):
                        xmlobj.add_device(dev)
                elif model == "usb3":
                    dev = DeviceController.get_usb3_controller(
                        xmlobj.conn, xmlobj)
                    xmlobj.add_device(dev)
                else:
                    dev = DeviceController(xmlobj.conn)
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

    def define_tpm(self, devobj, do_hotplug, model=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return

        if model != _SENTINEL:
            editdev.model = model

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

        devxml = devobj.get_xml()
        logging.debug("attach_device with xml=\n%s", devxml)
        self._backend.attachDevice(devxml)

    def detach_device(self, devobj):
        """
        Hotunplug device from running guest
        """
        if not self.is_active():
            return

        devxml = devobj.get_xml()
        logging.debug("detach_device with xml=\n%s", devxml)
        self._backend.detachDevice(devxml)

    def _update_device(self, devobj, flags=None):
        if flags is None:
            flags = getattr(libvirt, "VIR_DOMAIN_DEVICE_MODIFY_LIVE", 1)

        xml = devobj.get_xml()
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
        graphics = self.xmlobj.devices.graphics[0]
        if (graphics.type == "vnc" and
                graphics.get_first_listen_type() == "none" and
                not self.conn.SUPPORT_CONN_VNC_NONE_AUTH):
            flags = libvirt.VIR_DOMAIN_OPEN_GRAPHICS_SKIPAUTH

        return self._backend.openGraphicsFD(0, flags)

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

    def refresh_interface_addresses(self, iface):
        def agent_ready():
            for dev in self.xmlobj.devices.channel:
                if (dev.type == "unix" and
                    dev.target_name == dev.CHANNEL_NAME_QEMUGA and
                    dev.target_state == "connected"):
                    return True
            return False

        self._ip_cache = {"qemuga": {}, "arp": {}}
        if iface.type == "network":
            net = self.conn.get_net(iface.source)
            if net:
                net.refresh_dhcp_leases()
        if not self.is_active():
            return

        if agent_ready():
            self._ip_cache["qemuga"] = self._get_interface_addresses(
                libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT)

        arp_flag = getattr(libvirt,
            "VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP", 3)
        self._ip_cache["arp"] = self._get_interface_addresses(arp_flag)

    def _get_interface_addresses(self, source):
        logging.debug("Calling interfaceAddresses source=%s", source)
        try:
            return self._backend.interfaceAddresses(source)
        except Exception as e:
            logging.debug("interfaceAddresses failed: %s", str(e))
        return {}

    def get_interface_addresses(self, iface):
        if self._ip_cache is None:
            self.refresh_interface_addresses(iface)

        qemuga = self._ip_cache["qemuga"]
        arp = self._ip_cache["arp"]
        leases = []
        if iface.type == "network":
            net = self.conn.get_net(iface.source)
            if net:
                leases = net.get_dhcp_leases()

        def extract_dom(info):
            ipv4 = None
            ipv6 = None
            for addrs in info.values():
                if addrs["hwaddr"] != iface.macaddr:
                    continue
                if not addrs["addrs"]:
                    continue
                for addr in addrs["addrs"]:
                    if addr["type"] == 0:
                        ipv4 = addr["addr"]
                    elif (addr["type"] == 1 and
                          not str(addr["addr"]).startswith("fe80")):
                        ipv6 = addr["addr"] + "/" + str(addr["prefix"])
            return ipv4, ipv6

        def extract_lease(info):
            ipv4 = None
            ipv6 = None
            if info["mac"] == iface.macaddr:
                if info["type"] == 0:
                    ipv4 = info["ipaddr"]
                if info["type"] == 1:
                    ipv6 = info["ipaddr"]
            return ipv4, ipv6

        for ips in ([qemuga] + leases + [arp]):
            if "expirytime" in ips:
                ipv4, ipv6 = extract_lease(ips)
            else:
                ipv4, ipv6 = extract_dom(ips)
            if ipv4 or ipv6:
                return ipv4, ipv6
        return None, None

    def refresh_snapshots(self):
        self._snapshot_list = None


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

        for d in self.xmlobj.devices.disk:
            if not cdrom and d.device == "cdrom":
                cdrom = d
            if not floppy and d.device == "floppy":
                floppy = d
            if not disk and d.device not in ["cdrom", "floppy"]:
                disk = d
            if cdrom and disk and floppy:
                break

        for n in self.xmlobj.devices.interface:
            net = n
            break

        for b in boot_order:
            if b == "network" and net:
                ret.append(net.get_xml_id())
            if b == "hd" and disk:
                ret.append(disk.get_xml_id())
            if b == "cdrom" and cdrom:
                ret.append(cdrom.get_xml_id())
            if b == "fd" and floppy:
                ret.append(floppy.get_xml_id())
        return ret

    def _get_device_boot_order(self):
        devs = self.get_bootable_devices()
        order = []
        for dev in devs:
            if not dev.boot.order:
                continue
            order.append((dev.get_xml_id(), dev.boot.order))

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

    def get_interface_devices_norefresh(self):
        xmlobj = self.get_xmlobj(refresh_if_nec=False)
        return xmlobj.devices.interface
    def get_disk_devices_norefresh(self):
        xmlobj = self.get_xmlobj(refresh_if_nec=False)
        return xmlobj.devices.disk

    def serial_is_console_dup(self, serial):
        if serial.DEVICE_TYPE != "serial":
            return False

        consoles = self.xmlobj.devices.console
        if not consoles:
            return False

        console = consoles[0]
        if (console.type == serial.type and
            (console.target_type is None or console.target_type == "serial")):
            return True
        return False

    def can_use_device_boot_order(self):
        # Return 'True' if guest can use new style boot device ordering
        return self.conn.is_qemu() or self.conn.is_test()

    def get_bootable_devices(self):
        # redirdev can also be marked bootable, but it should be rarely
        # used and clutters the UI
        devs = (self.xmlobj.devices.disk +
                self.xmlobj.devices.interface +
                self.xmlobj.devices.hostdev)
        return devs

    def get_serialcon_devices(self):
        return self.xmlobj.devices.serial + self.xmlobj.devices.console

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


    ###################
    # Stats accessors #
    ###################

    def _get_stats(self):
        return self.conn.statsmanager.get_vm_statslist(self)
    def stats_memory(self):
        return self._get_stats().get_record("curmem")
    def cpu_time(self):
        return self._get_stats().get_record("cpuTime")
    def host_cpu_time_percentage(self):
        return self._get_stats().get_record("cpuHostPercent")
    def guest_cpu_time_percentage(self):
        return self._get_stats().get_record("cpuGuestPercent")
    def network_rx_rate(self):
        return self._get_stats().get_record("netRxRate")
    def network_tx_rate(self):
        return self._get_stats().get_record("netTxRate")
    def disk_read_rate(self):
        return self._get_stats().get_record("diskRdRate")
    def disk_write_rate(self):
        return self._get_stats().get_record("diskWrRate")

    def network_traffic_rate(self):
        return self.network_tx_rate() + self.network_rx_rate()
    def network_traffic_max_rate(self):
        stats = self._get_stats()
        return max(stats.netRxMaxRate, stats.netTxMaxRate)
    def disk_io_rate(self):
        return self.disk_read_rate() + self.disk_write_rate()
    def disk_io_max_rate(self):
        stats = self._get_stats()
        return max(stats.diskRdMaxRate, stats.diskWrMaxRate)

    def host_cpu_time_vector(self, limit=None):
        return self._get_stats().get_vector("cpuHostPercent", limit)
    def guest_cpu_time_vector(self, limit=None):
        return self._get_stats().get_vector("cpuGuestPercent", limit)
    def stats_memory_vector(self, limit=None):
        return self._get_stats().get_vector("currMemPercent", limit)
    def network_traffic_vectors(self, limit=None, ceil=None):
        return self._get_stats().get_in_out_vector(
                "netRxRate", "netTxRate", limit, ceil)
    def disk_io_vectors(self, limit=None, ceil=None):
        return self._get_stats().get_in_out_vector(
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
        return LibvirtEnumMap.pretty_run_status(
                self.status(), self.has_managed_save())

    def run_status_reason(self):
        return LibvirtEnumMap.pretty_status_reason(
                self.status(), self.status_reason())

    def run_status_icon_name(self):
        status = self.status()
        if status not in LibvirtEnumMap.VM_STATUS_ICONS:
            logging.debug("Unknown status %s, using NOSTATE", status)
            status = libvirt.VIR_DOMAIN_NOSTATE
        return LibvirtEnumMap.VM_STATUS_ICONS[status]

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

    def get_cache_dir(self):
        ret = os.path.join(self.conn.get_cache_dir(), self.get_uuid())
        if not os.path.exists(ret):
            os.makedirs(ret, 0o755)
        return ret


    ###################
    # Polling helpers #
    ###################

    def tick(self, stats_update=True):
        if (not self._using_events() and
            not stats_update):
            return

        dosignal = False
        if not self._using_events():
            # For domains it's pretty important that we are always using
            # the latest XML, but other objects probably don't want to do
            # this since it could be a performance hit.
            self._invalidate_xml()
            info = self._backend.info()
            dosignal = self._refresh_status(newstatus=info[0], cansignal=False)

        if stats_update:
            self.conn.statsmanager.refresh_vm_stats(self)
        if dosignal:
            self.idle_emit("state-changed")
        if stats_update:
            self.idle_emit("resources-sampled")


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
        return self._backend.installer_instance.autostart
    def set_autostart(self, val):
        self._backend.installer_instance.autostart = bool(val)
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
        return self._backend.get_xml()

    def _define(self, xml):
        ignore = xml
        self.emit("state-changed")

    def _invalidate_xml(self):
        vmmDomain._invalidate_xml(self)
        self._orig_xml = None

    def _make_xmlobj_to_define(self):
        if not self._orig_xml:
            self._orig_xml = self._backend.get_xml()
        return self._backend

    def _redefine_xmlobj(self, xmlobj, origxml=None):
        vmmDomain._redefine_xmlobj(self, xmlobj, origxml=self._orig_xml)
