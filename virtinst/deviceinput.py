#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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


class VirtualInputDevice(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_INPUT

    TYPE_MOUSE = "mouse"
    TYPE_TABLET = "tablet"
    TYPE_KEYBOARD = "keyboard"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_MOUSE, TYPE_TABLET, TYPE_KEYBOARD, TYPE_DEFAULT]

    BUS_PS2 = "ps2"
    BUS_USB = "usb"
    BUS_XEN = "xen"
    BUS_DEFAULT = "default"
    BUSES = [BUS_PS2, BUS_USB, BUS_XEN, BUS_DEFAULT]

    type = XMLProperty("./@type",
                       default_cb=lambda s: s.TYPE_MOUSE,
                       default_name=TYPE_DEFAULT)

    def _default_bus(self):
        if self.type == self.TYPE_TABLET:
            return self.BUS_USB
        if self.conn.is_xen():
            return self.BUS_XEN
        return self.BUS_PS2
    bus = XMLProperty("./@bus",
                      default_cb=_default_bus,
                      default_name=BUS_DEFAULT)


VirtualInputDevice.register_type()
