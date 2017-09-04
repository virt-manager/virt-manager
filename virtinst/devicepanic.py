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

    MODEL_DEFAULT = "default"
    MODEL_ISA = "isa"
    MODELS = [MODEL_ISA]

    ISA_ADDRESS_TYPE = "isa"

    @staticmethod
    def get_pretty_model(panic_model):
        if panic_model == VirtualPanicDevice.MODEL_ISA:
            return _("ISA")
        return panic_model

    def _get_default_address_type(self):
        if self.iobase:
            return VirtualPanicDevice.ISA_ADDRESS_TYPE
        return None

    model = XMLProperty("./@model",
                        default_cb=lambda s: VirtualPanicDevice.MODEL_ISA,
                        default_name=MODEL_DEFAULT)
    type = XMLProperty("./address/@type",
                       default_cb=_get_default_address_type)
    iobase = XMLProperty("./address/@iobase")

VirtualPanicDevice.register_type()
