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

    @staticmethod
    def get_pretty_model(panic_model):
        if panic_model == DevicePanic.MODEL_ISA:
            return _("ISA")
        elif panic_model == DevicePanic.MODEL_PSERIES:
            return _("pSeries")
        elif panic_model == DevicePanic.MODEL_HYPERV:
            return _("Hyper-V")
        elif panic_model == DevicePanic.MODEL_S390:
            return _("s390")
        return panic_model

    @staticmethod
    def get_models(os):
        if os.is_x86():
            return [DevicePanic.MODEL_ISA,
                    DevicePanic.MODEL_HYPERV]
        elif os.is_pseries():
            return [DevicePanic.MODEL_PSERIES]
        elif os.is_s390x():
            return [DevicePanic.MODEL_S390]
        return []

    model = XMLProperty("./@model")
    type = XMLProperty("./address/@type")
    iobase = XMLProperty("./address/@iobase")


    ##################
    # Default config #
    ##################

    @staticmethod
    def get_default_model(guest):
        models = DevicePanic.get_models(guest.os)
        if models:
            return models[0]
        return None

    def set_defaults(self, guest):
        if not self.type and self.iobase:
            self.type = "isa"
        if not self.model:
            self.model = self.get_default_model(guest)
