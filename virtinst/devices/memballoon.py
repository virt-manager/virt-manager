# Copyright (C) 2013 Red Hat, Inc.
#
# Copyright 2012
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceMemballoon(Device):
    XML_NAME = "memballoon"

    model = XMLProperty("./@model")
    autodeflate = XMLProperty("./@autodeflate", is_onoff=True)
    stats_period = XMLProperty("./stats/@period", is_int=True)
    freePageReporting = XMLProperty("./@freePageReporting", is_onoff=True)


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if not self.model:
            self.model = "virtio"
