# Copyright (C) 2006, 2013, 2014, 2015 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import threading
import time
import traceback

import libvirt

import virtinst
from virtinst import log
from virtinst import pollhelpers

from .lib import connectauth
from .lib import testmock
from .baseclass import vmmGObject
from .lib.libvirtenummap import LibvirtEnumMap
from .object.domain import vmmDomain
from .object.network import vmmNetwork
from .object.nodedev import vmmNodeDevice
from .object.storagepool import vmmStoragePool
from .lib.statsmanager import vmmStatsManager


class _ObjectList(vmmGObject):
    """
    Class that wraps our internal list of libvirt objects
    """
    # pylint: disable=not-context-manager
    # pylint doesn't know that lock() has 'with' support
    BLACKLIST_COUNT = 3

    def __init__(self):
        vmmGObject.__init__(self)

        self._objects = []
        self._denylist = {}
        self._lock = threading.Lock()

    def _cleanup(self):
        self._objects = []

    def _denylist_key(self, obj):
        return str(obj.__class__) + obj.get_name()

    def add_denylist(self, obj):
        """
        Add an object to the denylist. Basically a list of objects we
        choose not to poll, because they threw an error at init time

        :param obj: vmmLibvirtObject to denylist
        :returns: number of added object to list
        """
        key = self._denylist_key(obj)
        count = self._denylist.get(key, 0)
        self._denylist[key] = count + 1
        return self._denylist[key]

    def remove_denylist(self, obj):
        """
        :param obj: vmmLibvirtObject to remove from denylist
        :returns: True if object was denylisted or False otherwise.
        """
        key = self._denylist_key(obj)
        return bool(self._denylist.pop(key, 0))

    def in_denylist(self, obj):
        """
        If an object is in list only once don't consider it denylisted,
        give it one more chance.

        :param obj: vmmLibvirtObject to check
        :returns: True if object is denylisted
        """
        key = self._denylist_key(obj)
        return self._denylist.get(key, 0) >= _ObjectList.BLACKLIST_COUNT

    def remove(self, obj):
        """
        Remove an object from the list.

        :param obj: vmmLibvirtObject to remove
        :returns: True if object removed, False if object was not found
        """
        with self._lock:
            # Identity check is sufficient here, since we should never be
            # asked to remove an object that wasn't at one point in the list.
            if obj not in self._objects:
                return self.remove_denylist(obj)

            self._objects.remove(obj)
            return True

    def add(self, obj):
        """
        Add an object to the list.

        :param obj: vmmLibvirtObject to add
        :returns: True if object added, False if object already in the list
        """
        with self._lock:
            # We don't look up based on identity here, to prevent tick()
            # races from adding the same domain twice
            #
            # We don't use lookup_object here since we need to hold the
            # lock the whole time to prevent a 'time of check' issue
            for checkobj in self._objects:
                if (checkobj.__class__ == obj.__class__ and
                    checkobj.get_name() == obj.get_name()):
                    return False

            self._objects.append(obj)
            return True

    def get_objects_for_class(self, classobj):
        """
        Return all objects over the passed vmmLibvirtObject class
        """
        with self._lock:
            return [o for o in self._objects if o.__class__ is classobj]

    def lookup_object(self, classobj, name):
        """
        Lookup an object with the passed classobj + name
        """
        # Doesn't require locking, since get_objects_for_class covers us
        for obj in self.get_objects_for_class(classobj):
            if obj.get_name() == name:
                return obj
        return None

    def all_objects(self):
        with self._lock:
            return self._objects[:]


class vmmConnection(vmmGObject):
    __gsignals__ = {
        "vm-added": (vmmGObject.RUN_FIRST, None, [object]),
        "vm-removed": (vmmGObject.RUN_FIRST, None, [object]),
        "net-added": (vmmGObject.RUN_FIRST, None, [object]),
        "net-removed": (vmmGObject.RUN_FIRST, None, [object]),
        "pool-added": (vmmGObject.RUN_FIRST, None, [object]),
        "pool-removed": (vmmGObject.RUN_FIRST, None, [object]),
        "nodedev-added": (vmmGObject.RUN_FIRST, None, [object]),
        "nodedev-removed": (vmmGObject.RUN_FIRST, None, [object]),
        "resources-sampled": (vmmGObject.RUN_FIRST, None, []),
        "state-changed": (vmmGObject.RUN_FIRST, None, []),
        "open-completed": (vmmGObject.RUN_FIRST, None, [object]),
    }

    (_STATE_DISCONNECTED,
     _STATE_CONNECTING,
     _STATE_ACTIVE) = range(1, 4)

    def __init__(self, uri):
        self._uri = uri
        vmmGObject.__init__(self)

        self._state = self._STATE_DISCONNECTED
        self._backend = virtinst.VirtinstConnection(self._uri)
        self._closing = False

        # Error strings are stored here if open() fails
        self.connect_error = None

        self._init_object_count = None
        self._init_object_event = None

        self.using_domain_events = False
        self._domain_cb_ids = []
        self.using_network_events = False
        self._network_cb_ids = []
        self.using_storage_pool_events = False
        self._storage_pool_cb_ids = []
        self.using_node_device_events = False
        self._node_device_cb_ids = []

        self._xml_flags = {}

        self._objects = _ObjectList()
        self.statsmanager = vmmStatsManager()

        self._stats = []
        self._hostinfo = None

        self.add_gsettings_handle(
            self._on_config_pretty_name_changed(
                self._config_pretty_name_changed_cb))

        self._init_virtconn()


    @staticmethod
    def pretty_hv(gtype, domtype):
        """
        Convert XML <domain type='foo'> and <os><type>bar</type>
        into a more human relevant string.
        """

        gtype = gtype.lower()
        domtype = domtype.lower()

        label = domtype
        if domtype == "xen":
            if gtype == "xen":
                label = "xen (paravirt)"
            elif gtype == "hvm":
                label = "xen (fullvirt)"
        elif domtype == "test":
            if gtype == "xen":
                label = "test (xen)"
            elif gtype == "hvm":
                label = "test (hvm)"
        elif domtype == "qemu":
            label = "QEMU TCG"
        elif domtype == "kvm":
            label = "KVM"

        return label

    def __repr__(self):
        # pylint: disable=arguments-differ
        return "<%s uri=%s id=%s>" % (
                self.__class__.__name__, self.get_uri(), hex(id(self)))


    #################
    # Init routines #
    #################

    def _wait_for_condition(self, compare_cb, timeout=3):
        """
        Wait for this object to emit the specified signal. Will not
        block the mainloop.
        """
        from gi.repository import Gtk
        is_main_thread = (threading.current_thread().name == "MainThread")
        start_time = time.time()

        while True:
            cur_time = time.time()
            if compare_cb():
                return
            if (cur_time - start_time) >= timeout:
                return  # pragma: no cover

            if is_main_thread:
                if Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                    continue

            time.sleep(.1)

    def _init_virtconn(self):
        self._backend.cb_fetch_all_domains = (
            lambda: [obj.get_xmlobj(refresh_if_nec=False)
                     for obj in self.list_vms()])
        self._backend.cb_fetch_all_pools = (
            lambda: [obj.get_xmlobj(refresh_if_nec=False)
                     for obj in self.list_pools()])
        self._backend.cb_fetch_all_nodedevs = (
            lambda: [obj.get_xmlobj(refresh_if_nec=False)
                     for obj in self.list_nodedevs()])

        def fetch_all_vols():
            ret = []
            for pool in self.list_pools():
                for vol in pool.get_volumes():
                    try:
                        ret.append(vol.get_xmlobj(refresh_if_nec=False))
                    except Exception as e:  # pragma: no cover
                        log.debug("Fetching volume XML failed: %s", e)
            return ret
        self._backend.cb_fetch_all_vols = fetch_all_vols

        def cache_new_pool(obj):
            if not self.is_active():
                return
            name = obj.name()
            self.schedule_priority_tick(pollpool=True)
            def compare_cb():
                return bool(self.get_pool_by_name(name))
            self._wait_for_condition(compare_cb)
        self._backend.cb_cache_new_pool = cache_new_pool


    ########################
    # General data getters #
    ########################

    def get_uri(self):
        return self._uri
    def get_backend(self):
        return self._backend

    def invalidate_caps(self):
        return self._backend.invalidate_caps()
    caps = property(lambda self: getattr(self, "_backend").caps)

    def host_memory_size(self):
        if not self._backend.is_open() or self._hostinfo is None:
            return 0
        return self._hostinfo[1] * 1024

    def host_active_processor_count(self):
        if not self._backend.is_open() or self._hostinfo is None:
            return 0  # pragma: no cover
        return self._hostinfo[2]


    ##########################
    # URI + hostname helpers #
    ##########################

    def libvirt_gethostname(self):
        return self._backend.getHostname()

    get_uri_hostname = property(lambda s:
        getattr(s, "_backend").get_uri_hostname)
    get_uri_username = property(lambda s:
        getattr(s, "_backend").get_uri_username)
    get_uri_transport = property(lambda s:
        getattr(s, "_backend").get_uri_transport)
    get_uri_port = property(lambda s: getattr(s, "_backend").get_uri_port)
    get_driver = property(lambda s: getattr(s, "_backend").get_uri_driver)
    is_container_only = property(
            lambda s: getattr(s, "_backend").is_container_only)
    is_lxc = property(lambda s: getattr(s, "_backend").is_lxc)
    is_vz = property(lambda s: getattr(s, "_backend").is_vz)
    is_xen = property(lambda s: getattr(s, "_backend").is_xen)
    is_remote = property(lambda s: getattr(s, "_backend").is_remote)
    is_qemu = property(lambda s: getattr(s, "_backend").is_qemu)
    is_qemu_privileged = property(lambda s: getattr(s, "_backend").is_qemu_privileged)
    is_qemu_unprivileged = property(lambda s:
                               getattr(s, "_backend").is_qemu_unprivileged)
    is_test = property(lambda s: getattr(s, "_backend").is_test)
    is_unprivileged = property(lambda s: getattr(s, "_backend").is_unprivileged)


    def get_cache_dir(self):
        uri = self.get_uri().replace("/", "_")
        ret = os.path.join(self._backend.get_app_cache_dir(), uri)
        if not os.path.exists(ret):
            os.makedirs(ret, 0o755)  # pragma: no cover
        return ret

    def get_default_storage_format(self):
        raw = self.config.get_default_storage_format(raw=True)
        if raw != "default":
            return raw  # pragma: no cover

        fmt = self.config.get_default_storage_format()
        if fmt != "qcow2":
            return fmt  # pragma: no cover

        if self.support.conn_default_qcow2():
            return fmt
        return None  # pragma: no cover


    ####################################
    # Connection pretty print routines #
    ####################################

    def get_pretty_desc(self):
        """
        Return a pretty label for use in the manager view, and various
        connection lists.
        """
        if self._get_config_pretty_name():
            return self._get_config_pretty_name()

        pretty_map = {
            "esx":        "ESX",
            "lxc":        "LXC",
            "openvz":     "OpenVZ",
            "qemu":       "QEMU/KVM",
            "vbox":       "Virtualbox",
            "vmware":     "VMWare",
            "xen":        "Xen",
        }

        hv = pretty_map.get(self.get_driver(), self.get_driver())
        hostname = self.get_uri_hostname()
        path = self.get_backend().get_uri_path()

        ret = hv

        if path == "/session":
            ret += " " + _("User session")
        elif (path and path != "/system" and os.path.basename(path)):
            # Used by test URIs to report what XML file they are using
            ret += " %s" % os.path.basename(path)

        if hostname:
            ret += ": %s" % hostname

        return ret


    #######################
    # API support helpers #
    #######################

    @property
    def support(self):
        return self._backend.support

    def _get_flags_helper(self, obj, key, check_func):
        ignore = obj
        flags_dict = self._xml_flags.get(key)

        if flags_dict is None:
            # Flags already set
            inact, act = check_func()
            flags_dict = {}
            flags_dict["active"] = act
            flags_dict["inactive"] = inact

            self._xml_flags[key] = flags_dict

        active_flags   = flags_dict["active"]
        inactive_flags = flags_dict["inactive"]

        return (inactive_flags, active_flags)

    def get_dom_flags(self, vm):
        key = "domain"

        def check_func():
            act   = 0
            inact = 0

            if self.support.domain_xml_inactive(vm):
                inact = libvirt.VIR_DOMAIN_XML_INACTIVE
            else:  # pragma: no cover
                log.debug("Domain XML inactive flag not supported.")

            if self.support.domain_xml_secure(vm):
                inact |= libvirt.VIR_DOMAIN_XML_SECURE
                act = libvirt.VIR_DOMAIN_XML_SECURE
            else:  # pragma: no cover
                log.debug("Domain XML secure flag not supported.")

            return inact, act

        return self._get_flags_helper(vm, key, check_func)

    def get_default_pool(self):
        poolxml = virtinst.StoragePool.lookup_default_pool(self.get_backend())
        if poolxml:
            for p in self.list_pools():
                if p.get_name() == poolxml.name:
                    return p
        return None

    def get_vol_by_path(self, path):
        for pool in self.list_pools():
            for vol in pool.get_volumes():
                try:
                    if vol.get_target_path() == path:
                        return vol
                except Exception as e:  # pragma: no cover
                    # Errors can happen if the volume disappeared, bug 1092739
                    log.debug("Error looking up volume from path=%s: %s",
                        path, e)
        return None


    ###################################
    # Connection state getter/setters #
    ###################################

    def _change_state(self, newstate):
        if self._state != newstate:
            self._state = newstate
            log.debug("conn=%s changed to state=%s",
                self.get_uri(), self.get_state_text())
            self.emit("state-changed")

    def is_active(self):
        return self._state == self._STATE_ACTIVE
    def is_disconnected(self):
        return self._state == self._STATE_DISCONNECTED
    def is_connecting(self):
        return self._state == self._STATE_CONNECTING

    def get_state_text(self):
        if self.is_disconnected():
            return _("Disconnected")
        elif self.is_connecting():
            return _("Connecting")
        return _("Active")


    #################################
    # Libvirt object lookup methods #
    #################################

    def get_vm_by_name(self, name):
        return self._objects.lookup_object(vmmDomain, name)
    def list_vms(self):
        return self._objects.get_objects_for_class(vmmDomain)

    def get_net_by_name(self, name):
        return self._objects.lookup_object(vmmNetwork, name)
    def list_nets(self):
        return self._objects.get_objects_for_class(vmmNetwork)

    def get_pool_by_name(self, name):
        return self._objects.lookup_object(vmmStoragePool, name)
    def list_pools(self):
        return self._objects.get_objects_for_class(vmmStoragePool)

    def get_nodedev_by_name(self, name):
        return self._objects.lookup_object(vmmNodeDevice, name)
    def list_nodedevs(self):
        return self._objects.get_objects_for_class(vmmNodeDevice)


    ############################
    # nodedev helper functions #
    ############################

    def filter_nodedevs(self, devtype):
        retdevs = []
        for dev in self.list_nodedevs():
            try:
                xmlobj = dev.get_xmlobj()
            except libvirt.libvirtError as e:  # pragma: no cover
                # Libvirt nodedev XML fetching can be busted
                # https://bugzilla.redhat.com/show_bug.cgi?id=1225771
                if e.get_error_code() != libvirt.VIR_ERR_NO_NODE_DEVICE:
                    log.debug("Error fetching nodedev XML", exc_info=True)
                continue

            if devtype and xmlobj.device_type != devtype:
                continue

            retdevs.append(dev)
        return retdevs


    ###################################
    # Libvirt object creation methods #
    ###################################

    def define_domain(self, xml):
        return self._backend.defineXML(xml)
    def define_network(self, xml):
        return self._backend.networkDefineXML(xml)
    def define_pool(self, xml):
        return self._backend.storagePoolDefineXML(xml, 0)

    def rename_object(self, obj, origxml, newxml):
        if obj.is_domain():
            define_cb = self.define_domain
        elif obj.is_pool():
            define_cb = self.define_pool
        elif obj.is_network():
            define_cb = self.define_network
        else:
            raise virtinst.xmlutil.DevError("rename_object "
                "helper doesn't support object class %s" % obj.__class__)

        # Undefine the original object
        obj.delete(force=False)

        newobj = None
        try:
            # Redefine new domain
            newobj = define_cb(newxml)
        except Exception as renameerr:
            try:
                log.debug("Error defining new name %s XML",
                    obj.class_name(), exc_info=True)
                newobj = define_cb(origxml)
            except Exception as fixerr:  # pragma: no cover
                log.debug("Failed to redefine original %s!",
                    obj.class_name(), exc_info=True)
                msg = _("%(object)s rename failed. Attempting to recover also "
                        "failed.\n"
                        "\n"
                        "Original error: %(origerror)s\n"
                        "\n"
                        "Recover error: %(recovererror)s") % {
                            "object": obj.class_name(),
                            "origerror": str(renameerr),
                            "recovererror": str(fixerr),
                        }
                raise RuntimeError(msg) from None
            raise
        finally:
            if newobj:
                # Reinsert handle into new obj
                obj.change_name_backend(newobj)


    #########################
    # Domain event handling #
    #########################

    # Our strategy here isn't the most efficient: since we need to keep the
    # poll helpers around for compat with old libvirt, switching to a fully
    # event driven setup is hard, so we end up doing more polling than
    # necessary on most events.

    def _domain_xml_misc_event(self, conn, domain, *args):
        # Just trigger a domain XML refresh for hotplug type events
        ignore = conn
        args = list(args)
        eventstr = args.pop(-1)

        name = domain.name()
        log.debug("domain xmlmisc event: domain=%s event=%s args=%s",
                name, eventstr, args)
        obj = self.get_vm_by_name(name)
        if obj:
            self.idle_add(obj.recache_from_event_loop)

    def _domain_lifecycle_event(self, conn, domain, state, reason, userdata):
        ignore = conn
        ignore = userdata

        name = domain.name()
        log.debug("domain lifecycle event: domain=%s %s", name,
                LibvirtEnumMap.domain_lifecycle_str(state, reason))

        obj = self.get_vm_by_name(name)

        if obj:
            self.idle_add(obj.recache_from_event_loop)
        else:
            self.schedule_priority_tick(pollvm=True, force=True)

    def _domain_agent_lifecycle_event(self, conn, domain, state, reason, userdata):
        ignore = conn
        ignore = userdata

        name = domain.name()
        log.debug("domain agent lifecycle event: domain=%s %s", name,
                LibvirtEnumMap.domain_agent_lifecycle_str(state, reason))

        obj = self.get_vm_by_name(name)

        if obj:
            self.idle_add(obj.recache_from_event_loop)
        else:
            self.schedule_priority_tick(pollvm=True, force=True)  # pragma: no cover

    def _network_lifecycle_event(self, conn, network, state, reason, userdata):
        ignore = conn
        ignore = userdata

        name = network.name()
        log.debug("network lifecycle event: network=%s %s",
                name, LibvirtEnumMap.network_lifecycle_str(state, reason))
        obj = self.get_net_by_name(name)

        if obj:
            self.idle_add(obj.recache_from_event_loop)
        else:
            self.schedule_priority_tick(pollnet=True, force=True)

    def _storage_pool_lifecycle_event(self, conn, pool,
                                      state, reason, userdata):
        ignore = conn
        ignore = userdata

        name = pool.name()
        log.debug("storage pool lifecycle event: pool=%s %s",
            name, LibvirtEnumMap.storage_lifecycle_str(state, reason))

        obj = self.get_pool_by_name(name)

        if obj:
            self.idle_add(obj.recache_from_event_loop)
        else:
            self.schedule_priority_tick(pollpool=True, force=True)

    def _storage_pool_refresh_event(self, conn, pool, userdata):
        ignore = conn
        ignore = userdata

        name = pool.name()
        log.debug("storage pool refresh event: pool=%s", name)

        obj = self.get_pool_by_name(name)

        if not obj:
            return

        self.idle_add(obj.refresh_pool_cache_from_event_loop)

    def _node_device_lifecycle_event(self, conn, dev,
                                     state, reason, userdata):
        ignore = conn
        ignore = userdata

        name = dev.name()
        log.debug("node device lifecycle event: nodedev=%s %s",
            name, LibvirtEnumMap.nodedev_lifecycle_str(state, reason))

        self.schedule_priority_tick(pollnodedev=True, force=True)

    def _node_device_update_event(self, conn, dev, userdata):
        ignore = conn
        ignore = userdata

        name = dev.name()
        log.debug("node device update event: nodedev=%s", name)

        obj = self.get_nodedev_by_name(name)

        if obj:
            self.idle_add(obj.recache_from_event_loop)

    def _add_conn_events(self):
        if not self.support.conn_working_xen_events():
            return  # pragma: no cover

        def _check_events_disabled():
            if self.config.CLITestOptions.no_events:
                raise RuntimeError("events disabled via cli")

        try:
            _check_events_disabled()

            self._domain_cb_ids.append(
                self.get_backend().domainEventRegisterAny(
                None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                self._domain_lifecycle_event, None))
            self.using_domain_events = True
            log.debug("Using domain events")
        except Exception as e:
            self.using_domain_events = False
            log.debug("Error registering domain events: %s", e)

        def _add_domain_xml_event(eventname, eventval, cb=None):
            if not self.using_domain_events:
                return
            if not cb:
                cb = self._domain_xml_misc_event
            try:
                eventid = getattr(libvirt, eventname, eventval)
                self._domain_cb_ids.append(
                    self.get_backend().domainEventRegisterAny(
                    None, eventid, cb, eventname))

                if (eventname == "VIR_DOMAIN_EVENT_ID_AGENT_LIFECYCLE" and
                    self.config.CLITestOptions.fake_agent_event):
                    testmock.schedule_fake_agent_event(self, cb)
            except Exception as e:  # pragma: no cover
                log.debug("Error registering %s event: %s",
                    eventname, e)

        _add_domain_xml_event("VIR_DOMAIN_EVENT_ID_BALLOON_CHANGE", 13)
        _add_domain_xml_event("VIR_DOMAIN_EVENT_ID_TRAY_CHANGE", 10)
        _add_domain_xml_event("VIR_DOMAIN_EVENT_ID_DEVICE_REMOVED", 15)
        _add_domain_xml_event("VIR_DOMAIN_EVENT_ID_DEVICE_ADDED", 19)
        _add_domain_xml_event("VIR_DOMAIN_EVENT_ID_AGENT_LIFECYCLE", 18,
                              self._domain_agent_lifecycle_event)
        _add_domain_xml_event("VIR_DOMAIN_EVENT_ID_METADATA_CHANGE", 23)

        try:
            _check_events_disabled()

            eventid = getattr(libvirt, "VIR_NETWORK_EVENT_ID_LIFECYCLE", 0)
            self._network_cb_ids.append(
                self.get_backend().networkEventRegisterAny(
                None, eventid, self._network_lifecycle_event, None))
            self.using_network_events = True
            log.debug("Using network events")
        except Exception as e:
            self.using_network_events = False
            log.debug("Error registering network events: %s", e)

        try:
            _check_events_disabled()

            eventid = getattr(libvirt,
                              "VIR_STORAGE_POOL_EVENT_ID_LIFECYCLE", 0)
            refreshid = getattr(libvirt,
                              "VIR_STORAGE_POOL_EVENT_ID_REFRESH", 1)
            self._storage_pool_cb_ids.append(
                self.get_backend().storagePoolEventRegisterAny(
                None, eventid, self._storage_pool_lifecycle_event, None))
            self._storage_pool_cb_ids.append(
                self.get_backend().storagePoolEventRegisterAny(
                None, refreshid, self._storage_pool_refresh_event, None))
            self.using_storage_pool_events = True
            log.debug("Using storage pool events")
        except Exception as e:
            self.using_storage_pool_events = False
            log.debug("Error registering storage pool events: %s", e)

        try:
            _check_events_disabled()

            eventid = getattr(libvirt, "VIR_NODE_DEVICE_EVENT_ID_LIFECYCLE", 0)
            updateid = getattr(libvirt, "VIR_NODE_DEVICE_EVENT_ID_UPDATE", 1)
            lifecycle_cb = self._node_device_lifecycle_event
            update_cb = self._node_device_update_event

            self._node_device_cb_ids.append(
                self.get_backend().nodeDeviceEventRegisterAny(
                None, eventid, lifecycle_cb, None))
            self._node_device_cb_ids.append(
                self.get_backend().nodeDeviceEventRegisterAny(
                None, updateid, update_cb, None))

            if self.config.CLITestOptions.fake_nodedev_event:
                testmock.schedule_fake_nodedev_event(self,
                        lifecycle_cb, update_cb)

            self.using_node_device_events = True
            log.debug("Using node device events")
        except Exception as e:
            self.using_network_events = False
            log.debug("Error registering node device events: %s", e)


    ######################################
    # Connection closing/opening methods #
    ######################################

    def _schedule_close(self):
        self._closing = True
        self.idle_add(self.close)

    def close(self):
        if not self.is_disconnected():
            log.debug("conn.close() uri=%s", self.get_uri())
        self._closing = True

        try:
            if self._backend.is_open():
                for eid in self._domain_cb_ids:
                    self._backend.domainEventDeregisterAny(eid)
                for eid in self._network_cb_ids:
                    self._backend.networkEventDeregisterAny(eid)
                for eid in self._storage_pool_cb_ids:
                    self._backend.storagePoolEventDeregisterAny(eid)
                for eid in self._node_device_cb_ids:
                    self._backend.nodeDeviceEventDeregisterAny(eid)
        except Exception:  # pragma: no cover
            log.debug("Failed to deregister events in conn cleanup",
                exc_info=True)
        finally:
            self._domain_cb_ids = []
            self._network_cb_ids = []
            self._storage_pool_cb_ids = []
            self._node_device_cb_ids = []

        self._stats = []

        if self._init_object_event:
            self._init_object_event.clear()  # pragma: no cover

        for obj in self._objects.all_objects():
            self._objects.remove(obj)
            try:
                self._remove_object_signal(obj)
                obj.cleanup()
            except Exception as e:  # pragma: no cover
                log.debug("Failed to cleanup %s: %s", obj, e)
        self._objects.cleanup()
        self._objects = _ObjectList()

        closeret = self._backend.close()
        if closeret == 1:
            log.debug(  # pragma: no cover
                    "LEAK: conn close() returned 1, "
                    "meaning refs may have leaked.")

        self._change_state(self._STATE_DISCONNECTED)
        self._closing = False

    def _cleanup(self):
        self.close()

        self._objects = None
        self._backend.cb_fetch_all_domains = None
        self._backend.cb_fetch_all_pools = None
        self._backend.cb_fetch_all_nodedevs = None
        self._backend.cb_fetch_all_vols = None
        self._backend.cb_cache_new_pool = None

        self.statsmanager.cleanup()
        self.statsmanager = None

    def open(self):
        if not self.is_disconnected():
            return  # pragma: no cover

        self._change_state(self._STATE_CONNECTING)

        log.debug("Scheduling background open thread for %s",
                      self.get_uri())
        self._start_thread(self._open_thread, "Connect %s" % self.get_uri())

    def _do_open(self):
        warnconsole = False
        libvirt_error_code = None
        libvirt_error_message = None
        exc = None

        try:
            cb = connectauth.creds_dialog
            data = self
            if self.config.CLITestOptions.fake_openauth:
                testmock.fake_openauth(self, cb, data)
            if self.config.CLITestOptions.fake_session_error:
                lerr = libvirt.libvirtError("fake session error")
                lerr.err = [libvirt.VIR_ERR_AUTH_FAILED, None,
                            "fake session error not authorized"]
                raise lerr
            self._backend.open(cb, data)
            return True, None
        except Exception as e:
            exc = e
            tb = "".join(traceback.format_exc())
            if isinstance(exc, libvirt.libvirtError):
                # pylint: disable=no-member
                libvirt_error_code = exc.get_error_code()
                libvirt_error_message = exc.get_error_message()

        if (libvirt_error_code ==
            getattr(libvirt, "VIR_ERR_AUTH_CANCELLED", None)):  # pragma: no cover
            log.debug("User cancelled auth, not raising any error.")
            return False, None

        if (libvirt_error_code == libvirt.VIR_ERR_AUTH_FAILED and
            "not authorized" in libvirt_error_message.lower()):
            log.debug("Looks like we might have failed policykit "
                          "auth. Checking to see if we have a valid "
                          "console session")
            if not self.is_remote():
                warnconsole = bool(not connectauth.do_we_have_session())
            if self.config.CLITestOptions.fake_session_error:
                warnconsole = True

        ConnectError = connectauth.connect_error(
                self, str(exc), tb, warnconsole)
        return False, ConnectError

    def _populate_initial_state(self):
        if not self.support.conn_domain():  # pragma: no cover
            raise RuntimeError("Connection does not support required "
                    "domain listing APIs")

        if not self.support.conn_storage():  # pragma: no cover
            log.debug("Connection doesn't seem to support storage APIs.")
        if not self.support.conn_network():  # pragma: no cover
            log.debug("Connection doesn't seem to support network APIs.")
        if not self.support.conn_nodedev():  # pragma: no cover
            log.debug("Connection doesn't seem to support nodedev APIs.")

        self._add_conn_events()

        try:
            self._backend.setKeepAlive(20, 1)
        except Exception as e:
            log.debug("Failed to setKeepAlive: %s", str(e))

        # The initial tick will set up a threading event that will only
        # trigger after all the polled libvirt objects are fully initialized.
        # That way we only report the connection is open when everything is
        # nicely setup for the rest of the app.

        self._init_object_event = threading.Event()
        self._init_object_count = 0

        self.schedule_priority_tick(stats_update=True,
            pollvm=True, pollnet=True,
            pollpool=True, pollnodedev=True,
            force=True, initial_poll=True)

        self._init_object_event.wait()
        self._init_object_event = None
        self._init_object_count = None

        # Try to create the default storage pool
        # We need this after events setup so we can determine if the default
        # pool already exists
        try:
            virtinst.StoragePool.build_default_pool(self.get_backend())
        except Exception as e:  # pragma: no cover
            log.debug("Building default pool failed: %s", str(e))

    def _open_thread(self):
        try:
            is_active, ConnectError = self._do_open()
            if is_active:
                self._populate_initial_state()
        except Exception as e:  # pragma: no cover
            is_active = False
            ConnectError = connectauth.connect_error(self, str(e),
                    "".join(traceback.format_exc()), False)

        if is_active:
            self.idle_add(self._change_state, self._STATE_ACTIVE)
        else:
            self._schedule_close()

        self.idle_emit("open-completed", ConnectError)


    #######################
    # Tick/Update methods #
    #######################

    def _remove_object_signal(self, obj):
        if obj.is_domain():
            self.emit("vm-removed", obj)
        elif obj.is_network():
            self.emit("net-removed", obj)
        elif obj.is_pool():
            self.emit("pool-removed", obj)
        elif obj.is_nodedev():
            self.emit("nodedev-removed", obj)

    def _gone_object_signals(self, gone_objects):
        """
        Responsible for signaling the UI for any updates. All possible UI
        updates need to go here to enable threading that doesn't block the
        app with long tick operations.
        """
        if not self._backend.is_open():
            return  # pragma: no cover

        for obj in gone_objects:
            class_name = obj.class_name()
            name = obj.get_name()

            if not self._objects.remove(obj):
                log.debug("Requested removal of %s=%s, but it's "
                    "not in our object list.", class_name, name)
                continue

            log.debug("%s=%s removed", class_name, name)
            self._remove_object_signal(obj)
            obj.cleanup()

    def _new_object_cb(self, obj, initialize_failed):
        if not self._backend.is_open():
            return  # pragma: no cover

        try:
            class_name = obj.class_name()

            if initialize_failed:
                log.debug("Blacklisting %s=%s", class_name, obj.get_name())
                count = self._objects.add_denylist(obj)
                log.debug("Object added in denylist, count=%d", count)
                return

            self._objects.remove_denylist(obj)
            if not self._objects.add(obj):
                log.debug("New %s=%s requested, but it's already tracked.",
                    class_name, obj.get_name())
                obj.cleanup()
                return

            if not obj.is_nodedev():
                # Skip nodedev logging since it's noisy and not interesting
                log.debug("%s=%s status=%s added", class_name,
                    obj.get_name(), obj.run_status())
            if obj.is_domain():
                self.emit("vm-added", obj)
            elif obj.is_network():
                self.emit("net-added", obj)
            elif obj.is_pool():
                self.emit("pool-added", obj)
            elif obj.is_nodedev():
                self.emit("nodedev-added", obj)
        finally:
            if self._init_object_event:
                self._init_object_count -= 1
                if self._init_object_count <= 0:
                    self._init_object_event.set()

    def _poll(self, initial_poll,
            pollvm, pollnet, pollpool, pollnodedev):
        """
        Helper called from tick() to do necessary polling and return
        the relevant object lists
        """
        gone_objects = []
        preexisting_objects = []

        def _process_objects(ptype):
            if ptype == "nets":
                dopoll = pollnet
                objs = self.list_nets()
                cls = vmmNetwork
                pollcb = pollhelpers.fetch_nets
            elif ptype == "pools":
                dopoll = pollpool
                objs = self.list_pools()
                cls = vmmStoragePool
                pollcb = pollhelpers.fetch_pools
            elif ptype == "nodedevs":
                dopoll = pollnodedev
                objs = self.list_nodedevs()
                cls = vmmNodeDevice
                pollcb = pollhelpers.fetch_nodedevs
            else:
                dopoll = pollvm
                objs = self.list_vms()
                cls = vmmDomain
                pollcb = pollhelpers.fetch_vms


            keymap = dict((o.get_name(), o) for o in objs)
            def cb(obj, name):
                return cls(self, obj, name)
            if dopoll:
                gone, new, master = pollcb(self._backend, keymap, cb)
            else:
                gone, new, master = [], [], list(keymap.values())

            if initial_poll:
                self._init_object_count += len(new)

            gone_objects.extend(gone)
            preexisting_objects.extend([o for o in master if o not in new])
            new = [n for n in new if not self._objects.in_denylist(n)]
            return new

        new_vms = _process_objects("vms")
        new_nets = _process_objects("nets")
        new_pools = _process_objects("pools")
        new_nodedevs = _process_objects("nodedevs")

        # Kick off one thread per object type to handle the initial
        # XML fetching. Going any more fine grained then this probably
        # won't be that useful due to libvirt's locking structure.
        #
        # Would prefer to start refreshing some objects before all polling
        # is complete, but we need init_object_count to be fully accurate
        # before we start initializing objects

        if initial_poll and self._init_object_count == 0:
            # If the connection doesn't have any objects, new_object_cb
            # is never called and the event is never set, so let's do it here
            self._init_object_event.set()

        for newlist in [new_vms, new_nets, new_pools, new_nodedevs]:
            if not newlist:
                continue

            def cb(lst):
                for obj in lst:
                    obj.connect_once("initialized", self._new_object_cb)
                    obj.init_libvirt_state()

            self._start_thread(cb,
                "refreshing xml for new %s" % newlist[0].class_name(),
                args=(newlist,))

        return gone_objects, preexisting_objects

    def _tick(self, stats_update=False,
             pollvm=False, pollnet=False,
             pollpool=False, pollnodedev=False,
             force=False, initial_poll=False):
        """
        main update function: polls for new objects, updates stats, ...

        :param force: Perform the requested polling even if async events
            are in use.
        """
        if self._closing:
            return  # pragma: no cover
        if self.is_disconnected():
            return  # pragma: no cover
        if self.is_connecting() and not force:
            return  # pragma: no cover

        # We need to set this before the event check, since stats polling
        # is independent of events
        if not pollvm:
            stats_update = False

        if self.using_domain_events and not force:
            pollvm = False
        if self.using_network_events and not force:
            pollnet = False
        if self.using_storage_pool_events and not force:
            pollpool = False
        if self.using_node_device_events and not force:
            pollnodedev = False

        self._hostinfo = self._backend.getInfo()
        if stats_update:
            self.statsmanager.cache_all_stats(self)

        gone_objects, preexisting_objects = self._poll(
            initial_poll, pollvm, pollnet, pollpool, pollnodedev)
        self.idle_add(self._gone_object_signals, gone_objects)

        # Only tick() pre-existing objects, since new objects will be
        # initialized asynchronously and tick() would be redundant
        for obj in preexisting_objects:
            try:
                if obj.reports_stats() and stats_update:
                    pass
                elif obj.is_domain() and not pollvm:
                    continue
                elif obj.is_network() and not pollnet:
                    continue
                elif obj.is_pool() and not pollpool:
                    continue
                elif obj.is_nodedev() and not pollnodedev:
                    continue

                if self.config.CLITestOptions.conn_crash:
                    self._backend.close()
                    e = libvirt.libvirtError("fake error")
                    e.err = [libvirt.VIR_ERR_SYSTEM_ERROR]
                    raise e

                obj.tick(stats_update=stats_update)
            except Exception as e:
                log.exception("Tick for %s failed", obj)
                if (isinstance(e, libvirt.libvirtError) and
                    (getattr(e, "get_error_code")() ==
                     libvirt.VIR_ERR_SYSTEM_ERROR)):
                    # Try a simple getInfo call to see if conn was dropped
                    self._backend.getInfo()
                    log.debug(  # pragma: no cover
                            "vm tick raised system error but "
                            "connection doesn't seem to have dropped. "
                            "Ignoring.")

        if stats_update:
            self._recalculate_stats(
                [o for o in preexisting_objects if o.reports_stats()])
            self.idle_emit("resources-sampled")

    def _recalculate_stats(self, vms):
        if not self._backend.is_open():
            return  # pragma: no cover

        now = time.time()
        expected = self.config.get_stats_history_length()
        current = len(self._stats)
        if current > expected:
            del self._stats[expected:current]  # pragma: no cover

        mem = 0
        cpuTime = 0
        rdRate = 0
        wrRate = 0
        rxRate = 0
        txRate = 0
        diskMaxRate = self.disk_io_max_rate() or 10.0
        netMaxRate = self.network_traffic_max_rate() or 10.0

        for vm in vms:
            if not vm.is_active():
                continue

            cpuTime += vm.cpu_time()
            mem += vm.stats_memory()
            rdRate += vm.disk_read_rate()
            wrRate += vm.disk_write_rate()
            rxRate += vm.network_rx_rate()
            txRate += vm.network_tx_rate()

            netMaxRate = max(netMaxRate, vm.network_traffic_max_rate())
            diskMaxRate = max(diskMaxRate, vm.disk_io_max_rate())

        pcentHostCpu = 0
        pcentMem = mem * 100.0 / self.host_memory_size()

        if len(self._stats) > 0:
            prevTimestamp = self._stats[0]["timestamp"]
            host_cpus = self.host_active_processor_count()

            pcentHostCpu = ((cpuTime) * 100.0 /
                            ((now - prevTimestamp) *
                             1000.0 * 1000.0 * 1000.0 * host_cpus))

        pcentHostCpu = max(0.0, min(100.0, pcentHostCpu))
        pcentMem = max(0.0, min(100.0, pcentMem))

        newStats = {
            "timestamp": now,
            "memory": mem,
            "memoryPercent": pcentMem,
            "cpuTime": cpuTime,
            "cpuHostPercent": pcentHostCpu,
            "diskRdRate": rdRate,
            "diskWrRate": wrRate,
            "netRxRate": rxRate,
            "netTxRate": txRate,
            "diskMaxRate": diskMaxRate,
            "netMaxRate": netMaxRate,
        }

        self._stats.insert(0, newStats)


    def schedule_priority_tick(self, **kwargs):
        from .engine import vmmEngine
        vmmEngine.get_instance().schedule_priority_tick(self, kwargs)

    def tick_from_engine(self, *args, **kwargs):
        try:
            self._tick(*args, **kwargs)
        except Exception:
            self._schedule_close()
            raise


    ########################
    # Stats getter methods #
    ########################

    def _get_record_helper(self, record_name):
        if len(self._stats) == 0:
            return 0
        return self._stats[0][record_name]

    def _vector_helper(self, record_name, limit, ceil=100.0):
        vector = []
        statslen = self.config.get_stats_history_length() + 1
        if limit is not None:
            statslen = min(statslen, limit)  # pragma: no cover

        for i in range(statslen):
            if i < len(self._stats):
                vector.append(self._stats[i][record_name] / ceil)
            else:
                vector.append(0)

        return vector

    def stats_memory_vector(self, limit=None):
        return self._vector_helper("memoryPercent", limit)
    def host_cpu_time_vector(self, limit=None):
        return self._vector_helper("cpuHostPercent", limit)

    def stats_memory(self):
        return self._get_record_helper("memory")
    def host_cpu_time_percentage(self):
        return self._get_record_helper("cpuHostPercent")
    def guest_cpu_time_percentage(self):
        return self.host_cpu_time_percentage()
    def network_traffic_rate(self):
        return (self._get_record_helper("netRxRate") +
                self._get_record_helper("netTxRate"))
    def disk_io_rate(self):
        return (self._get_record_helper("diskRdRate") +
                self._get_record_helper("diskWrRate"))

    def network_traffic_max_rate(self):
        return self._get_record_helper("netMaxRate")
    def disk_io_max_rate(self):
        return self._get_record_helper("diskMaxRate")


    ###########################
    # Per-conn config helpers #
    ###########################

    def get_autoconnect(self):
        return self.config.get_conn_autoconnect(self.get_uri())
    def set_autoconnect(self, val):
        self.config.set_conn_autoconnect(self.get_uri(), val)

    def set_config_pretty_name(self, value):
        cfgname = self._get_config_pretty_name()
        if value == cfgname:
            return  # pragma: no cover
        if not cfgname and value == self.get_pretty_desc():
            # Don't encode the default connection value into gconf right
            # away, require the user to edit it first
            return
        self.config.set_perconn(self.get_uri(), "/pretty-name", value)
    def _get_config_pretty_name(self):
        return self.config.get_perconn(self.get_uri(), "/pretty-name")
    def _on_config_pretty_name_changed(self, *args, **kwargs):
        return self.config.listen_perconn(self.get_uri(), "/pretty-name",
            *args, **kwargs)
    def _config_pretty_name_changed_cb(self):
        self.emit("state-changed")

    def set_details_window_size(self, w, h):
        self.config.set_perconn(self.get_uri(), "/window-size", (w, h))
    def get_details_window_size(self):
        ret = self.config.get_perconn(self.get_uri(), "/window-size")
        return ret
