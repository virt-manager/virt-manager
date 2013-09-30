#
# Copyright 2013 Red Hat, Inc.
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
Classes for building and installing libvirt <network> XML
"""

import logging

import libvirt

from virtinst import util
from virtinst.xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


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
        self._add_child(r)
        return r


class _NetworkRoute(XMLBuilder):
    _XML_ROOT_NAME = "route"

    family = XMLProperty("./@family")
    address = XMLProperty("./@address")
    prefix = XMLProperty("./@prefix", is_int=True)
    gateway = XMLProperty("./@gateway")
    netmask = XMLProperty("./@netmask")


class _NetworkForward(XMLBuilder):
    _XML_ROOT_NAME = "forward"

    mode = XMLProperty("./@mode")
    dev = XMLProperty("./@dev")

    def pretty_desc(self):
        return Network.pretty_forward_desc(self.mode, self.dev)


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
                    desc = "%s to %s" % (mode, dev)
                else:
                    desc = "%s network" % mode.capitalize()
        else:
            desc = _("Isolated network, internal and host routing only")

        return desc

    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)
        self._random_uuid = None


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

    def _check_name_collision(self, name):
        try:
            self.conn.networkLookupByName(name)
        except libvirt.libvirtError:
            return
        raise ValueError(_("Name '%s' already in use by another network." %
                         name))

    def _get_default_uuid(self):
        if self._random_uuid is None:
            self._random_uuid = util.generate_uuid(self.conn)
        return self._random_uuid


    ##################
    # XML properties #
    ##################

    _XML_ROOT_NAME = "network"
    _XML_PROP_ORDER = ["ipv6", "name", "uuid", "forward",
                       "bridge", "stp", "delay", "domain_name",
                       "macaddr", "ips", "routes"]

    ipv6 = XMLProperty("./@ipv6", is_yesno=True)
    name = XMLProperty("./name", validate_cb=_check_name_collision)
    uuid = XMLProperty("./uuid",
                       validate_cb=lambda s, v: util.validate_uuid(v),
                       default_cb=_get_default_uuid)

    # Not entirely correct, there can be multiple routes
    forward = XMLChildProperty(_NetworkForward, is_single=True)

    domain_name = XMLProperty("./domain/@name")

    bridge = XMLProperty("./bridge/@name")
    stp = XMLProperty("./bridge/@stp", is_onoff=True)
    delay = XMLProperty("./bridge/@delay", is_int=True)
    macaddr = XMLProperty("./mac/@address")

    ips = XMLChildProperty(_NetworkIP)
    routes = XMLChildProperty(_NetworkRoute)

    def add_ip(self):
        ip = _NetworkIP(self.conn)
        self._add_child(ip)
        return ip
    def add_route(self):
        route = _NetworkRoute(self.conn)
        self._add_child(route)
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
        except:
            net.undefine()
            raise

        return net
