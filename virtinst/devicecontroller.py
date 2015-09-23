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

from .device import VirtualDevice
from .xmlbuilder import XMLProperty


class VirtualController(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_CONTROLLER

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
            VirtualController.TYPE_IDE           : "IDE",
            VirtualController.TYPE_FDC           : _("Floppy"),
            VirtualController.TYPE_SCSI          : "SCSI",
            VirtualController.TYPE_SATA          : "SATA",
            VirtualController.TYPE_VIRTIOSERIAL  : "VirtIO Serial",
            VirtualController.TYPE_USB           : "USB",
            VirtualController.TYPE_PCI           : "PCI",
            VirtualController.TYPE_CCID          : "CCID",
       }

        if ctype not in pretty_mappings:
            return ctype
        return pretty_mappings[ctype]

    @staticmethod
    def get_usb2_controllers(conn):
        ret = []
        ctrl = VirtualController(conn)
        ctrl.type = "usb"
        ctrl.model = "ich9-ehci1"
        ret.append(ctrl)

        ctrl = VirtualController(conn)
        ctrl.type = "usb"
        ctrl.model = "ich9-uhci1"
        ctrl.master_startport = 0
        ret.append(ctrl)

        ctrl = VirtualController(conn)
        ctrl.type = "usb"
        ctrl.model = "ich9-uhci2"
        ctrl.master_startport = 2
        ret.append(ctrl)

        ctrl = VirtualController(conn)
        ctrl.type = "usb"
        ctrl.model = "ich9-uhci3"
        ctrl.master_startport = 4
        ret.append(ctrl)
        return ret


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
        return ret

VirtualController.register_type()
