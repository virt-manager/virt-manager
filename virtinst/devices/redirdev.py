#
# Copyright 2011, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .char import CharSource
from .device import Device
from ..xmlbuilder import XMLChildProperty, XMLProperty


class DeviceRedirdev(Device):
    XML_NAME = "redirdev"

    _XML_PROP_ORDER = ["bus", "type", "source"]

    bus = XMLProperty("./@bus")
    type = XMLProperty("./@type")
    source = XMLChildProperty(CharSource, is_single=True)


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if not self.bus:
            self.bus = "usb"
        if not self.type:
            self.type = "spicevmc"
