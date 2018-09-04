# Copyright (C) 2006, 2013-2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import ipaddress
import logging

from virtinst import Network

from .libvirtobject import vmmLibvirtObject


def _make_addr_str(addrStr, prefix, netmaskStr):
    if prefix:
        return str(
            ipaddress.ip_network(
                str("{}/{}").format(addrStr, prefix), strict=False
            )
        )
    elif netmaskStr:
        netmask = ipaddress.ip_address(str((netmaskStr)))
        network = ipaddress.ip_address(str((addrStr)))
        return str(
            ipaddress.ip_network(
                str("{}/{}").format(network, netmask), strict=False
            )
        )
    else:
        return str(ipaddress.ip_network(str(addrStr), strict=False))


class vmmNetwork(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, Network)

        self._leases = None


    ##########################
    # Required class methods #
    ##########################

    def _conn_tick_poll_param(self):
        return "pollnet"
    def class_name(self):
        return "network"

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _define(self, xml):
        return self.conn.define_network(xml)
    def _using_events(self):
        return self.conn.using_network_events
    def _check_supports_isactive(self):
        return self.conn.check_support(
            self.conn.SUPPORT_NET_ISACTIVE, self._backend)
    def _get_backend_status(self):
        return self._backend_get_active()

    def tick(self, stats_update=True):
        ignore = stats_update
        self._refresh_status()

    def _init_libvirt_state(self):
        self.tick()


    ###########
    # Actions #
    ###########

    @vmmLibvirtObject.lifecycle_action
    def start(self):
        self._backend.create()

    @vmmLibvirtObject.lifecycle_action
    def stop(self):
        self._backend.destroy()

    @vmmLibvirtObject.lifecycle_action
    def delete(self, force=True):
        ignore = force
        self._backend.undefine()
        self._backend = None


    ###############################
    # XML/config handling parsing #
    ###############################

    def get_autostart(self):
        return self._backend.autostart()
    def set_autostart(self, value):
        self._backend.setAutostart(value)

    def refresh_dhcp_leases(self):
        try:
            self._leases = self._backend.DHCPLeases()
        except Exception as e:
            logging.debug("Error getting %s DHCP leases: %s", self, str(e))
            self._leases = []

    def get_dhcp_leases(self):
        if self._leases is None:
            self.refresh_dhcp_leases()
        return self._leases

    def set_qos(self, **kwargs):
        xmlobj = self._make_xmlobj_to_define()
        q = xmlobj.bandwidth
        for key, val in kwargs.items():
            setattr(q, key, val)

        self._redefine_xmlobj(xmlobj)
        return self.is_active()

    def get_uuid(self):
        return self.get_xmlobj().uuid
    def get_bridge_device(self):
        return self.get_xmlobj().bridge
    def get_name_domain(self):
        return self.get_xmlobj().domain_name
    def get_ipv6_enabled(self):
        return self.get_xmlobj().ipv6
    def get_ipv4_forward_mode(self):
        return self.get_xmlobj().forward.mode
    def pretty_forward_mode(self):
        return self.get_xmlobj().forward.pretty_desc()
    def get_qos(self):
        return self.get_xmlobj().bandwidth

    def can_pxe(self):
        return self.get_xmlobj().can_pxe()

    def _get_static_route(self, family):
        xmlobj = self.get_xmlobj()
        route = None
        for r in xmlobj.routes:
            if (r.family == family or (family == "ipv4" and not r.family)):
                route = r
                break
        if not route:
            return [None, None]

        routeAddr = _make_addr_str(route.address, route.prefix, route.netmask)
        routeVia = str(ipaddress.ip_address(str(route.gateway)))

        if not routeAddr or not routeVia:
            return [None, None]
        return [routeAddr, routeVia]

    def _get_network(self, family):
        dhcpstart = None
        dhcpend = None

        xmlobj = self.get_xmlobj()
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
            dhcp = [str(ipaddress.ip_address(str(dhcpstart))),
                    str(ipaddress.ip_address(str(dhcpend)))]
        return [ret, dhcp]

    def get_ipv4_network(self):
        ret = self._get_network("ipv4")
        return ret + [self._get_static_route("ipv4")]
    def get_ipv6_network(self):
        ret = self._get_network("ipv6")
        return ret + [self._get_static_route("ipv6")]

    def get_sriov_vf_networks(self):
        xmlobj = self.get_xmlobj()
        pf_name = None
        vfs = None
        ret = False
        if xmlobj.forward.mode == "hostdev":
            ret = True
            if xmlobj.forward.pf:
                pf_name = xmlobj.forward.pf[0].dev
                vfs = xmlobj.forward.vfs
        return (ret, pf_name, vfs)
