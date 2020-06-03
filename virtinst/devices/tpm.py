#
# Copyright 2011, 2013 Red Hat, Inc.
# Copyright 2013 IBM Corporation
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceTpm(Device):
    XML_NAME = "tpm"

    VERSION_1_2 = "1.2"
    VERSION_2_0 = "2.0"
    VERSIONS = [VERSION_1_2, VERSION_2_0]

    TYPE_PASSTHROUGH = "passthrough"
    TYPE_EMULATOR = "emulator"
    TYPES = [TYPE_PASSTHROUGH, TYPE_EMULATOR]

    MODEL_TIS = "tpm-tis"
    MODEL_CRB = "tpm-crb"
    MODEL_SPAPR = "tpm-spapr"
    MODELS = [MODEL_TIS, MODEL_CRB, MODEL_SPAPR]

    type = XMLProperty("./backend/@type")
    version = XMLProperty("./backend/@version")
    model = XMLProperty("./@model")
    device_path = XMLProperty("./backend/device/@path")
    encryption_secret = XMLProperty("./backend/encryption/@secret")


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if not self.type:
            self.type = self.TYPE_PASSTHROUGH
        if not self.model:
            self.model = self.MODEL_TIS

            if guest.os.is_ppc64():
                self.model = self.MODEL_SPAPR
