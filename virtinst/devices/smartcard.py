#
# Copyright 2011, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .char import CharSource
from .device import Device
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _Certificate(XMLBuilder):
    XML_NAME = "certificate"

    value = XMLProperty("./.")


class DeviceSmartcard(Device):
    XML_NAME = "smartcard"
    _XML_PROP_ORDER = ["mode", "type"]

    mode = XMLProperty("./@mode")
    type = XMLProperty("./@type")
    source = XMLChildProperty(CharSource, is_single=True)

    database = XMLProperty("./database")
    certificates = XMLChildProperty(_Certificate)


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
