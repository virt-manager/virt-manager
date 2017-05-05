#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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
"""
Classes for building and installing libvirt interface xml
"""

import logging

import libvirt
import ipaddr

from . import util
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _IPAddress(XMLBuilder):
    _XML_PROP_ORDER = ["address", "prefix"]
    _XML_ROOT_NAME = "ip"

    ######################
    # Validation helpers #
    ######################

    def _validate_ipaddr(self, addr):
        ipaddr.IPAddress(addr)
        return addr

    address = XMLProperty("./@address", validate_cb=_validate_ipaddr)
    prefix = XMLProperty("./@prefix", is_int=True)


class InterfaceProtocol(XMLBuilder):
    INTERFACE_PROTOCOL_FAMILY_IPV4 = "ipv4"
    INTERFACE_PROTOCOL_FAMILY_IPV6 = "ipv6"
    INTERFACE_PROTOCOL_FAMILIES = [INTERFACE_PROTOCOL_FAMILY_IPV4,
                                    INTERFACE_PROTOCOL_FAMILY_IPV6]

    _XML_ROOT_NAME = "protocol"
    _XML_PROP_ORDER = ["autoconf", "dhcp", "dhcp_peerdns", "ips", "gateway"]

    family = XMLProperty("./@family")
    dhcp = XMLProperty("./dhcp", is_bool=True, doc=_("Whether to enable DHCP"))
    dhcp_peerdns = XMLProperty("./dhcp/@peerdns", is_yesno=True)
    gateway = XMLProperty("./route/@gateway", doc=_("Network gateway address"))
    autoconf = XMLProperty("./autoconf", is_bool=True,
        doc=_("Whether to enable IPv6 autoconfiguration"))


    #####################
    # IP child handling #
    #####################

    def add_ip(self, addr, prefix=None):
        ip = _IPAddress(self.conn)
        ip.address = addr
        ip.prefix = prefix
        self.add_child(ip)
    def remove_ip(self, ip):
        self.remove_child(ip)
        ip.clear()
    ips = XMLChildProperty(_IPAddress)


class Interface(XMLBuilder):
    """
    Base class for building any libvirt interface object.

    Mostly meaningless to directly instantiate.
    """

    INTERFACE_TYPE_BRIDGE   = "bridge"
    INTERFACE_TYPE_BOND     = "bond"
    INTERFACE_TYPE_ETHERNET = "ethernet"
    INTERFACE_TYPE_VLAN     = "vlan"
    INTERFACE_TYPES = [INTERFACE_TYPE_BRIDGE, INTERFACE_TYPE_BOND,
                       INTERFACE_TYPE_ETHERNET, INTERFACE_TYPE_VLAN]

    INTERFACE_START_MODE_NONE    = "none"
    INTERFACE_START_MODE_ONBOOT  = "onboot"
    INTERFACE_START_MODE_HOTPLUG = "hotplug"
    INTERFACE_START_MODES = [INTERFACE_START_MODE_NONE,
                             INTERFACE_START_MODE_ONBOOT,
                             INTERFACE_START_MODE_HOTPLUG]

    INTERFACE_BOND_MODES = ["active-backup", "balance-alb", "balance-rr",
                             "balance-tlb", "balance-xor", "broadcast",
                             "802.3ad"]

    INTERFACE_BOND_MONITOR_MODE_ARP = "arpmon"
    INTERFACE_BOND_MONITOR_MODE_MII = "miimon"
    INTERFACE_BOND_MONITOR_MODES    = [INTERFACE_BOND_MONITOR_MODE_ARP,
                                        INTERFACE_BOND_MONITOR_MODE_MII]

    INTERFACE_BOND_MONITOR_MODE_ARP_VALIDATE_MODES = ["active", "backup",
                                                       "all"]

    INTERFACE_BOND_MONITOR_MODE_MII_CARRIER_TYPES = ["netif", "ioctl"]


    @staticmethod
    def find_free_name(conn, prefix):
        """
        Generate an unused interface name based on prefix. For example,
        if prefix="br", we find the first unused name such as "br0", "br1",
        etc.
        """
        return util.generate_name(prefix, conn.interfaceLookupByName, sep="",
                                  force_num=True)

    _XML_ROOT_NAME = "interface"
    _XML_PROP_ORDER = ["type", "name", "start_mode", "macaddr", "mtu",
                       "stp", "delay", "bond_mode", "arp_interval",
                       "arp_target", "arp_validate_mode", "mii_frequency",
                       "mii_downdelay", "mii_updelay", "mii_carrier_mode",
                       "tag", "parent_interface",
                       "protocols", "interfaces"]

    ##################
    # Child handling #
    ##################

    def add_interface(self, obj):
        self.add_child(obj)
    def remove_interface(self, obj):
        self.remove_child(obj)
    # 'interfaces' property is added outside this class, since it needs
    # to reference the completed Interface class

    def add_protocol(self, obj):
        self.add_child(obj)
    def remove_protocol(self, obj):
        self.remove_child(obj)
    protocols = XMLChildProperty(InterfaceProtocol)


    ######################
    # Validation helpers #
    ######################

    def _validate_name(self, name):
        if name == self.name:
            return
        try:
            self.conn.interfaceLookupByName(name)
        except libvirt.libvirtError:
            return

        raise ValueError(_("Name '%s' already in use by another interface.") %
                           name)

    def _validate_mac(self, val):
        util.validate_macaddr(val)
        return val


    ##################
    # General params #
    ##################

    type = XMLProperty("./@type")
    mtu = XMLProperty("./mtu/@size", is_int=True,
                      doc=_("Maximum transmit size in bytes"))
    start_mode = XMLProperty("./start/@mode",
                             doc=_("When the interface will be auto-started."))

    name = XMLProperty("./@name", validate_cb=_validate_name,
                       doc=_("Name for the interface object."))

    macaddr = XMLProperty("./mac/@address", validate_cb=_validate_mac,
                          doc=_("Interface MAC address"))


    #################
    # Bridge params #
    #################

    stp = XMLProperty("./bridge/@stp", is_onoff=True,
                      doc=_("Whether STP is enabled on the bridge"))
    delay = XMLProperty("./bridge/@delay",
                        doc=_("Delay in seconds before forwarding begins when "
                              "joining a network."))

    ###############
    # Bond params #
    ###############

    bond_mode = XMLProperty("./bond/@mode",
                            doc=_("Mode of operation of the bonding device"))

    arp_interval = XMLProperty("./bond/arpmon/@interval", is_int=True,
                               doc=_("ARP monitoring interval in "
                                     "milliseconds"))
    arp_target = XMLProperty("./bond/arpmon/@target",
                             doc=_("IP target used in ARP monitoring packets"))
    arp_validate_mode = XMLProperty("./bond/arpmon/@validate",
                                    doc=_("ARP monitor validation mode"))

    mii_carrier_mode = XMLProperty("./bond/miimon/@carrier",
                                   doc=_("MII monitoring method."))
    mii_frequency = XMLProperty("./bond/miimon/@freq", is_int=True,
                                doc=_("MII monitoring interval in "
                                      "milliseconds"))
    mii_updelay = XMLProperty("./bond/miimon/@updelay", is_int=True,
                              doc=_("Time in milliseconds to wait before "
                                    "enabling a slave after link recovery "))
    mii_downdelay = XMLProperty("./bond/miimon/@downdelay", is_int=True,
                                doc=_("Time in milliseconds to wait before "
                                      "disabling a slave after link failure"))


    ###############
    # VLAN params #
    ###############

    tag = XMLProperty("./vlan/@tag", is_int=True,
                      doc=_("VLAN device tag number"))
    parent_interface = XMLProperty("./vlan/interface/@name",
                                   doc=_("Parent interface to create VLAN on"))


    ##################
    # Build routines #
    ##################

    def validate(self):
        if (self.type == self.INTERFACE_TYPE_VLAN and
            (self.tag is None or self.parent_interface is None)):
            raise ValueError(_("VLAN Tag and parent interface are required."))

    def install(self, meter=None, create=True):
        """
        Install network interface xml.
        """
        ignore = meter
        xml = self.get_xml_config()
        logging.debug("Creating interface '%s' with xml:\n%s",
                      self.name, xml)

        try:
            iface = self.conn.interfaceDefineXML(xml, 0)
        except Exception as e:
            raise RuntimeError(_("Could not define interface: %s") % str(e))

        errmsg = None
        if create and not errmsg:
            try:
                iface.create(0)
            except Exception as e:
                errmsg = _("Could not create interface: %s") % str(e)

        if errmsg:
            # Try and clean up the leftover pool
            try:
                iface.undefine()
            except Exception as e:
                logging.debug("Error cleaning up interface after failure: " +
                              "%s" % str(e))
            raise RuntimeError(errmsg)

        return iface

Interface.interfaces = XMLChildProperty(Interface,
                                        relative_xpath="./%(type)s")
