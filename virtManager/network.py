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

import ipaddr

from virtinst import Network

from virtManager.libvirtobject import vmmLibvirtObject


def _make_addr_str(addrStr, prefix, netmaskStr):
    if prefix:
        return str(ipaddr.IPNetwork(str(addrStr) + "/" +
                                      str(prefix)).masked())
    elif netmaskStr:
        netmask = ipaddr.IPAddress(netmaskStr)
        network = ipaddr.IPAddress(addrStr)
        return str(ipaddr.IPNetwork(str(network) + "/" +
                                    str(netmask)).masked())
    else:
        return str(ipaddr.IPNetwork(str(addrStr)))


class vmmNetwork(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, parseclass=Network)
        self._active = True

        self._support_isactive = None

        self.tick()


    ##########################
    # Required class methods #
    ##########################

    def get_name(self):
        return self._backend.name()
    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _define(self, xml):
        return self.conn.define_network(xml)


    ###########
    # Actions #
    ###########

    def _backend_get_active(self):
        if self._support_isactive is None:
            self._support_isactive = self.conn.check_net_support(
                                        self._backend,
                                        self.conn.SUPPORT_NET_ISACTIVE)

        if not self._support_isactive:
            return True
        return bool(self._backend.isActive())

    def _set_active(self, state):
        if state == self._active:
            return
        self.idle_emit(state and "started" or "stopped")
        self._active = state

    def is_active(self):
        return self._active

    def _kick_conn(self):
        self.conn.schedule_priority_tick(pollnet=True)

    def start(self):
        self._backend.create()
        self._kick_conn()

    def stop(self):
        self._backend.destroy()
        self._kick_conn()

    def delete(self):
        self._backend.undefine()
        self._backend = None
        self._kick_conn()

    def get_autostart(self):
        return self._backend.autostart()
    def set_autostart(self, value):
        self._backend.setAutostart(value)

    def tick(self):
        self._set_active(self._backend_get_active())


    ###############
    # XML parsing #
    ###############

    def get_uuid(self):
        return self._get_xmlobj().uuid
    def get_bridge_device(self):
        return self._get_xmlobj().bridge
    def get_name_domain(self):
        return self._get_xmlobj().domain_name
    def get_ipv6_enabled(self):
        return self._get_xmlobj().ipv6
    def get_ipv4_forward_mode(self):
        return self._get_xmlobj().forward.mode
    def pretty_forward_mode(self):
        return self._get_xmlobj().forward.pretty_desc()

    def can_pxe(self):
        forward = self.get_ipv4_forward_mode()
        if forward and forward != "nat":
            return True
        for ip in self._get_xmlobj().ips:
            if ip.bootp_file:
                return True
        return False

    def _get_static_route(self, family):
        xmlobj = self._get_xmlobj()
        route = None
        for r in xmlobj.routes:
            if (r.family == family or (family == "ipv4" and not r.family)):
                route = r
                break
        if not route:
            return [None, None]

        routeAddr = _make_addr_str(route.address, route.prefix, route.netmask)
        routeVia = str(ipaddr.IPAddress(str(route.gateway)))

        if not routeAddr or not routeVia:
            return [None, None]
        return [routeAddr, routeVia]

    def _get_network(self, family):
        dhcpstart = None
        dhcpend = None

        xmlobj = self._get_xmlobj()
        ip = None
        for i in xmlobj.ips:
            if (i.family == family or
                (family == "ipv4" and not i.family)):
                if i.ranges:
                    ip = i
                    dhcpstart = i.ranges[0].start
                    dhcpend = i.ranges[0].end
                    break

        if not ip:
            for i in xmlobj.ips:
                if (i.family == family or
                    (family == "ipv4" and not i.family)):
                    ip = i
                    break

        ret = None
        if ip:
            ret = _make_addr_str(ip.address, ip.prefix, ip.netmask)

        dhcp = [None, None]
        if dhcpstart and dhcpend:
            dhcp = [str(ipaddr.IPAddress(dhcpstart)),
                    str(ipaddr.IPAddress(dhcpend))]
        return [ret, dhcp]

    def get_ipv4_network(self):
        ret = self._get_network("ipv4")
        return ret + [self._get_static_route("ipv4")]
    def get_ipv6_network(self):
        ret = self._get_network("ipv6")
        return ret + [self._get_static_route("ipv6")]
