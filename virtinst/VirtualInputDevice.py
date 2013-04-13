#
# Copyright 2009  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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


class VirtualInputDevice(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_INPUT

    INPUT_TYPE_MOUSE = "mouse"
    INPUT_TYPE_TABLET = "tablet"
    INPUT_TYPE_DEFAULT = "default"
    input_types = [INPUT_TYPE_MOUSE, INPUT_TYPE_TABLET, INPUT_TYPE_DEFAULT]

    INPUT_BUS_PS2 = "ps2"
    INPUT_BUS_USB = "usb"
    INPUT_BUS_XEN = "xen"
    INPUT_BUS_DEFAULT = "default"
    input_buses = [INPUT_BUS_PS2, INPUT_BUS_USB, INPUT_BUS_XEN,
                   INPUT_BUS_DEFAULT]

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        VirtualDevice.__init__(self, conn, parsexml,
                                             parsexmlnode, caps)

        self._type = None
        self._bus = None

        if self._is_parse():
            return

        self.type = self.INPUT_TYPE_DEFAULT
        self.bus = self.INPUT_BUS_DEFAULT

    def _convert_default_bus(self, val):
        if val == self.INPUT_BUS_DEFAULT:
            return self.INPUT_BUS_XEN
        return val
    def _convert_default_type(self, val):
        if val == self.INPUT_TYPE_DEFAULT:
            return self.INPUT_TYPE_MOUSE
        return val

    def get_type(self):
        return self._type
    def set_type(self, val):
        if val not in self.input_types:
            raise ValueError(_("Unknown input type '%s'.") % val)
        self._type = val
    type = _xml_property(get_type, set_type,
                         xpath="./@type")

    def get_bus(self):
        return self._bus
    def set_bus(self, val):
        if val not in self.input_buses:
            raise ValueError(_("Unknown input bus '%s'.") % val)
        self._bus = val
    bus = _xml_property(get_bus, set_bus,
                        xpath="./@bus")

    def _get_xml_config(self):
        typ = self._convert_default_type(self.type)
        bus = self._convert_default_bus(self.bus)

        return "    <input type='%s' bus='%s'/>" % (typ, bus)
