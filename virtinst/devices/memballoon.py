# Copyright (C) 2013 Red Hat, Inc.
#
# Copyright 2012
# Eiichi Tsukata <devel@etsukata.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceMemballoon(Device):
    XML_NAME = "memballoon"

    model = XMLProperty("./@model")


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if not self.model:
            self.model = "virtio"
