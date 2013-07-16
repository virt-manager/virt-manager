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
from virtinst.xmlbuilder import XMLProperty


class VirtualInputDevice(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_INPUT

    TYPE_MOUSE = "mouse"
    TYPE_TABLET = "tablet"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_MOUSE, TYPE_TABLET, TYPE_DEFAULT]

    BUS_PS2 = "ps2"
    BUS_USB = "usb"
    BUS_XEN = "xen"
    BUS_DEFAULT = "default"
    BUSES = [BUS_PS2, BUS_USB, BUS_XEN, BUS_DEFAULT]

    type = XMLProperty(xpath="./@type",
                       default_cb=lambda s: s.TYPE_MOUSE,
                       default_name=TYPE_DEFAULT)
    bus = XMLProperty(xpath="./@bus",
                      default_cb=lambda s: s.BUS_XEN,
                      default_name=BUS_DEFAULT)
