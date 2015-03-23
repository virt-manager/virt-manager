#
# Copyright 2013 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
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


class VirtualPanicDevice(VirtualDevice):

    virtual_device_type = VirtualDevice.VIRTUAL_DEV_PANIC
    ADDRESS_TYPE_ISA = "isa"
    TYPE_DEFAULT = ADDRESS_TYPE_ISA
    TYPES = [ADDRESS_TYPE_ISA]
    IOBASE_DEFAULT = "0x505"

    @staticmethod
    def get_pretty_type(panic_type):
        if panic_type == VirtualPanicDevice.ADDRESS_TYPE_ISA:
            return _("ISA")
        return panic_type


    type = XMLProperty("./address/@type",
                       default_cb=lambda s: s.ADDRESS_TYPE_ISA)
    iobase = XMLProperty("./address/@iobase",
                       default_cb=lambda s: s.IOBASE_DEFAULT)

VirtualPanicDevice.register_type()
