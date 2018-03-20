#
# Copyright 2010, 2013, 2014 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceController(Device):
    virtual_device_type = Device.DEVICE_CONTROLLER

    TYPE_IDE             = "ide"
    TYPE_FDC             = "fdc"
    TYPE_SCSI            = "scsi"
    TYPE_SATA            = "sata"
    TYPE_VIRTIOSERIAL    = "virtio-serial"
    TYPE_USB             = "usb"
    TYPE_PCI             = "pci"
    TYPE_CCID            = "ccid"
    TYPES = [TYPE_IDE, TYPE_FDC,
             TYPE_SCSI, TYPE_SATA,
             TYPE_VIRTIOSERIAL, TYPE_USB,
             TYPE_PCI, TYPE_CCID]

    @staticmethod
    def pretty_type(ctype):
        pretty_mappings = {
            DeviceController.TYPE_IDE:             "IDE",
            DeviceController.TYPE_FDC:              _("Floppy"),
            DeviceController.TYPE_SCSI:            "SCSI",
            DeviceController.TYPE_SATA:            "SATA",
            DeviceController.TYPE_VIRTIOSERIAL:    "VirtIO Serial",
            DeviceController.TYPE_USB:             "USB",
            DeviceController.TYPE_PCI:             "PCI",
            DeviceController.TYPE_CCID:            "CCID",
       }

        if ctype not in pretty_mappings:
            return ctype
        return pretty_mappings[ctype]

    @staticmethod
    def get_usb2_controllers(conn):
        ret = []
        ctrl = DeviceController(conn)
        ctrl.type = "usb"
        ctrl.model = "ich9-ehci1"
        ret.append(ctrl)

        ctrl = DeviceController(conn)
        ctrl.type = "usb"
        ctrl.model = "ich9-uhci1"
        ctrl.master_startport = 0
        ret.append(ctrl)

        ctrl = DeviceController(conn)
        ctrl.type = "usb"
        ctrl.model = "ich9-uhci2"
        ctrl.master_startport = 2
        ret.append(ctrl)

        ctrl = DeviceController(conn)
        ctrl.type = "usb"
        ctrl.model = "ich9-uhci3"
        ctrl.master_startport = 4
        ret.append(ctrl)
        return ret

    @staticmethod
    def get_usb3_controller(conn, guest):
        ctrl = DeviceController(conn)
        ctrl.type = "usb"
        ctrl.model = "nec-xhci"
        if ((guest.os.is_arm_machvirt() or guest.os.is_pseries()) and
            conn.check_support(conn.SUPPORT_CONN_QEMU_XHCI)):
            ctrl.model = "qemu-xhci"
        if conn.check_support(conn.SUPPORT_CONN_USB3_PORTS):
            ctrl.ports = 8
        return ctrl


    _XML_PROP_ORDER = ["type", "index", "model", "master_startport"]

    type = XMLProperty("./@type")
    model = XMLProperty("./@model")
    vectors = XMLProperty("./@vectors", is_int=True)
    ports = XMLProperty("./@ports", is_int=True)
    master_startport = XMLProperty("./master/@startport", is_int=True)

    index = XMLProperty("./@index", is_int=True, default_cb=lambda s: 0)

    def pretty_desc(self):
        ret = self.pretty_type(self.type)
        if self.type == "scsi":
            if self.model == "virtio-scsi":
                ret = "Virtio " + ret
            elif self.address.type == "spapr-vio":
                ret = "sPAPR " + ret
        if self.type == "pci" and self.model == "pcie-root":
            ret = "PCIe"
        return ret

DeviceController.register_type()
