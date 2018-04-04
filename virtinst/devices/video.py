#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceVideo(Device):
    XML_NAME = "video"

    # Default models list
    MODEL_DEFAULT = "default"
    MODELS = ["cirrus", "vga", "vmvga", "xen", "qxl", "virtio"]

    @staticmethod
    def pretty_model(model):
        if model in ["qxl", "vmvga", "vga"]:
            return model.upper()
        return model.capitalize()

    _XML_PROP_ORDER = ["model", "vram", "heads", "vgamem"]
    model = XMLProperty("./model/@type",
                        default_cb=lambda s: "cirrus",
                        default_name=MODEL_DEFAULT)
    vram = XMLProperty("./model/@vram", is_int=True)
    vram64 = XMLProperty("./model/@vram64", is_int=True)
    ram = XMLProperty("./model/@ram", is_int=True)
    heads = XMLProperty("./model/@heads", is_int=True)
    vgamem = XMLProperty("./model/@vgamem", is_int=True)
    accel3d = XMLProperty("./model/acceleration/@accel3d", is_yesno=True)
