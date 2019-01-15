# Copyright (C) 2018 VMware, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceVsock(Device):
    XML_NAME = "vsock"

    model = XMLProperty("./@model")
    auto_cid = XMLProperty("./cid/@auto", is_yesno=True)
    cid = XMLProperty("./cid/@address", is_int=True)


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if not self.model:
            self.model = "virtio"

        if self.auto_cid is None and self.cid is None:
            self.auto_cid = True
