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

from virtManager.libvirtobject import vmmLibvirtObject


class vmmInterface(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key, Interface)

        self._active = True

        (self._inactive_xml_flags,
         self._active_xml_flags) = self.conn.get_interface_flags(self._backend)

        self._support_isactive = None

        self.tick()
        self.refresh_xml()

    # Routines from vmmLibvirtObject
    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def _define(self, xml):
        return self.conn.define_interface(xml)

    def set_active(self, state):
        if state == self._active:
            return

        self.idle_emit(state and "started" or "stopped")
        self._active = state
        self.refresh_xml()

    def _backend_get_active(self):
        ret = True
        if self._support_isactive is None:
            self._support_isactive = self.conn.check_support(
                self.conn.SUPPORT_INTERFACE_ISACTIVE, self._backend)

        if not self._support_isactive:
            return True
        return bool(self._backend.isActive())

    def tick(self):
        self.set_active(self._backend_get_active())

    def is_active(self):
        return self._active

    def get_mac(self):
        return self.get_xmlobj().macaddr

    def _kick_conn(self):
        self.conn.schedule_priority_tick(polliface=True)

    def start(self):
        self._backend.create(0)
        self.idle_add(self.refresh_xml)
        self._kick_conn()

    def stop(self):
        self._backend.destroy(0)
        self.idle_add(self.refresh_xml)
        self._kick_conn()

    def delete(self, force=True):
        ignore = force
        self._backend.undefine()
        self._kick_conn()

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
            return "Interface"

    def get_startmode(self):
        return self.get_xmlobj().start_mode or "none"

    def set_startmode(self, newmode):
        def change(obj):
            obj.start_mode = newmode
        self._redefine(change)
        self.redefine_cached()

    def get_slaves(self):
        return [[obj.name, obj.type or "Unknown"] for obj in
                self.get_xmlobj().interfaces]

    def get_slave_names(self):
        # Returns a list of names of all enslaved interfaces
        return [x[0] for x in self.get_slaves()]

    def _get_ip(self, iptype):
        obj = self.get_xmlobj()
        found = None
        for protocol in obj.protocols:
            if protocol.family == iptype:
                found = protocol
                break
        if not found:
            return None, []

        ret = []
        for ip in found.ips:
            ipstr = ip.address
            if not ipstr:
                continue
            if ip.prefix:
                ipstr += "/%s" % ip.prefix
            ret.append(ipstr)
        return found, ret

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

    def get_protocol_xml(self):
        return self.get_xmlobj().protocols[:]
