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
    _XML_PROP_ORDER = ["mode", "type"]

    mode = XMLProperty("./@mode")
    type = XMLProperty("./@type")


    ##################
    # Default config #
    ##################

    def default_type(self):
        return self.mode == "passthrough" and "spicevmc" or "tcp"

    def set_defaults(self, guest):
        if not self.mode:
            self.mode = "passthrough"
        if not self.type:
            self.type = self.default_type()
