# Copyright (C) 2006, 2013-2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import ipaddress

from virtinst import log
from virtinst import Network

from .libvirtobject import vmmLibvirtObject
from ..lib import testmock


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
    def _get_backend_status(self):
        return (bool(self._backend.isActive()) and
                self._STATUS_ACTIVE or
                self._STATUS_INACTIVE)


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
    def set_autostart(self, val):
        self._backend.setAutostart(val)

    def _refresh_dhcp_leases(self):
        ret = []
        try:
            ret = self._backend.DHCPLeases()
        except Exception as e:
            log.debug("Error getting %s DHCP leases: %s", self, str(e))
            if self.conn.is_test():
                ret = testmock.fake_dhcp_leases()
        self._leases = ret

    def get_dhcp_leases(self, refresh=False):
        if self._leases is None or refresh:
            self._refresh_dhcp_leases()
        return self._leases

    def get_bridge_device(self):
        return self.get_xmlobj().bridge
    def get_name_domain(self):
        return self.get_xmlobj().domain_name
    def get_ipv6_enabled(self):
        return self.get_xmlobj().ipv6

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
        return self._get_network("ipv4")
    def get_ipv6_network(self):
        return self._get_network("ipv6")

    def pretty_forward_mode(self):
        mode = self.xmlobj.forward.mode
        dev = self.xmlobj.forward.dev

        if not mode:
            return _("Isolated network")

        if mode == "nat":
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
            modestr = mode.capitalize()
            desc = _("%s network") % modestr

        return desc
