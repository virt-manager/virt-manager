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

    @staticmethod
    def get_recommended_models(guest):
        if guest.conn.is_xen():
            return ["xen", "vga"]
        if guest.conn.is_qemu() or guest.conn.is_test():
            return ["vga", "qxl", "virtio"]
        return []

    @staticmethod
    def pretty_model(model):
        if model in ["qxl", "vmvga", "vga"]:
            return model.upper()
        return model.capitalize()

    _XML_PROP_ORDER = ["model", "vram", "heads", "vgamem"]
    model = XMLProperty("./model/@type")
    vram = XMLProperty("./model/@vram", is_int=True)
    vram64 = XMLProperty("./model/@vram64", is_int=True)
    ram = XMLProperty("./model/@ram", is_int=True)
    heads = XMLProperty("./model/@heads", is_int=True)
    vgamem = XMLProperty("./model/@vgamem", is_int=True)
    accel3d = XMLProperty("./model/acceleration/@accel3d", is_yesno=True)


    ##################
    # Default config #
    ##################

    @staticmethod
    def default_model(guest):
        if guest.os.is_pseries():
            return "vga"
        if guest.os.is_arm_machvirt():
            return "virtio"
        if guest.has_spice() and guest.os.is_x86():
            if guest.has_gl():
                return "virtio"
            return "qxl"
        if guest.os.is_hvm():
            if guest.conn.is_qemu():
                return "qxl"
            return "vga"
        return None

    def set_defaults(self, guest):
        if not self.model:
            self.model = self.default_model(guest)
        if self.model == 'virtio' and guest.has_gl():
            self.accel3d = True
