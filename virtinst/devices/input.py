#
# Copyright 2009, 2013 Red Hat, Inc.
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
    TYPE_EVDEV = "evdev"

    BUS_PS2 = "ps2"
    BUS_USB = "usb"
    BUS_VIRTIO = "virtio"
    BUS_XEN = "xen"


    type = XMLProperty("./@type")
    bus = XMLProperty("./@bus")
    model = XMLProperty("./@model")

    source_evdev = XMLProperty("./source/@evdev")
    source_dev = XMLProperty("./source/@dev")
    source_repeat = XMLProperty("./source/@repeat", is_onoff=True)
    source_grab = XMLProperty("./source/@grab")
    source_grabToggle = XMLProperty("./source/@grabToggle")


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if not self.type:
            self.type = self.TYPE_MOUSE
