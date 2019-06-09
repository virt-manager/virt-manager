#
# Copyright 2013 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DevicePanic(Device):
    XML_NAME = "panic"

    MODEL_ISA = "isa"
    MODEL_PSERIES = "pseries"
    MODEL_HYPERV = "hyperv"
    MODEL_S390 = "s390"

    model = XMLProperty("./@model")


    ##################
    # Default config #
    ##################

    @staticmethod
    def get_models(guest):
        if guest.os.is_x86():
            return [DevicePanic.MODEL_ISA,
                    DevicePanic.MODEL_HYPERV]
        elif guest.os.is_pseries():
            return [DevicePanic.MODEL_PSERIES]
        elif guest.os.is_s390x():
            return [DevicePanic.MODEL_S390]
        return []

    @staticmethod
    def get_default_model(guest):
        models = DevicePanic.get_models(guest)
        if models:
            return models[0]
        return None

    def set_defaults(self, guest):
        if not self.address.type and self.address.iobase:
            self.address.type = "isa"
        if not self.model:
            self.model = DevicePanic.get_default_model(guest)
