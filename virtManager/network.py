#
# Copyright (C) 2006, 2013 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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
#
from virtManager import util
import ipaddr
import libxml2
from virtManager.libvirtobject import vmmLibvirtObject


class vmmNetwork(vmmLibvirtObject):
    @staticmethod
    def pretty_desc(forward, forwardDev):
        if forward or forwardDev:
            if not forward or forward == "nat":
                if forwardDev:
                    desc = _("NAT to %s") % forwardDev
                else:
                    desc = _("NAT")
            elif forward == "route":
                if forwardDev:
                    desc = _("Route to %s") % forwardDev
                else:
                    desc = _("Routed network")
            else:
                if forwardDev:
                    desc = "%s to %s" % (forward, forwardDev)
                else:
                    desc = "%s network" % forward.capitalize()
        else:
            desc = _("Isolated network, internal and host routing only")

        return desc

    def __init__(self, conn, net, uuid):
        vmmLibvirtObject.__init__(self, conn)
        self.net = net
        self.uuid = uuid
        self.active = True

        self._support_isactive = None

        self.tick()


    # Required class methods
    def get_name(self):
        return self.net.name()
    def _XMLDesc(self, flags):
        return self.net.XMLDesc(flags)
    def _define(self, xml):
        return self.conn.get_backend().networkDefineXML(xml)

    def set_active(self, state):
        if state == self.active:
            return
        self.idle_emit(state and "started" or "stopped")
        self.active = state

    def is_active(self):
        return self.active

    def get_label(self):
        return self.get_name()

    def get_uuid(self):
        return self.uuid

    def get_bridge_device(self):
        try:
            return self.net.bridgeName()
        except:
            return ""

    def start(self):
        self.net.create()

    def stop(self):
        self.net.destroy()

    def delete(self):
        self.net.undefine()
        self.net = None

    def set_autostart(self, value):
        self.net.setAutostart(value)

    def get_autostart(self):
        return self.net.autostart()

    def _backend_get_active(self):
        if self._support_isactive is None:
            self._support_isactive = self.conn.check_net_support(
                                        self.net,
                                        self.conn.SUPPORT_NET_ISACTIVE)

        if not self._support_isactive:
            return True
        return bool(self.net.isActive())

    def tick(self):
        self.set_active(self._backend_get_active())


    ########################
    # XML parsing routines #
    ########################

    def get_ipv4_static_route(self):
        doc = None
        ret = None
        routeAddr = None
        routeVia = None
        xml = self.get_xml()
        doc = libxml2.parseDoc(xml)
        nodes = doc.xpathEval('//route')
        for node in nodes:
            family = node.xpathEval('string(./@family)')
            if not family or family == 'ipv4':
                addrStr    = node.xpathEval('string(./@address)')
                netmaskStr = node.xpathEval('string(./@netmask)')
                gatewayStr = node.xpathEval('string(./@gateway)')
                prefix     = node.xpathEval('string(./@prefix)')
                if prefix:
                    prefix = int(prefix)
                    routeAddr = str(ipaddr.IPNetwork(str(addrStr) + "/" + str(prefix)).masked())
                elif netmaskStr:
                    netmask = ipaddr.IPAddress(netmaskStr)
                    network = ipaddr.IPAddress(addrStr)
                    routeAddr = str(ipaddr.IPNetwork(str(network) + "/" + str(netmask)).masked())
                else:
                    routeAddr = str(ipaddr.IPNetwork(str(addrStr)))
                routeVia = str(ipaddr.IPAddress(str(gatewayStr)))
                break

        if doc:
            doc.freeDoc()
        if routeAddr and routeVia:
            ret = [routeAddr, routeVia]
        else:
            ret = None
        return ret

    def get_ipv4_network(self):
        doc = None
        ret = None
        goodNode = None
        dhcpstart = None
        dhcpend = None
        xml = self.get_xml()
        doc = libxml2.parseDoc(xml)
        nodes = doc.xpathEval('//ip')
        for node in nodes:
            family = node.xpathEval('string(./@family)')
            if not family or family == 'ipv4':
                dhcp = node.xpathEval('string(./dhcp)')
                if dhcp:
                    dhcpstart = node.xpathEval('string(./dhcp/range[1]/@start)')
                    dhcpend = node.xpathEval('string(./dhcp/range[1]/@end)')
                    goodNode = node
                    break

        if goodNode is None:
            for node in nodes:
                family = node.xpathEval('string(./@family)')
                if not family or family == 'ipv4':
                    goodNode = node
                    break

        if goodNode:
            addrStr    = goodNode.xpathEval('string(./@address)')
            netmaskStr = goodNode.xpathEval('string(./@netmask)')
            prefix     = goodNode.xpathEval('string(./@prefix)')
            if prefix:
                prefix = int(prefix)
                ret = str(ipaddr.IPNetwork(str(addrStr) + "/" + str(prefix)).masked())
            elif netmaskStr:
                netmask = ipaddr.IPAddress(netmaskStr)
                network = ipaddr.IPAddress(addrStr)
                ret = str(ipaddr.IPNetwork(str(network) + "/" + str(netmask)).masked())
            else:
                ret = str(ipaddr.IPNetwork(str(addrStr)))
        if doc:
            doc.freeDoc()
        if dhcpstart and dhcpend:
            dhcp = [str(ipaddr.IPAddress(dhcpstart)), str(ipaddr.IPAddress(dhcpend))]
        else:
            dhcp = None
        route = self.get_ipv4_static_route()
        return [ret, dhcp, route]

    def get_ipv6_static_route(self):
        doc = None
        ret = None
        routeAddr = None
        routeVia = None
        xml = self.get_xml()
        doc = libxml2.parseDoc(xml)
        nodes = doc.xpathEval('//route')
        for node in nodes:
            family = node.xpathEval('string(./@family)')
            if family and family == 'ipv6':
                addrStr    = node.xpathEval('string(./@address)')
                prefix     = node.xpathEval('string(./@prefix)')
                gatewayStr = node.xpathEval('string(./@gateway)')
                if prefix:
                    prefix    = int(prefix)
                    routeAddr = str(ipaddr.IPNetwork(str(addrStr) + "/" + str(prefix)).masked())
                else:
                    routeAddr = str(ipaddr.IPNetwork(str(addrStr)))
                routeVia = str(ipaddr.IPAddress(str(gatewayStr)))
                break

        if doc:
            doc.freeDoc()
        if routeAddr and routeVia:
            ret = [routeAddr, routeVia]
        else:
            ret = None
        return ret

    def get_ipv6_network(self):
        doc = None
        ret = None
        goodNode = None
        dhcpstart = None
        dhcpend = None
        xml = self.get_xml()
        doc = libxml2.parseDoc(xml)
        nodes = doc.xpathEval('//ip')
        for node in nodes:
            family = node.xpathEval('string(./@family)')
            if family and family == 'ipv6':
                dhcp = node.xpathEval('string(./dhcp)')
                if dhcp:
                    dhcpstart = node.xpathEval('string(./dhcp/range[1]/@start)')
                    dhcpend = node.xpathEval('string(./dhcp/range[1]/@end)')
                    goodNode = node
                    break

        if goodNode is None:
            for node in nodes:
                family = node.xpathEval('string(./@family)')
                if family and family == 'ipv6':
                    goodNode = node
                    break

        if goodNode:
            addrStr    = goodNode.xpathEval('string(./@address)')
            prefix     = goodNode.xpathEval('string(./@prefix)')
            if prefix:
                prefix = int(prefix)
                ret = str(ipaddr.IPNetwork(str(addrStr) + "/" + str(prefix)).masked())
            else:
                ret = str(ipaddr.IPNetwork(str(addrStr)))
        if doc:
            doc.freeDoc()
        if dhcpstart and dhcpend:
            dhcp = [str(ipaddr.IPAddress(dhcpstart)), str(ipaddr.IPAddress(dhcpend))]
        else:
            dhcp = None
        route = self.get_ipv6_static_route()
        return [ret, dhcp, route]

    def get_name_domain(self):
        xml = self.get_xml()
        name_domain = util.xpath(xml, "/network/domain/@name")
        return name_domain

    def get_ipv6_routing(self):
        xml = self.get_xml()
        ipv6_routing = util.xpath(xml, "/network/@ipv6")
        return ipv6_routing

    def get_ipv4_forward(self):
        xml = self.get_xml()
        fw = util.xpath(xml, "/network/forward/@mode")
        forwardDev = util.xpath(xml, "/network/forward/@dev")
        return [fw, forwardDev]

    def pretty_forward_mode(self):
        forward, forwardDev = self.get_ipv4_forward()
        return vmmNetwork.pretty_desc(forward, forwardDev)

    def can_pxe(self):
        xml = self.get_xml()
        forward = self.get_ipv4_forward()[0]
        if forward and forward != "nat":
            return True
        return bool(util.xpath(xml, "/network/ip/dhcp/bootp/@file"))
