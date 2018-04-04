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

    TYPE_PASSTHROUGH = "passthrough"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_PASSTHROUGH]

    MODEL_TIS = "tpm-tis"
    MODEL_DEFAULT = "default"
    MODELS = [MODEL_TIS]

    @staticmethod
    def get_pretty_type(tpm_type):
        if tpm_type == DeviceTpm.TYPE_PASSTHROUGH:
            return _("Passthrough device")
        return tpm_type

    def supports_property(self, propname):
        """
        Whether the TPM dev type supports the passed property name
        """
        users = {
            "device_path": [self.TYPE_PASSTHROUGH],
        }

        if users.get(propname):
            return self.type in users[propname]

        return hasattr(self, propname)

    type = XMLProperty("./backend/@type",
                       default_cb=lambda s: s.TYPE_PASSTHROUGH)
    model = XMLProperty("./@model",
                       default_cb=lambda s: s.MODEL_TIS)
    device_path = XMLProperty("./backend/device/@path",
                              default_cb=lambda s: "/dev/tpm0")
