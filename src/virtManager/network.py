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
import virtinst.util as util

from virtManager.IPy import IP

class vmmNetwork(gobject.GObject):
    __gsignals__ = { }

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
            desc = _("Isolated network")

        return desc

    def __init__(self, config, connection, net, uuid, active):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.net = net
        self.uuid = uuid
        self.active = active
        self._xml = self.net.XMLDesc(0)

    def set_handle(self, net):
        self.net = net

    def set_active(self, state):
        self.active = state

    def get_xml(self):
        if not self._xml:
            self._update_xml()
        return self._xml

    def _update_xml(self):
        self._xml = self.net.XMLDesc(0)

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
        del(self.net)
        self.net = None

    def set_autostart(self, value):
        self.net.setAutostart(value)

    def get_autostart(self):
        return self.net.autostart()

    def get_ipv4_network(self):
        xml = self.get_xml()
        addrStr = util.get_xml_path(xml, "/network/ip/@address")
        netmaskStr = util.get_xml_path(xml, "/network/ip/@netmask")

        netmask = IP(netmaskStr)
        gateway = IP(addrStr)

        network = IP(gateway.int() & netmask.int())
        return IP(str(network)+ "/" + netmaskStr)

    def get_ipv4_forward(self):
        xml = self.get_xml()
        fw = util.get_xml_path(xml, "/network/forward/@mode")
        forwardDev = util.get_xml_path(xml, "/network/forward/@dev")
        return [fw, forwardDev]

    def get_ipv4_dhcp_range(self):
        xml = self.get_xml()
        dhcpstart = util.get_xml_path(xml, "/network/ip/dhcp/range[1]/@start")
        dhcpend = util.get_xml_path(xml, "/network/ip/dhcp/range[1]/@end")
        if not dhcpstart or not dhcpend:
            return None

        return [IP(dhcpstart), IP(dhcpend)]

    def pretty_forward_mode(self):
        forward, forwardDev = self.get_ipv4_forward()
        return vmmNetwork.pretty_desc(forward, forwardDev)

    def is_read_only(self):
        if self.connection.is_read_only():
            return True
        return False

gobject.type_register(vmmNetwork)
