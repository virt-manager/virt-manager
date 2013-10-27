# Copyright (C) 2013 Red Hat, Inc.
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

import os
import unittest
import logging

from virtinst import Interface, InterfaceProtocol
from tests import utils

conn = utils.open_testdriver()
datadir = "tests/interface-xml"


def _m(_n):
    xml = conn.interfaceLookupByName(_n).XMLDesc(0)
    return Interface(conn, parsexml=xml)


class TestInterfaces(unittest.TestCase):
    def build_interface(self, interface_type, name):
        iobj = Interface(conn)
        iobj.type = interface_type
        iobj.name = name

        return iobj

    def set_general_params(self, iface_obj):
        iface_obj.mtu = 1501
        iface_obj.macaddr = "AA:AA:AA:AA:AA:AA"
        iface_obj.start_mode = Interface.INTERFACE_START_MODE_ONBOOT
        proto = InterfaceProtocol(conn)
        proto.family = InterfaceProtocol.INTERFACE_PROTOCOL_FAMILY_IPV4
        iface_obj.add_protocol(proto)

    def add_child_interfaces(self, iface_obj):
        if iface_obj.type == Interface.INTERFACE_TYPE_BRIDGE:
            iface_obj.add_interface(_m("vlaneth1"))
            iface_obj.add_interface(_m("bond-brbond"))
            iface_obj.add_interface(_m("eth0"))
        elif iface_obj.type == Interface.INTERFACE_TYPE_BOND:
            iface_obj.add_interface(_m("eth0"))
            iface_obj.add_interface(_m("eth1"))
            iface_obj.add_interface(_m("eth2"))

    def define_xml(self, obj, compare=True):
        obj.validate()

        xml = obj.get_xml_config()
        logging.debug("Defining interface XML:\n%s", xml)

        if compare:
            filename = os.path.join(datadir, obj.name + ".xml")
            utils.diff_compare(xml, filename)

        iface = obj.install()

        newxml = iface.XMLDesc(0)
        logging.debug("Defined XML:\n%s", newxml)

        iface.undefine()

    # Bridge tests
    def testBridgeInterface(self):
        filename = "bridge"
        obj = self.build_interface(Interface.INTERFACE_TYPE_BRIDGE,
                                   "test-%s" % filename)
        self.add_child_interfaces(obj)

        obj.stp = False
        obj.delay = "7"

        self.define_xml(obj)

    def testBridgeInterfaceIP(self):
        filename = "bridge-ip"
        obj = self.build_interface(Interface.INTERFACE_TYPE_BRIDGE,
                                   "test-%s" % filename)
        self.add_child_interfaces(obj)

        # IPv4 proto
        iface_proto1 = InterfaceProtocol(conn)
        iface_proto1.family = InterfaceProtocol.INTERFACE_PROTOCOL_FAMILY_IPV4
        iface_proto1.add_ip("129.63.1.2")
        iface_proto1.add_ip("255.255.255.0")
        iface_proto1.gateway = "1.2.3.4"
        iface_proto1.dhcp = True
        iface_proto1.dhcp_peerdns = True

        # IPv6 proto
        iface_proto2 = InterfaceProtocol(conn)
        iface_proto2.family = InterfaceProtocol.INTERFACE_PROTOCOL_FAMILY_IPV6

        iface_proto2.add_ip("fe99::215:58ff:fe6e:5", prefix="32")
        iface_proto2.add_ip("fe80::215:58ff:fe6e:5", prefix="64")
        iface_proto2.gateway = "1.2.3.4"
        iface_proto2.dhcp = True
        iface_proto2.dhcp_peerdns = True
        iface_proto2.autoconf = True

        obj.add_protocol(iface_proto1)
        obj.add_protocol(iface_proto2)

        self.define_xml(obj)

    # Bond tests
    def testBondInterface(self):
        filename = "bond"
        obj = self.build_interface(Interface.INTERFACE_TYPE_BOND,
                                   "test-%s" % filename)
        self.add_child_interfaces(obj)
        self.set_general_params(obj)

        self.define_xml(obj)

    def testBondInterfaceARP(self):
        filename = "bond-arp"
        obj = self.build_interface(Interface.INTERFACE_TYPE_BOND,
                                   "test-%s" % filename)
        self.add_child_interfaces(obj)
        self.set_general_params(obj)

        obj.arp_interval = 100
        obj.arp_target = "192.168.100.200"
        obj.arp_validate_mode = "backup"

        self.define_xml(obj)

    def testBondInterfaceMII(self):
        filename = "bond-mii"
        obj = self.build_interface(Interface.INTERFACE_TYPE_BOND,
                                   "test-%s" % filename)
        self.add_child_interfaces(obj)
        self.set_general_params(obj)

        obj.mii_frequency = "123"
        obj.mii_updelay   = "12"
        obj.mii_downdelay = "34"
        obj.mii_carrier_mode = "netif"

        self.define_xml(obj)

    # Ethernet tests
    def testEthernetInterface(self):
        filename = "ethernet"
        obj = self.build_interface(Interface.INTERFACE_TYPE_ETHERNET,
                                   "test-%s" % filename)
        self.define_xml(obj)

    def testEthernetManyParam(self):
        filename = "ethernet-params"
        obj = self.build_interface(Interface.INTERFACE_TYPE_ETHERNET,
                                    "test-%s" % filename)

        obj.mtu = 1234
        obj.mac = "AA:BB:FF:FF:BB:AA"
        obj.start_mode = Interface.INTERFACE_START_MODE_HOTPLUG

        self.define_xml(obj)

    # VLAN tests
    def testVLANInterface(self):
        filename = "vlan"
        obj = self.build_interface(Interface.INTERFACE_TYPE_VLAN,
                                   "test-%s" % filename)

        obj.tag = "123"
        obj.parent_interface = "eth2"

        self.define_xml(obj)

    def testVLANInterfaceBusted(self):
        obj = self.build_interface(Interface.INTERFACE_TYPE_VLAN,
                                   "vlan1")

        try:
            self.define_xml(obj, compare=False)
            assert(False)
        except ValueError:
            pass
        except:
            assert(False)

    # protocol_xml test
    def testEthernetProtocolInterface(self):
        filename = "ethernet-copy-proto"
        obj = self.build_interface(Interface.INTERFACE_TYPE_ETHERNET,
                                   "test-%s" % filename)

        protoxml = ("  <protocol family='ipv6'>\n"
                    "    <dhcp/>\n"
                    "  </protocol>\n")
        proto = InterfaceProtocol(conn, parsexml=protoxml)
        obj.add_protocol(proto)

        self.define_xml(obj)


if __name__ == "__main__":
    unittest.main()
