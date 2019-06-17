#
# Copyright 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
"""
Classes for building and installing libvirt <network> XML
"""

from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _NetworkDHCPRange(XMLBuilder):
    XML_NAME = "range"
    start = XMLProperty("./@start")
    end = XMLProperty("./@end")


class _NetworkDHCPHost(XMLBuilder):
    XML_NAME = "host"
    macaddr = XMLProperty("./@mac")
    name = XMLProperty("./@name")
    ip = XMLProperty("./@ip")


class _NetworkIP(XMLBuilder):
    XML_NAME = "ip"

    family = XMLProperty("./@family")
    address = XMLProperty("./@address")
    prefix = XMLProperty("./@prefix", is_int=True)
    netmask = XMLProperty("./@netmask")

    tftp = XMLProperty("./tftp/@root")
    bootp_file = XMLProperty("./dhcp/bootp/@file")
    bootp_server = XMLProperty("./dhcp/bootp/@server")

    ranges = XMLChildProperty(_NetworkDHCPRange, relative_xpath="./dhcp")
    hosts = XMLChildProperty(_NetworkDHCPHost, relative_xpath="./dhcp")


class _NetworkRoute(XMLBuilder):
    XML_NAME = "route"

    family = XMLProperty("./@family")
    address = XMLProperty("./@address")
    prefix = XMLProperty("./@prefix", is_int=True)
    gateway = XMLProperty("./@gateway")
    netmask = XMLProperty("./@netmask")


class _NetworkForwardPf(XMLBuilder):
    XML_NAME = "pf"
    dev = XMLProperty("./@dev")


class _NetworkForward(XMLBuilder):
    XML_NAME = "forward"

    mode = XMLProperty("./@mode")
    dev = XMLProperty("./@dev")
    managed = XMLProperty("./@managed")
    pf = XMLChildProperty(_NetworkForwardPf)


class _NetworkPortgroup(XMLBuilder):
    XML_NAME = "portgroup"

    name = XMLProperty("./@name")
    default = XMLProperty("./@default", is_yesno=True)


class Network(XMLBuilder):
    """
    Top level class for <network> object XML
    """
    XML_NAME = "network"
    _XML_PROP_ORDER = ["ipv6", "name", "uuid", "forward", "virtualport_type",
                       "bridge", "stp", "delay", "domain_name",
                       "macaddr", "ips", "routes"]

    ipv6 = XMLProperty("./@ipv6", is_yesno=True)
    name = XMLProperty("./name")
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
