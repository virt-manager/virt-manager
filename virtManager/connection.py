#
# Copyright (C) 2006, 2013, 2014, 2015 Red Hat, Inc.
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
import threading
import time
import traceback

import libvirt

from gi.repository import GObject

import virtinst
from virtinst import pollhelpers
from virtinst import support
from virtinst import util

from . import connectauth
from .baseclass import vmmGObject
from .domain import vmmDomain
from .interface import vmmInterface
from .network import vmmNetwork
from .nodedev import vmmNodeDevice
from .storagepool import vmmStoragePool


# debugging helper to turn off events
# Can be enabled with virt-manager --test-no-events
FORCE_DISABLE_EVENTS = False


class _ObjectList(vmmGObject):
    """
    Class that wraps our internal list of libvirt objects
    """

    BLACKLIST_COUNT = 3

    def __init__(self):
        vmmGObject.__init__(self)

        self._objects = []
        self._blacklist = {}
        self._lock = threading.Lock()

    def _cleanup(self):
        try:
            self._lock.acquire()

            for obj in self._objects:
                try:
                    obj.cleanup()
                except Exception:
                    logging.debug("Failed to cleanup %s", exc_info=True)
            self._objects = []
        finally:
            self._lock.release()

    def _blacklist_key(self, obj):
        return str(obj.__class__) + obj.get_connkey()

    def add_blacklist(self, obj):
        """
        Add an object to the blacklist. Basically a list of objects we
        choose not to poll, because they threw an error at init time

        :param obj: vmmLibvirtObject to blacklist
        :returns: number of added object to list
        """
        key = self._blacklist_key(obj)
        if self.in_blacklist(obj):
            self._blacklist[key] += 1
        self._blacklist[key] = 1
        return self._blacklist[key]

    def remove_blacklist(self, obj):
        """
        :param obj: vmmLibvirtObject to remove from blacklist
        :returns: True if object was blacklisted or False otherwise.
        """
        return bool(self._blacklist.pop(self._blacklist_key(obj), 0))

    def in_blacklist(self, obj):
        """
        If an object is in list only once don't consider it blacklisted,
        give it one more chance.

        :param obj: vmmLibvirtObject to check
        :returns: True if object is blacklisted
        """
        return self._blacklist.get(self._blacklist_key(obj), 0) > _ObjectList.BLACKLIST_COUNT

    def remove(self, obj):
        """
        Remove an object from the list.

        :param obj: vmmLibvirtObject to remove
        :returns: True if object removed, False if object was not found
        """
        try:
            self._lock.acquire()

            # Identity check is sufficient here, since we should never be
            # asked to remove an object that wasn't at one point in the list.
            if obj not in self._objects:
                return self.remove_blacklist(obj)

            self._objects.remove(obj)
            return True
        finally:
            self._lock.release()

    def add(self, obj):
        """
        Add an object to the list.

        :param obj: vmmLibvirtObject to add
        :returns: True if object added, False if object already in the list
        """
        try:
            self._lock.acquire()

            # We don't look up based on identity here, to prevent tick()
            # races from adding the same domain twice
            #
            # We don't use lookup_object here since we need to hold the
            # lock the whole time to prevent a 'time of check' issue
            for checkobj in self._objects:
                if (checkobj.__class__ == obj.__class__ and
                    checkobj.get_connkey() == obj.get_connkey()):
                    return False
            if obj in self._objects:
                return False

            self._objects.append(obj)
            return True
        finally:
            self._lock.release()

    def get_objects_for_class(self, classobj):
        """
        Return all objects over the passed vmmLibvirtObject class
        """
        try:
            self._lock.acquire()
            return [o for o in self._objects if o.__class__ is classobj]
        finally:
            self._lock.release()

    def lookup_object(self, classobj, connkey):
        """
        Lookup an object with the passed classobj + connkey
        """
        # Doesn't require locking, since get_objects_for_class covers us
        for obj in self.get_objects_for_class(classobj):
            if obj.get_connkey() == connkey:
                return obj
        return None


class vmmConnection(vmmGObject):
    __gsignals__ = {
        "vm-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "vm-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "vm-renamed": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
        "net-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "net-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "pool-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "pool-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "interface-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "interface-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "nodedev-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "nodedev-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "resources-sampled": (GObject.SignalFlags.RUN_FIRST, None, []),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "connect-error": (GObject.SignalFlags.RUN_FIRST, None,
                          [str, str, bool]),
        "priority-tick": (GObject.SignalFlags.RUN_FIRST, None, [object]),
    }

    (_STATE_DISCONNECTED,
     _STATE_CONNECTING,
     _STATE_ACTIVE) = range(1, 4)

    def __init__(self, uri):
        vmmGObject.__init__(self)

        self._uri = uri
        if self._uri is None or self._uri.lower() == "xen":
            self._uri = "xen:///"

        self._state = self._STATE_DISCONNECTED
        self._backend = virtinst.VirtualConnection(self._uri)
        self._closing = False

        self._init_object_count = None
        self._init_object_event = None

        self._network_capable = None
        self._storage_capable = None
        self._interface_capable = None
        self._nodedev_capable = None

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
                return

            if is_main_thread:
                if Gtk.events_pending():
                    Gtk.main_iteration_do(False)
                    continue

            time.sleep(.1)

    def _init_virtconn(self):
        self._backend.cb_fetch_all_guests = (
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
                    except Exception as e:
                        logging.debug("Fetching volume XML failed: %s", e)
            return ret
        self._backend.cb_fetch_all_vols = fetch_all_vols

        def cache_new_pool(obj):
            if not self.is_active():
                return
            name = obj.name()
            self.schedule_priority_tick(pollpool=True)
            def compare_cb():
                return bool(self.get_pool(name))
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
        if not self._backend.is_open():
            return 0
        return self._hostinfo[1] * 1024

    def host_active_processor_count(self):
        if not self._backend.is_open():
            return 0
        return self._hostinfo[2]

    def connect(self, name, callback, *args):
        handle_id = vmmGObject.connect(self, name, callback, *args)

        if name == "vm-added":
            for vm in self.list_vms():
                self.emit("vm-added", vm.get_connkey())

        return handle_id


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
    is_container = property(lambda s: getattr(s, "_backend").is_container)
    is_lxc = property(lambda s: getattr(s, "_backend").is_lxc)
    is_openvz = property(lambda s: getattr(s, "_backend").is_openvz)
    is_vz = property(lambda s: getattr(s, "_backend").is_vz)
    is_xen = property(lambda s: getattr(s, "_backend").is_xen)
    is_remote = property(lambda s: getattr(s, "_backend").is_remote)
    is_qemu = property(lambda s: getattr(s, "_backend").is_qemu)
    is_qemu_system = property(lambda s: getattr(s, "_backend").is_qemu_system)
    is_qemu_session = property(lambda s:
                               getattr(s, "_backend").is_qemu_session)
    is_test = property(lambda s: getattr(s, "_backend").is_test)
    is_session_uri = property(lambda s: getattr(s, "_backend").is_session_uri)


    # Connection capabilities debug helpers
    def stable_defaults(self, *args, **kwargs):
        return self._backend.stable_defaults(*args, **kwargs)

    def get_cache_dir(self):
        uri = self.get_uri().replace("/", "_")
        ret = os.path.join(util.get_cache_dir(), uri)
        if not os.path.exists(ret):
            os.makedirs(ret, 0o755)
        return ret

    def get_default_storage_format(self):
        raw = self.config.get_default_storage_format(raw=True)
        if raw != "default":
            return raw

        fmt = self.config.get_default_storage_format()
        if fmt != "qcow2":
            return fmt

        if self.check_support(self._backend.SUPPORT_CONN_DEFAULT_QCOW2):
            return fmt
        return None


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
            "gsx":        "GSX",
            "libxl":      "libxl",
            "lxc":        "LXC",
            "openvz":     "OpenVZ",
            "phyp":       "phyp",
            "qemu":       "QEMU/KVM",
            "test":       "test",
            "uml":        "UML",
            "vbox":       "VBox",
            "vmware":     "VMWare",
            "xen":        "Xen",
            "xenapi":     "XenAPI",
        }

        hv = pretty_map.get(self.get_driver(), self.get_driver())
        hostname = self.get_uri_hostname()
        path = self.get_backend().get_uri_path()
        is_session = self.get_backend().is_session_uri()

        ret = hv

        if is_session:
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

    for _supportname in [_supportname for _supportname in
                         dir(virtinst.VirtualConnection) if
                         _supportname.startswith("SUPPORT_")]:
        locals()[_supportname] = getattr(virtinst.VirtualConnection,
                                         _supportname)
    def check_support(self, *args):
        # pylint: disable=no-value-for-parameter
        return self._backend.check_support(*args)

    def is_storage_capable(self):
        if self._storage_capable is None:
            self._storage_capable = self.check_support(
                                        self._backend.SUPPORT_CONN_STORAGE)
            if self._storage_capable is False:
                logging.debug("Connection doesn't seem to support storage "
                              "APIs. Skipping all storage polling.")

        return self._storage_capable

    def is_network_capable(self):
        if self._network_capable is None:
            self._network_capable = self.check_support(
                                       self._backend.SUPPORT_CONN_NETWORK)
            if self._network_capable is False:
                logging.debug("Connection doesn't seem to support network "
                              "APIs. Skipping all network polling.")

        return self._network_capable

    def is_interface_capable(self):
        if self._interface_capable is None:
            self._interface_capable = self.check_support(
                                       self._backend.SUPPORT_CONN_INTERFACE)
            if self._interface_capable is False:
                logging.debug("Connection doesn't seem to support interface "
                              "APIs. Skipping all interface polling.")

        return self._interface_capable

    def is_nodedev_capable(self):
        if self._nodedev_capable is None:
            self._nodedev_capable = self.check_support(
                                            self._backend.SUPPORT_CONN_NODEDEV)
        return self._nodedev_capable

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

            if self.check_support(
                self._backend.SUPPORT_DOMAIN_XML_INACTIVE, vm):
                inact = libvirt.VIR_DOMAIN_XML_INACTIVE
            else:
                logging.debug("Domain XML inactive flag not supported.")

            if self.check_support(
                self._backend.SUPPORT_DOMAIN_XML_SECURE, vm):
                inact |= libvirt.VIR_DOMAIN_XML_SECURE
                act = libvirt.VIR_DOMAIN_XML_SECURE
            else:
                logging.debug("Domain XML secure flag not supported.")

            return inact, act

        return self._get_flags_helper(vm, key, check_func)

    def get_interface_flags(self, iface):
        key = "interface"

        def check_func():
            act   = 0
            inact = 0

            if self.check_support(
                self._backend.SUPPORT_INTERFACE_XML_INACTIVE, iface):
                inact = libvirt.VIR_INTERFACE_XML_INACTIVE
            else:
                logging.debug("Interface XML inactive flag not supported.")

            return (inact, act)

        return self._get_flags_helper(iface, key, check_func)

    def get_default_pool(self):
        for p in self.list_pools():
            if p.get_name() == "default":
                return p
        return None

    def get_vol_by_path(self, path):
        for pool in self.list_pools():
            for vol in pool.get_volumes():
                try:
                    if vol.get_target_path() == path:
                        return vol
                except Exception as e:
                    # Errors can happen if the volume disappeared, bug 1092739
                    logging.debug("Error looking up volume from path=%s: %s",
                        path, e)
        return None


    ###################################
    # Connection state getter/setters #
    ###################################

    def _change_state(self, newstate):
        if self._state != newstate:
            self._state = newstate
            logging.debug("conn=%s changed to state=%s",
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
        elif self.is_active():
            return _("Active")
        else:
            return _("Unknown")


    #################################
    # Libvirt object lookup methods #
    #################################

    def get_vm(self, connkey):
        return self._objects.lookup_object(vmmDomain, connkey)
    def list_vms(self):
        return self._objects.get_objects_for_class(vmmDomain)

    def get_net(self, connkey):
        return self._objects.lookup_object(vmmNetwork, connkey)
    def list_nets(self):
        return self._objects.get_objects_for_class(vmmNetwork)

    def get_pool(self, connkey):
        return self._objects.lookup_object(vmmStoragePool, connkey)
    def list_pools(self):
        return self._objects.get_objects_for_class(vmmStoragePool)

    def get_interface(self, connkey):
        return self._objects.lookup_object(vmmInterface, connkey)
    def list_interfaces(self):
        return self._objects.get_objects_for_class(vmmInterface)

    def get_nodedev(self, connkey):
        return self._objects.lookup_object(vmmNodeDevice, connkey)
    def list_nodedevs(self):
        return self._objects.get_objects_for_class(vmmNodeDevice)


    ############################
    # nodedev helper functions #
    ############################

    def filter_nodedevs(self, devtype=None, devcap=None):
        retdevs = []
        for dev in self.list_nodedevs():
            try:
                xmlobj = dev.get_xmlobj()
            except libvirt.libvirtError as e:
                # Libvirt nodedev XML fetching can be busted
                # https://bugzilla.redhat.com/show_bug.cgi?id=1225771
                if e.get_error_code() != libvirt.VIR_ERR_NO_NODE_DEVICE:
                    logging.debug("Error fetching nodedev XML", exc_info=True)
                continue

            if devtype and xmlobj.device_type != devtype:
                continue

            if devcap:
                if (not hasattr(xmlobj, "capability_type") or
                    xmlobj.capability_type != devcap):
                    continue

            if (devtype == "usb_device" and
                (("Linux Foundation" in str(xmlobj.vendor_name) or
                 ("Linux" in str(xmlobj.vendor_name) and
                  xmlobj.vendor_id == "0x1d6b")) and
                 ("root hub" in str(xmlobj.product_name) or
                  ("host controller" in str(xmlobj.product_name).lower() and
                   str(xmlobj.product_id).startswith("0x000"))))):
                continue

            retdevs.append(dev)

        return retdevs

    def get_nodedev_count(self, devtype, vendor, product):
        count = 0
        devs = self.filter_nodedevs(devtype)

        for dev in devs:
            if (vendor == dev.xmlobj.vendor_id and
                product == dev.xmlobj.product_id):
                count += 1

        logging.debug("There are %d node devices with "
                      "vendorId: %s, productId: %s",
                       count, vendor, product)

        return count


    ###################################
    # Libvirt object creation methods #
    ###################################

    def define_domain(self, xml):
        return self._backend.defineXML(xml)
    def define_network(self, xml):
        return self._backend.networkDefineXML(xml)
    def define_pool(self, xml):
        return self._backend.storagePoolDefineXML(xml, 0)
    def define_interface(self, xml):
        return self._backend.interfaceDefineXML(xml, 0)

    def rename_object(self, obj, origxml, newxml, oldconnkey):
        if obj.class_name() == "domain":
            define_cb = self.define_domain
        elif obj.class_name() == "pool":
            define_cb = self.define_pool
        elif obj.class_name() == "network":
            define_cb = self.define_network
        else:
            raise RuntimeError("programming error: rename_object "
                "helper doesn't support object class %s" % obj.__class__)

        # Undefine the original object
        obj.delete(force=False)

        newobj = None
        try:
            # Redefine new domain
            newobj = define_cb(newxml)
        except Exception as renameerr:
            try:
                logging.debug("Error defining new name %s XML",
                    obj.class_name(), exc_info=True)
                newobj = define_cb(origxml)
            except Exception as fixerr:
                logging.debug("Failed to redefine original %s!",
                    obj.class_name(), exc_info=True)
                raise RuntimeError(
                    _("%s rename failed. Attempting to recover also "
                      "failed.\n\n"
                      "Original error: %s\n\n"
                      "Recover error: %s" %
                      (obj.class_name(), str(renameerr), str(fixerr))))
            raise
        finally:
            if newobj:
                # Reinsert handle into new obj
                obj.change_name_backend(newobj)

        if newobj and obj.class_name() == "domain":
            self.emit("vm-renamed", oldconnkey, obj.get_connkey())


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

        name = domain.name()
        logging.debug("domain xmlmisc event: domain=%s args=%s ", name, args)
        obj = self.get_vm(name)
        if not obj:
            return

        self.idle_add(obj.recache_from_event_loop)

    def _domain_lifecycle_event(self, conn, domain, event, reason, userdata):
        ignore = conn
        ignore = userdata

        name = domain.name()
        logging.debug("domain lifecycle event: domain=%s event=%s "
            "reason=%s", name, event, reason)
        obj = self.get_vm(name)

        if obj:
            self.idle_add(obj.recache_from_event_loop)
        else:
            self.schedule_priority_tick(pollvm=True, force=True)

    def _network_lifecycle_event(self, conn, network, event, reason, userdata):
        ignore = conn
        ignore = userdata

        name = network.name()
        logging.debug("network lifecycle event: network=%s event=%s "
            "reason=%s", name, event, reason)
        obj = self.get_net(name)

        if obj:
            self.idle_add(obj.recache_from_event_loop)
        else:
            self.schedule_priority_tick(pollnet=True, force=True)

    def _storage_pool_lifecycle_event(self, conn, pool,
                                      event, reason, userdata):
        ignore = conn
        ignore = userdata

        name = pool.name()
        logging.debug("storage pool lifecycle event: storage=%s event=%s "
            "reason=%s", name, event, reason)

        obj = self.get_pool(name)

        if obj:
            self.idle_add(obj.recache_from_event_loop)
        else:
            self.schedule_priority_tick(pollpool=True, force=True)

    def _storage_pool_refresh_event(self, conn, pool, userdata):
        ignore = conn
        ignore = userdata

        name = pool.name()
        logging.debug("storage pool refresh event: pool=%s", name)

        obj = self.get_pool(name)

        if not obj:
            return

        self.idle_add(obj.refresh_pool_cache_from_event_loop)

    def _node_device_lifecycle_event(self, conn, dev,
                                     event, reason, userdata):
        ignore = conn
        ignore = userdata

        name = dev.name()
        logging.debug("node device lifecycle event: device=%s event=%s "
            "reason=%s", name, event, reason)

        self.schedule_priority_tick(pollnodedev=True, force=True)

    def _node_device_update_event(self, conn, dev, userdata):
        ignore = conn
        ignore = userdata

        name = dev.name()
        logging.debug("node device update event: device=%s", name)

        obj = self.get_nodedev(name)

        if obj:
            self.idle_add(obj.recache_from_event_loop)

    def _add_conn_events(self):
        if not self.check_support(support.SUPPORT_CONN_WORKING_XEN_EVENTS):
            return

        try:
            if FORCE_DISABLE_EVENTS:
                raise RuntimeError("FORCE_DISABLE_EVENTS = True")

            self._domain_cb_ids.append(
                self.get_backend().domainEventRegisterAny(
                None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                self._domain_lifecycle_event, None))
            self.using_domain_events = True
            logging.debug("Using domain events")
        except Exception as e:
            self.using_domain_events = False
            logging.debug("Error registering domain events: %s", e)

        def _add_domain_xml_event(eventid, typestr):
            if not self.using_domain_events:
                return
            try:
                self._domain_cb_ids.append(
                    self.get_backend().domainEventRegisterAny(
                    None, eventid, self._domain_xml_misc_event, None))
            except Exception as e:
                logging.debug("Error registering domain %s event: %s",
                    typestr, e)

        _add_domain_xml_event(
            getattr(libvirt, "VIR_DOMAIN_EVENT_ID_BALLOON_CHANGE", 13),
            "balloon")
        _add_domain_xml_event(
            getattr(libvirt, "VIR_DOMAIN_EVENT_ID_TRAY_CHANGE", 10), "tray")
        _add_domain_xml_event(
            getattr(libvirt, "VIR_DOMAIN_EVENT_ID_DEVICE_REMOVED", 15),
            "device removed")
        _add_domain_xml_event(
            getattr(libvirt, "VIR_DOMAIN_EVENT_ID_DEVICE_ADDED", 19),
            "device added")

        try:
            if FORCE_DISABLE_EVENTS:
                raise RuntimeError("FORCE_DISABLE_EVENTS = True")

            eventid = getattr(libvirt, "VIR_NETWORK_EVENT_ID_LIFECYCLE", 0)
            self._network_cb_ids.append(
                self.get_backend().networkEventRegisterAny(
                None, eventid, self._network_lifecycle_event, None))
            self.using_network_events = True
            logging.debug("Using network events")
        except Exception as e:
            self.using_network_events = False
            logging.debug("Error registering network events: %s", e)

        try:
            if FORCE_DISABLE_EVENTS:
                raise RuntimeError("FORCE_DISABLE_EVENTS = True")

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
            logging.debug("Using storage pool events")
        except Exception as e:
            self.using_storage_pool_events = False
            logging.debug("Error registering storage pool events: %s", e)

        try:
            if FORCE_DISABLE_EVENTS:
                raise RuntimeError("FORCE_DISABLE_EVENTS = True")

            eventid = getattr(libvirt, "VIR_NODE_DEVICE_EVENT_ID_LIFECYCLE", 0)
            updateid = getattr(libvirt, "VIR_NODE_DEVICE_EVENT_ID_UPDATE", 1)
            self._node_device_cb_ids.append(
                self.get_backend().nodeDeviceEventRegisterAny(
                None, eventid, self._node_device_lifecycle_event, None))
            self._node_device_cb_ids.append(
                self.get_backend().nodeDeviceEventRegisterAny(
                None, updateid, self._node_device_update_event, None))

            self.using_node_device_events = True
            logging.debug("Using node device events")
        except Exception as e:
            self.using_network_events = False
            logging.debug("Error registering node device events: %s", e)


    ######################################
    # Connection closing/opening methods #
    ######################################

    def _schedule_close(self):
        self._closing = True
        self.idle_add(self.close)

    def close(self):
        if not self.is_disconnected():
            logging.debug("conn.close() uri=%s", self.get_uri())
        self._closing = True

        try:
            if not self._backend.is_closed():
                for eid in self._domain_cb_ids:
                    self._backend.domainEventDeregisterAny(eid)
                for eid in self._network_cb_ids:
                    self._backend.networkEventDeregisterAny(eid)
                for eid in self._storage_pool_cb_ids:
                    self._backend.storagePoolEventDeregisterAny(eid)
                for eid in self._node_device_cb_ids:
                    self._backend.nodeDeviceEventDeregisterAny(eid)
        except Exception:
            logging.debug("Failed to deregister events in conn cleanup",
                exc_info=True)
        finally:
            self._domain_cb_ids = []
            self._network_cb_ids = []
            self._storage_pool_cb_ids = []
            self._node_device_cb_ids = []

        self._backend.close()
        self._stats = []

        if self._init_object_event:
            self._init_object_event.clear()

        self._objects.cleanup()
        self._objects = _ObjectList()

        self._change_state(self._STATE_DISCONNECTED)
        self._closing = False

    def _cleanup(self):
        self.close()

        self._objects = None
        self._backend.cb_fetch_all_guests = None
        self._backend.cb_fetch_all_pools = None
        self._backend.cb_fetch_all_nodedevs = None
        self._backend.cb_fetch_all_vols = None
        self._backend.cb_cache_new_pool = None

    def open(self):
        if not self.is_disconnected():
            return

        self._change_state(self._STATE_CONNECTING)

        logging.debug("Scheduling background open thread for " +
                     self.get_uri())
        self._start_thread(self._open_thread, "Connect %s" % self.get_uri())

    def _do_creds_password(self, creds):
        try:
            return connectauth.creds_dialog(self, creds)
        except Exception:
            logging.debug("Launching creds dialog failed", exc_info=True)
            return -1

    def _do_open(self, retry_for_tgt=True):
        warnconsole = False
        libvirt_error_code = None
        libvirt_error_message = None

        try:
            self._backend.open(self._do_creds_password)
            return True, None
        except Exception as exc:
            tb = "".join(traceback.format_exc())
            if isinstance(exc, libvirt.libvirtError):
                # pylint: disable=no-member
                libvirt_error_code = exc.get_error_code()
                libvirt_error_message = exc.get_error_message()

        if (libvirt_error_code ==
            getattr(libvirt, "VIR_ERR_AUTH_CANCELLED", None)):
            logging.debug("User cancelled auth, not raising any error.")
            return False, None

        if (libvirt_error_code == libvirt.VIR_ERR_AUTH_FAILED and
            "not authorized" in libvirt_error_message.lower()):
            logging.debug("Looks like we might have failed policykit "
                          "auth. Checking to see if we have a valid "
                          "console session")
            if (not self.is_remote() and
                not connectauth.do_we_have_session()):
                warnconsole = True

        if (libvirt_error_code == libvirt.VIR_ERR_AUTH_FAILED and
            "GSSAPI Error" in libvirt_error_message and
            "No credentials cache found" in libvirt_error_message):
            if retry_for_tgt and connectauth.acquire_tgt():
                self._do_open(retry_for_tgt=False)

        connectError = (str(exc), tb, warnconsole)
        return False, connectError

    def _populate_initial_state(self):
        logging.debug("libvirt version=%s",
                      self._backend.local_libvirt_version())
        logging.debug("daemon version=%s",
                      self._backend.daemon_version())
        logging.debug("conn version=%s", self._backend.conn_version())
        logging.debug("%s capabilities:\n%s",
                      self.get_uri(), self.caps.get_xml_config())

        # Try to create the default storage pool
        # We want this before events setup to save some needless polling
        try:
            virtinst.StoragePool.build_default_pool(self.get_backend())
        except Exception as e:
            logging.debug("Building default pool failed: %s", str(e))

        self._add_conn_events()

        # Prime CPU cache
        self.caps.get_cpu_values(self.caps.host.cpu.arch)

        try:
            self._backend.setKeepAlive(20, 1)
        except Exception as e:
            if (type(e) is not AttributeError and
                not util.is_error_nosupport(e)):
                raise
            logging.debug("Connection doesn't support KeepAlive, "
                "skipping")

        # The initial tick will set up a threading event that will only
        # trigger after all the polled libvirt objects are fully initialized.
        # That way we only report the connection is open when everything is
        # nicely setup for the rest of the app.

        self._init_object_event = threading.Event()
        self._init_object_count = 0

        self.schedule_priority_tick(stats_update=True,
            pollvm=True, pollnet=True,
            pollpool=True, polliface=True,
            pollnodedev=True, force=True, initial_poll=True)

        self._init_object_event.wait()
        self._init_object_event = None
        self._init_object_count = None

    def _open_thread(self):
        try:
            is_active, connectError = self._do_open()
            if is_active:
                self._populate_initial_state()

            self.idle_add(self._change_state, is_active and
                self._STATE_ACTIVE or self._STATE_DISCONNECTED)
        except Exception as e:
            is_active = False
            self._schedule_close()
            connectError = (str(e), "".join(traceback.format_exc()), False)

        if not is_active:
            if connectError:
                self.idle_emit("connect-error", *connectError)


    #######################
    # Tick/Update methods #
    #######################

    def _gone_object_signals(self, gone_objects):
        """
        Responsible for signaling the UI for any updates. All possible UI
        updates need to go here to enable threading that doesn't block the
        app with long tick operations.
        """
        if not self._backend.is_open():
            return

        for obj in gone_objects:
            class_name = obj.class_name()
            try:
                name = obj.get_name()
            except Exception:
                name = str(obj)

            if not self._objects.remove(obj):
                logging.debug("Requested removal of %s=%s, but it's "
                    "not in our object list.", class_name, name)
                continue

            logging.debug("%s=%s removed", class_name, name)
            if class_name == "domain":
                self.emit("vm-removed", obj.get_connkey())
            elif class_name == "network":
                self.emit("net-removed", obj.get_connkey())
            elif class_name == "pool":
                self.emit("pool-removed", obj.get_connkey())
            elif class_name == "interface":
                self.emit("interface-removed", obj.get_connkey())
            elif class_name == "nodedev":
                self.emit("nodedev-removed", obj.get_connkey())
            obj.cleanup()

    def _new_object_cb(self, obj, initialize_failed, skip_init=False):
        if not self._backend.is_open():
            return

        try:
            class_name = obj.class_name()

            if initialize_failed:
                logging.debug("Blacklisting %s=%s", class_name, obj.get_name())
                count = self._objects.add_blacklist(obj)
                if count <= _ObjectList.BLACKLIST_COUNT:
                    logging.debug("Object added in blacklist, count=%d", count)
                else:
                    logging.debug("Object already blacklisted?")
                return
            else:
                self._objects.remove_blacklist(obj)

            if not self._objects.add(obj):
                logging.debug("New %s=%s requested, but it's already tracked.",
                    class_name, obj.get_name())
                return

            if class_name != "nodedev":
                # Skip nodedev logging since it's noisy and not interesting
                logging.debug("%s=%s status=%s added", class_name,
                    obj.get_name(), obj.run_status())
            if class_name == "domain":
                self.emit("vm-added", obj.get_connkey())
            elif class_name == "network":
                self.emit("net-added", obj.get_connkey())
            elif class_name == "pool":
                self.emit("pool-added", obj.get_connkey())
            elif class_name == "interface":
                self.emit("interface-added", obj.get_connkey())
            elif class_name == "nodedev":
                self.emit("nodedev-added", obj.get_connkey())
        finally:
            if self._init_object_event and not skip_init:
                self._init_object_count -= 1
                if self._init_object_count <= 0:
                    self._init_object_event.set()

    def _update_nets(self, dopoll):
        keymap = dict((o.get_connkey(), o) for o in self.list_nets())
        if not dopoll or not self.is_network_capable():
            return [], [], keymap.values()
        return pollhelpers.fetch_nets(self._backend, keymap,
                    (lambda obj, key: vmmNetwork(self, obj, key)))

    def _update_pools(self, dopoll):
        keymap = dict((o.get_connkey(), o) for o in self.list_pools())
        if not dopoll or not self.is_storage_capable():
            return [], [], keymap.values()
        return pollhelpers.fetch_pools(self._backend, keymap,
                    (lambda obj, key: vmmStoragePool(self, obj, key)))

    def _update_interfaces(self, dopoll):
        keymap = dict((o.get_connkey(), o) for o in self.list_interfaces())
        if not dopoll or not self.is_interface_capable():
            return [], [], keymap.values()
        return pollhelpers.fetch_interfaces(self._backend, keymap,
                    (lambda obj, key: vmmInterface(self, obj, key)))

    def _update_nodedevs(self, dopoll):
        keymap = dict((o.get_connkey(), o) for o in self.list_nodedevs())
        if not dopoll or not self.is_nodedev_capable():
            return [], [], keymap.values()
        return pollhelpers.fetch_nodedevs(self._backend, keymap,
                    (lambda obj, key: vmmNodeDevice(self, obj, key)))

    def _update_vms(self, dopoll):
        keymap = dict((o.get_connkey(), o) for o in self.list_vms())
        if not dopoll:
            return [], [], keymap.values()
        return pollhelpers.fetch_vms(self._backend, keymap,
                    (lambda obj, key: vmmDomain(self, obj, key)))

    def _poll(self, initial_poll,
            pollvm, pollnet, pollpool, polliface, pollnodedev):
        """
        Helper called from tick() to do necessary polling and return
        the relevant object lists
        """
        gone_objects = []
        preexisting_objects = []

        def _process_objects(polloutput):
            gone, new, master = polloutput

            if initial_poll:
                self._init_object_count += len(new)

            gone_objects.extend(gone)
            preexisting_objects.extend([o for o in master if o not in new])
            new = [n for n in new if not self._objects.in_blacklist(n)]
            return new

        new_vms = _process_objects(self._update_vms(pollvm))
        new_nets = _process_objects(self._update_nets(pollnet))
        new_pools = _process_objects(self._update_pools(pollpool))
        new_ifaces = _process_objects(self._update_interfaces(polliface))
        new_nodedevs = _process_objects(self._update_nodedevs(pollnodedev))

        # Kick off one thread per object type to handle the initial
        # XML fetching. Going any more fine grained then this probably
        # won't be that useful due to libvirt's locking structure.
        #
        # Would prefer to start refreshing some objects before all polling
        # is complete, but we need init_object_count to be fully accurate
        # before we start initializing objects
        for newlist in [new_vms, new_nets, new_pools,
                new_ifaces, new_nodedevs]:
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
             pollpool=False, polliface=False,
             pollnodedev=False,
             force=False, initial_poll=False):
        """
        main update function: polls for new objects, updates stats, ...

        :param force: Perform the requested polling even if async events
            are in use.
        """
        if self._closing:
            return
        if self.is_disconnected():
            return
        if self.is_connecting() and not force:
            return

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

        gone_objects, preexisting_objects = self._poll(
            initial_poll, pollvm, pollnet, pollpool, polliface, pollnodedev)
        self.idle_add(self._gone_object_signals, gone_objects)

        # Only tick() pre-existing objects, since new objects will be
        # initialized asynchronously and tick() would be redundant
        for obj in preexisting_objects:
            try:
                if obj.reports_stats() and stats_update:
                    pass
                elif obj.__class__ is vmmDomain and not pollvm:
                    continue
                elif obj.__class__ is vmmNetwork and not pollnet:
                    continue
                elif obj.__class__ is vmmStoragePool and not pollpool:
                    continue
                elif obj.__class__ is vmmInterface and not polliface:
                    continue
                elif obj.__class__ is vmmNodeDevice and not pollnodedev:
                    continue

                obj.tick(stats_update=stats_update)
            except Exception as e:
                logging.exception("Tick for %s failed", obj)
                if (isinstance(e, libvirt.libvirtError) and
                    (getattr(e, "get_error_code")() ==
                     libvirt.VIR_ERR_SYSTEM_ERROR)):
                    # Try a simple getInfo call to see if conn was dropped
                    self._backend.getInfo()
                    logging.debug("vm tick raised system error but "
                                  "connection doesn't seem to have dropped. "
                                  "Ignoring.")

        if stats_update:
            self._recalculate_stats(
                [o for o in preexisting_objects if o.reports_stats()])
            self.idle_emit("resources-sampled")

    def _recalculate_stats(self, vms):
        if not self._backend.is_open():
            return

        now = time.time()
        expected = self.config.get_stats_history_length()
        current = len(self._stats)
        if current > expected:
            del self._stats[expected:current]

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
        self.idle_emit("priority-tick", kwargs)

    def tick_from_engine(self, *args, **kwargs):
        e = None
        try:
            self._tick(*args, **kwargs)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            pass

        if e is None:
            return

        from_remote = getattr(libvirt, "VIR_FROM_REMOTE", None)
        from_rpc = getattr(libvirt, "VIR_FROM_RPC", None)
        sys_error = getattr(libvirt, "VIR_ERR_SYSTEM_ERROR", None)
        internal_error = getattr(libvirt, "VIR_ERR_INTERNAL_ERROR", None)

        dom = -1
        code = -1
        if isinstance(e, libvirt.libvirtError):
            # pylint: disable=no-member
            dom = e.get_error_domain()
            code = e.get_error_code()

        logging.debug("Error polling connection %s",
            self.get_uri(), exc_info=True)

        if (dom in [from_remote, from_rpc] and
            code in [sys_error, internal_error]):
            e = None
            logging.debug("Not showing user error since libvirtd "
                "appears to have stopped.")

        self._schedule_close()
        if e:
            raise e  # pylint: disable=raising-bad-type


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
            statslen = min(statslen, limit)

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
            return
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
