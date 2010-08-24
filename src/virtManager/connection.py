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
import gtk

import logging
import os, sys
import traceback
import re
import threading
from time import time
from socket import gethostbyaddr, gethostname

import dbus
import libvirt
import virtinst

from virtManager import util
from virtManager.domain import vmmDomain
from virtManager.network import vmmNetwork
from virtManager.storagepool import vmmStoragePool
from virtManager.interface import vmmInterface
from virtManager.netdev import vmmNetDevice
from virtManager.mediadev import vmmMediaDevice

class vmmConnection(gobject.GObject):
    __gsignals__ = {
        "vm-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                     [str, str]),
        "vm-started": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                     [str, str]),
        "vm-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                       [str, str]),

        "net-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      [str, str]),
        "net-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                        [str, str]),
        "net-started": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                        [str, str]),
        "net-stopped": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                        [str, str]),

        "pool-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                       [str, str]),
        "pool-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                         [str, str]),
        "pool-started": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                         [str, str]),
        "pool-stopped": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                         [str, str]),

        "interface-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                            [str, str]),
        "interface-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                              [str, str]),
        "interface-started": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                              [str, str]),
        "interface-stopped": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                              [str, str]),

        "nodedev-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                          [str, str]),
        "nodedev-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                            [str, str]),

        "mediadev-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                          [object]),
        "mediadev-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                            [str]),

        "resources-sampled": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                              []),
        "state-changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                          []),
        "connect-error": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                          [str]),
        }

    STATE_DISCONNECTED = 0
    STATE_CONNECTING = 1
    STATE_ACTIVE = 2
    STATE_INACTIVE = 3

    def __init__(self, config, uri, readOnly=None, engine=None):
        self.__gobject_init__()

        self.config = config
        self.engine = engine

        self.connectThread = None
        self.connectThreadEvent = threading.Event()
        self.connectThreadEvent.set()
        self.connectError = None
        self.uri = uri
        if self.uri is None or self.uri.lower() == "xen":
            self.uri = "xen:///"

        self.readOnly = readOnly
        self.state = self.STATE_DISCONNECTED
        self.vmm = None

        self._caps = None
        self._caps_xml = None

        self.network_capable = None
        self.storage_capable = None
        self.interface_capable = None
        self._nodedev_capable = None

        self._xml_flags = {}
        self._support_dict = {}

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
        # Running virtual machines. UUID -> vmmDomain object
        self.activeUUIDs = []
        # Resource utilization statistics
        self.record = []
        self.hostinfo = None

        self.hal_helper_remove_sig = None

        self.netdev_initialized = False
        self.netdev_error = ""
        self.netdev_use_libvirt = False

        self.mediadev_initialized = False
        self.mediadev_error = ""
        self.mediadev_use_libvirt = False

    #################
    # Init routines #
    #################

    def get_hal_helper(self):
        if self.engine:
            return self.engine.get_hal_helper()
        return None

    def _set_hal_remove_sig(self, hal_helper):
        if not self.hal_helper_remove_sig:
            sig = hal_helper.connect("device-removed",
                                     self._haldev_removed)
            self.hal_helper_remove_sig = sig

    def _init_netdev(self):
        """
        Determine how we will be polling for net devices (HAL or libvirt)
        """
        if self.is_nodedev_capable() and self.interface_capable:
            try:
                self._build_libvirt_netdev_list()
                self.netdev_use_libvirt = True
            except Exception, e:
                self.netdev_error = _("Could not build physical interface "
                                      "list via libvirt: %s") % str(e)
        elif self.get_hal_helper():
            hal_helper = self.get_hal_helper()

            if self.is_remote():
                self.netdev_error = _("Libvirt version does not support "
                                      "physical interface listing")

            else:
                error = hal_helper.get_init_error()
                if not error:
                    hal_helper.connect("netdev-added", self._netdev_added)
                    self._set_hal_remove_sig(hal_helper)

                else:
                    self.netdev_error = _("Could not initialize HAL for "
                                          "interface listing: %s") % error
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

        elif self.get_hal_helper():
            hal_helper = self.get_hal_helper()

            if self.is_remote():
                self.mediadev_error = _("Libvirt version does not support "
                                        "media listing.")

            else:
                error = hal_helper.get_init_error()
                if not error:
                    hal_helper.connect("optical-added", self._optical_added)
                    self._set_hal_remove_sig(hal_helper)

                else:
                    self.mediadev_error = _("Could not initialize HAL for "
                                            "media listing: %s") % error
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

    def is_read_only(self):
        return self.readOnly

    def get_uri(self):
        return self.uri

    def _invalidate_caps(self):
        self._caps_xml = None
        self._caps = None

    def _check_caps(self):
        self._caps_xml = self.vmm.getCapabilities()
        self._caps = virtinst.CapabilitiesParser.parse(self._caps_xml)

    def get_capabilities_xml(self):
        xml = None
        while xml == None:
            self._check_caps()
            xml = self._caps_xml

        return xml

    def get_capabilities(self):
        # Make sure we aren't returning None
        caps = None
        while caps == None:
            self._check_caps()
            caps = self._caps

        return caps

    def get_max_vcpus(self, _type=None):
        return virtinst.util.get_max_vcpus(self.vmm, _type)

    def get_host_info(self):
        return self.hostinfo

    def pretty_host_memory_size(self):
        if self.vmm is None:
            return ""
        mem = self.host_memory_size()
        if mem > (10*1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.0f MB" % (mem/1024.0)

    def host_memory_size(self):
        if self.vmm is None:
            return 0
        return self.hostinfo[1]*1024

    def host_architecture(self):
        if self.vmm is None:
            return ""
        return self.hostinfo[0]

    def host_active_processor_count(self):
        if self.vmm is None:
            return 0
        return self.hostinfo[2]

    def host_maximum_processor_count(self):
        if self.vmm is None:
            return 0
        return (self.hostinfo[4] * self.hostinfo[5] *
                self.hostinfo[6] * self.hostinfo[7])

    def connect(self, name, callback, *args):
        handle_id = gobject.GObject.connect(self, name, callback, *args)

        if name == "vm-added":
            for uuid in self.vms.keys():
                self.emit("vm-added", self.uri, uuid)
        elif name == "mediadev-added":
            for dev in self.mediadevs.values():
                self.emit("mediadev-added", dev)
        elif name == "nodedev-added":
            for key in self.nodedevs.keys():
                self.emit("nodedev-added", self.get_uri(), key)

        return handle_id

    ##########################
    # URI + hostname helpers #
    ##########################

    def get_qualified_hostname(self):
        if virtinst.support.check_conn_support(self.vmm,
                                virtinst.support.SUPPORT_CONN_GETHOSTNAME):
            return self.vmm.getHostname()

        uri_hostname = self.get_uri_hostname()
        if self.is_remote() and uri_hostname.lower() != "localhost":
            return uri_hostname

        # This can throw an exception, so beware when calling!
        return gethostbyaddr(gethostname())[0]

    def get_uri_hostname(self):
        return virtinst.util.get_uri_hostname(self.uri)

    def get_short_hostname(self):
        hostname = self.get_hostname()
        offset = hostname.find(".")
        if offset > 0 and not hostname[0].isdigit():
            return hostname[0:offset]
        return hostname

    def get_hostname(self, resolveLocal=False):
        try:
            return self.get_qualified_hostname()
        except:
            return self.get_uri_hostname()

    def get_transport(self):
        return virtinst.util.get_uri_transport(self.uri)

    def get_driver(self):
        return virtinst.util.get_uri_driver(self.uri)

    def is_local(self):
        return bool(self.get_uri_hostname() == "localhost")

    def is_xen(self):
        scheme = virtinst.util.uri_split(self.uri)[0]
        return scheme.startswith("xen")

    def is_qemu(self):
        scheme = virtinst.util.uri_split(self.uri)[0]
        return scheme.startswith("qemu")

    def is_remote(self):
        return virtinst.util.is_uri_remote(self.uri)

    def is_qemu_system(self):
        (scheme, ignore, ignore,
         path, ignore, ignore) = virtinst.util.uri_split(self.uri)
        if path == "/system" and scheme.startswith("qemu"):
            return True
        return False

    def is_qemu_session(self):
        (scheme, ignore, ignore,
         path, ignore, ignore) = virtinst.util.uri_split(self.uri)
        if path == "/session" and scheme.startswith("qemu"):
            return True
        return False

    def is_test_conn(self):
        (scheme, ignore, ignore,
         ignore, ignore, ignore) = virtinst.util.uri_split(self.uri)
        if scheme.startswith("test"):
            return True
        return False

    # Connection capabilities debug helpers
    def is_kvm_supported(self):
        return self.get_capabilities().is_kvm_available()

    def no_install_options(self):
        return self.get_capabilities().no_install_options()

    def hw_virt_supported(self):
        return self.get_capabilities().hw_virt_supported()

    def is_bios_virt_disabled(self):
        return self.get_capabilities().is_bios_virt_disabled()

    # Connection pretty print routines

    def _get_pretty_desc(self, active, shorthost):
        def match_whole_string(orig, reg):
            match = re.match(reg, orig)
            if not match:
                return False

            return ((match.end() - match.start()) == len(orig))

        def is_ip_addr(orig):
            return match_whole_string(orig, "[0-9.]+")

        (scheme, ignore, hostname,
         path, ignore, ignore) = virtinst.util.uri_split(self.uri)

        hv = ""
        rest = ""
        scheme = scheme.split("+")[0]

        if hostname.count(":"):
            hostname = hostname.split(":")[0]

        if hostname:
            if shorthost and not is_ip_addr(hostname):
                rest = hostname.split(".")[0]
            else:
                rest = hostname
        else:
            rest = "localhost"

        if scheme == "qemu":
            hv = "QEMU"
            if active and self.is_kvm_supported():
                hv += "/KVM"
        elif scheme in ('esx', 'gsx'):
            hv = scheme.upper()
        else:
            hv = scheme.capitalize()

        if path and path != "/system" and path != "/":
            if path == "/session":
                hv += " Usermode"
            else:
                hv += " %s" % os.path.basename(path)

        return "%s (%s)" % (rest, hv)

    def get_pretty_desc_inactive(self, shorthost=True):
        return self._get_pretty_desc(False, shorthost)

    def get_pretty_desc_active(self, shorthost=True):
        return self._get_pretty_desc(True, shorthost)


    #######################
    # API support helpers #
    #######################

    def is_storage_capable(self):
        return virtinst.util.is_storage_capable(self.vmm)

    def is_nodedev_capable(self):
        if self._nodedev_capable == None:
            self._nodedev_capable = virtinst.NodeDeviceParser.is_nodedev_capable(self.vmm)
        return self._nodedev_capable

    def _get_flags_helper(self, obj, key, check_func):
        flags_dict = self._xml_flags.get(key)

        if flags_dict == None:
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

            if virtinst.support.check_domain_support(vm,
                                virtinst.support.SUPPORT_DOMAIN_XML_INACTIVE):
                inact = libvirt.VIR_DOMAIN_XML_INACTIVE
            else:
                logging.debug("Domain XML inactive flag not supported.")

            if virtinst.support.check_domain_support(vm,
                                virtinst.support.SUPPORT_DOMAIN_XML_SECURE):
                inact |= libvirt.VIR_DOMAIN_XML_SECURE
                act = libvirt.VIR_DOMAIN_XML_SECURE
            else:
                logging.debug("Domain XML secure flag not supported.")

            return inact, act

        return self._get_flags_helper(vm, key, check_func)

    def get_dom_managedsave_supported(self, vm):
        key = virtinst.support.SUPPORT_DOMAIN_MANAGED_SAVE
        if key not in self._support_dict:
            val = virtinst.support.check_domain_support(vm, key)
            logging.debug("Connection managed save support: %s" % val)
            self._support_dict[key] = val

        return self._support_dict[key]

    def get_interface_flags(self, iface):
        key = "interface"

        def check_func():
            act   = 0
            inact = 0

            if virtinst.support.check_interface_support(iface,
                            virtinst.support.SUPPORT_INTERFACE_XML_INACTIVE):
                inact = libvirt.VIR_INTERFACE_XML_INACTIVE

                # XXX: We intentionally use 'inactive' XML even for active
                # interfaces, since active XML doesn't show much info
                act = inact
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
            if self.is_read_only():
                return _("Active (RO)")
            else:
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

        for nodedev in self.get_devices("net"):
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
    def get_devices(self, devtype=None, devcap=None):
        retdevs = []
        for vdev in self.nodedevs.values():
            if devtype and vdev.device_type != devtype:
                continue

            if devcap:
                if (not hasattr(vdev, "capability_type") or
                    vdev.capability_type != devcap):
                    continue

            retdevs.append(vdev)

        return retdevs

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

    def get_vol_by_path(self, path):
        for pool in self.pools.values():
            for vol in pool.get_volumes().values():
                if vol.get_path() == path:
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

    def create_network(self, xml, start=True, autostart=True):
        # Define network
        net = self.vmm.networkDefineXML(xml)

        try:
            if start:
                net.create()
            net.setAutostart(autostart)
        except:
            net.undefine()
            raise

        return net

    def define_domain(self, xml):
        self.vmm.defineXML(xml)
    def define_interface(self, xml):
        self.vmm.interfaceDefineXML(xml, 0)

    def restore(self, frm):
        self.vmm.restore(frm)
        try:
            # FIXME: This isn't correct in the remote case. Why do we even
            #        do this? Seems like we should provide an option for this
            #        to the user.
            os.remove(frm)
        except:
            logging.debug("Couldn't remove save file '%s' used for restore." %
                          frm)

    ####################
    # Update listeners #
    ####################

    # Generic media device helpers
    def _remove_mediadev(self, key):
        del(self.mediadevs[key])
        self.emit("mediadev-removed", key)
    def _add_mediadev(self, key, dev):
        self.mediadevs[key] = dev
        self.emit("mediadev-added", dev)

    def _haldev_removed(self, ignore, hal_path):
        # Physical net device
        for name, obj in self.netdevs.items():
            if obj.get_hal_path() == hal_path:
                del self.netdevs[name]
                return

        for key, obj in self.mediadevs.items():
            if key == hal_path:
                self._remove_mediadev(key)

    def _netdev_added(self, ignore, netdev):
        name = netdev.get_name()
        if self.netdevs.has_key(name):
            return

        self.netdevs[name] = netdev

    # Optical HAL listener
    def _optical_added(self, ignore, dev):
        key = dev.get_key()
        if self.mediadevs.has_key(key):
            return

        self._add_mediadev(key, dev)

    def _nodedev_mediadev_added(self, ignore1, ignore2, name):
        if self.mediadevs.has_key(name):
            return

        vobj = self.get_nodedev(name)
        mediadev = vmmMediaDevice.mediadev_from_nodedev(self, vobj)
        if not mediadev:
            return

        self._add_mediadev(name, mediadev)

    def _nodedev_mediadev_removed(self, ignore1, ignore2, name):
        if not self.mediadevs.has_key(name):
            return

        self._remove_mediadev(name)

    ######################################
    # Connection closing/opening methods #
    ######################################

    def get_autoconnect(self):
        return self.config.get_conn_autoconnect(self.get_uri())
    def set_autoconnect(self, val):
        self.config.set_conn_autoconnect(self.get_uri(), val)

    def close(self):
        if self.vmm == None:
            return

        self.vmm = None
        self.nets = {}
        self.pools = {}
        self.vms = {}
        self.activeUUIDs = []
        self.record = []
        self._change_state(self.STATE_DISCONNECTED)

    def open(self):
        if self.state != self.STATE_DISCONNECTED:
            return

        self._change_state(self.STATE_CONNECTING)

        logging.debug("Scheduling background open thread for " + self.uri)
        self.connectThreadEvent.clear()
        self.connectThread = threading.Thread(target = self._open_thread,
                                              name = "Connect %s" % self.uri)
        self.connectThread.setDaemon(True)
        self.connectThread.start()

    def _do_creds_polkit(self, action):
        if os.getuid() == 0:
            logging.debug("Skipping policykit check as root")
            return 0
        logging.debug("Doing policykit for %s" % action)

        try:
            bus = dbus.SessionBus()
            # First try to use org.freedesktop.PolicyKit.AuthenticationAgent
            # which is introduced with PolicyKit-0.7
            obj = bus.get_object("org.freedesktop.PolicyKit.AuthenticationAgent", "/")
            pkit = dbus.Interface(obj, "org.freedesktop.PolicyKit.AuthenticationAgent")
            pkit.ObtainAuthorization(action, 0, os.getpid())
        except dbus.exceptions.DBusException, e:
            if e.get_dbus_name() != "org.freedesktop.DBus.Error.ServiceUnknown":
                raise e
            logging.debug("Falling back to org.gnome.PolicyKit")
            # If PolicyKit < 0.7, fallback to org.gnome.PolicyKit
            obj = bus.get_object("org.gnome.PolicyKit", "/org/gnome/PolicyKit/Manager")
            pkit = dbus.Interface(obj, "org.gnome.PolicyKit.Manager")
            pkit.ShowDialog(action, 0)
        return 0

    def _do_creds_dialog(self, creds):
        try:
            gtk.gdk.threads_enter()
            return self._do_creds_dialog_main(creds)
        finally:
            gtk.gdk.threads_leave()

    def _do_creds_dialog_main(self, creds):
        dialog = gtk.Dialog("Authentication required", None, 0,
                            (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                             gtk.STOCK_OK, gtk.RESPONSE_OK))
        label = []
        entry = []

        box = gtk.Table(2, len(creds))
        box.set_border_width(6)
        box.set_row_spacings(6)
        box.set_col_spacings(12)

        row = 0
        for cred in creds:
            if (cred[0] == libvirt.VIR_CRED_AUTHNAME or
                cred[0] == libvirt.VIR_CRED_PASSPHRASE):
                prompt = cred[1]
                if not prompt.endswith(":"):
                    prompt += ":"

                text_label = gtk.Label(prompt)
                text_label.set_alignment(0.0, 0.5)

                label.append(text_label)
            else:
                return -1

            ent = gtk.Entry()
            if cred[0] == libvirt.VIR_CRED_PASSPHRASE:
                ent.set_visibility(False)
            entry.append(ent)

            box.attach(label[row], 0, 1, row, row+1, gtk.FILL, 0, 0, 0)
            box.attach(entry[row], 1, 2, row, row+1, gtk.FILL, 0, 0, 0)
            row = row + 1

        vbox = dialog.get_child()
        vbox.add(box)

        dialog.show_all()
        res = dialog.run()
        dialog.hide()

        if res == gtk.RESPONSE_OK:
            row = 0
            for cred in creds:
                cred[4] = entry[row].get_text()
                row = row + 1
            dialog.destroy()
            return 0
        else:
            dialog.destroy()
            return -1

    def _do_creds(self, creds, cbdata):
        try:
            if (len(creds) == 1 and
                creds[0][0] == libvirt.VIR_CRED_EXTERNAL and
                creds[0][2] == "PolicyKit"):
                return self._do_creds_polkit(creds[0][1])

            for cred in creds:
                if cred[0] == libvirt.VIR_CRED_EXTERNAL:
                    return -1

            return self._do_creds_dialog(creds)
        except Exception, e:
            # Detailed error message, in English so it can be Googled.
            self.connectError = ("Failed to get credentials for '%s':\n%s\n%s"
                                 % (str(self.uri), str(e),
                                    "".join(traceback.format_exc())))
            return -1

    def _acquire_tgt(self):
        logging.debug("In acquire tgt.")
        try:
            bus = dbus.SessionBus()
            ka = bus.get_object('org.gnome.KrbAuthDialog',
                                '/org/gnome/KrbAuthDialog')
            ret = ka.acquireTgt("", dbus_interface='org.gnome.KrbAuthDialog')
        except Exception, e:
            logging.info("Cannot acquire tgt" + str(e))
            ret = False
        return ret

    def _try_open(self):
        try:
            flags = 0
            if self.readOnly:
                logging.info("Caller requested read only connection")
                flags = libvirt.VIR_CONNECT_RO

            if virtinst.support.support_openauth():
                self.vmm = libvirt.openAuth(self.uri,
                                            [[libvirt.VIR_CRED_AUTHNAME,
                                              libvirt.VIR_CRED_PASSPHRASE,
                                              libvirt.VIR_CRED_EXTERNAL],
                                             self._do_creds,
                                             None], flags)
            else:
                if flags:
                    self.vmm = libvirt.openReadOnly(self.uri)
                else:
                    self.vmm = libvirt.open(self.uri)
        except:
            return sys.exc_info()

    def _open_thread(self):
        logging.debug("Background thread is running")

        done = False
        while not done:
            open_error = self._try_open()
            done = True

            if not open_error:
                self.state = self.STATE_ACTIVE
                continue

            self.state = self.STATE_DISCONNECTED
            (_type, value, stacktrace) = open_error

            if (_type == libvirt.libvirtError and
                value.get_error_code() == libvirt.VIR_ERR_AUTH_FAILED and
                "GSSAPI Error" in value.get_error_message() and
                "No credentials cache found" in value.get_error_message()):
                if self._acquire_tgt():
                    done = False
                    continue

            tb = "".join(traceback.format_exception(_type, value, stacktrace))

            self.connectError = "%s\n\n%s" % (str(value), str(tb))

        # We want to kill off this thread asap, so schedule a gobject
        # idle even to inform the UI of result
        logging.debug("Background open thread complete, scheduling notify")
        util.safe_idle_add(self._open_notify)
        self.connectThread = None

    def _open_notify(self):
        logging.debug("Notifying open result")

        try:
            util.safe_idle_add(util.idle_emit, self, "state-changed")

            if self.state == self.STATE_ACTIVE:
                caps = self.get_capabilities_xml()
                logging.debug("%s capabilities:\n%s" %
                              (self.get_uri(), caps))

                self.tick()
                # If VMs disappeared since the last time we connected to
                # this uri, remove their gconf entries so we don't pollute
                # the database
                self.config.reconcile_vm_entries(self.get_uri(),
                                                 self.vms.keys())

            if self.state == self.STATE_DISCONNECTED:
                util.safe_idle_add(util.idle_emit, self, "connect-error",
                                   self.connectError)
                self.connectError = None
        finally:
            self.connectThreadEvent.set()


    #######################
    # Tick/Update methods #
    #######################

    def _update_nets(self):
        """
        Return lists of start/stopped/new networks
        """

        origNets = self.nets
        currentNets = {}
        startNets = []
        stopNets = []
        newNets = []
        newActiveNetNames = []
        newInactiveNetNames = []

        if self.network_capable == None:
            self.network_capable = virtinst.support.check_conn_support(
                                       self.vmm,
                                       virtinst.support.SUPPORT_CONN_NETWORK)
            if self.network_capable is False:
                logging.debug("Connection doesn't seem to support network "
                              "APIs. Skipping all network polling.")

        if not self.network_capable:
            return (stopNets, startNets, origNets, newNets, currentNets)

        try:
            newActiveNetNames = self.vmm.listNetworks()
        except:
            logging.exception("Unable to list active networks")
        try:
            newInactiveNetNames = self.vmm.listDefinedNetworks()
        except:
            logging.exception("Unable to list inactive networks")

        for name in newActiveNetNames:
            try:
                net = self.vmm.networkLookupByName(name)
                uuid = util.uuidstr(net.UUID())
                if not origNets.has_key(uuid):
                    # Brand new network
                    currentNets[uuid] = vmmNetwork(self.config, self, net,
                                                   uuid, True)
                    newNets.append(uuid)
                    startNets.append(uuid)
                else:
                    # Already present network, see if it changed state
                    currentNets[uuid] = origNets[uuid]
                    if not currentNets[uuid].is_active():
                        currentNets[uuid].set_active(True)
                        startNets.append(uuid)
                    del origNets[uuid]
            except:
                logging.exception("Couldn't fetch active network name '%s'" %
                                  name)

        for name in newInactiveNetNames:
            try:
                net = self.vmm.networkLookupByName(name)
                uuid = util.uuidstr(net.UUID())
                if not origNets.has_key(uuid):
                    currentNets[uuid] = vmmNetwork(self.config, self, net,
                                                 uuid, False)
                    newNets.append(uuid)
                else:
                    currentNets[uuid] = origNets[uuid]
                    if currentNets[uuid].is_active():
                        currentNets[uuid].set_active(False)
                        stopNets.append(uuid)
                    del origNets[uuid]
            except:
                logging.exception("Couldn't fetch inactive network name '%s'"
                                  % name)

        return (startNets, stopNets, newNets, origNets, currentNets)

    def _update_pools(self):
        origPools = self.pools
        currentPools = {}
        startPools = []
        stopPools = []
        newPools = []
        newActivePoolNames = []
        newInactivePoolNames = []

        if self.storage_capable == None:
            self.storage_capable = virtinst.util.is_storage_capable(self.vmm)
            if self.storage_capable is False:
                logging.debug("Connection doesn't seem to support storage "
                              "APIs. Skipping all storage polling.")

            else:
                # Try to create the default storage pool
                try:
                    util.build_default_pool(self.vmm)
                except Exception, e:
                    logging.debug("Building default pool failed: %s" % str(e))

        if not self.storage_capable:
            return (stopPools, startPools, origPools, newPools, currentPools)

        try:
            newActivePoolNames = self.vmm.listStoragePools()
        except:
            logging.exception("Unable to list active pools")
        try:
            newInactivePoolNames = self.vmm.listDefinedStoragePools()
        except:
            logging.exception("Unable to list inactive pools")

        for name in newActivePoolNames:
            try:
                pool = self.vmm.storagePoolLookupByName(name)
                uuid = util.uuidstr(pool.UUID())
                if not origPools.has_key(uuid):
                    currentPools[uuid] = vmmStoragePool(self.config, self,
                                                        pool, uuid, True)
                    newPools.append(uuid)
                    startPools.append(uuid)
                else:
                    currentPools[uuid] = origPools[uuid]
                    if not currentPools[uuid].is_active():
                        currentPools[uuid].set_active(True)
                        startPools.append(uuid)
                    del origPools[uuid]
            except:
                logging.exception("Couldn't fetch active pool '%s'" % name)

        for name in newInactivePoolNames:
            try:
                pool = self.vmm.storagePoolLookupByName(name)
                uuid = util.uuidstr(pool.UUID())
                if not origPools.has_key(uuid):
                    currentPools[uuid] = vmmStoragePool(self.config, self,
                                                        pool, uuid, False)
                    newPools.append(uuid)
                else:
                    currentPools[uuid] = origPools[uuid]
                    if currentPools[uuid].is_active():
                        currentPools[uuid].set_active(False)
                        stopPools.append(uuid)
                    del origPools[uuid]
            except:
                logging.exception("Couldn't fetch inactive pool '%s'" % name)
        return (stopPools, startPools, origPools, newPools, currentPools)

    def _update_interfaces(self):
        orig = self.interfaces
        current = {}
        start = []
        stop = []
        new = []
        newActiveNames = []
        newInactiveNames = []

        if self.interface_capable == None:
            self.interface_capable = virtinst.support.check_conn_support(
                                       self.vmm,
                                       virtinst.support.SUPPORT_CONN_INTERFACE)
            if self.interface_capable is False:
                logging.debug("Connection doesn't seem to support interface "
                              "APIs. Skipping all interface polling.")

        if not self.interface_capable:
            return (stop, start, orig, new, current)

        try:
            newActiveNames = self.vmm.listInterfaces()
        except:
            logging.exception("Unable to list active interfaces")
        try:
            newInactiveNames = self.vmm.listDefinedInterfaces()
        except:
            logging.exception("Unable to list inactive interfaces")

        def check_obj(name, is_active):
            key = name

            if not orig.has_key(key):
                obj = self.vmm.interfaceLookupByName(name)
                # Object is brand new this tick period
                current[key] = vmmInterface(self.config, self, obj, key,
                                            is_active)
                new.append(key)

                if is_active:
                    start.append(key)
            else:
                # Previously known object, see if it changed state
                current[key] = orig[key]

                if current[key].is_active() != is_active:
                    current[key].set_active(is_active)

                    if is_active:
                        start.append(key)
                    else:
                        stop.append(key)

                del orig[key]

        for name in newActiveNames:
            try:
                check_obj(name, True)
            except:
                logging.exception("Couldn't fetch active "
                                  "interface '%s'" % name)

        for name in newInactiveNames:
            try:
                check_obj(name, False)
            except:
                logging.exception("Couldn't fetch inactive "
                                  "interface '%s'" % name)

        return (stop, start, orig, new, current)

    def _update_nodedevs(self):
        orig = self.nodedevs
        current = {}
        new = []
        newActiveNames = []

        if self._nodedev_capable == None:
            self._nodedev_capable = self.is_nodedev_capable()
            if self._nodedev_capable is False:
                logging.debug("Connection doesn't seem to support nodedev "
                              "APIs. Skipping all nodedev polling.")

        if not self.is_nodedev_capable():
            return (orig, new, current)

        try:
            newActiveNames = self.vmm.listDevices(None, 0)
        except:
            logging.exception("Unable to list nodedev devices")

        def check_obj(name):
            key = name

            if not orig.has_key(key):
                obj = self.vmm.nodeDeviceLookupByName(name)
                vdev = virtinst.NodeDeviceParser.parse(obj.XMLDesc(0))

                # Object is brand new this tick period
                current[key] = vdev
                new.append(key)

            else:
                # Previously known object, remove it from the orig list
                current[key] = orig[key]
                del orig[key]

        for name in newActiveNames:
            try:
                check_obj(name)
            except:
                logging.exception("Couldn't fetch nodedev '%s'" % name)

        return (orig, new, current)

    def _update_vms(self):
        """
        returns lists of changed VM states
        """

        oldActiveIDs = {}
        oldInactiveNames = {}
        for uuid in self.vms.keys():
            # first pull out all the current inactive VMs we know about
            vm = self.vms[uuid]
            if vm.get_id() == -1:
                oldInactiveNames[vm.get_name()] = vm
        for uuid in self.activeUUIDs:
            # Now get all the vms that were active the last time around
            # and are still active
            vm = self.vms[uuid]
            if vm.get_id() != -1:
                oldActiveIDs[vm.get_id()] = vm

        newActiveIDs = []
        try:
            newActiveIDs = self.vmm.listDomainsID()
        except:
            logging.exception("Unable to list active domains")

        newInactiveNames = []
        try:
            newInactiveNames = self.vmm.listDefinedDomains()
        except:
            logging.exception("Unable to list inactive domains")

        curUUIDs = {}       # new master list of vms
        maybeNewUUIDs = {}  # list of vms that changed state or are brand new
        oldUUIDs = {}       # no longer present vms
        newUUIDs = []       # brand new vms
        startedUUIDs = []   # previously present vms that are now running
        activeUUIDs = []    # all running vms

        # NB in these first 2 loops, we go to great pains to
        # avoid actually instantiating a new VM object so that
        # the common case of 'no new/old VMs' avoids hitting
        # XenD too much & thus slowing stuff down.

        # Filter out active domains which haven't changed
        if newActiveIDs != None:
            for _id in newActiveIDs:
                if oldActiveIDs.has_key(_id):
                    # No change, copy across existing VM object
                    vm = oldActiveIDs[_id]
                    curUUIDs[vm.get_uuid()] = vm
                    activeUUIDs.append(vm.get_uuid())
                else:
                    # May be a new VM, we have no choice but
                    # to create the wrapper so we can see
                    # if its a previously inactive domain.
                    try:
                        vm = self.vmm.lookupByID(_id)
                        uuid = util.uuidstr(vm.UUID())
                        maybeNewUUIDs[uuid] = vm
                        startedUUIDs.append(uuid)
                        activeUUIDs.append(uuid)
                    except:
                        logging.exception("Couldn't fetch domain id '%s'" %
                                          str(_id))

        # Filter out inactive domains which haven't changed
        if newInactiveNames != None:
            for name in newInactiveNames:
                if oldInactiveNames.has_key(name):
                    # No change, copy across existing VM object
                    vm = oldInactiveNames[name]
                    curUUIDs[vm.get_uuid()] = vm
                else:
                    # May be a new VM, we have no choice but
                    # to create the wrapper so we can see
                    # if its a previously inactive domain.
                    try:
                        vm = self.vmm.lookupByName(name)
                        uuid = util.uuidstr(vm.UUID())
                        maybeNewUUIDs[uuid] = vm
                    except:
                        logging.exception("Couldn't fetch domain id '%s'" %
                                          str(id))

        # At this point, maybeNewUUIDs has domains which are
        # either completely new, or changed state.

        # Filter out VMs which merely changed state, leaving
        # only new domains
        for uuid in maybeNewUUIDs.keys():
            rawvm = maybeNewUUIDs[uuid]
            if not(self.vms.has_key(uuid)):
                vm = vmmDomain(self.config, self, rawvm, uuid)
                newUUIDs.append(uuid)
                curUUIDs[uuid] = vm
            else:
                vm = self.vms[uuid]
                vm.set_handle(rawvm)
                curUUIDs[uuid] = vm

        # Finalize list of domains which went away altogether
        for uuid in self.vms.keys():
            vm = self.vms[uuid]
            if not(curUUIDs.has_key(uuid)):
                oldUUIDs[uuid] = vm

        return (startedUUIDs, newUUIDs, oldUUIDs, curUUIDs, activeUUIDs)

    def tick(self, noStatsUpdate=False):
        """ main update function: polls for new objects, updates stats, ..."""
        if self.state != self.STATE_ACTIVE:
            return

        self.hostinfo = self.vmm.getInfo()
        self._invalidate_caps()

        # Poll for new virtual network objects
        (startNets, stopNets, newNets,
         oldNets, self.nets) = self._update_nets()

        # Update pools
        (stopPools, startPools, oldPools,
         newPools, self.pools) = self._update_pools()

        # Update interfaces
        (stopInterfaces, startInterfaces, oldInterfaces,
         newInterfaces, self.interfaces) = self._update_interfaces()

        # Update nodedevice list
        (oldNodedevs, newNodedevs, self.nodedevs) = self._update_nodedevs()

        # Poll for changed/new/removed VMs
        (startVMs, newVMs, oldVMs,
         self.vms, self.activeUUIDs) = self._update_vms()

        def tick_send_signals():
            """
            Responsible for signaling the UI for any updates. All possible UI
            updates need to go here to enable threading that doesn't block the
            app with long tick operations.
            """
            # Connection closed out from under us
            if not self.vmm:
                return

            # Make sure device polling is setup
            if not self.netdev_initialized:
                self._init_netdev()

            if not self.mediadev_initialized:
                self._init_mediadev()

            # Update VM states
            for uuid in oldVMs:
                self.emit("vm-removed", self.uri, uuid)

                # This forces the backing virDomain to be deleted and
                # unreferenced. Not forcing this seems to cause refcount
                # issues, and if the user creates another domain with the
                # same name, libvirt will return the original UUID when
                # requested, causing confusion.
                oldVMs[uuid].release_handle()
            for uuid in newVMs:
                self.emit("vm-added", self.uri, uuid)
            for uuid in startVMs:
                self.emit("vm-started", self.uri, uuid)

            # Update virtual network states
            for uuid in oldNets:
                self.emit("net-removed", self.uri, uuid)
            for uuid in newNets:
                self.emit("net-added", self.uri, uuid)
            for uuid in startNets:
                self.emit("net-started", self.uri, uuid)
            for uuid in stopNets:
                self.emit("net-stopped", self.uri, uuid)

            # Update storage pool states
            for uuid in oldPools:
                self.emit("pool-removed", self.uri, uuid)
            for uuid in newPools:
                self.emit("pool-added", self.uri, uuid)
            for uuid in startPools:
                self.emit("pool-started", self.uri, uuid)
            for uuid in stopPools:
                self.emit("pool-stopped", self.uri, uuid)

            # Update interface states
            for name in oldInterfaces:
                self.emit("interface-removed", self.uri, name)
            for name in newInterfaces:
                self.emit("interface-added", self.uri, name)
            for name in startInterfaces:
                self.emit("interface-started", self.uri, name)
            for name in stopInterfaces:
                self.emit("interface-stopped", self.uri, name)

            # Update nodedev list
            for name in oldNodedevs:
                self.emit("nodedev-removed", self.uri, name)
            for name in newNodedevs:
                self.emit("nodedev-added", self.uri, name)

        util.safe_idle_add(tick_send_signals)

        # Finally, we sample each domain
        now = time()

        updateVMs = self.vms
        if noStatsUpdate:
            updateVMs = newVMs

        for uuid in updateVMs:
            vm = self.vms[uuid]
            try:
                vm.tick(now)
            except libvirt.libvirtError, e:
                if e.get_error_code() == libvirt.VIR_ERR_SYSTEM_ERROR:
                    raise
                logging.exception("Tick for VM '%s' failed" % vm.get_name())
            except Exception, e:
                logging.exception("Tick for VM '%s' failed" % vm.get_name())

        if not noStatsUpdate:
            self._recalculate_stats(now)

            util.safe_idle_add(util.idle_emit, self, "resources-sampled")

        return 1

    def _recalculate_stats(self, now):
        if self.vmm is None:
            return

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

        for uuid in self.vms:
            vm = self.vms[uuid]
            if vm.get_id() != -1:
                cpuTime = cpuTime + vm.cpu_time()
                mem = mem + vm.get_memory()
                rdRate += vm.disk_read_rate()
                wrRate += vm.disk_write_rate()
                rxRate += vm.network_rx_rate()
                txRate += vm.network_tx_rate()

        pcentCpuTime = 0
        if len(self.record) > 0:
            prevTimestamp = self.record[0]["timestamp"]

            pcentCpuTime = (cpuTime) * 100.0 / ((now - prevTimestamp)*1000.0*1000.0*1000.0*self.host_active_processor_count())
            # Due to timing diffs between getting wall time & getting
            # the domain's time, its possible to go a tiny bit over
            # 100% utilization. This freaks out users of the data, so
            # we hard limit it.
            if pcentCpuTime > 100.0:
                pcentCpuTime = 100.0
            # Enforce >= 0 just in case
            if pcentCpuTime < 0.0:
                pcentCpuTime = 0.0

        pcentMem = mem * 100.0 / self.host_memory_size()
        if pcentMem > 100.0:
            pcentMem = 100.0

        newStats = {
            "timestamp": now,
            "memory": mem,
            "memoryPercent": pcentMem,
            "cpuTime": cpuTime,
            "cpuTimePercent": pcentCpuTime,
            "diskRdRate" : rdRate,
            "diskWrRate" : wrRate,
            "netRxRate" : rxRate,
            "netTxRate" : txRate,
        }

        self.record.insert(0, newStats)


    ########################
    # Stats getter methods #
    ########################

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

    def cpu_time_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["cpuTimePercent"]

    def current_memory(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["memory"]

    def pretty_current_memory(self):
        mem = self.current_memory()
        if mem > (10*1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.0f MB" % (mem/1024.0)

    def current_memory_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["memoryPercent"]

    def current_memory_vector(self):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["memoryPercent"]/100.0)
            else:
                vector.append(0)
        return vector

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

    def disk_io_vector_limit(self, dummy):
        """No point to accumulate unnormalized I/O for a conenction"""
        return [ 0.0 ]

    def network_traffic_vector_limit(self, dummy):
        """No point to accumulate unnormalized Rx/Tx for a conenction"""
        return [ 0.0 ]


    ####################################
    # Per-Connection gconf preferences #
    ####################################

    def config_add_iso_path(self, path):
        self.config.set_perhost(self.get_uri(), self.config.add_iso_path, path)
    def config_get_iso_paths(self):
        return self.config.get_perhost(self.get_uri(),
                                       self.config.get_iso_paths)

gobject.type_register(vmmConnection)

