#
# Copyright 2011, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
# Marc-Andre Lureau <marcandre.lureau@redhat.com>
#
# Copyright 2013 IBM Corporation
# Author: Stefan Berger <stefanb@linux.vnet.ibm.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceTpm(Device):
    XML_NAME = "tpm"

    VERSION_1_2 = "1.2"
    VERSION_2_0 = "2.0"
    VERSION_DEFAULT = "default"
    VERSIONS = [VERSION_1_2, VERSION_2_0]

    TYPE_PASSTHROUGH = "passthrough"
    TYPE_EMULATOR = "emulator"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_PASSTHROUGH, TYPE_EMULATOR]

    MODEL_TIS = "tpm-tis"
    MODEL_CRB = "tpm-crb"
    MODEL_DEFAULT = "default"
    MODELS = [MODEL_TIS, MODEL_CRB]

    @staticmethod
    def get_pretty_type(tpm_type):
        if tpm_type == DeviceTpm.TYPE_PASSTHROUGH:
            return _("Passthrough device")
        if tpm_type == DeviceTpm.TYPE_EMULATOR:
            return _("Emulated device")
        return tpm_type

    @staticmethod
    def get_pretty_model(tpm_model):
        if tpm_model == DeviceTpm.MODEL_TIS:
            return _("TIS")
        if tpm_model == DeviceTpm.MODEL_CRB:
            return _("CRB")
        return tpm_model

    def supports_property(self, propname):
        """
        Whether the TPM dev type supports the passed property name
        """
        users = {
            "device_path": [self.TYPE_PASSTHROUGH],
            "version": [self.TYPE_EMULATOR],
        }

        if users.get(propname):
            return self.type in users[propname]

        return hasattr(self, propname)

    type = XMLProperty("./backend/@type",
                       default_cb=lambda s: s.TYPE_PASSTHROUGH)

    def _get_default_version(self):
        if not self.supports_property("version"):
            return None
        return self.VERSION_1_2
    version = XMLProperty("./backend/@version",
                          default_cb=_get_default_version)
    model = XMLProperty("./@model",
                       default_cb=lambda s: s.MODEL_TIS)


    def _get_default_device_path(self):
        if not self.supports_property("device_path"):
            return None
        return "/dev/tpm0"
    device_path = XMLProperty("./backend/device/@path",
                              default_cb=_get_default_device_path)
