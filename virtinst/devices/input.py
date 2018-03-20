#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceInput(Device):
    _XML_ROOT_NAME = "input"

    TYPE_MOUSE = "mouse"
    TYPE_TABLET = "tablet"
    TYPE_KEYBOARD = "keyboard"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_MOUSE, TYPE_TABLET, TYPE_KEYBOARD, TYPE_DEFAULT]

    BUS_PS2 = "ps2"
    BUS_USB = "usb"
    BUS_XEN = "xen"
    BUS_DEFAULT = "default"
    BUSES = [BUS_PS2, BUS_USB, BUS_XEN, BUS_DEFAULT]

    type = XMLProperty("./@type",
                       default_cb=lambda s: s.TYPE_MOUSE,
                       default_name=TYPE_DEFAULT)

    def _default_bus(self):
        if self.type == self.TYPE_TABLET:
            return self.BUS_USB
        if self.conn.is_xen():
            return self.BUS_XEN
        return self.BUS_PS2
    bus = XMLProperty("./@bus",
                      default_cb=_default_bus,
                      default_name=BUS_DEFAULT)
