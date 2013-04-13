#
# Copyright 2009 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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
"""
Classes for building and installing libvirt interface xml
"""

import libvirt

import logging

from virtinst import util
from virtinst import support


class Interface(object):
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

    @staticmethod
    def interface_class_for_type(interface_type):
        if interface_type not in Interface.INTERFACE_TYPES:
            raise ValueError("Unknown interface type '%s'" % interface_type)

        if interface_type == Interface.INTERFACE_TYPE_BRIDGE:
            return InterfaceBridge
        elif interface_type == Interface.INTERFACE_TYPE_BOND:
            return InterfaceBond
        elif interface_type == Interface.INTERFACE_TYPE_ETHERNET:
            return InterfaceEthernet
        elif interface_type == Interface.INTERFACE_TYPE_VLAN:
            return InterfaceVLAN
        else:
            raise ValueError("No class for interface type '%s'" %
                             interface_type)

    @staticmethod
    def find_free_name(conn, prefix):
        """
        Generate an unused interface name based on prefix. For example,
        if prefix="br", we find the first unused name such as "br0", "br1",
        etc.
        """
        return util.generate_name(prefix, conn.interfaceLookupByName, sep="",
                                   force_num=True)

    def __init__(self, object_type, name, conn=None):
        """
        Initialize  object parameters
        """
        if object_type not in self.INTERFACE_TYPES:
            raise ValueError("Unknown interface object type: %s" %
                             object_type)

        self._object_type = object_type
        self._conn = None
        self._name = None
        self._mtu = None
        self._macaddr = None
        self._start_mode = None
        self._protocols = []
        self._protocol_xml = None

        if conn is not None:
            self.conn = conn

        self.name = name

        # Initialize all optional properties
        self._perms = None


    ## Properties
    def _get_object_type(self):
        return self._object_type
    object_type = property(_get_object_type)

    def _get_conn(self):
        return self._conn
    def _set_conn(self, val):
        if not isinstance(val, libvirt.virConnect):
            raise ValueError(_("'conn' must be a libvirt connection object."))
        if not support.check_conn_support(val, support.SUPPORT_CONN_INTERFACE):
            raise ValueError(_("Passed connection is not libvirt interface "
                               "capable"))
        self._conn = val
    conn = property(_get_conn, _set_conn, doc="""
    Libvirt connection to check object against/install on
    """)

    def _get_name(self):
        return self._name
    def _set_name(self, val):
        util.validate_name(_("Interface name"), val)

        self._check_name_collision(val)
        self._name = val
    name = property(_get_name, _set_name,
                    doc=_("Name for the interface object."))

    def _get_mtu(self):
        return self._mtu
    def _set_mtu(self, val):
        self._mtu = val
    mtu = property(_get_mtu, _set_mtu,
                   doc=_("Maximum transmit size in bytes"))

    def _get_macaddr(self):
        return self._macaddr
    def _set_macaddr(self, val):
        util.validate_macaddr(val)
        self._macaddr = val
    macaddr = property(_get_macaddr, _set_macaddr,
                       doc=_("Interface MAC address"))

    def _get_start_mode(self):
        return self._start_mode
    def _set_start_mode(self, val):
        if val not in self.INTERFACE_START_MODES:
            raise ValueError(_("Unknown start mode '%s") % val)
        self._start_mode = val
    start_mode = property(_get_start_mode, _set_start_mode,
                          doc=_("When the interface will be auto-started."))

    def _get_protocols(self):
        return self._protocols
    def _set_protocols(self, val):
        self._protocols = val
    protocols = property(_get_protocols, _set_protocols,
                         doc=_("Network protocol configuration"))

    def _get_protocol_xml_attr(self):
        return self._protocol_xml
    def _set_protocol_xml_attr(self, val):
        self._protocol_xml = val
    protocol_xml = property(_get_protocol_xml_attr, _set_protocol_xml_attr,
                            doc="String of XML to use in place of "
                                "generated protocol XML. This can be "
                                "parsed from an existing interface for "
                                "example.")

    def _check_name_collision(self, name):
        pool = None
        try:
            pool = self.conn.interfaceLookupByName(name)
        except libvirt.libvirtError:
            return

        raise ValueError(_("Name '%s' already in use by another interface.") %
                           name)

    # XML Building
    def _get_protocol_xml(self):
        """
        Returns IP protocol XML
        """
        if self.protocol_xml is not None:
            return self.protocol_xml
        xml = ""
        for p in self.protocols:
            xml += p.get_xml_config()
        return xml

    def _get_interface_xml(self):
        """
        Returns the bridge/bond/... specific xml blob
        """
        raise NotImplementedError("Must be implemented in subclass")

    def get_xml_config(self):
        """
        Construct the xml description of the interface object

        @returns: xml description
        @rtype: C{str}
        """
        xml = ""


        xml += "<interface type='%s' name='%s'>\n""" % (self.object_type,
                                                        self.name)

        if self.start_mode:
            xml += "  <start mode='%s'/>\n" % self.start_mode

        if self.macaddr:
            xml += "  <mac address='%s'/>\n" % self.macaddr

        if self.mtu is not None:
            xml += "  <mtu size='%s'/>\n" % str(self.mtu)

        xml += self._get_protocol_xml()
        xml += self._get_interface_xml()

        xml += "</interface>\n"

        return xml

    def install(self, meter=None, create=True):
        """
        Install network interface xml.
        """
        xml = self.get_xml_config()
        logging.debug("Creating interface '%s' with xml:\n%s",
                      self.name, xml)

        try:
            iface = self.conn.interfaceDefineXML(xml, 0)
        except Exception, e:
            raise RuntimeError(_("Could not define interface: %s" % str(e)))

        errmsg = None
        if create and not errmsg:
            try:
                iface.create(0)
            except Exception, e:
                errmsg = _("Could not create interface: %s" % str(e))

        if errmsg:
            # Try and clean up the leftover pool
            try:
                iface.undefine()
            except Exception, e:
                logging.debug("Error cleaning up interface after failure: " +
                              "%s" % str(e))
            raise RuntimeError(errmsg)

        return iface


class _InterfaceCompound(Interface):
    """
    Class representing an interface which can have child interfaces
    """

    def __init__(self, interface_type, name, conn=None):
        Interface.__init__(self, interface_type, name, conn)
        self._interfaces = []

    def _get_interfaces(self):
        return self._interfaces
    def _set_interfaces(self, val):
        if val is not None:
            if type(val) is not list:
                raise ValueError("Interfaces must be a list or None")

            for i in val:
                if type(i) is str:
                    # Assume this is a plain ethernet name
                    continue

                if not isinstance(i, libvirt.virInterface):
                    raise ValueError("List members must be virInterface "
                                     "instances, not %s" % type(i))

        self._interfaces = val
    interfaces = property(_get_interfaces, _set_interfaces)

    def _indent_xml(self, xml, indent_size):
        newxml = ""
        for line in xml.split("\n"):
            if line:
                line = (" " * indent_size) + line + "\n"
            newxml += line

        return newxml

    def _get_child_interface_xml(self):
        xml = ""
        for i in self.interfaces:
            if type(i) is str:
                iface_xml = "    <interface name='%s' type='ethernet'/>\n" % i
            else:
                iface_xml = self._indent_xml(i.XMLDesc(0), 4)

            xml += iface_xml
        return xml

    def _get_interface_xml(self):
        raise NotImplementedError("Must be implemented in subclass")


class InterfaceBridge(_InterfaceCompound):
    """
    Class for building and installing libvirt interface bridge xml
    """

    def __init__(self, name, conn=None):
        _InterfaceCompound.__init__(self, Interface.INTERFACE_TYPE_BRIDGE,
                                    name, conn)

        self._stp = None
        self._delay = None

    def _get_stp(self):
        return self._stp
    def _set_stp(self, val):
        if type(val) is not bool:
            raise ValueError("STP must be a bool value")
        self._stp = val
    stp = property(_get_stp, _set_stp,
                   doc=_("Whether STP is enabled on the bridge"))

    def _get_delay(self):
        return self._delay
    def _set_delay(self, val):
        self._delay = val
    delay = property(_get_delay, _set_delay,
                     doc=_("Delay in seconds before forwarding begins when "
                           "joining a network."))

    def _get_interface_xml(self):
        xml = "  <bridge"
        if self.stp is not None:
            xml += " stp='%s'" % (self.stp and "on" or "off")
        if self.delay is not None:
            xml += " delay='%s'" % str(self.delay)
        xml += ">\n"

        xml += self._get_child_interface_xml()
        xml += "  </bridge>\n"
        return xml


class InterfaceBond(_InterfaceCompound):
    """
    Class for building and installing libvirt interface bond xml
    """

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

    def __init__(self, name, conn=None):
        _InterfaceCompound.__init__(self, Interface.INTERFACE_TYPE_BOND,
                                    name, conn)

        self._bond_mode = None
        self._monitor_mode = None

        # ARP values
        self._arp_interval = None
        self._arp_target = None
        self._arp_validate_mode = None

        # MII values
        self._mii_frequency = None
        self._mii_updelay   = None
        self._mii_downdelay = None
        self._mii_carrier_mode = None

    def _get_bond_mode(self):
        return self._bond_mode
    def _set_bond_mode(self, val):
        if val is None:
            self._bond_mode = None
            return

        self._bond_mode = val
    bond_mode = property(_get_bond_mode, _set_bond_mode,
                         doc=_("Mode of operation of the bonding device"))

    def _get_monitor_mode(self):
        return self._monitor_mode
    def _set_monitor_mode(self, val):
        if val is None:
            self._monitor_mode = None
            return

        self._monitor_mode = val
    monitor_mode = property(_get_monitor_mode, _set_monitor_mode,
                            doc=_("Availability monitoring mode for the bond "
                                  "device"))

    # ARP props
    def _get_arp_interval(self):
        return self._arp_interval
    def _set_arp_interval(self, val):
        self._arp_interval = val
    arp_interval = property(_get_arp_interval, _set_arp_interval,
                            doc=_("ARP monitoring interval in milliseconds"))

    def _get_arp_target(self):
        return self._arp_target
    def _set_arp_target(self, val):
        self._arp_target = val
    arp_target = property(_get_arp_target, _set_arp_target,
                          doc=_("IP target used in ARP monitoring packets"))

    def _get_arp_validate_mode(self):
        return self._arp_validate_mode
    def _set_arp_validate_mode(self, val):
        self._arp_validate_mode = val
    arp_validate_mode = property(_get_arp_validate_mode,
                                 _set_arp_validate_mode,
                                 doc=_("ARP monitor validation mode"))

    # MII props
    def _get_mii_carrier_mode(self):
        return self._mii_carrier_mode
    def _set_mii_carrier_mode(self, val):
        self._mii_carrier_mode = val
    mii_carrier_mode = property(_get_mii_carrier_mode, _set_mii_carrier_mode,
                                doc=_("MII monitoring method."))

    def _get_mii_frequency(self):
        return self._mii_frequency
    def _set_mii_frequency(self, val):
        self._mii_frequency = val
    mii_frequency = property(_get_mii_frequency, _set_mii_frequency,
                             doc=_("MII monitoring interval in milliseconds"))

    def _get_mii_updelay(self):
        return self._mii_updelay
    def _set_mii_updelay(self, val):
        self._mii_updelay = val
    mii_updelay = property(_get_mii_updelay, _set_mii_updelay,
                           doc=_("Time in milliseconds to wait before "
                                 "enabling a slave after link recovery "))

    def _get_mii_downdelay(self):
        return self._mii_downdelay
    def _set_mii_downdelay(self, val):
        self._mii_downdelay = val
    mii_downdelay = property(_get_mii_downdelay, _set_mii_downdelay,
                             doc=_("Time in milliseconds to wait before "
                                   "disabling a slave after link failure"))



    # XML Building methods
    def _get_monitor_xml(self):
        mode_xml = ""
        if self.monitor_mode == self.INTERFACE_BOND_MONITOR_MODE_ARP:
            mode_xml = "    <arpmon"

            if self.arp_interval is not None:
                mode_xml += " interval='%s'" % str(self.arp_interval)
            if self.arp_target is not None:
                mode_xml += " target='%s'" % str(self.arp_target)
            if self.arp_validate_mode is not None:
                mode_xml += " validate='%s'" % str(self.arp_validate_mode)

            mode_xml += "/>\n"

        elif self.monitor_mode == self.INTERFACE_BOND_MONITOR_MODE_MII:
            mode_xml = "    <miimon"

            if self.mii_frequency is not None:
                mode_xml += " freq='%s'" % str(self.mii_frequency)
            if self.mii_downdelay is not None:
                mode_xml += " downdelay='%s'" % str(self.mii_downdelay)
            if self.mii_updelay is not None:
                mode_xml += " updelay='%s'" % str(self.mii_updelay)
            if self.mii_carrier_mode is not None:
                mode_xml += " carrier='%s'" % str(self.mii_carrier_mode)

            mode_xml += "/>\n"

        return mode_xml

    def _get_interface_xml(self):
        xml = ""

        xml += "  <bond"
        if self.bond_mode:
            xml += " mode='%s'" % self.bond_mode
        xml += ">\n"

        xml += self._get_monitor_xml()
        xml += self._get_child_interface_xml()

        xml += "  </bond>\n"
        return xml


class InterfaceEthernet(Interface):
    """
    Class for building and installing libvirt interface ethernet xml
    """

    def __init__(self, name, conn=None):
        Interface.__init__(self, Interface.INTERFACE_TYPE_ETHERNET,
                           name, conn)

    def _get_interface_xml(self):
        # No ethernet specific XML
        return ""


class InterfaceVLAN(Interface):
    """
    Class for building and installing libvirt interface vlan xml
    """

    def __init__(self, name, conn=None):
        Interface.__init__(self, Interface.INTERFACE_TYPE_VLAN,
                           name, conn)

        self._tag = None
        self._parent_interface = None

    def _get_tag(self):
        return self._tag
    def _set_tag(self, val):
        self._tag = val
    tag = property(_get_tag, _set_tag,
                   doc=_("VLAN device tag number"))

    def _get_parent_interface(self):
        return self._parent_interface
    def _set_parent_interface(self, val):
        if (type(val) is not str and
            not isinstance(val, libvirt.virInterface)):
            raise ValueError("VLAN parent interface must be a virInterface "
                             "instance or string, not '%s'" % val)
        self._parent_interface = val
    parent_interface = property(_get_parent_interface,
                                _set_parent_interface,
                                doc=_("Parent interface to create VLAN on"))

    def _get_interface_xml(self):
        if self.tag is None or self.parent_interface is None:
            raise ValueError(_("Tag and parent interface are required."))

        if type(self.parent_interface) is str:
            name = self.parent_interface
        else:
            name = self.parent_interface.name()

        xml  = "  <vlan tag='%s'>\n" % self.tag
        xml += "    <interface name='%s'/>\n" % name
        xml += "  </vlan>\n"

        return xml


class InterfaceProtocol(object):

    INTERFACE_PROTOCOL_FAMILY_IPV4 = "ipv4"
    INTERFACE_PROTOCOL_FAMILY_IPV6 = "ipv6"
    INTERFACE_PROTOCOL_FAMILIES = [INTERFACE_PROTOCOL_FAMILY_IPV4,
                                    INTERFACE_PROTOCOL_FAMILY_IPV6]

    @staticmethod
    def protocol_class_for_family(family):
        if family not in InterfaceProtocol.INTERFACE_PROTOCOL_FAMILIES:
            raise ValueError("Unknown interface protocol family '%s'" %
                             family)

        if family == InterfaceProtocol.INTERFACE_PROTOCOL_FAMILY_IPV4:
            return InterfaceProtocolIPv4
        elif family == InterfaceProtocol.INTERFACE_PROTOCOL_FAMILY_IPV6:
            return InterfaceProtocolIPv6

    def __init__(self, family):
        if family not in InterfaceProtocol.INTERFACE_PROTOCOL_FAMILIES:
            raise ValueError("Unknown interface protocol family '%s'" %
                             family)

        self._family = family

    def _get_family(self):
        return self._family
    family = property(_get_family)

    def _get_protocol_xml(self):
        raise NotImplementedError("Must be implemented in subclass")

    def get_xml_config(self):
        xml = ""
        xml += "  <protocol family='%s'>\n" % self.family
        xml += self._get_protocol_xml()
        xml += "  </protocol>\n"

        return xml


class InterfaceProtocolIP(InterfaceProtocol):

    def __init__(self, family):
        InterfaceProtocol.__init__(self, family)

        self._autoconf = False

        self._dhcp = False
        self._dhcp_peerdns = None

        self._ips = []

        self._gateway = None


    def _get_dhcp(self):
        return self._dhcp
    def _set_dhcp(self, val):
        self._dhcp = val
    dhcp = property(_get_dhcp, _set_dhcp,
                    doc=_("Whether to enable DHCP"))

    def _get_dhcp_peerdns(self):
        return self._dhcp_peerdns
    def _set_dhcp_peerdns(self, val):
        self._dhcp_peerdns = val
    dhcp_peerdns = property(_get_dhcp_peerdns, _set_dhcp_peerdns)

    def _get_gateway(self):
        return self._gateway
    def _set_gateway(self, val):
        self._gateway = val
    gateway = property(_get_gateway, _set_gateway,
                       doc=_("Network gateway address"))

    def _get_ips(self):
        return self._ips
    def _set_ips(self, val):
        self._ips = val
    ips = property(_get_ips, _set_ips,
                   doc=_("Static IP addresses"))

    def _get_protocol_xml(self):
        raise NotImplementedError("Must be implemented in subclass")

    def _get_ip_xml(self):
        xml = ""

        if self.dhcp:
            xml += "    <dhcp"
            if self.dhcp_peerdns is not None:
                xml += " peerdns='%s'" % (bool(self.dhcp_peerdns) and "yes"
                                                                  or "no")
            xml += "/>\n"

        for ip in self.ips:
            xml += ip.get_xml_config()

        if self.gateway:
            xml += "    <route gateway='%s'/>\n" % self.gateway

        return xml


class InterfaceProtocolIPv4(InterfaceProtocolIP):
    def __init__(self):
        InterfaceProtocolIP.__init__(self, self.INTERFACE_PROTOCOL_FAMILY_IPV4)

    def _get_protocol_xml(self):
        return self._get_ip_xml()


class InterfaceProtocolIPv6(InterfaceProtocolIP):
    def __init__(self):
        InterfaceProtocolIP.__init__(self, self.INTERFACE_PROTOCOL_FAMILY_IPV6)

        self._autoconf = False

    def _get_autoconf(self):
        return self._autoconf
    def _set_autoconf(self, val):
        self._autoconf = bool(val)
    autoconf = property(_get_autoconf, _set_autoconf,
                        doc=_("Whether to enable IPv6 autoconfiguration"))

    def _get_protocol_xml(self):
        xml = ""

        if self.autoconf:
            xml += "    <autoconf/>\n"

        xml += self._get_ip_xml()
        return xml


class InterfaceProtocolIPAddress(object):
    def __init__(self, address, prefix=None):
        self._address = address
        self._prefix = prefix

    def _get_prefix(self):
        return self._prefix
    def _set_prefix(self, val):
        self._prefix = val
    prefix = property(_get_prefix, _set_prefix,
                      doc=_("IPv6 address prefix"))

    def _get_address(self):
        return self._address
    def _set_address(self, val):
        self._address = val
    address = property(_get_address, _set_address,
                       doc=_("IP address"))

    def get_xml_config(self):
        xml = "    <ip address='%s'" % self.address

        if self.prefix is not None:
            xml += " prefix='%s'" % self.prefix

        xml += "/>\n"
        return xml
