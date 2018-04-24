#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceInput(Device):
    XML_NAME = "input"

    TYPE_MOUSE = "mouse"
    TYPE_TABLET = "tablet"
    TYPE_KEYBOARD = "keyboard"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_MOUSE, TYPE_TABLET, TYPE_KEYBOARD, TYPE_DEFAULT]

    BUS_PS2 = "ps2"
    BUS_USB = "usb"
    BUS_VIRTIO = "virtio"
    BUS_XEN = "xen"
    BUS_DEFAULT = "default"
    BUSES = [BUS_PS2, BUS_USB, BUS_XEN, BUS_DEFAULT]

    @staticmethod
    def pretty_name(typ, bus):
        if typ == "tablet" and bus == "usb":
            return _("EvTouch USB Graphics Tablet")

        if bus in ["usb", "ps2"]:
            return _("Generic") + (" %s %s" %
                (bus.upper(), str(typ).capitalize()))
        return "%s %s" % (str(bus).capitalize(), str(typ).capitalize())


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
