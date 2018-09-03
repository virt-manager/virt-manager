#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
"""
Classes for building and installing libvirt interface xml
"""

import ipaddress
import logging

import libvirt

from . import util
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _IPAddress(XMLBuilder):
    _XML_PROP_ORDER = ["address", "prefix"]
    XML_NAME = "ip"

    address = XMLProperty("./@address")
    prefix = XMLProperty("./@prefix", is_int=True)


class InterfaceProtocol(XMLBuilder):
    INTERFACE_PROTOCOL_FAMILY_IPV4 = "ipv4"
    INTERFACE_PROTOCOL_FAMILY_IPV6 = "ipv6"
    INTERFACE_PROTOCOL_FAMILIES = [INTERFACE_PROTOCOL_FAMILY_IPV4,
                                    INTERFACE_PROTOCOL_FAMILY_IPV6]

    XML_NAME = "protocol"
    _XML_PROP_ORDER = ["autoconf", "dhcp", "dhcp_peerdns", "ips", "gateway"]

    family = XMLProperty("./@family")
    dhcp = XMLProperty("./dhcp", is_bool=True)
    dhcp_peerdns = XMLProperty("./dhcp/@peerdns", is_yesno=True)
    gateway = XMLProperty("./route/@gateway")
    autoconf = XMLProperty("./autoconf", is_bool=True)


    #####################
    # IP child handling #
    #####################

    def add_ip(self, addr, prefix=None):
        ip = self.ips.add_new()
        ip.address = addr
        ip.prefix = prefix
    def remove_ip(self, ip):
        self.remove_child(ip)
        ip.clear()
    ips = XMLChildProperty(_IPAddress)


class _BondConfig(XMLBuilder):
    XML_NAME = "bond"


class _BridgeConfig(XMLBuilder):
    XML_NAME = "bridge"


class _VLANConfig(XMLBuilder):
    XML_NAME = "vlan"


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

    XML_NAME = "interface"
    _XML_PROP_ORDER = ["type", "name", "start_mode", "macaddr", "mtu",
                       "stp", "delay", "bond_mode", "arp_interval",
                       "arp_target", "arp_validate_mode", "mii_frequency",
                       "mii_downdelay", "mii_updelay", "mii_carrier_mode",
                       "tag", "parent_interface",
                       "protocols", "_bond", "_bridge", "_vlan"]

    ######################
    # Interface handling #
    ######################

    # The recursive nature of nested interfaces complicates things here,
    # which is why this is strange. See bottom of the file for more
    # weirdness

    _bond = XMLChildProperty(_BondConfig, is_single=True)
    _bridge = XMLChildProperty(_BridgeConfig, is_single=True)
    _vlan = XMLChildProperty(_VLANConfig, is_single=True)

    def add_interface(self, obj):
        getattr(self, "_" + self.type).add_child(obj)
    def remove_interface(self, obj):
        getattr(self, "_" + self.type).remove_child(obj)

    @property
    def interfaces(self):
        if self.type != "ethernet":
            return getattr(self, "_" + self.type).interfaces
        return []


    ######################
    # Validation helpers #
    ######################

    @staticmethod
    def validate_name(conn, name):
        try:
            conn.interfaceLookupByName(name)
        except libvirt.libvirtError:
            return

        raise ValueError(_("Name '%s' already in use by another interface.") %
                           name)


    ##################
    # General params #
    ##################

    type = XMLProperty("./@type")
    mtu = XMLProperty("./mtu/@size", is_int=True)
    start_mode = XMLProperty("./start/@mode")

    name = XMLProperty("./@name")
    macaddr = XMLProperty("./mac/@address")

    def add_protocol(self, obj):
        self.add_child(obj)
    def remove_protocol(self, obj):
        self.remove_child(obj)
    protocols = XMLChildProperty(InterfaceProtocol)


    #################
    # Bridge params #
    #################

    stp = XMLProperty("./bridge/@stp", is_onoff=True)
    delay = XMLProperty("./bridge/@delay")


    ###############
    # Bond params #
    ###############

    bond_mode = XMLProperty("./bond/@mode")

    arp_interval = XMLProperty("./bond/arpmon/@interval", is_int=True)
    arp_target = XMLProperty("./bond/arpmon/@target")
    arp_validate_mode = XMLProperty("./bond/arpmon/@validate")

    mii_carrier_mode = XMLProperty("./bond/miimon/@carrier")
    mii_frequency = XMLProperty("./bond/miimon/@freq", is_int=True)
    mii_updelay = XMLProperty("./bond/miimon/@updelay", is_int=True)
    mii_downdelay = XMLProperty("./bond/miimon/@downdelay", is_int=True)


    ###############
    # VLAN params #
    ###############

    tag = XMLProperty("./vlan/@tag", is_int=True)
    parent_interface = XMLProperty("./vlan/interface/@name")


    ##################
    # Build routines #
    ##################

    def validate(self):
        self.validate_name(self.conn, self.name)
        if self.macaddr:
            util.validate_macaddr(self.macaddr)

        for protocol in self.protocols:
            for ip in protocol.ips:
                ipaddress.ip_address(ip.address)

        if (self.type == self.INTERFACE_TYPE_VLAN and
            (self.tag is None or self.parent_interface is None)):
            raise ValueError(_("VLAN Tag and parent interface are required."))

    def install(self, meter=None, create=True):
        """
        Install network interface xml.
        """
        ignore = meter
        xml = self.get_xml()
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
                logging.debug("Error cleaning up interface after failure: %s",
                              str(e))
            raise RuntimeError(errmsg)

        return iface


# Interface can recursively have child interfaces which we can't define
# inline in the class config, hence this hackery
_BondConfig.interfaces = XMLChildProperty(Interface)
_BridgeConfig.interfaces = XMLChildProperty(Interface)
_VLANConfig.interfaces = XMLChildProperty(Interface)
