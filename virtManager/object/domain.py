# Copyright (C) 2006, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import time
import threading

import libvirt

from virtinst import DeviceConsole
from virtinst import DeviceController
from virtinst import DeviceDisk
from virtinst import DomainSnapshot
from virtinst import Guest
from virtinst import log

from .libvirtobject import vmmLibvirtObject
from ..baseclass import vmmGObject
from ..lib.libvirtenummap import LibvirtEnumMap
from ..lib import testmock


class _SENTINEL(object):
    pass


def start_job_progress_thread(vm, meter, progtext):
    current_thread = threading.current_thread()

    def jobinfo_cb():
        while True:
            time.sleep(0.5)

            if not current_thread.is_alive():
                return

            try:
                jobinfo = vm.job_info()
                data_total = int(jobinfo[3])
                data_remaining = int(jobinfo[5])

                # data_total is 0 if the job hasn't started yet
                if not data_total:
                    continue  # pragma: no cover

                if not meter.is_started():
                    meter.start(progtext, data_total)

                progress = data_total - data_remaining
                meter.update(progress)
            except Exception:  # pragma: no cover
                log.exception("Error calling jobinfo")
                return

    if vm.supports_domain_job_info():
        t = threading.Thread(target=jobinfo_cb, name="job progress reporting", args=())
        t.daemon = True
        t.start()


class _IPFetcher:
    """
    Helper class to contain all IP fetching and processing logic
    """

    def __init__(self):
        self._cache = None

    def refresh(self, vm, iface):
        self._cache = {"qemuga": {}, "arp": {}}

        if iface.type == "network":
            net = vm.conn.get_net_by_name(iface.source)
            if net:
                net.get_dhcp_leases(refresh=True)

        if not vm.is_active():
            return

        if vm.agent_ready():
            self._cache["qemuga"] = vm.get_interface_addresses(
                iface, libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT
            )

        arp_flag = getattr(libvirt, "VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_ARP", 3)
        self._cache["arp"] = vm.get_interface_addresses(iface, arp_flag)

    def get(self, vm, iface):
        if self._cache is None:
            self.refresh(vm, iface)

        qemuga = self._cache["qemuga"]
        arp = self._cache["arp"]
        leases = []
        if iface.type == "network":
            net = vm.conn.get_net_by_name(iface.source)
            if net:
                leases = net.get_dhcp_leases()

        def extract_dom(addrs):
            ipv4 = None
            ipv6 = None
            if addrs["hwaddr"] == iface.macaddr:
                for addr in addrs["addrs"] or []:
                    if addr["type"] == 0:
                        ipv4 = addr["addr"]
                    elif addr["type"] == 1 and not str(addr["addr"]).startswith("fe80"):
                        ipv6 = addr["addr"] + "/" + str(addr["prefix"])
            return ipv4, ipv6

        def extract_lease(lease):
            ipv4 = None
            ipv6 = None
            mac = lease["mac"]
            if vm.conn.is_test():
                # Hack it to match our interface for UI testing
                mac = iface.macaddr
            if mac == iface.macaddr:
                if lease["type"] == 0:
                    ipv4 = lease["ipaddr"]
                elif lease["type"] == 1:
                    ipv6 = lease["ipaddr"]
            return ipv4, ipv6

        for datalist in [list(qemuga.values()), leases, list(arp.values())]:
            ipv4 = None
            ipv6 = None
            for data in datalist:
                if "expirytime" in data:
                    tmpipv4, tmpipv6 = extract_lease(data)
                else:
                    tmpipv4, tmpipv6 = extract_dom(data)
                ipv4 = tmpipv4 or ipv4
                ipv6 = tmpipv6 or ipv6
            if ipv4 or ipv6:
                return ipv4, ipv6
        return None, None


class vmmInspectionApplication(object):
    def __init__(self):
        self.name = None
        self.display_name = None
        self.epoch = None
        self.version = None
        self.release = None
        self.summary = None
        self.description = None


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
        self.package_format = None


class vmmDomainSnapshot(vmmLibvirtObject):
    """
    Class wrapping a virDomainSnapshot object
    """

    def __init__(self, conn, backend):
        vmmLibvirtObject.__init__(self, conn, backend, backend.getName(), DomainSnapshot)

    ##########################
    # Required class methods #
    ##########################

    def _conn_tick_poll_param(self):
        return None  # pragma: no cover

    def class_name(self):
        return "snapshot"  # pragma: no cover

    def _XMLDesc(self, flags):
        return self._backend.getXMLDesc(flags=flags)

    def _get_backend_status(self):
        return self._STATUS_ACTIVE

    ###########
    # Actions #
    ###########

    def delete(self, force=True):
        ignore = force
        self._backend.delete()

    def _state_str_to_int(self):
        state = self.get_xmlobj().state
        statemap = {
            "nostate": libvirt.VIR_DOMAIN_NOSTATE,
            "running": libvirt.VIR_DOMAIN_RUNNING,
            "blocked": libvirt.VIR_DOMAIN_BLOCKED,
            "paused": libvirt.VIR_DOMAIN_PAUSED,
            "shutdown": libvirt.VIR_DOMAIN_SHUTDOWN,
            "shutoff": libvirt.VIR_DOMAIN_SHUTOFF,
            "crashed": libvirt.VIR_DOMAIN_CRASHED,
            "pmsuspended": getattr(libvirt, "VIR_DOMAIN_PMSUSPENDED", 7),
        }
        return statemap.get(state, libvirt.VIR_DOMAIN_SHUTOFF)

    def run_status(self):
        status = self._state_str_to_int()
        return LibvirtEnumMap.pretty_run_status(status, False)

    def run_status_icon_name(self):
        status = self._state_str_to_int()
        if status not in LibvirtEnumMap.VM_STATUS_ICONS:  # pragma: no cover
            log.debug("Unknown status %d, using NOSTATE", status)
            status = libvirt.VIR_DOMAIN_NOSTATE
        return LibvirtEnumMap.VM_STATUS_ICONS[status]

    def is_running(self):
        """
        Captured state is a running domain.
        """
        return self._state_str_to_int() in [libvirt.VIR_DOMAIN_RUNNING]

    def has_run_state(self):
        """
        Captured state contains run state in addition to disk state.
        """
        return self._state_str_to_int() in [libvirt.VIR_DOMAIN_RUNNING, libvirt.VIR_DOMAIN_PAUSED]

    def is_current(self):
        return self._backend.isCurrent()

    def is_external(self):
        if self.get_xmlobj().memory_type == "external":
            return True
        for disk in self.get_xmlobj().disks:
            if disk.snapshot == "external":
                return True
        return False


class _vmmDomainSetTimeThread(vmmGObject):
    """
    A separate thread handling time setting operations as not to block the main
    UI.
    """

    def __init__(self, domain):
        vmmGObject.__init__(self)
        self._domain = domain
        self._do_cancel = threading.Event()
        self._do_cancel.clear()
        self._thread = None
        self._maxwait = 30
        self._sleep = 0.5

    def start(self):
        """
        Start time setting thread if setting time is supported by the
        connection. Stop the old thread first. May block until the old thread
        terminates.
        """
        self.stop()

        # Only run the API for qemu and test drivers, they are the only ones
        # that support it. This will save spamming logs with error output.
        if not self._domain.conn.is_qemu() and not self._domain.conn.is_test():
            return  # pragma: no cover

        # For qemu, only run the API if the VM has the qemu guest agent in
        # the XML.
        if self._domain.conn.is_qemu() and not self._domain.has_agent():
            return

        log.debug("Starting time setting thread")
        self._thread = threading.Thread(name="settime thread", target=self._do_loop)
        self._thread.start()

    def stop(self):
        """
        Signal running thread to terminate and wait for it to do so.
        """
        if not self._thread:
            return

        log.debug("Stopping time setting thread")
        self._do_cancel.set()
        # thread may be in a loop waiting for an agent to come online or just
        # waiting for a set time operation to finish
        self._thread.join()
        self._thread = None
        self._do_cancel.clear()

    def _wait_for_agent(self):
        # Setting time of a qemu domain can only work if an agent is
        # defined and online. We only get here if one is defined. So wait
        # for it to come online now.
        waited = 0
        while waited < self._maxwait and not self._domain.agent_ready():
            if waited == 0:
                log.debug("Waiting for qemu guest agent to come online...")

            # sleep some time and potentially abort
            if self._do_cancel.wait(self._sleep):
                return

            waited += self._sleep

        if not self._domain.agent_ready():  # pragma: no cover
            log.debug("Giving up on qemu guest agent for time sync")
            return

    def _do_loop(self):
        """
        Run the domain's set time operation. Potentially wait for a guest agent
        to come online beforehand.
        """
        if self._domain.conn.is_qemu():
            self._wait_for_agent()
        self._domain.set_time()

    def _cleanup(self):
        self.stop()


class vmmDomain(vmmLibvirtObject):
    """
    Class wrapping virDomain libvirt objects. Is also extended to be
    backed by a virtinst.Guest object for new VM 'customize before install'
    """

    __gsignals__ = {
        "resources-sampled": (vmmLibvirtObject.RUN_FIRST, None, []),
        "inspection-changed": (vmmLibvirtObject.RUN_FIRST, None, []),
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
        self._ipfetcher = _IPFetcher()

        self.managedsave_supported = False
        self._domain_state_supported = False

        self.inspection = vmmInspectionData()
        self._set_time_thread = _vmmDomainSetTimeThread(self)

    def _cleanup(self):
        for snap in self._snapshot_list or []:
            snap.cleanup()
        self._snapshot_list = None
        self._set_time_thread.cleanup()
        self._set_time_thread = None
        vmmLibvirtObject._cleanup(self)

    def _init_libvirt_state(self):
        self.managedsave_supported = self.conn.support.domain_managed_save(self._backend)
        self._domain_state_supported = self.conn.support.domain_state(self._backend)

        # Determine available XML flags (older libvirt versions will error
        # out if passed SECURE_XML, INACTIVE_XML, etc)
        (self._inactive_xml_flags, self._active_xml_flags) = self.conn.get_dom_flags(self._backend)

        # Prime caches
        info = self._backend.info()
        self._refresh_status(newstatus=info[0])
        self.has_managed_save()
        self.snapshots_supported()

        if (
            self.get_name() == "Domain-0"
            and self.get_uuid() == "00000000-0000-0000-0000-000000000000"
        ):
            # We don't want virt-manager to track Domain-0 since it
            # doesn't work with our UI. Raising an error will ensures it
            # is denylisted.
            raise RuntimeError("Can't track Domain-0 as a vmmDomain")  # pragma: no cover

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

    # If manual shutdown or destroy specified, make sure we don't continue
    # install process
    def get_install_abort(self):
        return bool(self._install_abort)

    def has_nvram(self):
        return bool(self.get_xmlobj().is_uefi() or self.get_xmlobj().os.nvram)

    def has_tpm_state(self):
        return any(tpm.type == "emulator" for tpm in self.get_xmlobj().devices.tpm)

    def is_persistent(self):
        return bool(self._backend.isPersistent())

    def has_shared_mem(self):
        """
        Return a value for 'Enable shared memory' UI, and an error if
        the value is not editable
        """
        is_shared = False
        err = None
        domcaps = self.get_domain_capabilities()

        if self.xmlobj.cpu.cells:
            err = _("Can not change shared memory setting when <numa> is configured.")
        elif (
            not domcaps.supports_filesystem_virtiofs() or not domcaps.supports_memorybacking_memfd()
        ):
            err = _("Libvirt may not be new enough to support memfd.")
        else:
            is_shared = self.xmlobj.memoryBacking.source_type == "memfd"

        return is_shared, err

    ##################
    # Support checks #
    ##################

    def supports_domain_job_info(self):
        if self.conn.is_test():
            # jobinfo isn't actually supported but this tests more code
            return True
        return self.conn.support.domain_job_info(self._backend)

    def snapshots_supported(self):
        if not self.conn.support.domain_list_snapshots(self._backend):
            return _("Libvirt connection does not support snapshots.")

    def get_domain_capabilities(self):
        if not self._domain_caps:
            self._domain_caps = self.get_xmlobj().lookup_domcaps()
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

        dev = xmlobj.find_device(origdev)
        if dev:
            return dev

        # If we are removing multiple dev from an active VM, a double
        # attempt may result in a lookup failure. If device is present
        # in the active XML, assume all is good.
        if self.get_xmlobj().find_device(origdev):  # pragma: no cover
            log.debug("Device in active config but not inactive config.")
            return

        raise RuntimeError(  # pragma: no cover
            _("Could not find specified device in the inactive VM configuration: %s")
            % repr(origdev)
        )

    def _process_device_define(self, editdev, xmlobj, do_hotplug):
        if do_hotplug:
            self.hotplug(device=editdev)
        else:
            self._redefine_xmlobj(xmlobj)

    def _copy_nvram_file(self, new_name):
        """
        We need to do this copy magic because there is no Libvirt storage API
        to rename storage volume.
        """
        if not self.has_nvram():
            return None, None

        old_nvram_path = self.get_xmlobj().os.nvram
        if not old_nvram_path:  # pragma: no cover
            # Probably using firmware=efi which doesn't put nvram
            # path in the XML on older libvirt. Build the implied path
            old_nvram_path = os.path.join(
                self.conn.get_backend().get_libvirt_data_root_dir(),
                self.conn.get_backend().get_uri_driver(),
                "nvram",
                "%s_VARS.fd" % self.get_name(),
            )
            log.debug(
                "Guest is expected to use <nvram> but we didn't "
                "find one in the XML. Generated implied path=%s",
                old_nvram_path,
            )

        if not DeviceDisk.path_definitely_exists(
            self.conn.get_backend(), old_nvram_path
        ):  # pragma: no cover
            log.debug(
                "old_nvram_path=%s but it doesn't appear to exist. "
                "skipping rename nvram duplication",
                old_nvram_path,
            )
            return None, None

        from virtinst import Cloner

        old_nvram = DeviceDisk(self.conn.get_backend())
        old_nvram.set_source_path(old_nvram_path)
        ext = os.path.splitext(old_nvram_path)[1]

        nvram_dir = os.path.dirname(old_nvram.get_source_path())
        new_nvram_path = os.path.join(
            nvram_dir, "%s_VARS%s" % (os.path.basename(new_name), ext or ".fd")
        )

        new_nvram = Cloner.build_clone_disk(old_nvram, new_nvram_path, True, False)

        new_nvram.build_storage(None)
        return new_nvram, old_nvram

    ##############################
    # Persistent XML change APIs #
    ##############################

    def rename_domain(self, new_name):
        if new_name == self.get_name():
            return
        Guest.validate_name(self.conn.get_backend(), str(new_name))

        new_nvram, old_nvram = self._copy_nvram_file(new_name)

        try:
            self.define_name(new_name)
        except Exception as error:
            if new_nvram:
                try:
                    new_nvram.get_vol_object().delete(0)
                except Exception as warn:  # pragma: no cover
                    log.debug("rename failed and new nvram was not removed: '%s'", warn)
            raise error

        if not new_nvram:
            return

        try:
            old_nvram.get_vol_object().delete(0)
        except Exception as warn:  # pragma: no cover
            log.debug("old nvram file was not removed: '%s'", warn)

        self.define_overview(nvram=new_nvram.get_source_path())

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
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, False)
        if not editdev:
            return  # pragma: no cover

        xmlobj.remove_device(editdev)

        self._redefine_xmlobj(xmlobj)

    def replace_device_xml(self, devobj, newxml):
        """
        When device XML is editing from the XML editor window.
        """
        do_hotplug = False
        devclass = devobj.__class__
        newdev = devclass(devobj.conn, parsexml=newxml)

        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        xmlobj.devices.replace_child(editdev, newdev)
        self._redefine_xmlobj(xmlobj)
        return editdev, newdev

    ##########################
    # non-device XML editing #
    ##########################

    def define_cpu(
        self,
        vcpus=_SENTINEL,
        model=_SENTINEL,
        secure=_SENTINEL,
        sockets=_SENTINEL,
        cores=_SENTINEL,
        threads=_SENTINEL,
        clear_topology=_SENTINEL,
    ):
        guest = self._make_xmlobj_to_define()

        if vcpus != _SENTINEL:
            guest.vcpus = int(vcpus)
            guest.vcpu_current = int(vcpus)

        if clear_topology is True:
            guest.cpu.topology.clear()
        elif sockets != _SENTINEL:
            guest.cpu.topology.sockets = sockets
            guest.cpu.topology.cores = cores
            guest.cpu.topology.threads = threads

        if secure != _SENTINEL or model != _SENTINEL:
            guest.cpu.secure = secure
            if model in guest.cpu.SPECIAL_MODES:
                guest.cpu.set_special_mode(guest, model)
            else:
                guest.cpu.set_model(guest, model)

        self._redefine_xmlobj(guest)

    def _edit_shared_mem(self, guest, mem_shared):
        source_type = _SENTINEL
        access_mode = _SENTINEL

        if mem_shared:
            source_type = "memfd"
            access_mode = "shared"
        else:
            source_type = None
            access_mode = None

        if source_type != _SENTINEL:
            guest.memoryBacking.source_type = source_type
        if access_mode != _SENTINEL:
            guest.memoryBacking.access_mode = access_mode

    def define_memory(self, memory=_SENTINEL, maxmem=_SENTINEL, mem_shared=_SENTINEL):
        guest = self._make_xmlobj_to_define()

        if memory != _SENTINEL:
            guest.currentMemory = int(memory)
        if maxmem != _SENTINEL:
            guest.memory = int(maxmem)
        if mem_shared != _SENTINEL:
            self._edit_shared_mem(guest, mem_shared)

        self._redefine_xmlobj(guest)

    def define_overview(
        self,
        machine=_SENTINEL,
        description=_SENTINEL,
        title=_SENTINEL,
        loader=_SENTINEL,
        nvram=_SENTINEL,
        firmware=_SENTINEL,
    ):
        guest = self._make_xmlobj_to_define()

        old_machine = None
        if machine != _SENTINEL:
            old_machine = guest.os.machine
            guest.os.machine = machine
            self._domain_caps = None
        if description != _SENTINEL:
            guest.description = description or None
        if title != _SENTINEL:
            guest.title = title or None

        if loader != _SENTINEL and firmware != _SENTINEL:
            guest.os.firmware = firmware
            if loader is None:
                guest.os.loader = None

                # But if switching to firmware=efi we may need to
                # preserve NVRAM paths, so skip clearing all the properties
                # and let libvirt do it for us.
                if firmware is None:
                    guest.disable_uefi()
            else:
                # Implies UEFI
                guest.set_uefi_path(loader)

        if nvram != _SENTINEL:
            guest.os.nvram = nvram

        if old_machine == "pc" and guest.os.machine == "q35":
            guest.add_q35_pcie_controllers()

        elif old_machine == "q35" and guest.os.machine == "pc":
            for dev in guest.devices.controller:
                if dev.model in ["pcie-root", "pcie-root-port"]:
                    guest.remove_device(dev)

        self._redefine_xmlobj(guest)

    def define_os(self, os_name=_SENTINEL):
        guest = self._make_xmlobj_to_define()

        if os_name != _SENTINEL:
            guest.set_os_name(os_name)

        self._redefine_xmlobj(guest)

    def define_boot(
        self,
        boot_order=_SENTINEL,
        boot_menu=_SENTINEL,
        kernel=_SENTINEL,
        initrd=_SENTINEL,
        dtb=_SENTINEL,
        kernel_args=_SENTINEL,
        init=_SENTINEL,
        initargs=_SENTINEL,
    ):

        guest = self._make_xmlobj_to_define()
        if boot_order != _SENTINEL:
            legacy = not self.can_use_device_boot_order()
            guest.set_boot_order(boot_order, legacy=legacy)

        if boot_menu != _SENTINEL:
            guest.os.bootmenu_enable = bool(boot_menu)
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

    def define_disk(
        self,
        devobj,
        do_hotplug,
        path=_SENTINEL,
        readonly=_SENTINEL,
        shareable=_SENTINEL,
        removable=_SENTINEL,
        cache=_SENTINEL,
        discard=_SENTINEL,
        bus=_SENTINEL,
        serial=_SENTINEL,
    ):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        validate = False
        if path != _SENTINEL:
            editdev.set_source_path(path)
            if not do_hotplug:
                editdev.sync_path_props()
                validate = True

        if readonly != _SENTINEL:
            editdev.read_only = readonly
        if shareable != _SENTINEL:
            editdev.shareable = shareable
        if removable != _SENTINEL:
            editdev.removable = removable

        if serial != _SENTINEL:
            editdev.serial = serial or None
        if cache != _SENTINEL:
            editdev.driver_cache = cache or None
        if discard != _SENTINEL:
            editdev.driver_discard = discard or None

        if bus != _SENTINEL:
            editdev.change_bus(self.xmlobj, bus)

        if validate:
            editdev.validate()
        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_network(
        self,
        devobj,
        do_hotplug,
        ntype=_SENTINEL,
        source=_SENTINEL,
        mode=_SENTINEL,
        model=_SENTINEL,
        macaddr=_SENTINEL,
        linkstate=_SENTINEL,
        portgroup=_SENTINEL,
    ):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        if ntype != _SENTINEL:
            editdev.source = None

            editdev.type = ntype
            editdev.source = source
            editdev.source_mode = mode or None
            editdev.portgroup = portgroup or None

        if model != _SENTINEL:
            if editdev.model != model:
                editdev.address.clear()
            editdev.model = model

        if macaddr != _SENTINEL:
            editdev.macaddr = macaddr

        if linkstate != _SENTINEL:
            editdev.link_state = "up" if linkstate else "down"

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_graphics(
        self,
        devobj,
        do_hotplug,
        listen=_SENTINEL,
        port=_SENTINEL,
        passwd=_SENTINEL,
        gtype=_SENTINEL,
        gl=_SENTINEL,
        rendernode=_SENTINEL,
    ):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        if listen != _SENTINEL:
            editdev.listen = listen
        if port != _SENTINEL:
            editdev.port = port
        if passwd != _SENTINEL:
            editdev.passwd = passwd
        if gtype != _SENTINEL:
            editdev.type = gtype
        if gl != _SENTINEL:
            editdev.gl = gl
        if rendernode != _SENTINEL:
            editdev.rendernode = rendernode

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_sound(self, devobj, do_hotplug, model=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        if model != _SENTINEL:
            if editdev.model != model:
                editdev.address.clear()
            editdev.model = model

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_video(self, devobj, do_hotplug, model=_SENTINEL, accel3d=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

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

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_watchdog(self, devobj, do_hotplug, model=_SENTINEL, action=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        if model != _SENTINEL:
            if editdev.model != model:
                editdev.address.clear()
            editdev.model = model

        if action != _SENTINEL:
            editdev.action = action

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_smartcard(self, devobj, do_hotplug, model=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        if model != _SENTINEL:
            editdev.mode = model
            editdev.type = None
            editdev.type = editdev.default_type()

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_controller(self, devobj, do_hotplug, model=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        def _change_model():
            if editdev.type == "usb":
                ctrls = xmlobj.devices.controller
                ctrls = [x for x in ctrls if (x.type == DeviceController.TYPE_USB)]
                for dev in ctrls:
                    xmlobj.remove_device(dev)

                if model == "ich9-ehci1":
                    for dev in DeviceController.get_usb2_controllers(xmlobj.conn):
                        xmlobj.add_device(dev)
                elif model == "usb3":
                    dev = DeviceController.get_usb3_controller(xmlobj.conn, xmlobj)
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

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_filesystem(self, devobj, do_hotplug, newdev=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        if newdev != _SENTINEL:
            # pylint: disable=maybe-no-member
            editdev.type = newdev.type
            editdev.accessmode = newdev.accessmode
            editdev.driver_type = newdev.driver_type
            editdev.driver_format = newdev.driver_format
            editdev.readonly = newdev.readonly
            editdev.source_units = newdev.source_units
            editdev.source = newdev.source
            editdev.target = newdev.target

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_hostdev(self, devobj, do_hotplug, rom_bar=_SENTINEL, startup_policy=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        if rom_bar != _SENTINEL:
            editdev.rom_bar = rom_bar

        if startup_policy != _SENTINEL:
            editdev.startup_policy = startup_policy

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_tpm(self, devobj, do_hotplug, newdev=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        if newdev != _SENTINEL:
            editdev.model = newdev.model
            editdev.type = newdev.type
            editdev.version = newdev.version
            editdev.device_path = newdev.device_path

        self._process_device_define(editdev, xmlobj, do_hotplug)

    def define_vsock(self, devobj, do_hotplug, auto_cid=_SENTINEL, cid=_SENTINEL):
        xmlobj = self._make_xmlobj_to_define()
        editdev = self._lookup_device_to_define(xmlobj, devobj, do_hotplug)
        if not editdev:
            return  # pragma: no cover

        if auto_cid != _SENTINEL:
            editdev.auto_cid = auto_cid
        if cid != _SENTINEL:
            editdev.cid = cid

        self._process_device_define(editdev, xmlobj, do_hotplug)

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
        log.debug("attach_device with xml=\n%s", devxml)
        self._backend.attachDevice(devxml)

    def detach_device(self, devobj):
        """
        Hotunplug device from running guest
        """
        if not self.is_active():
            return

        devxml = devobj.get_xml()
        log.debug("detach_device with xml=\n%s", devxml)
        self._backend.detachDevice(devxml)

    def _update_device(self, devobj, flags=None):
        if flags is None:
            flags = getattr(libvirt, "VIR_DOMAIN_DEVICE_MODIFY_LIVE", 1)

        xml = devobj.get_xml()
        log.debug("update_device with xml=\n%s", xml)

        if self.config.CLITestOptions.test_update_device_fail:
            raise RuntimeError("fake update device failure")
        self._backend.updateDeviceFlags(xml, flags)

    def hotplug(
        self,
        memory=_SENTINEL,
        maxmem=_SENTINEL,
        description=_SENTINEL,
        title=_SENTINEL,
        device=_SENTINEL,
    ):
        if not self.is_active():
            return

        def _hotplug_memory(val):
            if val != self.xmlobj.currentMemory:
                self._backend.setMemory(val)

        def _hotplug_maxmem(val):
            if val != self.xmlobj.memory:
                self._backend.setMaxMemory(val)

        def _hotplug_metadata(val, mtype):
            flags = libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG
            self._backend.setMetadata(mtype, val, None, None, flags)

        if memory != _SENTINEL:
            log.debug(
                "Hotplugging curmem=%s maxmem=%s for VM '%s'", memory, maxmem, self.get_name()
            )

            actual_cur = self.xmlobj.currentMemory
            if maxmem < actual_cur:
                # Set current first to avoid error
                _hotplug_memory(memory)
                _hotplug_maxmem(maxmem)
            else:
                _hotplug_maxmem(maxmem)
                _hotplug_memory(memory)

        if description != _SENTINEL:
            _hotplug_metadata(description, libvirt.VIR_DOMAIN_METADATA_DESCRIPTION)
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
        if self.conn.is_test():
            return testmock.fake_job_info()
        # It's tough to hit this via uitests because it depends
        # on the job lasting more than a second
        return self._backend.jobInfo()  # pragma: no cover

    def abort_job(self):
        self._backend.abortJob()

    def open_console(self, devname, stream, flags=0):
        return self._backend.openConsole(devname, stream, flags)

    def open_graphics_fd(self, idx):
        flags = 0
        return self._backend.openGraphicsFD(idx, flags)

    def list_snapshots(self):
        if self._snapshot_list is None:
            newlist = []
            for rawsnap in self._backend.listAllSnapshots():
                obj = vmmDomainSnapshot(self.conn, rawsnap)
                obj.init_libvirt_state()
                newlist.append(obj)
            self._snapshot_list = newlist
        return self._snapshot_list[:]

    def get_current_snapshot(self):
        if self._backend.hasCurrentSnapshot(0):
            rawsnap = self._backend.snapshotCurrent(0)
            obj = vmmDomainSnapshot(self.conn, rawsnap)
            obj.init_libvirt_state()
            return obj

        return None

    @vmmLibvirtObject.lifecycle_action
    def revert_to_snapshot(self, snap):
        # no use trying to set the guest time if is going to be switched off
        # after reverting to the snapshot
        will_be_running = snap.is_running()
        self._backend.revertToSnapshot(snap.get_backend())
        # looking at the domain state after revert will always come back as
        # paused, so look at the snapshot state instead
        if will_be_running:
            self._async_set_time()

    def create_snapshot(self, xml, redefine=False, diskOnly=False):
        flags = 0
        if redefine:
            flags = flags | libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REDEFINE
        else:
            if diskOnly:
                flags = flags | libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY
            log.debug("Creating snapshot flags=%s xml=\n%s", flags, xml)
        obj = self._backend.snapshotCreateXML(xml, flags)
        log.debug("returned new snapshot XML:\n%s", obj.getXMLDesc(0))

    def _get_agent(self):
        """
        Return agent channel object if it is defined.
        """
        for dev in self.xmlobj.devices.channel:
            if dev.type == "unix" and dev.target_name == dev.CHANNEL_NAME_QEMUGA:
                return dev
        return None

    def has_agent(self):
        """
        Return True if domain has a guest agent defined.
        """
        return self._get_agent() is not None

    def agent_ready(self):
        """
        Return connected state of an agent.
        """
        dev = self._get_agent()
        if not dev:
            return False

        target_state = dev.target_state
        if self.conn.is_test():
            # test driver doesn't report 'connected' state so hack it here
            target_state = "connected"
        return target_state == "connected"

    def refresh_snapshots(self):
        self._snapshot_list = None

    def get_interface_addresses(self, iface, source):
        ret = {}
        log.debug("Calling interfaceAddresses source=%s", source)
        try:
            ret = self._backend.interfaceAddresses(source)
        except Exception as e:
            log.debug("interfaceAddresses failed: %s", str(e))
        if self.conn.is_test():
            ret = testmock.fake_interface_addresses(iface, source)
        return ret

    def get_ips(self, iface):
        return self._ipfetcher.get(self, iface)

    def refresh_ips(self, iface):
        return self._ipfetcher.refresh(self, iface)

    def set_time(self):
        """
        Try to set VM time to the current value. This is typically useful when
        clock wasn't running on the VM for some time (e.g. during suspension or
        migration), especially if the time delay exceeds NTP tolerance.
        It is not guaranteed that the time is actually set (it depends on guest
        environment, especially QEMU agent presence) or that the set time is
        very precise (NTP in the guest should take care of it if needed).

        Heavily based on
        https://github.com/openstack/nova/commit/414df1e56ea9df700756a1732125e06c5d97d792.
        """
        t = time.time()
        seconds = int(t)
        nseconds = int((t - seconds) * 10**9)
        try:
            self._backend.setTime(time={"seconds": seconds, "nseconds": nseconds})
            log.debug("Successfully set guest time")
        except Exception as e:  # pragma: no cover
            log.debug("Failed to set time: %s", e)

    def _async_set_time(self):
        """
        Asynchronously try to set guest time and maybe wait for a guest agent
        to come online using a separate thread.
        """
        self._set_time_thread.start()

    def _cancel_set_time(self):
        """
        Cancel a running guest time setting operation
        """
        self._set_time_thread.stop()

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
        import shlex

        init = self.get_xmlobj().os.init
        initargs = " ".join([shlex.quote(i.val) for i in self.get_xmlobj().os.initargs])
        return init, initargs

    def get_emulator(self):
        return self.get_xmlobj().emulator

    def get_machtype(self):
        return self.get_xmlobj().os.machine

    def get_name_or_title(self):
        title = self.get_title()
        if title:
            return title
        return self.get_name()

    def get_title(self):
        return self.get_xmlobj().title

    def get_description(self):
        return self.get_xmlobj().description

    def get_boot_order(self):
        legacy = not self.can_use_device_boot_order()
        return self.xmlobj.get_boot_order(legacy=legacy)

    def get_boot_menu(self):
        guest = self.get_xmlobj()
        return bool(guest.os.bootmenu_enable)

    def get_boot_kernel_info(self):
        guest = self.get_xmlobj()
        return (guest.os.kernel, guest.os.initrd, guest.os.dtb, guest.os.kernel_args)

    def get_interface_devices_norefresh(self):
        xmlobj = self.get_xmlobj(refresh_if_nec=False)
        return xmlobj.devices.interface

    def get_disk_devices_norefresh(self):
        xmlobj = self.get_xmlobj(refresh_if_nec=False)
        return xmlobj.devices.disk

    def serial_is_console_dup(self, serial):
        return DeviceConsole.get_console_duplicate(self.xmlobj, serial)

    def can_use_device_boot_order(self):
        # Return 'True' if guest can use new style boot device ordering
        return self.conn.support.conn_device_boot_order()

    def get_bootable_devices(self):
        # redirdev can also be marked bootable, but it should be rarely
        # used and clutters the UI
        return self.xmlobj.get_bootable_devices(exclude_redirdev=True)

    ############################
    # Domain lifecycle methods #
    ############################

    # All these methods are usually run asynchronously from threads, so
    # let's be extra careful and have anything which might touch UI
    # or GObject.props invoked in an idle callback

    @vmmLibvirtObject.lifecycle_action
    def shutdown(self):
        self._cancel_set_time()
        self._install_abort = True
        self._backend.shutdown()

    @vmmLibvirtObject.lifecycle_action
    def reboot(self):
        self._cancel_set_time()
        self._install_abort = True
        self._backend.reboot(0)

    @vmmLibvirtObject.lifecycle_action
    def destroy(self):
        self._cancel_set_time()
        self._install_abort = True
        self._backend.destroy()

    @vmmLibvirtObject.lifecycle_action
    def reset(self):
        self._cancel_set_time()
        self._install_abort = True
        self._backend.reset(0)

    @vmmLibvirtObject.lifecycle_action
    def startup(self):
        has_managed = self.has_managed_save()
        if self.config.CLITestOptions.test_vm_run_fail or (
            has_managed and self.config.CLITestOptions.test_managed_save
        ):
            raise RuntimeError("fake error for managed save")

        self._backend.create()
        if has_managed:
            self._async_set_time()

    @vmmLibvirtObject.lifecycle_action
    def suspend(self):
        self._cancel_set_time()
        self._backend.suspend()

    @vmmLibvirtObject.lifecycle_action
    def delete(self, force=True):
        """
        @force: True if we are deleting domain, False if we are renaming domain

        If the domain is renamed we need to keep the nvram file.
        """
        flags = 0
        if force:
            flags |= getattr(libvirt, "VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA", 0)
            flags |= getattr(libvirt, "VIR_DOMAIN_UNDEFINE_MANAGED_SAVE", 0)
            if self.has_nvram():
                flags |= getattr(libvirt, "VIR_DOMAIN_UNDEFINE_NVRAM", 0)
        else:
            if self.has_nvram():
                flags |= getattr(libvirt, "VIR_DOMAIN_UNDEFINE_KEEP_NVRAM", 0)
            if self.has_tpm_state() and self.conn.support.domain_undefine_keep_tpm():
                flags |= getattr(libvirt, "VIR_DOMAIN_UNDEFINE_KEEP_TPM", 0)
        try:
            self._backend.undefineFlags(flags)
        except libvirt.libvirtError:
            log.exception("libvirt undefineFlags failed, falling back to old style")
            self._backend.undefine()

    @vmmLibvirtObject.lifecycle_action
    def resume(self):
        self._backend.resume()
        self._async_set_time()

    @vmmLibvirtObject.lifecycle_action
    def save(self, meter=None):
        self._cancel_set_time()
        self._install_abort = True

        if meter:
            start_job_progress_thread(self, meter, _("Saving domain to disk"))

        if self.config.CLITestOptions.test_managed_save:
            time.sleep(1.2)
        self._backend.managedSave(0)

    def has_managed_save(self):
        if not self.managedsave_supported:
            return False  # pragma: no cover

        if self._has_managed_save is None:
            try:
                self._has_managed_save = self._backend.hasManagedSaveImage(0)
            except Exception as e:  # pragma: no cover
                if self.conn.support.is_libvirt_error_no_domain(e):
                    return False
                raise

        return self._has_managed_save

    def remove_saved_image(self):
        if not self.has_managed_save():
            return  # pragma: no cover
        self._backend.managedSaveRemove(0)
        self._has_managed_save = None

    def migrate(
        self,
        destconn,
        dest_uri=None,
        tunnel=False,
        unsafe=False,
        temporary=False,
        xml=None,
        meter=None,
    ):
        self._cancel_set_time()
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
        log.debug(
            "Migrating: conn=%s flags=%s uri=%s tunnel=%s unsafe=%s temporary=%s",
            destconn,
            flags,
            dest_uri,
            tunnel,
            unsafe,
            temporary,
        )

        if meter:
            start_job_progress_thread(self, meter, _("Migrating domain"))

        params = {}
        if dest_uri and not tunnel:
            params[libvirt.VIR_MIGRATE_PARAM_URI] = dest_uri
        if xml:
            params[libvirt.VIR_MIGRATE_PARAM_DEST_XML] = xml

        if self.conn.is_test() and "TESTSUITE-FAKE" in (dest_uri or ""):
            # If using the test driver and a special URI, fake successful
            # migration so we can test more of the migration wizard
            time.sleep(1.2)
            if not xml:
                xml = self.get_xml_to_define()
            destconn.define_domain(xml).create()
            self.delete()
        elif tunnel:
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
        return max(stats.netRxMaxRate, stats.netTxMaxRate, 10.0)

    def disk_io_rate(self):
        return self.disk_read_rate() + self.disk_write_rate()

    def disk_io_max_rate(self):
        stats = self._get_stats()
        return max(stats.diskRdMaxRate, stats.diskWrMaxRate, 10.0)

    def host_cpu_time_vector(self, limit=None):
        return self._get_stats().get_vector("cpuHostPercent", limit)

    def guest_cpu_time_vector(self, limit=None):
        return self._get_stats().get_vector("cpuGuestPercent", limit)

    def stats_memory_vector(self, limit=None):
        return self._get_stats().get_vector("currMemPercent", limit)

    def network_traffic_vectors(self, limit=None, ceil=None):
        if ceil is None:
            ceil = self.network_traffic_max_rate()
        return self._get_stats().get_in_out_vector("netRxRate", "netTxRate", limit, ceil)

    def disk_io_vectors(self, limit=None, ceil=None):
        if ceil is None:
            ceil = self.disk_io_max_rate()
        return self._get_stats().get_in_out_vector("diskRdRate", "diskWrRate", limit, ceil)

    ###################
    # Status helpers ##
    ###################

    def _normalize_status(self, status):
        if status == libvirt.VIR_DOMAIN_NOSTATE:
            return libvirt.VIR_DOMAIN_RUNNING  # pragma: no cover
        elif status == libvirt.VIR_DOMAIN_BLOCKED:
            return libvirt.VIR_DOMAIN_RUNNING  # pragma: no cover
        return status

    def is_active(self):
        return not self.is_shutoff()

    def is_shutoff(self):
        return self.status() == libvirt.VIR_DOMAIN_SHUTOFF

    def is_crashed(self):
        return self.status() == libvirt.VIR_DOMAIN_CRASHED

    def is_stoppable(self):
        return self.status() in [
            libvirt.VIR_DOMAIN_RUNNING,
            libvirt.VIR_DOMAIN_PAUSED,
            libvirt.VIR_DOMAIN_CRASHED,
            libvirt.VIR_DOMAIN_PMSUSPENDED,
        ]

    def is_destroyable(self):
        return self.is_stoppable() or self.status() in [libvirt.VIR_DOMAIN_CRASHED]

    def is_runable(self):
        return self.is_shutoff()

    def is_pauseable(self):
        return self.status() in [libvirt.VIR_DOMAIN_RUNNING]

    def is_unpauseable(self):
        return self.status() in [libvirt.VIR_DOMAIN_PAUSED]

    def is_paused(self):
        return self.status() in [libvirt.VIR_DOMAIN_PAUSED]

    def is_cloneable(self):
        return self.status() in [libvirt.VIR_DOMAIN_SHUTOFF]

    def run_status(self):
        return LibvirtEnumMap.pretty_run_status(self.status(), self.has_managed_save())

    def run_status_reason(self):
        return LibvirtEnumMap.pretty_status_reason(self.status(), self.status_reason())

    def run_status_icon_name(self):
        status = self.status()
        if status not in LibvirtEnumMap.VM_STATUS_ICONS:  # pragma: no cover
            log.debug("Unknown status %s, using NOSTATE", status)
            status = libvirt.VIR_DOMAIN_NOSTATE
        return LibvirtEnumMap.VM_STATUS_ICONS[status]

    def set_inspection_data(self, data):
        self.inspection = data
        self.idle_emit("inspection-changed")

    ##################
    # config helpers #
    ##################

    def on_console_scaling_changed(self, *args, **kwargs):
        return self.config.listen_pervm(self.get_uuid(), "/scaling", *args, **kwargs)

    def set_console_scaling(self, value):
        self.config.set_pervm(self.get_uuid(), "/scaling", value)

    def get_console_scaling(self):
        ret = self.config.get_pervm(self.get_uuid(), "/scaling")
        if ret == -1:
            return self.config.get_console_scaling()
        return ret

    def on_console_resizeguest_changed(self, *args, **kwargs):
        return self.config.listen_pervm(self.get_uuid(), "/resize-guest", *args, **kwargs)

    def set_console_resizeguest(self, value):
        self.config.set_pervm(self.get_uuid(), "/resize-guest", value)

    def get_console_resizeguest(self):
        ret = self.config.get_pervm(self.get_uuid(), "/resize-guest")
        if ret == -1:
            return self.config.get_console_resizeguest()
        return ret

    def on_console_autoconnect_changed(self, *args, **kwargs):
        return self.config.listen_pervm(self.get_uuid(), "/resize-guest", *args, **kwargs)

    def set_console_autoconnect(self, value):
        self.config.set_pervm(self.get_uuid(), "/autoconnect", value)

    def get_console_autoconnect(self):
        ret = self.config.get_pervm(self.get_uuid(), "/autoconnect")
        if ret == -1:
            return self.config.get_console_autoconnect()
        return ret

    def set_details_window_size(self, w, h):
        self.config.set_pervm(self.get_uuid(), "/vm-window-size", (w, h))

    def get_details_window_size(self):
        ret = self.config.get_pervm(self.get_uuid(), "/vm-window-size")
        return ret

    def get_console_username(self):
        return self.config.get_pervm(self.get_uuid(), "/console-username")

    def set_console_username(self, username):
        return self.config.set_pervm(self.get_uuid(), "/console-username", username)

    def del_console_username(self):
        return self.config.set_pervm(self.get_uuid(), "/console-username", "")

    def get_cache_dir(self):
        ret = os.path.join(self.conn.get_cache_dir(), self.get_uuid())
        os.makedirs(ret, 0o755, exist_ok=True)
        return ret

    ###################
    # Polling helpers #
    ###################

    def tick(self, stats_update=True):
        if not self._using_events() and not stats_update:
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

    def __init__(self, conn, backend, key, installer):
        vmmDomain.__init__(self, conn, backend, key)
        self._orig_xml = None
        self._orig_backend = self._backend
        self._installer = installer

        self._refresh_status()
        log.debug("%s initialized with XML=\n%s", self, self._XMLDesc(0))

    def get_name(self):
        return self._backend.name

    def get_uuid(self):
        return self._backend.uuid

    def get_id(self):
        return -1  # pragma: no cover

    def has_managed_save(self):
        return False

    def snapshots_supported(self):
        return False

    def get_autostart(self):
        return self._installer.autostart

    def set_autostart(self, val):
        self._installer.autostart = bool(val)
        self.emit("state-changed")

    def _using_events(self):
        return False

    def _get_backend_status(self):
        return libvirt.VIR_DOMAIN_SHUTOFF

    def _cleanup(self):
        self._orig_backend = None
        self._installer = None
        super()._cleanup()

    ################
    # XML handling #
    ################

    def _sync_disk_storage_params(self, origdisk, newdisk):
        """
        When raw disk XML is edited from the customize wizard, the
        original DeviceDisk is completely blown away, but that will
        lose the storage creation info. This syncs that info across
        to the new DeviceDisk
        """
        if origdisk.get_source_path() != newdisk.get_source_path():
            return

        if origdisk.get_vol_object():
            log.debug(
                "Syncing vol_object=%s from origdisk=%s to newdisk=%s",
                origdisk.get_vol_object(),
                origdisk,
                newdisk,
            )
            newdisk.set_vol_object(origdisk.get_vol_object(), origdisk.get_parent_pool())
        elif origdisk.get_vol_install():
            log.debug(
                "Syncing vol_install=%s from origdisk=%s to newdisk=%s",
                origdisk.get_vol_install(),
                origdisk,
                newdisk,
            )
            newdisk.set_vol_install(origdisk.get_vol_install())

    def _replace_domain_xml(self, newxml):
        """
        Blow away the Guest instance we are tracking internally with
        a new one from the xmleditor UI, and sync over all disk storage
        info afterwards
        """
        newbackend = Guest(self._backend.conn, parsexml=newxml)

        for origdisk in self._backend.devices.disk:
            for newdisk in newbackend.devices.disk:
                if origdisk.compare_device(newdisk, newdisk.get_xml_idx()):
                    self._sync_disk_storage_params(origdisk, newdisk)
                    break

        self._backend = newbackend

    def replace_device_xml(self, devobj, newxml):
        """
        Overwrite vmmDomain's implementation, since we need to wire in
        syncing disk details.
        """
        if self._backend == self._orig_backend:
            # If the backend hasn't been replace yet, do it, so we don't
            # have a mix of is_build Guest with XML parsed objects which
            # might contain dragons
            self._replace_domain_xml(self._backend.get_xml())
        editdev, newdev = vmmDomain.replace_device_xml(self, devobj, newxml)
        if editdev.DEVICE_TYPE == "disk":
            self._sync_disk_storage_params(editdev, newdev)

    def define_xml(self, xml):
        origxml = self._backend.get_xml()
        self._replace_domain_xml(xml)
        self._redefine_xml_internal(origxml, xml)

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

    def _redefine_xmlobj(self, xmlobj):
        self._redefine_xml_internal(self._orig_xml or "", xmlobj.get_xml())

    def rename_domain(self, new_name):
        Guest.validate_name(self._backend.conn, str(new_name))
        self.define_name(new_name)
