#
# Copyright (C) 2006 Red Hat, Inc.
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

import gobject
import libvirt
import libxml2
import os
import sys
import logging
from virtManager.IPy import IP

class vmmNetwork(gobject.GObject):
    __gsignals__ = { }

    def __init__(self, config, connection, net, uuid, active):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.net = net
        self.uuid = uuid
        self.active = active

    def set_handle(self, net):
        self.net = net

    def set_active(self, state):
        self.active = state

    def is_active(self):
        return self.active

    def get_connection(self):
        return self.connection

    def get_name(self):
        return self.net.name()

    def get_label(self):
        return self.get_name()

    def get_uuid(self):
        return self.uuid

    def get_bridge_device(self):
        return self.net.bridgeName()

    def start(self):
        self.net.create()

    def stop(self):
        name = self.get_name()
        self.net.destroy()
        # XXX nasty nasty hack - destroy() kills the virNetworkPtr object
        # so we have to grab a new one
        self.net = self.connection.vmm.networkLookupByName(name)

    def delete(self):
        self.net.undefine()
        # The virNetworkPtr is dead after this point, so nullify it
        self.net = None

    def set_autostart(self, value):
        self.net.setAutostart(value)

    def get_autostart(self):
        return self.net.autostart()

    def get_ipv4_network(self):
        try:
            xml = self.net.XMLDesc(0)
            doc = libxml2.parseDoc(xml)
            addrStr = self._get_xml_path(doc, "/network/ip/@address")
            netmaskStr = self._get_xml_path(doc, "/network/ip/@netmask")

            netmask = IP(netmaskStr)
            gateway = IP(addrStr)

            network = IP(gateway.int() & netmask.int())
            return IP(str(network)+ "/" + netmaskStr)
        finally:
            if doc is not None:
                doc.freeDoc()

    def get_ipv4_forward(self):
        try:
            xml = self.net.XMLDesc(0)
            doc = libxml2.parseDoc(xml)
            fw = self._get_xml_path(doc, "string(count(/network/forward))")

            if fw != None and int(fw) != 0:
                forwardDev = self._get_xml_path(doc, "string(/network/forward/@dev)")
                return [True, forwardDev]
            else:
                return [False, None]
        finally:
            if doc is not None:
                doc.freeDoc()

    def get_ipv4_dhcp_range(self):
        try:
            xml = self.net.XMLDesc(0)
            doc = libxml2.parseDoc(xml)
            dhcpstart = self._get_xml_path(doc, "/network/ip/dhcp/range[1]/@start")
            dhcpend = self._get_xml_path(doc, "/network/ip/dhcp/range[1]/@end")
            return [IP(dhcpstart), IP(dhcpend)]
        finally:
            if doc is not None:
                doc.freeDoc()

    def is_read_only(self):
        if self.connection.is_read_only():
            return True
        return False

    def _get_xml_path(self, doc, path):
        ctx = doc.xpathNewContext()
        try:
            ret = ctx.xpathEval(path)
            str = None
            if ret != None:
                if type(ret) == list:
                    if len(ret) == 1:
                        str = ret[0].content
                else:
                    str = ret
            ctx.xpathFreeContext()
            return str
        except:
            ctx.xpathFreeContext()
            return None

gobject.type_register(vmmNetwork)
