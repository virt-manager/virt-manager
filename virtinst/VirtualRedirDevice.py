# -*- coding: utf-8 -*-
#
# Copyright 2011  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
# Marc-André Lureau <marcandre.lureau@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

from virtinst.VirtualDevice import VirtualDevice

from virtinst.XMLBuilderDomain import _xml_property


class VirtualRedirDevice(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_REDIRDEV

    BUS_DEFAULT = "usb"
    _buses = ["usb"]

    TYPE_DEFAULT = "spicevmc"
    _types = ["tcp", "spicevmc", None]

    def __init__(self, bus=BUS_DEFAULT, stype=TYPE_DEFAULT,
                 conn=None, parsexml=None, parsexmlnode=None, caps=None):
        """
        @param conn: Connection the device/guest will be installed on
        @type conn: libvirt.virConnect
        """
        VirtualDevice.__init__(self, conn, parsexml,
                                             parsexmlnode, caps)

        self._type = None
        self._bus = None
        self._host = None
        self._service = None
        if self._is_parse():
            return

        self.bus = bus
        self.type = stype

    def get_buses(self):
        return self._buses[:]
    buses = property(get_buses)

    def get_bus(self):
        return self._bus
    def set_bus(self, new_val):
        if new_val not in self.buses:
            raise ValueError(_("Unsupported bus '%s'" % new_val))
        self._bus = new_val
    bus = _xml_property(get_bus, set_bus,
                        xpath="./@bus")

    def get_types(self):
        return self._types[:]
    types = property(get_types)

    def get_type(self):
        return self._type
    def set_type(self, new_val):
        if new_val not in self.types:
            raise ValueError(_("Unsupported redirection type '%s'" % new_val))
        self._type = new_val
    type = _xml_property(get_type, set_type,
                         xpath="./@type")

    def get_host(self):
        return self._host
    def set_host(self, val):
        if len(val) == 0:
            raise ValueError(_("Invalid host value"))
        self._host = val
    host = _xml_property(get_host, set_host,
                        xpath="./source/@host")

    def get_service(self):
        return self._service
    def set_service(self, val):
        int(val)
        self._service = val
    service = _xml_property(get_service, set_service,
                        xpath="./source/@service")

    def parse_friendly_server(self, serverstr):
        if serverstr.count(":") == 1:
            self.host, self.service = serverstr.split(":")
        else:
            raise ValueError(_("Could not determine or unsupported format of '%s'") % serverstr)

    def _get_xml_config(self):
        xml  = ("    <redirdev bus='%s' type='%s'" %
                    (self.bus, self.type))
        if self.type == 'spicevmc':
            xml += "/>"
            return xml
        xml += ">\n"
        xml += ("      <source mode='connect' host='%s' service='%s'/>\n" %
                    (self.host, self.service))
        xml += "    </redirdev>"
        return xml
