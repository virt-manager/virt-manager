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
import os
import re
import socket
import threading
import time
import traceback

import libvirt
import virtinst

from virtManager import util
from virtManager import connectauth
from virtManager.baseclass import vmmGObject
from virtManager.domain import vmmDomain
from virtManager.interface import vmmInterface
from virtManager.mediadev import vmmMediaDevice
from virtManager.netdev import vmmNetDevice
from virtManager.network import vmmNetwork
from virtManager.nodedev import vmmNodeDevice
from virtManager.storagepool import vmmStoragePool

def _is_virtinst_test_uri(uri):
    try:
        from virtinst import cli
        return bool(cli._is_virtinst_test_uri(uri))
    except:
        return False


class vmmConnection(vmmGObject):

    STATE_DISCONNECTED = 0
    STATE_CONNECTING = 1
    STATE_ACTIVE = 2
    STATE_INACTIVE = 3

    def __init__(self, uri, readOnly=False):
        vmmGObject.__init__(self)

        self._uri = uri
        if self._uri is None or self._uri.lower() == "xen":
            self._uri = "xen:///"

        self.readOnly = readOnly
        self.state = self.STATE_DISCONNECTED
        self.connectThread = None
        self.connectError = None
        self._ticklock = threading.Lock()
        self.vmm = None

        self._caps = None
        self._caps_xml = None
        self._is_virtinst_test_uri = _is_virtinst_test_uri(self._uri)

        self.network_capable = None
        self._storage_capable = None
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
        # Resource utilization statistics
        self.record = []
        self.hostinfo = None

        self.hal_helper_remove_sig = None
        self.hal_handles = []

        self.netdev_initialized = False
        self.netdev_error = ""
        self.netdev_use_libvirt = False

        self.mediadev_initialized = False
        self.mediadev_error = ""
        self.mediadev_use_libvirt = False

    #################
    # Init routines #
    #################

    def _set_hal_remove_sig(self, hal_helper):
        if not self.hal_helper_remove_sig:
            sig = hal_helper.connect("device-removed",
                                     self._haldev_removed)
            self.hal_helper_remove_sig = sig
            self.hal_handles.append(sig)

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
        elif self.get_hal_helper():
            hal_helper = self.get_hal_helper()

            if self.is_remote():
                self.netdev_error = _("Libvirt version does not support "
                                      "physical interface listing")

            else:
                error = hal_helper.get_init_error()
                if not error:
                    self.hal_handles.append(
                        hal_helper.connect("netdev-added", self._netdev_added))
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
                    self.hal_handles.append(
                      hal_helper.connect("optical-added", self._optical_added))
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
        return self._uri

    def invalidate_caps(self):
        self._caps_xml = None
        self._caps = None

    def _check_caps(self):
        if not (self._caps_xml or self._caps):
            self._caps_xml = self.vmm.getCapabilities()
            self._caps = virtinst.CapabilitiesParser.parse(self._caps_xml)

    def get_capabilities_xml(self):
        if not self._caps_xml:
            self._check_caps()
        return self._caps_xml

    def get_capabilities(self):
        if not self._caps:
            self._check_caps()
        return self._caps

    def get_max_vcpus(self, _type=None):
        return virtinst.util.get_max_vcpus(self.vmm, _type)

    def get_host_info(self):
        return self.hostinfo

    def pretty_host_memory_size(self):
        if self.vmm is None:
            return ""
        return util.pretty_mem(self.host_memory_size())

    def host_memory_size(self):
        if self.vmm is None:
            return 0
        return self.hostinfo[1] * 1024

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
        if virtinst.support.check_conn_support(self.vmm,
                                virtinst.support.SUPPORT_CONN_GETHOSTNAME):
            return self.vmm.getHostname()

        uri_hostname = self.get_uri_hostname()
        if self.is_remote() and uri_hostname.lower() != "localhost":
            return uri_hostname

        # This can throw an exception, so beware when calling!
        return socket.gethostbyaddr(socket.gethostname())[0]

    def get_uri_hostname(self):
        return virtinst.util.get_uri_hostname(self.get_uri())

    def get_short_hostname(self):
        hostname = self.get_hostname()
        offset = hostname.find(".")
        if offset > 0 and not hostname[0].isdigit():
            return hostname[0:offset]
        return hostname

    def get_hostname(self, resolveLocal=False):
        ignore = resolveLocal
        try:
            return self.get_qualified_hostname()
        except:
            return self.get_uri_hostname()

    def get_transport(self):
        return virtinst.util.get_uri_transport(self.get_uri())

    def get_driver(self):
        return virtinst.util.get_uri_driver(self.get_uri())

    def is_local(self):
        return bool(self.get_uri_hostname() == "localhost")

    def is_container(self):
        return self.is_lxc() or self.is_openvz()

    def is_lxc(self):
        if self._is_virtinst_test_uri:
            self.get_uri().count(",lxc")

        return virtinst.util.uri_split(self.get_uri())[0].startswith("lxc")

    def is_openvz(self):
        return virtinst.util.uri_split(self.get_uri())[0].startswith("openvz")

    def is_xen(self):
        if self._is_virtinst_test_uri:
            return self.get_uri().count(",xen")

        scheme = virtinst.util.uri_split(self.get_uri())[0]
        return scheme.startswith("xen")

    def is_qemu(self):
        if self._is_virtinst_test_uri:
            return self.get_uri().count(",qemu")

        scheme = virtinst.util.uri_split(self.get_uri())[0]
        return scheme.startswith("qemu")

    def is_remote(self):
        return virtinst.util.is_uri_remote(self.get_uri())

    def is_qemu_system(self):
        (scheme, ignore, ignore,
         path, ignore, ignore) = virtinst.util.uri_split(self.get_uri())
        if path == "/system" and scheme.startswith("qemu"):
            return True
        return False

    def is_qemu_session(self):
        (scheme, ignore, ignore,
         path, ignore, ignore) = virtinst.util.uri_split(self.get_uri())
        if path == "/session" and scheme.startswith("qemu"):
            return True
        return False

    def is_test_conn(self):
        (scheme, ignore, ignore,
         ignore, ignore, ignore) = virtinst.util.uri_split(self.get_uri())
        if scheme.startswith("test"):
            return True
        return False

    def is_session_uri(self):
        path = virtinst.util.uri_split(self.get_uri())[3]
        return path == "/session"

    # Connection capabilities debug helpers
    def rhel6_defaults(self, emulator):
        if not self.is_qemu_system():
            return True
        if not str(emulator).startswith("/usr/libexec"):
            return True
        return self.config.rhel6_defaults

    def rhel6_defaults_caps(self):
        caps = self.get_capabilities()
        for guest in caps.guests:
            for dom in guest.domains:
                if dom.emulator.startswith("/usr/libexec"):
                    return self.config.rhel6_defaults
        return True

    def is_kvm_supported(self):
        return self.get_capabilities().is_kvm_available()

    def no_install_options(self):
        return self.get_capabilities().no_install_options()

    def hw_virt_supported(self):
        return self.get_capabilities().hw_virt_supported()

    def is_bios_virt_disabled(self):
        return self.get_capabilities().is_bios_virt_disabled()

    # Connection pretty print routines

    def _get_pretty_desc(self, active, shorthost, show_trans):
        def match_whole_string(orig, reg):
            match = re.match(reg, orig)
            if not match:
                return False

            return ((match.end() - match.start()) == len(orig))

        def is_ip_addr(orig):
            return match_whole_string(orig, "[0-9.]+")

        (scheme, username, hostname,
         path, ignore, ignore) = virtinst.util.uri_split(self.get_uri())

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

        if hv == "QEMU" and active and self.is_kvm_supported():
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

        return "%s (%s)" % (rest, hv)

    def get_pretty_desc_inactive(self, shorthost=True, transport=False):
        return self._get_pretty_desc(False, shorthost, transport)

    def get_pretty_desc_active(self, shorthost=True, transport=False):
        return self._get_pretty_desc(True, shorthost, transport)


    #######################
    # API support helpers #
    #######################

    def is_storage_capable(self):
        if self._storage_capable == None:
            self._storage_capable = virtinst.util.is_storage_capable(self.vmm)
            if self._storage_capable is False:
                logging.debug("Connection doesn't seem to support storage "
                              "APIs. Skipping all storage polling.")
            else:
                # Try to create the default storage pool
                try:
                    util.build_default_pool(self)
                except Exception, e:
                    logging.debug("Building default pool failed: %s", str(e))

        return self._storage_capable

    def is_network_capable(self):
        if self.network_capable == None:
            self.network_capable = virtinst.support.check_conn_support(
                                       self.vmm,
                                       virtinst.support.SUPPORT_CONN_NETWORK)
            if self.network_capable is False:
                logging.debug("Connection doesn't seem to support network "
                              "APIs. Skipping all network polling.")

        return self.network_capable

    def is_interface_capable(self):
        if self.interface_capable == None:
            self.interface_capable = virtinst.support.check_conn_support(
                                       self.vmm,
                                       virtinst.support.SUPPORT_CONN_INTERFACE)
            if self.interface_capable is False:
                logging.debug("Connection doesn't seem to support interface "
                              "APIs. Skipping all interface polling.")

        return self.interface_capable

    def is_nodedev_capable(self):
        if self._nodedev_capable == None:
            self._nodedev_capable = virtinst.NodeDeviceParser.is_nodedev_capable(self.vmm)
        return self._nodedev_capable

    def _get_flags_helper(self, obj, key, check_func):
        ignore = obj
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
            logging.debug("Connection managed save support: %s", val)
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
            vdev = dev.get_virtinst_obj()
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

    def rename_vm(self, domainobj, origxml, newxml):
        # Undefine old domain
        domainobj.delete()

        newobj = None
        try:
            try:
                # Redefine new domain
                newobj = self.define_domain(newxml)
            except Exception, renameerr:
                try:
                    logging.exception("Error defining new name XML")
                    newobj = self.define_domain(origxml)
                except Exception, fixerr:
                    logging.exception("Failed to redefine original domain!")
                    raise RuntimeError(
                        _("Domain rename failed. Attempting to recover also "
                          "failed.\n\n"
                          "Original error: %s\n\n"
                          "Recover error: %s" %
                          (str(renameerr), str(fixerr))))
                raise
        finally:
            if newobj:
                # Reinsert handle into new domain
                domainobj.change_name_backend(newobj)

    def define_domain(self, xml):
        return self.vmm.defineXML(xml)
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
            logging.debug("Couldn't remove save file '%s' used for restore",
                          frm)

    ####################
    # Update listeners #
    ####################

    # Generic media device helpers
    def _remove_mediadev(self, key):
        self.mediadevs[key].cleanup()
        del(self.mediadevs[key])
        self.emit("mediadev-removed", key)
    def _add_mediadev(self, key, dev):
        self.mediadevs[key] = dev
        self.emit("mediadev-added", dev)

    def _haldev_removed(self, ignore, hal_path):
        # Physical net device
        for name, obj in self.netdevs.items():
            if obj.get_hal_path() == hal_path:
                self.netdevs[name].cleanup()
                del self.netdevs[name]
                return

        for key, obj in self.mediadevs.items():
            if key == hal_path:
                self._remove_mediadev(key)

    def _netdev_added(self, ignore, netdev):
        name = netdev.get_name()
        if name in self.netdevs:
            return

        self.netdevs[name] = netdev

    # Optical HAL listener
    def _optical_added(self, ignore, dev):
        key = dev.get_key()
        if key in self.mediadevs:
            return

        self._add_mediadev(key, dev)

    def _nodedev_mediadev_added(self, ignore1, name):
        if name in self.mediadevs:
            return

        vobj = self.get_nodedev(name)
        mediadev = vmmMediaDevice.mediadev_from_nodedev(vobj)
        if not mediadev:
            return

        self._add_mediadev(name, mediadev)

    def _nodedev_mediadev_removed(self, ignore1, name):
        if name not in self.mediadevs:
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
        def cleanup(devs):
            for dev in devs.values():
                dev.cleanup()

        self.vmm = None
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

        hal_helper = self.get_hal_helper(init=False)
        if hal_helper:
            for h in self.hal_handles:
                hal_helper.disconnect(h)

    def _open_dev_conn(self, uri):
        """
        Allow using virtinsts connection hacking to fake capabilities
        and other reproducible/testable behavior
        """
        if not self._is_virtinst_test_uri:
            return

        try:
            from virtinst import cli
            return cli._open_test_uri(uri)
        except:
            logging.exception("Trouble opening test URI")
        return

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

    def _do_creds(self, creds, cbdata):
        """
        Generic libvirt openAuth callback
        """
        ignore = cbdata
        try:
            if (len(creds) == 1 and
                creds[0][0] == libvirt.VIR_CRED_EXTERNAL and
                creds[0][2] == "PolicyKit"):
                return connectauth.creds_polkit(creds[0][1])

            for cred in creds:
                if cred[0] == libvirt.VIR_CRED_EXTERNAL:
                    return -1

            return connectauth.creds_dialog(creds)
        except Exception, e:
            # Detailed error message, in English so it can be Googled.
            self.connectError = (
                "Failed to get credentials for '%s':\n%s\n%s" %
                (self.get_uri(), str(e), "".join(traceback.format_exc())))
            return -1

    def _try_open(self):
        flags = 0

        vmm = self._open_dev_conn(self.get_uri())
        if vmm:
            return vmm

        if self.readOnly:
            logging.info("Caller requested read only connection")
            flags = libvirt.VIR_CONNECT_RO

        if virtinst.support.support_openauth():
            vmm = libvirt.openAuth(self.get_uri(),
                                   [[libvirt.VIR_CRED_AUTHNAME,
                                     libvirt.VIR_CRED_PASSPHRASE,
                                     libvirt.VIR_CRED_EXTERNAL],
                                    self._do_creds, None],
                                   flags)
        else:
            if flags:
                vmm = libvirt.openReadOnly(self.get_uri())
            else:
                vmm = libvirt.open(self.get_uri())

        return vmm

    def _open_thread(self):
        logging.debug("Background 'open connection' thread is running")

        while True:
            libexc = None
            exc = None
            tb = None
            warnconsole = False
            try:
                self.vmm = self._try_open()
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
            caps = self.get_capabilities_xml()
            logging.debug("%s capabilities:\n%s",
                          self.get_uri(), caps)

            self.tick()
            # If VMs disappeared since the last time we connected to
            # this uri, remove their gconf entries so we don't pollute
            # the database
            self.config.reconcile_vm_entries(self.get_uri(),
                                             self.vms.keys())

        if self.state == self.STATE_DISCONNECTED:
            if self.connectError:
                self.idle_emit("connect-error", *self.connectError)
            self.connectError = None


    #######################
    # Tick/Update methods #
    #######################

    def _poll_helper(self,
                     origlist, typename, check_support,
                     active_list, inactive_list,
                     lookup_func, build_class):
        current = {}
        start = []
        stop = []
        new = []
        newActiveNames = []
        newInactiveNames = []

        if not check_support():
            return (stop, start, origlist, new, current)

        try:
            newActiveNames = active_list()
        except Exception, e:
            logging.debug("Unable to list active %ss: %s", typename, e)
        try:
            newInactiveNames = inactive_list()
        except Exception, e:
            logging.debug("Unable to list inactive %ss: %s", typename, e)

        def check_obj(key, is_active):
            if key not in origlist:
                try:
                    obj = lookup_func(key)
                except Exception, e:
                    logging.debug("Could not fetch %s '%s': %s",
                                  typename, key, e)
                    return

                # Object is brand new this tick period
                current[key] = build_class(self, obj, key, is_active)
                new.append(key)

                if is_active:
                    start.append(key)
            else:
                # Previously known object, see if it changed state
                current[key] = origlist[key]

                if current[key].is_active() != is_active:
                    current[key].set_active(is_active)

                    if is_active:
                        start.append(key)
                    else:
                        stop.append(key)

                del origlist[key]

        for name in newActiveNames:
            try:
                check_obj(name, True)
            except:
                logging.exception("Couldn't fetch active "
                                  "%s '%s'", typename, name)

        for name in newInactiveNames:
            try:
                check_obj(name, False)
            except:
                logging.exception("Couldn't fetch inactive "
                                  "%s '%s'", typename, name)

        return (stop, start, origlist, new, current)

    def _update_nets(self):
        orig = self.nets.copy()
        name = "network"
        active_list = self.vmm.listNetworks
        inactive_list = self.vmm.listDefinedNetworks
        check_support = self.is_network_capable
        lookup_func = self.vmm.networkLookupByName
        build_class = vmmNetwork

        return self._poll_helper(orig, name, check_support,
                                 active_list, inactive_list,
                                 lookup_func, build_class)

    def _update_pools(self):
        orig = self.pools.copy()
        name = "pool"
        active_list = self.vmm.listStoragePools
        inactive_list = self.vmm.listDefinedStoragePools
        check_support = self.is_storage_capable
        lookup_func = self.vmm.storagePoolLookupByName
        build_class = vmmStoragePool

        return self._poll_helper(orig, name, check_support,
                                 active_list, inactive_list,
                                 lookup_func, build_class)

    def _update_interfaces(self):
        orig = self.interfaces.copy()
        name = "interface"
        active_list = self.vmm.listInterfaces
        inactive_list = self.vmm.listDefinedInterfaces
        check_support = self.is_interface_capable
        lookup_func = self.vmm.interfaceLookupByName
        build_class = vmmInterface

        return self._poll_helper(orig, name, check_support,
                                 active_list, inactive_list,
                                 lookup_func, build_class)


    def _update_nodedevs(self):
        orig = self.nodedevs.copy()
        name = "nodedev"
        active_list = lambda: self.vmm.listDevices(None, 0)
        inactive_list = lambda: []
        check_support = self.is_nodedev_capable
        lookup_func = self.vmm.nodeDeviceLookupByName
        build_class = (lambda conn, obj, key, ignore:
                        vmmNodeDevice(conn, obj, key))

        return self._poll_helper(orig, name, check_support,
                                 active_list, inactive_list,
                                 lookup_func, build_class)

    def _update_vms(self):
        """
        returns lists of changed VM states
        """
        newActiveIDs = []
        newInactiveNames = []
        oldActiveIDs = {}
        oldInactiveNames = {}

        origlist = self.vms.copy()
        current = {}
        new = []

        # Build list of previous vms with proper id/name mappings
        for uuid in origlist:
            vm = origlist[uuid]
            if vm.is_active():
                oldActiveIDs[vm.get_id()] = vm
            else:
                oldInactiveNames[vm.get_name()] = vm

        try:
            newActiveIDs = self.vmm.listDomainsID()
        except Exception, e:
            logging.debug("Unable to list active domains: %s", e)

        try:
            newInactiveNames = self.vmm.listDefinedDomains()
        except Exception, e:
            logging.exception("Unable to list inactive domains: %s", e)

        # NB in these first 2 loops, we go to great pains to
        # avoid actually instantiating a new VM object so that
        # the common case of 'no new/old VMs' avoids hitting
        # XenD too much & thus slowing stuff down.

        def add_vm(vm):
            uuid = vm.get_uuid()

            current[uuid] = vm
            del(origlist[uuid])

        def check_new(rawvm, uuid):
            if uuid in origlist:
                vm = origlist[uuid]
                del(origlist[uuid])
            else:
                vm = vmmDomain(self, rawvm, uuid)
                new.append(uuid)

            current[uuid] = vm

        for _id in newActiveIDs:
            if _id in oldActiveIDs:
                # No change, copy across existing VM object
                vm = oldActiveIDs[_id]
                add_vm(vm)
            else:
                # Check if domain is brand new, or old one that changed state
                try:
                    vm = self.vmm.lookupByID(_id)
                    uuid = util.uuidstr(vm.UUID())

                    check_new(vm, uuid)
                except:
                    logging.exception("Couldn't fetch domain id '%s'", _id)


        for name in newInactiveNames:
            if name in oldInactiveNames:
                # No change, copy across existing VM object
                vm = oldInactiveNames[name]
                add_vm(vm)
            else:
                # Check if domain is brand new, or old one that changed state
                try:
                    vm = self.vmm.lookupByName(name)
                    uuid = util.uuidstr(vm.UUID())

                    check_new(vm, uuid)
                except:
                    logging.exception("Couldn't fetch domain '%s'", name)

        return (new, origlist, current)

    def tick(self, noStatsUpdate=False):
        try:
            self._ticklock.acquire()
            self._tick(noStatsUpdate)
        finally:
            self._ticklock.release()

    def _tick(self, noStatsUpdate=False):
        """ main update function: polls for new objects, updates stats, ..."""
        if self.state != self.STATE_ACTIVE:
            return

        self.hostinfo = self.vmm.getInfo()

        # Poll for new virtual network objects
        (startNets, stopNets, oldNets,
         newNets, self.nets) = self._update_nets()

        # Update pools
        (stopPools, startPools, oldPools,
         newPools, self.pools) = self._update_pools()

        # Update interfaces
        (stopInterfaces, startInterfaces, oldInterfaces,
         newInterfaces, self.interfaces) = self._update_interfaces()

        # Update nodedevice list
        (ignore, ignore, oldNodedevs,
         newNodedevs, self.nodedevs) = self._update_nodedevs()

        # Poll for changed/new/removed VMs
        (newVMs, oldVMs, self.vms) = self._update_vms()

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
                self.emit("vm-removed", uuid)
                oldVMs[uuid].cleanup()
            for uuid in newVMs:
                self.emit("vm-added", uuid)

            # Update virtual network states
            for uuid in oldNets:
                self.emit("net-removed", uuid)
                oldNets[uuid].cleanup()
            for uuid in newNets:
                self.emit("net-added", uuid)
            for uuid in startNets:
                self.emit("net-started", uuid)
            for uuid in stopNets:
                self.emit("net-stopped", uuid)

            # Update storage pool states
            for uuid in oldPools:
                self.emit("pool-removed", uuid)
                oldPools[uuid].cleanup()
            for uuid in newPools:
                self.emit("pool-added", uuid)
            for uuid in startPools:
                self.emit("pool-started", uuid)
            for uuid in stopPools:
                self.emit("pool-stopped", uuid)

            # Update interface states
            for name in oldInterfaces:
                self.emit("interface-removed", name)
                oldInterfaces[name].cleanup()
            for name in newInterfaces:
                self.emit("interface-added", name)
            for name in startInterfaces:
                self.emit("interface-started", name)
            for name in stopInterfaces:
                self.emit("interface-stopped", name)

            # Update nodedev list
            for name in oldNodedevs:
                self.emit("nodedev-removed", name)
                oldNodedevs[name].cleanup()
            for name in newNodedevs:
                self.emit("nodedev-added", name)

        self.idle_add(tick_send_signals)

        # Finally, we sample each domain
        now = time.time()

        updateVMs = self.vms
        if noStatsUpdate:
            updateVMs = newVMs

        for uuid in updateVMs:
            vm = self.vms[uuid]
            try:
                vm.tick(now)
            except Exception, e:
                logging.exception("Tick for VM '%s' failed", vm.get_name())
                if (isinstance(e, libvirt.libvirtError) and
                    (getattr(e, "get_error_code")() ==
                     libvirt.VIR_ERR_SYSTEM_ERROR)):
                    # Try a simple getInfo call to see if conn was dropped
                    self.vmm.getInfo()
                    logging.debug("vm tick raised system error but "
                                  "connection doesn't seem to have dropped. "
                                  "Ignoring.")

        for dev in self.mediadevs.values():
            dev.tick()

        if not noStatsUpdate:
            self._recalculate_stats(now, updateVMs)

            self.idle_emit("resources-sampled")

        return 1

    def _recalculate_stats(self, now, vms):
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
        diskMaxRate = self.disk_io_max_rate() or 10.0
        netMaxRate = self.network_traffic_max_rate() or 10.0

        for uuid in vms:
            vm = vms[uuid]
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

    def host_cpu_time_vector(self):
        return self._vector_helper("cpuHostPercent")
    guest_cpu_time_vector = host_cpu_time_vector
    def stats_memory_vector(self):
        return self._vector_helper("memoryPercent")

    def host_cpu_time_vector_limit(self, limit):
        cpudata = self.host_cpu_time_vector()
        if len(cpudata) > limit:
            cpudata = cpudata[0:limit]
        return cpudata
    guest_cpu_time_vector_limit = host_cpu_time_vector_limit
    def disk_io_vector_limit(self, dummy):
        #No point to accumulate unnormalized I/O for a conenction
        return [0.0]
    def network_traffic_vector_limit(self, dummy):
        #No point to accumulate unnormalized Rx/Tx for a connection
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

    ####################################
    # Per-Connection gconf preferences #
    ####################################

    def config_add_iso_path(self, path):
        self.config.set_perhost(self.get_uri(), self.config.add_iso_path, path)
    def config_get_iso_paths(self):
        return self.config.get_perhost(self.get_uri(),
                                       self.config.get_iso_paths)

vmmGObject.type_register(vmmConnection)
vmmGObject.signal_new(vmmConnection, "vm-added", [str])
vmmGObject.signal_new(vmmConnection, "vm-removed", [str])

vmmGObject.signal_new(vmmConnection, "net-added", [str])
vmmGObject.signal_new(vmmConnection, "net-removed", [str])
vmmGObject.signal_new(vmmConnection, "net-started", [str])
vmmGObject.signal_new(vmmConnection, "net-stopped", [str])

vmmGObject.signal_new(vmmConnection, "pool-added", [str])
vmmGObject.signal_new(vmmConnection, "pool-removed", [str])
vmmGObject.signal_new(vmmConnection, "pool-started", [str])
vmmGObject.signal_new(vmmConnection, "pool-stopped", [str])

vmmGObject.signal_new(vmmConnection, "interface-added", [str])
vmmGObject.signal_new(vmmConnection, "interface-removed", [str])
vmmGObject.signal_new(vmmConnection, "interface-started", [str])
vmmGObject.signal_new(vmmConnection, "interface-stopped", [str])

vmmGObject.signal_new(vmmConnection, "nodedev-added", [str])
vmmGObject.signal_new(vmmConnection, "nodedev-removed", [str])

vmmGObject.signal_new(vmmConnection, "mediadev-added", [object])
vmmGObject.signal_new(vmmConnection, "mediadev-removed", [str])

vmmGObject.signal_new(vmmConnection, "resources-sampled", [])
vmmGObject.signal_new(vmmConnection, "state-changed", [])
vmmGObject.signal_new(vmmConnection, "connect-error", [str, str, bool])
