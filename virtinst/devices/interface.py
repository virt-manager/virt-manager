#
# Copyright 2006-2009, 2013 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os
import random

from .. import util
from .device import Device
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


def _random_mac(conn):
    """Generate a random MAC address.

    00-16-3E allocated to xensource
    52-54-00 used by qemu/kvm

    The OUI list is available at https://standards.ieee.org/regauth/oui/oui.txt.

    The remaining 3 fields are random, with the first bit of the first
    random field set 0.

    @return: MAC address string
    """

    if conn.is_qemu():
        oui = [0x52, 0x54, 0x00]
    else:
        # Xen
        oui = [0x00, 0x16, 0x3E]

    mac = oui + [
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff)]
    return ':'.join(["%02x" % x for x in mac])


def _default_route():
    route_file = "/proc/net/route"
    if not os.path.exists(route_file):
        logging.debug("route_file=%s does not exist", route_file)
        return None

    for line in open(route_file):
        info = line.split()
        if len(info) != 11:
            logging.debug("Unexpected field count=%s when parsing %s",
                          len(info), route_file)
            break

        try:
            route = int(info[1], 16)
            if route == 0:
                return info[0]
        except ValueError:
            continue

    return None


def _default_bridge(conn):
    if "VIRTINST_TEST_SUITE" in os.environ:
        return "eth0"

    if conn.is_remote():
        return None

    dev = _default_route()
    if not dev:
        return None

    # New style peth0 == phys dev, eth0 == bridge, eth0 == default route
    if os.path.exists("/sys/class/net/%s/bridge" % dev):
        return dev

    # Old style, peth0 == phys dev, eth0 == netloop, xenbr0 == bridge,
    # vif0.0 == netloop enslaved, eth0 == default route
    try:
        defn = int(dev[-1])
    except Exception:
        defn = -1

    if (defn >= 0 and
        os.path.exists("/sys/class/net/peth%d/brport" % defn) and
        os.path.exists("/sys/class/net/xenbr%d/bridge" % defn)):
        return "xenbr%d"
    return None


def _default_network(conn):
    ret = _default_bridge(conn)
    if ret:
        return ["bridge", ret]
    return ["network", "default"]


class _VirtualPort(XMLBuilder):
    XML_NAME = "virtualport"

    type = XMLProperty("./@type")
    managerid = XMLProperty("./parameters/@managerid", is_int=True)
    typeid = XMLProperty("./parameters/@typeid", is_int=True)
    typeidversion = XMLProperty("./parameters/@typeidversion", is_int=True)
    instanceid = XMLProperty("./parameters/@instanceid")
    profileid = XMLProperty("./parameters/@profileid")
    interfaceid = XMLProperty("./parameters/@interfaceid")


class DeviceInterface(Device):
    XML_NAME = "interface"

    TYPE_BRIDGE     = "bridge"
    TYPE_VIRTUAL    = "network"
    TYPE_USER       = "user"
    TYPE_VHOSTUSER  = "vhostuser"
    TYPE_ETHERNET   = "ethernet"
    TYPE_DIRECT   = "direct"

    @staticmethod
    def get_models(guest):
        if not guest.os.is_hvm():
            return []

        ret = []
        if guest.type in ["kvm", "qemu", "vz", "test"]:
            ret.append("virtio")
        if guest.os.is_x86():
            if guest.os.is_q35():
                ret.append("e1000e")
            else:
                ret.append("rtl8139")
                ret.append("e1000")
        if guest.type in ["xen", "test"]:
            ret.append("netfront")

        ret.sort()
        return ret

    @staticmethod
    def get_network_type_desc(net_type):
        """
        Return human readable description for passed network type
        """
        desc = net_type.capitalize()

        if net_type == DeviceInterface.TYPE_BRIDGE:
            desc = _("Shared physical device")
        elif net_type == DeviceInterface.TYPE_VIRTUAL:
            desc = _("Virtual networking")
        elif net_type == DeviceInterface.TYPE_USER:
            desc = _("Usermode networking")

        return desc

    @staticmethod
    def generate_mac(conn):
        """
        Generate a random MAC that doesn't conflict with any VMs on
        the connection.
        """
        if conn.fake_conn_predictable():
            # Testing hack
            return "00:11:22:33:44:55"

        for ignore in range(256):
            mac = _random_mac(conn)
            try:
                DeviceInterface.is_conflict_net(conn, mac)
                return mac
            except RuntimeError:
                continue

        logging.debug("Failed to generate non-conflicting MAC")
        return None

    @staticmethod
    def is_conflict_net(conn, searchmac):
        """
        Raise RuntimeError if the passed mac conflicts with a defined VM
        """
        vms = conn.fetch_all_domains()
        for vm in vms:
            for nic in vm.devices.interface:
                nicmac = nic.macaddr or ""
                if nicmac.lower() == searchmac.lower():
                    raise RuntimeError(
                            _("The MAC address '%s' is in use "
                              "by another virtual machine.") % searchmac)


    ###############
    # XML helpers #
    ###############

    def _get_source(self):
        """
        Convenience function, try to return the relevant <source> value
        per the network type.
        """
        if self.type == self.TYPE_VIRTUAL:
            return self._network
        if self.type == self.TYPE_BRIDGE:
            return self._bridge
        if self.type == self.TYPE_DIRECT:
            return self._source_dev
        if self.type == self.TYPE_USER or self.type == self.TYPE_ETHERNET:
            return None
        return self._network or self._bridge or self._source_dev
    def _set_source(self, newsource):
        """
        Convenience function, try to set the relevant <source> value
        per the network type
        """
        self._bridge = None
        self._network = None
        self._source_dev = None

        if self.type == self.TYPE_VIRTUAL:
            self._network = newsource
        elif self.type == self.TYPE_BRIDGE:
            self._bridge = newsource
        elif self.type == self.TYPE_DIRECT:
            self._source_dev = newsource
    source = property(_get_source, _set_source)


    ##################
    # XML properties #
    ##################

    _XML_PROP_ORDER = [
        "_bridge", "_network", "_source_dev", "source_type", "source_path",
        "source_mode", "portgroup", "macaddr", "target_dev", "model",
        "virtualport", "filterref", "rom_bar", "rom_file", "mtu_size"]

    _bridge = XMLProperty("./source/@bridge")
    _network = XMLProperty("./source/@network")
    _source_dev = XMLProperty("./source/@dev")

    virtualport = XMLChildProperty(_VirtualPort, is_single=True)
    type = XMLProperty("./@type")
    trustGuestRxFilters = XMLProperty("./@trustGuestRxFilters", is_yesno=True)

    macaddr = XMLProperty("./mac/@address")

    source_type = XMLProperty("./source/@type")
    source_path = XMLProperty("./source/@path")
    source_mode = XMLProperty("./source/@mode")
    portgroup = XMLProperty("./source/@portgroup")
    model = XMLProperty("./model/@type")
    target_dev = XMLProperty("./target/@dev")
    filterref = XMLProperty("./filterref/@filter")
    link_state = XMLProperty("./link/@state")

    driver_name = XMLProperty("./driver/@name")
    driver_queues = XMLProperty("./driver/@queues", is_int=True)

    rom_bar = XMLProperty("./rom/@bar", is_onoff=True)
    rom_file = XMLProperty("./rom/@file")

    mtu_size = XMLProperty("./mtu/@size", is_int=True)


    #############
    # Build API #
    #############

    def validate(self):
        if not self.macaddr:
            return

        util.validate_macaddr(self.macaddr)
        self.is_conflict_net(self.conn, self.macaddr)

    def set_default_source(self):
        if (self.conn.is_qemu_session() or self.conn.is_test()):
            self.type = self.TYPE_USER
        else:
            self.type, self.source = _default_network(self.conn)


    ##################
    # Default config #
    ##################

    @staticmethod
    def default_model(guest):
        if not guest.os.is_hvm():
            return None
        if guest.supports_virtionet():
            return "virtio"
        if guest.os.is_q35():
            return "e1000e"
        if not guest.os.is_x86():
            return None

        prefs = ["e1000", "rtl8139", "ne2k_pci", "pcnet"]
        supported_models = guest.osinfo.supported_netmodels()
        for pref in prefs:
            if pref in supported_models:
                return pref
        return "e1000"

    def set_defaults(self, guest):
        if not self.type:
            self.type = self.TYPE_BRIDGE
        if not self.macaddr:
            self.macaddr = self.generate_mac(self.conn)
        if self.type == self.TYPE_BRIDGE and not self._bridge:
            self._bridge = _default_bridge(self.conn)
        if self.type == self.TYPE_DIRECT and not self.source_mode:
            self.source_mode = "vepa"
        if not self.model:
            self.model = self.default_model(guest)
