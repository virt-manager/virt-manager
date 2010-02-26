#
# Copyright (C) 2009 Red Hat, Inc.
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

import gobject

import virtinst
from virtinst import Interface

from virtManager.libvirtobject import vmmLibvirtObject

class vmmInterface(vmmLibvirtObject):
    __gsignals__ = { }

    def __init__(self, config, connection, interface, name, active):
        vmmLibvirtObject.__init__(self, config, connection)

        self.interface = interface  # Libvirt virInterface object
        self.name = name            # String name
        self.active = active        # bool indicating if it is running

        self._xml = None            # xml cache
        self._xml_flags = None

        (self._inactive_xml_flags,
         self._active_xml_flags) = self.connection.get_interface_flags(
                                                            self.interface)

        self.refresh_xml()

    # Routines from vmmLibvirtObject
    def _XMLDesc(self, flags):
        return self.interface.XMLDesc(flags)

    def _define(self, xml):
        return self.get_connection().interface_define(xml)

    def set_active(self, state):
        self.active = state
        self.refresh_xml()

    def is_active(self):
        return self.active

    def get_name(self):
        return self.name

    def get_mac(self):
        return virtinst.util.get_xml_path(self.get_xml(),
                                          "/interface/mac/@address")

    def start(self):
        self.interface.create(0)
        self.refresh_xml()

    def stop(self):
        self.interface.destroy(0)
        self.refresh_xml()

    def delete(self):
        self.interface.undefine()

    def is_bridge(self):
        typ = self.get_type()
        return typ == "bridge"

    def get_type(self):
        return virtinst.util.get_xml_path(self.get_xml(), "/interface/@type")

    def get_pretty_type(self):
        itype = self.get_type()

        if itype == Interface.Interface.INTERFACE_TYPE_VLAN:
            return "VLAN"
        elif itype:
            return str(itype).capitalize()
        else:
            return "Interface"

    def get_startmode(self):
        return virtinst.util.get_xml_path(self.get_xml(),
                                          "/interface/start/@mode") or "none"
    def set_startmode(self):
        return

    def get_slaves(self):
        typ = self.get_type()
        xpath = "/interface/%s/interface/@name" % typ

        def node_func(ctx):
            nodes = ctx.xpathEval(xpath)
            names = map(lambda x: x.content, nodes)
            ret = []

            for name in names:
                type_path = ("/interface/%s/interface[@name='%s']/@type" %
                             (typ, name))
                nodes = ctx.xpathEval(type_path)

                ret.append((name, nodes and nodes[0].content or "Unknown"))

            return ret

        ret = virtinst.util.get_xml_path(self.get_xml(), func=node_func)

        if not ret:
            return []
        return ret

    def get_slave_names(self):
        # Returns a list of names of all enslaved interfaces
        slaves = self.get_slaves()
        return map(lambda x: x[0], slaves)


gobject.type_register(vmmInterface)
