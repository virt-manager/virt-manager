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

# pylint: disable=E0611
from gi.repository import GObject
# pylint: enable=E0611

import logging
import os
import re
import socket
import threading
import time
import traceback

import libvirt
import virtinst
from virtinst import pollhelpers
from virtinst import util

from virtManager import connectauth
from virtManager.baseclass import vmmGObject
from virtManager.domain import vmmDomain
from virtManager.interface import vmmInterface
from virtManager.mediadev import vmmMediaDevice
from virtManager.netdev import vmmNetDevice
from virtManager.network import vmmNetwork
from virtManager.nodedev import vmmNodeDevice
from virtManager.storagepool import vmmStoragePool


class vmmConnection(vmmGObject):
    __gsignals__ = {
        "vm-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "vm-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "net-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "net-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "net-started": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "net-stopped": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "pool-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "pool-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "pool-started": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "pool-stopped": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "interface-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "interface-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "interface-started": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "interface-stopped": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "nodedev-added": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "nodedev-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "mediadev-added": (GObject.SignalFlags.RUN_FIRST, None, [object]),
        "mediadev-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "resources-sampled": (GObject.SignalFlags.RUN_FIRST, None, []),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "connect-error": (GObject.SignalFlags.RUN_FIRST, None,
                          [str, str, bool]),
        "priority-tick": (GObject.SignalFlags.RUN_FIRST, None, [object]),
    }

    STATE_DISCONNECTED = 0
    STATE_CONNECTING = 1
    STATE_ACTIVE = 2
    STATE_INACTIVE = 3

    def __init__(self, uri):
        vmmGObject.__init__(self)

        self._uri = uri
        if self._uri is None or self._uri.lower() == "xen":
            self._uri = "xen:///"

        self.state = self.STATE_DISCONNECTED
        self.connectThread = None
        self.connectError = None
        self._backend = virtinst.VirtualConnection(self._uri)

        self._caps = None
        self._caps_xml = None

        self._network_capable = None
        self._storage_capable = None
        self._interface_capable = None
        self._nodedev_capable = None

        self.using_domain_events = False
        self._domain_cb_id = None
        self.using_network_events = False
        self._network_cb_id = None

        self._xml_flags = {}

        # Physical network interfaces: name -> virtinst.NodeDevice
        self.nodedevs = {}
        # Physical network interfaces: name (eth0) -> vmmNetDevice
        self.netdevs = {}
        # Physical media devices: vmmMediaDevice.key -> vmmMediaDevice
        self.mediadevs = {}
        # Connection Storage pools: name -> vmmInterface
        self.interfaces = {}
        # Connection Storage pools: UUID -> vmmStoragePool
        self.pools = {}
        # Virtual networks UUUID -> vmmNetwork object
        self.nets = {}
        # Virtual machines. UUID -> vmmDomain object
        self.vms = {}
        # Resource utilization statistics
        self.record = []
        self.hostinfo = None

        self.netdev_initialized = False
        self.netdev_error = ""
        self.netdev_use_libvirt = False

        self.mediadev_initialized = False
        self.mediadev_error = ""
        self.mediadev_use_libvirt = False

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
        if domtype == "kvm":
            if gtype == "xen":
                label = "xenner"
        elif domtype == "xen":
            if gtype == "xen":
                label = "xen (paravirt)"
            elif gtype == "hvm":
                label = "xen (fullvirt)"
        elif domtype == "test":
            if gtype == "xen":
                label = "test (xen)"
            elif gtype == "hvm":
                label = "test (hvm)"

        return label

    #################
    # Init routines #
    #################

    def _init_virtconn(self):
        self._backend.cb_fetch_all_guests = (
            lambda: [obj.get_xmlobj(refresh_if_nec=False)
                     for obj in self.vms.values()])
        self._backend.cb_fetch_all_pools = (
            lambda: [obj.get_xmlobj(refresh_if_nec=False)
                     for obj in self.pools.values()])
        self._backend.cb_fetch_all_vols = (
            lambda: [obj.get_xmlobj(refresh_if_nec=False)
                     for pool in self.pools.values()
                     for obj in pool.get_volumes(refresh=False).values()])

        def clear_cache(pools=False):
            if not pools:
                return

            # We need to do this synchronously
            self.tick(False, pollpool=True)

        self._backend.cb_clear_cache = clear_cache


    def _init_netdev(self):
        """
        Determine how we will be polling for net devices (HAL or libvirt)
        """
        if self.is_nodedev_capable() and self.is_interface_capable():
            try:
                self._build_libvirt_netdev_list()
                self.netdev_use_libvirt = True
            except Exception, e:
                self.netdev_error = _("Could not build physical interface "
                                      "list via libvirt: %s") % str(e)
        else:
            self.netdev_error = _("Libvirt version does not support "
                                  "physical interface listing.")

        self.netdev_initialized = True
        if self.netdev_error:
            logging.debug(self.netdev_error)
        else:
            if self.netdev_use_libvirt:
                logging.debug("Using libvirt API for netdev enumeration")
            else:
                logging.debug("Using HAL for netdev enumeration")

    def _init_mediadev(self):
        if self.is_nodedev_capable():
            try:
                self.connect("nodedev-added", self._nodedev_mediadev_added)
                self.connect("nodedev-removed", self._nodedev_mediadev_removed)
                self.mediadev_use_libvirt = True
            except Exception, e:
                self.mediadev_error = _("Could not build media "
                                        "list via libvirt: %s") % str(e)
        else:
            self.mediadev_error = _("Libvirt version does not support "
                                    "media listing.")

        self.mediadev_initialized = True
        if self.mediadev_error:
            logging.debug(self.mediadev_error)
        else:
            if self.mediadev_use_libvirt:
                logging.debug("Using libvirt API for mediadev enumeration")
            else:
                logging.debug("Using HAL for mediadev enumeration")


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

    def get_host_info(self):
        return self.hostinfo

    def pretty_host_memory_size(self):
        if not self._backend.is_open():
            return ""
        return util.pretty_mem(self.host_memory_size())

    def host_memory_size(self):
        if not self._backend.is_open():
            return 0
        return self.hostinfo[1] * 1024

    def host_architecture(self):
        if not self._backend.is_open():
            return ""
        return self.hostinfo[0]

    def host_active_processor_count(self):
        if not self._backend.is_open():
            return 0
        return self.hostinfo[2]

    def host_maximum_processor_count(self):
        if not self._backend.is_open():
            return 0
        return (self.hostinfo[4] * self.hostinfo[5] *
                self.hostinfo[6] * self.hostinfo[7])

    def connect(self, name, callback, *args):
        handle_id = vmmGObject.connect(self, name, callback, *args)

        if name == "vm-added":
            for uuid in self.vms.keys():
                self.emit("vm-added", uuid)
        elif name == "mediadev-added":
            for dev in self.mediadevs.values():
                self.emit("mediadev-added", dev)
        elif name == "nodedev-added":
            for key in self.nodedevs.keys():
                self.emit("nodedev-added", key)

        return handle_id

    ##########################
    # URI + hostname helpers #
    ##########################

    def get_qualified_hostname(self):
        if self.check_support(self._backend.SUPPORT_CONN_GETHOSTNAME):
            return self._backend.getHostname()

        uri_hostname = self.get_uri_hostname()
        if self.is_remote() and uri_hostname.lower() != "localhost":
            return uri_hostname

        # This can throw an exception, so beware when calling!
        return socket.gethostbyaddr(socket.gethostname())[0]

    def get_short_hostname(self):
        hostname = self.get_hostname()
        offset = hostname.find(".")
        if offset > 0 and not hostname[0].isdigit():
            return hostname[0:offset]
        return hostname

    def get_hostname(self):
        try:
            return self.get_qualified_hostname()
        except:
            return self.get_uri_hostname()

    get_uri_hostname = property(lambda s:
                                getattr(s, "_backend").get_uri_hostname)
    get_transport = property(lambda s:
                             getattr(s, "_backend").get_uri_transport)
    get_driver = property(lambda s: getattr(s, "_backend").get_uri_driver)
    is_container = property(lambda s: getattr(s, "_backend").is_container)
    is_lxc = property(lambda s: getattr(s, "_backend").is_lxc)
    is_openvz = property(lambda s: getattr(s, "_backend").is_openvz)
    is_xen = property(lambda s: getattr(s, "_backend").is_xen)
    is_remote = property(lambda s: getattr(s, "_backend").is_remote)
    is_qemu = property(lambda s: getattr(s, "_backend").is_qemu)
    is_qemu_system = property(lambda s: getattr(s, "_backend").is_qemu_system)
    is_qemu_session = property(lambda s:
                               getattr(s, "_backend").is_qemu_session)
    is_test_conn = property(lambda s: getattr(s, "_backend").is_test)
    is_session_uri = property(lambda s: getattr(s, "_backend").is_session_uri)


    # Connection capabilities debug helpers
    def stable_defaults(self, emulator=None):
        if not self.is_qemu_system():
            return False
        if emulator:
            if not str(emulator).startswith("/usr/libexec"):
                return False
        else:
            for guest in self.caps.guests:
                for dom in guest.domains:
                    if dom.emulator.startswith("/usr/libexec"):
                        return self.config.stable_defaults
        return self.config.stable_defaults

    def get_cache_dir(self):
        uri = self.get_uri().replace("/", "_")
        ret = os.path.join(util.get_cache_dir(), uri)
        if not os.path.exists(ret):
            os.makedirs(ret, 0755)
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

    def _get_pretty_desc(self, active, shorthost, show_trans):
        def match_whole_string(orig, reg):
            match = re.match(reg, orig)
            if not match:
                return False

            return ((match.end() - match.start()) == len(orig))

        def is_ip_addr(orig):
            return match_whole_string(orig, "[0-9.]+")

        (scheme, username, hostname,
         path, ignore, ignore) = util.uri_split(self.get_uri())
        hostname, port = self.get_backend().get_uri_host_port()
        port = port or ""

        hv = ""
        rest = ""
        transport = ""
        port = ""
        if scheme.count("+"):
            transport = scheme.split("+")[1]
            scheme = scheme.split("+")[0]

        if hostname.count(":"):
            port = hostname.split(":")[1]
            hostname = hostname.split(":")[0]

        if hostname:
            if shorthost and not is_ip_addr(hostname):
                rest = hostname.split(".")[0]
            else:
                rest = hostname
        else:
            rest = "localhost"

        pretty_map = {
            "esx"       : "ESX",
            "gsx"       : "GSX",
            "libxl"     : "libxl",
            "lxc"       : "LXC",
            "openvz"    : "OpenVZ",
            "phyp"      : "phyp",
            "qemu"      : "QEMU",
            "test"      : "test",
            "uml"       : "UML",
            "vbox"      : "VBox",
            "vmware"    : "VMWare",
            "xen"       : "xen",
            "xenapi"    : "XenAPI",
        }

        hv = scheme
        if scheme in pretty_map:
            hv = pretty_map[scheme]

        if hv == "QEMU" and active and self.caps.is_kvm_available():
            hv += "/KVM"

        if show_trans:
            if transport:
                hv += "+" + transport
            if username:
                hostname = username + "@" + hostname
            if port:
                hostname += ":" + port

        if path and path != "/system" and path != "/":
            if path == "/session":
                hv += " Usermode"
            else:
                hv += " %s" % os.path.basename(path)

        if self._backend.fake_name():
            hv = self._backend.fake_name()

        return "%s (%s)" % (rest, hv)

    def get_pretty_desc_inactive(self, shorthost=True, transport=False):
        return self._get_pretty_desc(False, shorthost, transport)

    def get_pretty_desc_active(self, shorthost=True, transport=False):
        return self._get_pretty_desc(True, shorthost, transport)


    #######################
    # API support helpers #
    #######################

    for _supportname in [_supportname for _supportname in
                         dir(virtinst.VirtualConnection) if
                         _supportname.startswith("SUPPORT_")]:
        locals()[_supportname] = getattr(virtinst.VirtualConnection,
                                         _supportname)
    def check_support(self, *args):
        return self._backend.check_support(*args)

    def is_storage_capable(self):
        if self._storage_capable is None:
            self._storage_capable = self.check_support(
                                        self._backend.SUPPORT_CONN_STORAGE)
            if self._storage_capable is False:
                logging.debug("Connection doesn't seem to support storage "
                              "APIs. Skipping all storage polling.")
            else:
                # Try to create the default storage pool
                try:
                    virtinst.StoragePool.build_default_pool(self.get_backend())
                except Exception, e:
                    logging.debug("Building default pool failed: %s", str(e))

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


    ###################################
    # Connection state getter/setters #
    ###################################

    def _change_state(self, newstate):
        if self.state != newstate:
            self.state = newstate
            self.emit("state-changed")

    def get_state(self):
        return self.state

    def get_state_text(self):
        if self.state == self.STATE_DISCONNECTED:
            return _("Disconnected")
        elif self.state == self.STATE_CONNECTING:
            return _("Connecting")
        elif self.state == self.STATE_ACTIVE:
            return _("Active")
        elif self.state == self.STATE_INACTIVE:
            return _("Inactive")
        else:
            return _("Unknown")

    def pause(self):
        if self.state != self.STATE_ACTIVE:
            return
        self._change_state(self.STATE_INACTIVE)

    def resume(self):
        if self.state != self.STATE_INACTIVE:
            return
        self._change_state(self.STATE_ACTIVE)

    def is_active(self):
        return self.state == self.STATE_ACTIVE

    def is_paused(self):
        return self.state == self.STATE_INACTIVE

    def is_disconnected(self):
        return self.state == self.STATE_DISCONNECTED

    def is_connecting(self):
        return self.state == self.STATE_CONNECTING

    #################################
    # Libvirt object lookup methods #
    #################################

    def _build_libvirt_netdev_list(self):
        bridges = []
        netdev_list = {}

        def interface_to_netdev(interface):
            name = interface.get_name()
            mac = interface.get_mac()
            is_bridge = interface.is_bridge()
            slave_names = interface.get_slave_names()

            if is_bridge and slave_names:
                bridges.append((name, slave_names))
            else:
                netdev_list[name] = vmmNetDevice(name, mac, is_bridge, None)

        def nodedev_to_netdev(nodedev):
            name = nodedev.interface
            mac = nodedev.address

            if name not in netdev_list.keys():
                netdev_list[name] = vmmNetDevice(name, mac, False, None)
            else:
                # Believe this info over libvirt interface APIs, since
                # this comes from the hardware
                if mac:
                    netdev_list[name].mac = mac

        for name, iface in self.interfaces.items():
            interface_to_netdev(iface)

        for nodedev in self.get_nodedevs("net"):
            nodedev_to_netdev(nodedev)

        # Mark NetDevices as bridged where appropriate
        for bridge_name, slave_names in bridges:
            for name, netdev in netdev_list.items():
                if name not in slave_names:
                    continue

                # XXX: Can a physical device be in two bridges?
                netdev.bridge = bridge_name
                netdev.shared = True
                break

        # XXX: How to handle added/removed signals to clients?
        return netdev_list

    def get_vm(self, uuid):
        return self.vms[uuid]
    def get_net(self, uuid):
        return self.nets[uuid]
    def get_net_device(self, path):
        return self.netdevs[path]
    def get_pool(self, uuid):
        return self.pools[uuid]
    def get_interface(self, name):
        return self.interfaces[name]
    def get_nodedev(self, name):
        return self.nodedevs[name]
    def get_nodedevs(self, devtype=None, devcap=None):
        retdevs = []
        for dev in self.nodedevs.values():
            xmlobj = dev.get_xmlobj()
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

            retdevs.append(xmlobj)

        return retdevs

    def get_nodedevs_number(self, devtype, vendor, product):
        count = 0
        devs = self.get_nodedevs(devtype)

        for dev in devs:
            if (vendor == dev.vendor_id and
                product == dev.product_id):
                count += 1

        logging.debug("There are %d node devices with "
                      "vendorId: %s, productId: %s",
                       count, vendor, product)

        return count

    def get_net_by_name(self, name):
        for net in self.nets.values():
            if net.get_name() == name:
                return net

    def get_pool_by_path(self, path):
        for pool in self.pools.values():
            if pool.get_target_path() == path:
                return pool
        return None

    def get_pool_by_name(self, name):
        for p in self.pools.values():
            if p.get_name() == name:
                return p
        return None
    def get_default_pool(self):
        return self.get_pool_by_name("default")

    def get_vol_by_path(self, path):
        for pool in self.pools.values():
            for vol in pool.get_volumes().values():
                if vol.get_target_path() == path:
                    return vol
        return None

    def list_vm_uuids(self):
        return self.vms.keys()
    def list_net_uuids(self):
        return self.nets.keys()
    def list_net_device_paths(self):
        # Update netdev list
        if self.netdev_use_libvirt:
            self.netdevs = self._build_libvirt_netdev_list()
        return self.netdevs.keys()
    def list_pool_uuids(self):
        return self.pools.keys()
    def list_interface_names(self):
        return self.interfaces.keys()


    ###################################
    # Libvirt object creation methods #
    ###################################

    def restore(self, frm):
        self._backend.restore(frm)
        try:
            os.remove(frm)
        except:
            logging.debug("Couldn't remove save file '%s' for restore", frm)

    def define_domain(self, xml):
        return self._backend.defineXML(xml)
    def define_network(self, xml):
        return self._backend.networkDefineXML(xml)
    def define_pool(self, xml):
        return self._backend.storagePoolDefineXML(xml, 0)
    def define_interface(self, xml):
        return self._backend.interfaceDefineXML(xml, 0)

    def _rename_helper(self, objtype, define_cb, obj, origxml, newxml):
        # Undefine the original object
        obj.delete(force=False)

        newobj = None
        try:
            try:
                # Redefine new domain
                newobj = define_cb(newxml)
            except Exception, renameerr:
                try:
                    logging.exception("Error defining new name %s XML",
                                      objtype)
                    newobj = define_cb(origxml)
                except Exception, fixerr:
                    logging.exception("Failed to redefine original %s!",
                                      objtype)
                    raise RuntimeError(
                        _("%s rename failed. Attempting to recover also "
                          "failed.\n\n"
                          "Original error: %s\n\n"
                          "Recover error: %s" %
                          (objtype, str(renameerr), str(fixerr))))
                raise
        finally:
            if newobj:
                # Reinsert handle into new obj
                obj.change_name_backend(newobj)

    def rename_vm(self, obj, origxml, newxml):
        return self._rename_helper("domain", self.define_domain,
                                   obj, origxml, newxml)
    def rename_network(self, obj, origxml, newxml):
        return self._rename_helper("network", self.define_network,
                                   obj, origxml, newxml)
    def rename_pool(self, obj, origxml, newxml):
        return self._rename_helper("storagepool", self.define_pool,
                                   obj, origxml, newxml)

    #########################
    # Domain event handling #
    #########################

    # Our strategy here isn't the most efficient: since we need to keep the
    # poll helpers around for compat with old libvirt, switching to a fully
    # event driven setup is hard, so we end up doing more polling than
    # necessary on most events.

    def _domain_lifecycle_event(self, conn, domain, event, reason, userdata):
        ignore = conn
        ignore = reason
        ignore = userdata
        obj = self.vms.get(domain.UUIDString(), None)

        if obj:
            # If the domain disappeared, this will catch it and trigger
            # a domain list refresh
            self.idle_add(obj.force_update_status, True)

            if event == libvirt.VIR_DOMAIN_EVENT_DEFINED:
                self.idle_add(obj.refresh_xml)
        else:
            self.schedule_priority_tick(pollvm=True, force=True)

    def _network_lifecycle_event(self, conn, network, event, reason, userdata):
        ignore = conn
        ignore = reason
        ignore = userdata
        obj = self.nets.get(network.UUIDString(), None)

        if obj:
            self.idle_add(obj.force_update_status, True)

            if event == libvirt.VIR_NETWORK_EVENT_DEFINED:
                self.idle_add(obj.refresh_xml)
        else:
            self.schedule_priority_tick(pollnet=True, force=True)

    def _add_conn_events(self):
        try:
            self._domain_cb_id = self.get_backend().domainEventRegisterAny(
                None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                self._domain_lifecycle_event, None)
            self.using_domain_events = True
            logging.debug("Using domain events")
        except Exception, e:
            self.using_domain_events = False
            logging.debug("Error registering domain events: %s", e)

        try:
            self._network_cb_id = self.get_backend().networkEventRegisterAny(
                None, libvirt.VIR_NETWORK_EVENT_ID_LIFECYCLE,
                self._network_lifecycle_event, None)
            self.using_network_events = True
            logging.debug("Using network events")
        except Exception, e:
            self.using_network_events = False
            logging.debug("Error registering network events: %s", e)


    ####################
    # Update listeners #
    ####################

    def _nodedev_mediadev_added(self, ignore1, name):
        if name in self.mediadevs:
            return

        vobj = self.get_nodedev(name)
        mediadev = vmmMediaDevice.mediadev_from_nodedev(vobj)
        if not mediadev:
            return

        self.mediadevs[name] = mediadev
        self.emit("mediadev-added", mediadev)

    def _nodedev_mediadev_removed(self, ignore1, name):
        if name not in self.mediadevs:
            return

        self.mediadevs[name].cleanup()
        del(self.mediadevs[name])
        self.emit("mediadev-removed", name)


    ######################################
    # Connection closing/opening methods #
    ######################################

    def get_autoconnect(self):
        return self.config.get_conn_autoconnect(self.get_uri())
    def set_autoconnect(self, val):
        self.config.set_conn_autoconnect(self.get_uri(), val)

    def close(self):
        def cleanup(devs):
            for dev in devs.values():
                dev.cleanup()

        if self._backend:
            if self._domain_cb_id is None:
                self._backend.domainEventDeregisterAny(self._domain_cb_id)
            self._domain_cb_id = None

            if self._network_cb_id is None:
                self._backend.networkEventDeregisterAny(self._network_cb_id)
            self._network_cb_id = None

        self._backend.close()
        self.record = []

        cleanup(self.nodedevs)
        self.nodedevs = {}

        cleanup(self.netdevs)
        self.netdevs = {}

        cleanup(self.mediadevs)
        self.mediadevs = {}

        cleanup(self.interfaces)
        self.interfaces = {}

        cleanup(self.pools)
        self.pools = {}

        cleanup(self.nets)
        self.nets = {}

        cleanup(self.vms)
        self.vms = {}

        self._change_state(self.STATE_DISCONNECTED)

    def _cleanup(self):
        self.close()
        self.connectError = None

    def open(self, sync=False):
        if self.state != self.STATE_DISCONNECTED:
            return

        self.connectError = None
        self._change_state(self.STATE_CONNECTING)

        if sync:
            logging.debug("Opening connection synchronously: %s",
                          self.get_uri())
            self._open_thread()
        else:
            logging.debug("Scheduling background open thread for " +
                         self.get_uri())
            self.connectThread = threading.Thread(target=self._open_thread,
                                            name="Connect %s" % self.get_uri())
            self.connectThread.setDaemon(True)
            self.connectThread.start()

    def _do_creds_password(self, creds):
        try:
            return connectauth.creds_dialog(creds)
        except Exception, e:
            # Detailed error message, in English so it can be Googled.
            self.connectError = (
                "Failed to get credentials for '%s':\n%s\n%s" %
                (self.get_uri(), str(e), "".join(traceback.format_exc())))
            return -1

    def _open_thread(self):
        logging.debug("Background 'open connection' thread is running")

        while True:
            libexc = None
            exc = None
            tb = None
            warnconsole = False
            try:
                self._backend.open(self._do_creds_password)
            except libvirt.libvirtError, libexc:
                tb = "".join(traceback.format_exc())
            except Exception, exc:
                tb = "".join(traceback.format_exc())

            if libexc:
                exc = libexc

            if not exc:
                self.state = self.STATE_ACTIVE
                break

            self.state = self.STATE_DISCONNECTED

            if (libexc and
                (libexc.get_error_code() ==
                 getattr(libvirt, "VIR_ERR_AUTH_CANCELLED", None))):
                logging.debug("User cancelled auth, not raising any error.")
                break

            if (libexc and
                libexc.get_error_code() == libvirt.VIR_ERR_AUTH_FAILED and
                "not authorized" in libexc.get_error_message().lower()):
                logging.debug("Looks like we might have failed policykit "
                              "auth. Checking to see if we have a valid "
                              "console session")
                if (not self.is_remote() and
                    not connectauth.do_we_have_session()):
                    warnconsole = True

            if (libexc and
                libexc.get_error_code() == libvirt.VIR_ERR_AUTH_FAILED and
                "GSSAPI Error" in libexc.get_error_message() and
                "No credentials cache found" in libexc.get_error_message()):
                if connectauth.acquire_tgt():
                    continue

            self.connectError = (str(exc), tb, warnconsole)
            break

        # We want to kill off this thread asap, so schedule an
        # idle event to inform the UI of result
        logging.debug("Background open thread complete, scheduling notify")
        self.idle_add(self._open_notify)
        self.connectThread = None

    def _open_notify(self):
        logging.debug("Notifying open result")

        self.idle_emit("state-changed")

        if self.state == self.STATE_ACTIVE:
            logging.debug("libvirt version=%s",
                          self._backend.local_libvirt_version())
            logging.debug("daemon version=%s",
                          self._backend.daemon_version())
            logging.debug("conn version=%s", self._backend.conn_version())
            logging.debug("%s capabilities:\n%s",
                          self.get_uri(), self.caps.xml)
            self._add_conn_events()
            self.schedule_priority_tick(stats_update=True,
                                        pollvm=True, pollnet=True,
                                        pollpool=True, polliface=True,
                                        pollnodedev=True, pollmedia=True,
                                        force=True)

        if self.state == self.STATE_DISCONNECTED:
            if self.connectError:
                self.idle_emit("connect-error", *self.connectError)
            self.connectError = None


    #######################
    # Tick/Update methods #
    #######################

    def _update_nets(self, dopoll):
        if not dopoll or not self.is_network_capable():
            return {}, {}, self.nets
        return pollhelpers.fetch_nets(self._backend, self.nets.copy(),
                    (lambda obj, key: vmmNetwork(self, obj, key)))

    def _update_pools(self, dopoll):
        if not dopoll or not self.is_storage_capable():
            return {}, {}, self.pools
        return pollhelpers.fetch_pools(self._backend, self.pools.copy(),
                    (lambda obj, key: vmmStoragePool(self, obj, key)))

    def _update_interfaces(self, dopoll):
        if not dopoll or not self.is_interface_capable():
            return {}, {}, self.interfaces
        return pollhelpers.fetch_interfaces(self._backend,
                    self.interfaces.copy(),
                    (lambda obj, key: vmmInterface(self, obj, key)))

    def _update_nodedevs(self, dopoll):
        if not dopoll or not self.is_nodedev_capable():
            return {}, {}, self.nodedevs
        return pollhelpers.fetch_nodedevs(self._backend, self.nodedevs.copy(),
                    (lambda obj, key: vmmNodeDevice(self, obj, key)))

    def _update_vms(self, dopoll):
        if not dopoll:
            return {}, {}, self.vms
        return pollhelpers.fetch_vms(self._backend, self.vms.copy(),
                    (lambda obj, key: vmmDomain(self, obj, key)))


    def _obj_signal_proxy(self, obj, signal, key):
        ignore = obj
        self.emit(signal, key)

    def schedule_priority_tick(self, **kwargs):
        # args/kwargs are what is passed to def tick()
        if "stats_update" not in kwargs:
            kwargs["stats_update"] = False
        self.idle_emit("priority-tick", kwargs)

    def tick(self, stats_update,
             pollvm=False, pollnet=False,
             pollpool=False, polliface=False,
             pollnodedev=False, pollmedia=False,
             force=False):
        """
        main update function: polls for new objects, updates stats, ...
        @force: Perform the requested polling even if async events are in use
        """
        if self.state != self.STATE_ACTIVE:
            return

        if not pollvm:
            stats_update = False

        if self.using_domain_events and not force:
            pollvm = False
        if self.using_network_events and not force:
            pollnet = False

        self.hostinfo = self._backend.getInfo()

        (goneNets, newNets, nets) = self._update_nets(pollnet)
        (gonePools, newPools, pools) = self._update_pools(pollpool)
        (goneInterfaces,
         newInterfaces, interfaces) = self._update_interfaces(polliface)
        (goneNodedevs,
         newNodedevs, nodedevs) = self._update_nodedevs(pollnodedev)
        (goneVMs, newVMs, vms) = self._update_vms(pollvm)

        def tick_send_signals():
            """
            Responsible for signaling the UI for any updates. All possible UI
            updates need to go here to enable threading that doesn't block the
            app with long tick operations.
            """
            # Connection closed out from under us
            if not self._backend.is_open():
                return

            self.vms = vms
            self.nodedevs = nodedevs
            self.interfaces = interfaces
            self.pools = pools
            self.nets = nets

            # Make sure device polling is setup
            if not self.netdev_initialized:
                self._init_netdev()

            if not self.mediadev_initialized:
                self._init_mediadev()

            # Update VM states
            for uuid, obj in goneVMs.items():
                self.emit("vm-removed", uuid)
                obj.cleanup()
            for uuid, obj in newVMs.items():
                ignore = obj
                self.emit("vm-added", uuid)

            # Update virtual network states
            for uuid, obj in goneNets.items():
                self.emit("net-removed", uuid)
                obj.cleanup()
            for uuid, obj in newNets.items():
                obj.connect("started", self._obj_signal_proxy,
                            "net-started", uuid)
                obj.connect("stopped", self._obj_signal_proxy,
                            "net-stopped", uuid)
                self.emit("net-added", uuid)

            # Update storage pool states
            for uuid, obj in gonePools.items():
                self.emit("pool-removed", uuid)
                obj.cleanup()
            for uuid, obj in newPools.items():
                obj.connect("started", self._obj_signal_proxy,
                            "pool-started", uuid)
                obj.connect("stopped", self._obj_signal_proxy,
                            "pool-stopped", uuid)
                self.emit("pool-added", uuid)

            # Update interface states
            for name, obj in goneInterfaces.items():
                self.emit("interface-removed", name)
                obj.cleanup()
            for name, obj in newInterfaces.items():
                obj.connect("started", self._obj_signal_proxy,
                            "interface-started", name)
                obj.connect("stopped", self._obj_signal_proxy,
                            "interface-stopped", name)
                self.emit("interface-added", name)

            # Update nodedev list
            for name in goneNodedevs:
                self.emit("nodedev-removed", name)
                goneNodedevs[name].cleanup()
            for name in newNodedevs:
                self.emit("nodedev-added", name)

        self.idle_add(tick_send_signals)

        ticklist = []
        def add_to_ticklist(l, args=()):
            ticklist.extend([(o, args) for o in l])

        updateVMs = newVMs
        if stats_update:
            updateVMs = vms

        if stats_update:
            for key in vms:
                if key in updateVMs:
                    add_to_ticklist([vms[key]], (True,))
                else:
                    add_to_ticklist([vms[key]], (stats_update,))
        if pollnet:
            add_to_ticklist(nets.values())
        if pollpool:
            add_to_ticklist(pools.values())
        if polliface:
            add_to_ticklist(interfaces.values())
        if pollnodedev:
            add_to_ticklist(nodedevs.values())
        if pollmedia:
            add_to_ticklist(self.mediadevs.values())

        for obj, args in ticklist:
            try:
                obj.tick(*args)
            except Exception, e:
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
            self._recalculate_stats(updateVMs.values())
            self.idle_emit("resources-sampled")

        return 1

    def _recalculate_stats(self, vms):
        if not self._backend.is_open():
            return

        now = time.time()
        expected = self.config.get_stats_history_length()
        current = len(self.record)
        if current > expected:
            del self.record[expected:current]

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

        if len(self.record) > 0:
            prevTimestamp = self.record[0]["timestamp"]
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
            "diskRdRate" : rdRate,
            "diskWrRate" : wrRate,
            "netRxRate" : rxRate,
            "netTxRate" : txRate,
            "diskMaxRate" : diskMaxRate,
            "netMaxRate" : netMaxRate,
        }

        self.record.insert(0, newStats)


    ########################
    # Stats getter methods #
    ########################

    def _vector_helper(self, record_name):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length() + 1):
            if i < len(stats):
                vector.append(stats[i][record_name] / 100.0)
            else:
                vector.append(0)
        return vector

    def stats_memory_vector(self):
        return self._vector_helper("memoryPercent")

    def host_cpu_time_vector(self):
        return self._vector_helper("cpuHostPercent")
    guest_cpu_time_vector = host_cpu_time_vector

    def host_cpu_time_vector_limit(self, limit):
        cpudata = self.host_cpu_time_vector()
        if len(cpudata) > limit:
            cpudata = cpudata[0:limit]
        return cpudata
    guest_cpu_time_vector_limit = host_cpu_time_vector_limit

    def disk_io_vector_limit(self, ignore):
        return [0.0]
    def network_traffic_vector_limit(self, ignore):
        return [0.0]

    def _get_record_helper(self, record_name):
        if len(self.record) == 0:
            return 0
        return self.record[0][record_name]

    def stats_memory(self):
        return self._get_record_helper("memory")
    def pretty_stats_memory(self):
        return util.pretty_mem(self.stats_memory())

    def host_cpu_time_percentage(self):
        return self._get_record_helper("cpuHostPercent")
    guest_cpu_time_percentage = host_cpu_time_percentage

    def network_rx_rate(self):
        return self._get_record_helper("netRxRate")
    def network_tx_rate(self):
        return self._get_record_helper("netTxRate")
    def network_traffic_rate(self):
        return self.network_tx_rate() + self.network_rx_rate()
    def network_traffic_max_rate(self):
        return self._get_record_helper("netMaxRate")

    def disk_read_rate(self):
        return self._get_record_helper("diskRdRate")
    def disk_write_rate(self):
        return self._get_record_helper("diskWrRate")
    def disk_io_rate(self):
        return self.disk_read_rate() + self.disk_write_rate()
    def disk_io_max_rate(self):
        return self._get_record_helper("diskMaxRate")
