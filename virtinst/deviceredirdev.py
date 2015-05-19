#
# Copyright 2011, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
# Marc-Andre Lureau <marcandre.lureau@redhat.com>
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

from .device import VirtualDevice
from .xmlbuilder import XMLProperty


class VirtualRedirDevice(VirtualDevice):

    virtual_device_type = VirtualDevice.VIRTUAL_DEV_REDIRDEV

    BUS_DEFAULT = "default"
    BUSES = ["usb"]

    TYPE_DEFAULT = "default"
    TYPES = ["tcp", "spicevmc"]

    @staticmethod
    def pretty_type(typ):
        if typ == "tcp":
            return "TCP"
        if typ == "spicevmc":
            return "SpiceVMC"
        return typ and typ.capitalize()

    def parse_friendly_server(self, serverstr):
        if serverstr.count(":") != 1:
            raise ValueError(_("Could not determine or unsupported "
                               "format of '%s'") % serverstr)
        self.host, self.service = serverstr.split(":")


    _XML_PROP_ORDER = ["bus", "type"]

    bus = XMLProperty("./@bus",
                      default_cb=lambda s: "usb",
                      default_name=BUS_DEFAULT)
    type = XMLProperty("./@type",
                       default_cb=lambda s: "spicevmc",
                       default_name=TYPE_DEFAULT)

    host = XMLProperty("./source/@host")
    service = XMLProperty("./source/@service", is_int=True)


VirtualRedirDevice.register_type()
