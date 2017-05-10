#
# Copyright (C) 2009, 2013 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
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

from virtinst import Interface

from .libvirtobject import vmmLibvirtObject


class vmmInterface(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, Interface)


    ##########################
    # Required class methods #
    ##########################

    # Routines from vmmLibvirtObject
    def _conn_tick_poll_param(self):
        return "polliface"
    def class_name(self):
        return "interface"

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _define(self, xml):
        return self.conn.define_interface(xml)
    def _check_supports_isactive(self):
        return self.conn.check_support(
            self.conn.SUPPORT_INTERFACE_ISACTIVE, self._backend)
    def _get_backend_status(self):
        return self._backend_get_active()

    def tick(self, stats_update=True):
        ignore = stats_update
        self._refresh_status()

    def _init_libvirt_state(self):
        (self._inactive_xml_flags,
         self._active_xml_flags) = self.conn.get_interface_flags(self._backend)

        self.tick()


    #####################
    # Object operations #
    #####################

    @vmmLibvirtObject.lifecycle_action
    def start(self):
        self._backend.create(0)

    @vmmLibvirtObject.lifecycle_action
    def stop(self):
        self._backend.destroy(0)

    @vmmLibvirtObject.lifecycle_action
    def delete(self, force=True):
        self._backend.undefine()


    ################
    # XML routines #
    ################

    def get_mac(self):
        return self.get_xmlobj().macaddr

    def is_bridge(self):
        typ = self.get_type()
        return typ == "bridge"

    def get_type(self):
        return self.get_xmlobj().type

    def get_pretty_type(self):
        itype = self.get_type()

        if itype == Interface.INTERFACE_TYPE_VLAN:
            return "VLAN"
        elif itype:
            return str(itype).capitalize()
        else:
            return _("Interface")

    def get_startmode(self):
        return self.get_xmlobj(inactive=True).start_mode or "none"

    def set_startmode(self, newmode):
        xmlobj = self._make_xmlobj_to_define()
        xmlobj.start_mode = newmode
        self._redefine_xmlobj(xmlobj)

    def get_slaves(self):
        return [[obj.name, obj.type or _("Unknown")] for obj in
                self.get_xmlobj().interfaces]

    def get_slave_names(self):
        # Returns a list of names of all enslaved interfaces
        return [x[0] for x in self.get_slaves()]

    def _get_ip(self, iptype):
        # Get list of IP addresses from active XML and protocol configuration
        # from inactive XML to figure out whether the IP address is static or
        # from DHCP server.
        activeObj = self.get_xmlobj()
        inactiveObj = self.get_xmlobj(inactive=True)

        activeProto = None
        inactiveProto = None
        for protocol in activeObj.protocols:
            if protocol.family == iptype:
                activeProto = protocol
                break
        for protocol in inactiveObj.protocols:
            if protocol.family == iptype:
                inactiveProto = protocol
                break

        if not activeProto and not inactiveProto:
            return None, []

        ret = []
        if activeProto:
            for ip in activeProto.ips:
                ipstr = ip.address
                if not ipstr:
                    continue
                if ip.prefix:
                    ipstr += "/%s" % ip.prefix
                ret.append(ipstr)
        return inactiveProto or activeProto, ret

    def get_ipv4(self):
        proto, ips = self._get_ip("ipv4")
        if proto is None:
            return []

        ipstr = None
        if ips:
            ipstr = ips[0]
        return [proto.dhcp, ipstr]

    def get_ipv6(self):
        proto, ips = self._get_ip("ipv6")
        if proto is None:
            return []
        return [proto.dhcp, proto.autoconf, ips]

    def get_protocol_xml(self, inactive=False):
        return self.get_xmlobj(inactive=inactive).protocols[:]
