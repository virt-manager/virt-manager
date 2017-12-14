#
# Copyright 2013 Red Hat, Inc.
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
Classes for building and installing libvirt <network> XML
"""

import logging

import libvirt

from . import util
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _NetworkDHCPRange(XMLBuilder):
    _XML_ROOT_NAME = "range"
    start = XMLProperty("./@start")
    end = XMLProperty("./@end")


class _NetworkDHCPHost(XMLBuilder):
    _XML_ROOT_NAME = "host"
    macaddr = XMLProperty("./@mac")
    name = XMLProperty("./@name")
    ip = XMLProperty("./@ip")


class _NetworkIP(XMLBuilder):
    _XML_ROOT_NAME = "ip"

    family = XMLProperty("./@family")
    address = XMLProperty("./@address")
    prefix = XMLProperty("./@prefix", is_int=True)
    netmask = XMLProperty("./@netmask")

    tftp = XMLProperty("./tftp/@root")
    bootp_file = XMLProperty("./dhcp/bootp/@file")
    bootp_server = XMLProperty("./dhcp/bootp/@server")

    ranges = XMLChildProperty(_NetworkDHCPRange, relative_xpath="./dhcp")
    hosts = XMLChildProperty(_NetworkDHCPHost, relative_xpath="./dhcp")

    def add_range(self):
        r = _NetworkDHCPRange(self.conn)
        self.add_child(r)
        return r


class _NetworkRoute(XMLBuilder):
    _XML_ROOT_NAME = "route"

    family = XMLProperty("./@family")
    address = XMLProperty("./@address")
    prefix = XMLProperty("./@prefix", is_int=True)
    gateway = XMLProperty("./@gateway")
    netmask = XMLProperty("./@netmask")


class _NetworkForwardPf(XMLBuilder):
    _XML_ROOT_NAME = "pf"
    dev = XMLProperty("./@dev")


class _NetworkForwardAddress(XMLBuilder):
    _XML_ROOT_NAME = "address"
    type = XMLProperty("./@type")
    domain = XMLProperty("./@domain", is_int=True)
    bus = XMLProperty("./@bus", is_int=True)
    slot = XMLProperty("./@slot", is_int=True)
    function = XMLProperty("./@function", is_int=True)


class _NetworkForward(XMLBuilder):
    _XML_ROOT_NAME = "forward"

    mode = XMLProperty("./@mode")
    dev = XMLProperty("./@dev")
    managed = XMLProperty("./@managed")
    pf = XMLChildProperty(_NetworkForwardPf)
    vfs = XMLChildProperty(_NetworkForwardAddress)

    def add_pf(self):
        r = _NetworkForwardPf(self.conn)
        self.add_child(r)
        return r

    def pretty_desc(self):
        return Network.pretty_forward_desc(self.mode, self.dev)


class _NetworkBandwidth(XMLBuilder):
    _XML_ROOT_NAME = "bandwidth"

    inbound_average = XMLProperty("./inbound/@average")
    inbound_peak = XMLProperty("./inbound/@peak")
    inbound_burst = XMLProperty("./inbound/@burst")
    inbound_floor = XMLProperty("./inbound/@floor")

    outbound_average = XMLProperty("./outbound/@average")
    outbound_peak = XMLProperty("./outbound/@peak")
    outbound_burst = XMLProperty("./outbound/@burst")

    def is_inbound(self):
        return bool(self.inbound_average or self.inbound_peak or
                    self.inbound_burst or self.inbound_floor)

    def is_outbound(self):
        return bool(self.outbound_average or self.outbound_peak or
                    self.outbound_burst)

    def pretty_desc(self, inbound=True, outbound=True):
        items_in = [(self.inbound_average, _("Average"), "KiB/s"),
                    (self.inbound_peak, _("Peak"), "KiB"),
                    (self.inbound_burst, _("Burst"), "KiB/s"),
                    (self.inbound_floor, _("Floor"), "KiB/s")]

        items_out = [(self.outbound_average, _("Average"), "KiB/s"),
                     (self.outbound_peak, _("Peak"), "KiB"),
                     (self.outbound_burst, _("Burst"), "KiB/s")]

        def stringify_items(items):
            return ", ".join(["%s: %s %s" % (desc, val, unit)
                              for val, desc, unit in items if val])

        ret = ""
        show_name = inbound and outbound

        if inbound:
            if show_name:
                ret += _("Inbound: ")
            ret += stringify_items(items_in)

        if outbound:
            if ret:
                ret += "\n"
            if show_name:
                ret += _("Outbound: ")
            ret += stringify_items(items_out)

        return ret


class _NetworkPortgroup(XMLBuilder):
    _XML_ROOT_NAME = "portgroup"

    name = XMLProperty("./@name")
    default = XMLProperty("./@default", is_yesno=True)


class Network(XMLBuilder):
    """
    Top level class for <network> object XML
    """
    @staticmethod
    def pretty_forward_desc(mode, dev):
        if mode or dev:
            if not mode or mode == "nat":
                if dev:
                    desc = _("NAT to %s") % dev
                else:
                    desc = _("NAT")
            elif mode == "route":
                if dev:
                    desc = _("Route to %s") % dev
                else:
                    desc = _("Routed network")
            else:
                if dev:
                    desc = (_("%(mode)s to %(device)s") %
                            {"mode": mode, "device": dev})
                else:
                    desc = _("%s network") % mode.capitalize()
        else:
            desc = _("Isolated network, internal and host routing only")

        return desc


    ###################
    # Helper routines #
    ###################

    def can_pxe(self):
        forward = self.forward.mode
        if forward and forward != "nat":
            return True
        for ip in self.ips:
            if ip.bootp_file:
                return True
        return False

    ######################
    # Validation helpers #
    ######################

    def _validate_name(self, name):
        util.validate_name(_("Network"), name)

        try:
            self.conn.networkLookupByName(name)
        except libvirt.libvirtError:
            return
        raise ValueError(_("Name '%s' already in use by another network." %
                         name))


    ##################
    # XML properties #
    ##################

    _XML_ROOT_NAME = "network"
    _XML_PROP_ORDER = ["ipv6", "name", "uuid", "forward", "virtualport_type",
                       "bridge", "stp", "delay", "domain_name",
                       "macaddr", "ips", "routes", "bandwidth"]

    ipv6 = XMLProperty("./@ipv6", is_yesno=True)
    name = XMLProperty("./name", validate_cb=_validate_name)
    uuid = XMLProperty("./uuid")

    virtualport_type = XMLProperty("./virtualport/@type")

    # Not entirely correct, there can be multiple routes
    forward = XMLChildProperty(_NetworkForward, is_single=True)

    domain_name = XMLProperty("./domain/@name")

    bridge = XMLProperty("./bridge/@name")
    stp = XMLProperty("./bridge/@stp", is_onoff=True)
    delay = XMLProperty("./bridge/@delay", is_int=True)
    macaddr = XMLProperty("./mac/@address")

    portgroups = XMLChildProperty(_NetworkPortgroup)
    ips = XMLChildProperty(_NetworkIP)
    routes = XMLChildProperty(_NetworkRoute)
    bandwidth = XMLChildProperty(_NetworkBandwidth, is_single=True)

    def add_ip(self):
        ip = _NetworkIP(self.conn)
        self.add_child(ip)
        return ip
    def add_route(self):
        route = _NetworkRoute(self.conn)
        self.add_child(route)
        return route


    ##################
    # build routines #
    ##################

    def install(self, start=True, autostart=True):
        xml = self.get_xml_config()
        logging.debug("Creating virtual network '%s' with xml:\n%s",
                      self.name, xml)

        net = self.conn.networkDefineXML(xml)
        try:
            if start:
                net.create()
            if autostart:
                net.setAutostart(autostart)
        except Exception:
            net.undefine()
            raise

        return net
