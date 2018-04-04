#
# Copyright 2011, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
# Marc-Andre Lureau <marcandre.lureau@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceSmartcard(Device):
    XML_NAME = "smartcard"

    # Default models list
    MODE_DEFAULT = "default"
    MODES = ["passthrough", "host-certificates", "host"]

    TYPE_DEFAULT = "default"
    TYPES = ["tcp", "spicevmc", "default"]


    _XML_PROP_ORDER = ["mode", "type"]

    mode = XMLProperty("./@mode",
                       default_cb=lambda s: "passthrough",
                       default_name=MODE_DEFAULT)

    def _default_type(self):
        if self.mode == self.MODE_DEFAULT or self.mode == "passthrough":
            return "spicevmc"
        return "tcp"
    type = XMLProperty("./@type",
                       default_cb=_default_type,
                       default_name=TYPE_DEFAULT)
