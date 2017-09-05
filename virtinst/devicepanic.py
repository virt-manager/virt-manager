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
    MODEL_PSERIES = "pseries"
    MODEL_HYPERV = "hyperv"
    MODEL_S390 = "s390"
    MODELS = [MODEL_ISA, MODEL_PSERIES, MODEL_HYPERV, MODEL_S390]

    ISA_ADDRESS_TYPE = "isa"

    @staticmethod
    def get_pretty_model(panic_model):
        if panic_model == VirtualPanicDevice.MODEL_ISA:
            return _("ISA")
        elif panic_model == VirtualPanicDevice.MODEL_PSERIES:
            return _("pSeries")
        elif panic_model == VirtualPanicDevice.MODEL_HYPERV:
            return _("Hyper-V")
        elif panic_model == VirtualPanicDevice.MODEL_S390:
            return _("s390")
        return panic_model

    @staticmethod
    def get_models(os):
        if os.is_x86():
            return [VirtualPanicDevice.MODEL_ISA, VirtualPanicDevice.MODEL_HYPERV]
        elif os.is_pseries():
            return [VirtualPanicDevice.MODEL_PSERIES]
        elif os.is_s390x():
            return [VirtualPanicDevice.MODEL_S390]
        return None

    @staticmethod
    def get_default_model(os):
        models = VirtualPanicDevice.get_models(os)
        if models:
            return models[0]
        return None

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
