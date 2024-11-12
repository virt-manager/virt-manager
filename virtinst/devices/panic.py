#
# Copyright 2013 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DevicePanic(Device):
    XML_NAME = "panic"

    model = XMLProperty("./@model")
    set_stub = XMLProperty(".", is_bool=True)


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if not self.address.type and self.address.iobase:
            self.address.type = "isa"
        if not self.model:
            # This asks libvirt to fill in a default
            self.set_stub = True
