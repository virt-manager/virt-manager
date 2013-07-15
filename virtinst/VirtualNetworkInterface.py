#
# Copyright 2006-2009  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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
import random

from virtinst import util
from virtinst.VirtualDevice import VirtualDevice
from virtinst.xmlbuilder import XMLBuilder, XMLProperty


def _random_mac(conn):
    """Generate a random MAC address.

    00-16-3E allocated to xensource
    52-54-00 used by qemu/kvm

    The OUI list is available at http://standards.ieee.org/regauth/oui/oui.txt.

    The remaining 3 fields are random, with the first bit of the first
    random field set 0.

    @return: MAC address string
    """
    ouis = {'xen': [0x00, 0x16, 0x3E], 'qemu': [0x52, 0x54, 0x00]}

    try:
        oui = ouis[conn.getType().lower()]
    except KeyError:
        oui = ouis['xen']

    mac = oui + [
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff)]
    return ':'.join(["%02x" % x for x in mac])


class VirtualPort(XMLBuilder):
    type = XMLProperty(xpath="./virtualport/@type")

    managerid = XMLProperty(xpath="./virtualport/parameters/@managerid",
                            is_int=True)

    typeid = XMLProperty(xpath="./virtualport/parameters/@typeid", is_int=True)
    typeidversion = XMLProperty(
            xpath="./virtualport/parameters/@typeidversion", is_int=True)
    instanceid = XMLProperty(xpath="./virtualport/parameters/@instanceid")


class VirtualNetworkInterface(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_NET

    TYPE_BRIDGE     = "bridge"
    TYPE_VIRTUAL    = "network"
    TYPE_USER       = "user"
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
        if hasattr(conn, "_virtinst__fake_conn_predictable"):
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


    def __init__(self, conn, parsexml=None, parsexmlnode=None):
        VirtualDevice.__init__(self, conn, parsexml, parsexmlnode)

        self.virtualport = VirtualPort(conn, parsexml, parsexmlnode)
        self._XML_SUB_ELEMENTS.append("virtualport")

        self._random_mac = None
        self._default_bridge = None


    def _generate_default_bridge(self):
        ret = self._default_bridge
        if ret is None:
            ret = False
            default = util.default_bridge(self.conn)
            if default:
                ret = default[1]

        self._default_bridge = ret
        return ret or None

    def get_source(self):
        """
        Convenince function, try to return the relevant <source> value
        per the network type.
        """
        if self.type == self.TYPE_VIRTUAL:
            return self.network
        if self.type == self.TYPE_BRIDGE:
            return self.bridge
        if self.type == self.TYPE_ETHERNET or self.type == self.TYPE_DIRECT:
            return self.source_dev
        if self.type == self.TYPE_USER:
            return None
        return self.network or self.bridge or self.source_dev

    def set_source(self, newsource):
        """
        Conveninece function, try to set the relevant <source> value
        per the network type
        """
        if self.type == self.TYPE_VIRTUAL:
            self.network = newsource
        elif self.type == self.TYPE_BRIDGE:
            self.bridge = newsource
        elif self.type == self.TYPE_ETHERNET or self.type == self.TYPE_DIRECT:
            self.source_dev = newsource
        return
    source = property(get_source, set_source)

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


    _XML_ELEMENT_ORDER = ["source", "mac", "target", "model"]

    type = XMLProperty(xpath="./@type",
                       default_cb=lambda s: s.TYPE_BRIDGE)

    def _get_default_mac(self):
        if self._is_parse():
            return None
        if not self._random_mac:
            self._random_mac = self.generate_mac(self.conn)
        return self._random_mac
    def _validate_mac(self, val):
        util.validate_macaddr(val)
        return val
    macaddr = XMLProperty(xpath="./mac/@address",
                          set_converter=_validate_mac,
                          default_cb=_get_default_mac)

    def _get_default_bridge(self):
        if self.type == self.TYPE_BRIDGE:
            return self._generate_default_bridge()
        return None
    bridge = XMLProperty(xpath="./source/@bridge",
                         default_cb=_get_default_bridge)
    network = XMLProperty(xpath="./source/@network")
    source_dev = XMLProperty(xpath="./source/@dev")



    def _default_source_mode(self):
        if self.type == self.TYPE_DIRECT:
            return "vepa"
        return None
    source_mode = XMLProperty(xpath="./source/@mode",
                              default_cb=_default_source_mode)
    model = XMLProperty(xpath="./model/@type")
    target_dev = XMLProperty(xpath="./target/@dev")
