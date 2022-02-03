#
# Copyright 2009, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceVideo(Device):
    XML_NAME = "video"

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
        if not guest.os.is_hvm():
            return None
        if guest.os.is_pseries():
            return "vga"
        if guest.os.is_arm_machvirt():
            # For all cases here the hv and guest are new enough for virtio
            return "virtio"
        if guest.os.is_riscv_virt():
            # For all cases here the hv and guest are new enough for virtio
            return "virtio"
        if guest.os.is_s390x() and guest.conn.is_qemu():
            # s390x doesn't support any of the PCI video devices
            return "virtio"
        if guest.has_spice() and guest.has_gl():
            # virtio is implied in this case
            return "virtio"

        if (guest.lookup_domcaps().supports_video_virtio() and
            guest.osinfo.supports_virtiogpu()):
            # When the guest supports it, this is the top preference
            return "virtio"
        if (guest.os.is_x86() and
            guest.has_spice() and
            guest.lookup_domcaps().supports_video_qxl()):
            # qxl is only beneficial over regular vga when paired with spice.
            # The device still may not be available though
            return "qxl"
        if (guest.is_uefi() and
            guest.lookup_domcaps().supports_video_bochs()):
            return "bochs"
        return "vga"

    def set_defaults(self, guest):
        if not self.model:
            self.model = self.default_model(guest)
        if self.model == 'virtio' and guest.has_gl():
            self.accel3d = True
