#
# Copyright 2006-2009, 2013 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
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

import logging
import os
import random

from . import util
from .device import VirtualDevice
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


def _random_mac(conn):
    """Generate a random MAC address.

    00-16-3E allocated to xensource
    52-54-00 used by qemu/kvm

    The OUI list is available at http://standards.ieee.org/regauth/oui/oui.txt.

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

    for line in file(route_file):
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
    except:
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

    # FIXME: Check that this exists
    return ["network", "default"]


class VirtualPort(XMLBuilder):
    _XML_ROOT_NAME = "virtualport"

    type = XMLProperty("./@type")
    managerid = XMLProperty("./parameters/@managerid", is_int=True)
    typeid = XMLProperty("./parameters/@typeid", is_int=True)
    typeidversion = XMLProperty("./parameters/@typeidversion", is_int=True)
    instanceid = XMLProperty("./parameters/@instanceid")
    profileid = XMLProperty("./parameters/@profileid")
    interfaceid = XMLProperty("./parameters/@interfaceid")


class VirtualNetworkInterface(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_NET

    TYPE_BRIDGE     = "bridge"
    TYPE_VIRTUAL    = "network"
    TYPE_USER       = "user"
    TYPE_VHOSTUSER  = "vhostuser"
    TYPE_ETHERNET   = "ethernet"
    TYPE_DIRECT   = "direct"
    network_types = [TYPE_BRIDGE, TYPE_VIRTUAL, TYPE_USER, TYPE_ETHERNET,
                     TYPE_DIRECT]

    @staticmethod
    def get_network_type_desc(net_type):
        """
        Return human readable description for passed network type
        """
        desc = net_type.capitalize()

        if net_type == VirtualNetworkInterface.TYPE_BRIDGE:
            desc = _("Shared physical device")
        elif net_type == VirtualNetworkInterface.TYPE_VIRTUAL:
            desc = _("Virtual networking")
        elif net_type == VirtualNetworkInterface.TYPE_USER:
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
            ret = VirtualNetworkInterface.is_conflict_net(conn, mac)
            if ret[1] is None:
                return mac

        logging.debug("Failed to generate non-conflicting MAC")
        return None

    @staticmethod
    def is_conflict_net(conn, searchmac):
        """
        @returns: a two element tuple:
            first element is True if fatal collision occured
            second element is a string description of the collision.

            Non fatal collisions (mac addr collides with inactive guest) will
            return (False, "description of collision")
        """
        if searchmac is None:
            return (False, None)

        vms = conn.fetch_all_guests()
        for vm in vms:
            for nic in vm.get_devices("interface"):
                nicmac = nic.macaddr or ""
                if nicmac.lower() == searchmac.lower():
                    return (True, _("The MAC address '%s' is in use "
                                    "by another virtual machine.") % searchmac)
        return (False, None)


    def __init__(self, *args, **kwargs):
        VirtualDevice.__init__(self, *args, **kwargs)

        self._random_mac = None
        self._default_bridge = None


    ###############
    # XML helpers #
    ###############

    def _generate_default_bridge(self):
        ret = self._default_bridge
        if ret is None:
            ret = False
            default = _default_bridge(self.conn)
            if default:
                ret = default

        self._default_bridge = ret
        return ret or None

    def _get_default_bridge(self):
        if self.type == self.TYPE_BRIDGE:
            return self._generate_default_bridge()
        return None

    def _default_source_mode(self):
        if self.type == self.TYPE_DIRECT:
            return "vepa"
        return None

    def _get_default_mac(self):
        if not self._random_mac:
            self._random_mac = self.generate_mac(self.conn)
        return self._random_mac
    def _validate_mac(self, val):
        util.validate_macaddr(val)
        return val

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
        "virtualport", "filterref", "rom_bar", "rom_file"]

    _bridge = XMLProperty("./source/@bridge", default_cb=_get_default_bridge)
    _network = XMLProperty("./source/@network")
    _source_dev = XMLProperty("./source/@dev")

    virtualport = XMLChildProperty(VirtualPort, is_single=True)
    type = XMLProperty("./@type",
                       default_cb=lambda s: s.TYPE_BRIDGE)
    trustGuestRxFilters = XMLProperty("./@trustGuestRxFilters", is_yesno=True)

    macaddr = XMLProperty("./mac/@address",
                          set_converter=_validate_mac,
                          default_cb=_get_default_mac)

    source_type = XMLProperty("./source/@type")
    source_path = XMLProperty("./source/@path")
    source_mode = XMLProperty("./source/@mode",
                              default_cb=_default_source_mode)
    portgroup = XMLProperty("./source/@portgroup")
    model = XMLProperty("./model/@type")
    target_dev = XMLProperty("./target/@dev")
    filterref = XMLProperty("./filterref/@filter")
    link_state = XMLProperty("./link/@state")

    driver_name = XMLProperty("./driver/@name")
    driver_queues = XMLProperty("./driver/@queues", is_int=True)

    rom_bar = XMLProperty("./rom/@bar", is_onoff=True)
    rom_file = XMLProperty("./rom/@file")


    #############
    # Build API #
    #############

    def setup(self, meter=None):
        ignore = meter
        if not self.macaddr:
            return

        ret, msg = self.is_conflict_net(self.conn, self.macaddr)
        if msg is None:
            return
        if ret is False:
            logging.warning(msg)
        else:
            raise RuntimeError(msg)

    def set_default_source(self):
        if (self.conn.is_qemu_session() or self.conn.is_test()):
            self.type = self.TYPE_USER
        else:
            self.type, self.source = _default_network(self.conn)


VirtualNetworkInterface.register_type()
