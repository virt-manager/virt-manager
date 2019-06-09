#
# Copyright 2010, 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceController(Device):
    XML_NAME = "controller"

    TYPE_IDE             = "ide"
    TYPE_FDC             = "fdc"
    TYPE_SCSI            = "scsi"
    TYPE_SATA            = "sata"
    TYPE_VIRTIOSERIAL    = "virtio-serial"
    TYPE_USB             = "usb"
    TYPE_PCI             = "pci"
    TYPE_CCID            = "ccid"
    TYPE_XENBUS          = "xenbus"

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
        ignore = guest
        ctrl = DeviceController(conn)
        ctrl.type = "usb"
        ctrl.model = "nec-xhci"
        if conn.support.conn_qemu_xhci():
            ctrl.model = "qemu-xhci"
        if conn.support.conn_usb3_ports():
            # 15 is the max ports qemu supports, might as well
            # Add as many as possible
            ctrl.ports = 15
        return ctrl


    _XML_PROP_ORDER = ["type", "index", "model", "master_startport",
            "driver_queues", "maxGrantFrames"]

    type = XMLProperty("./@type")
    model = XMLProperty("./@model")
    vectors = XMLProperty("./@vectors", is_int=True)
    ports = XMLProperty("./@ports", is_int=True)
    master_startport = XMLProperty("./master/@startport", is_int=True)
    driver_queues = XMLProperty("./driver/@queues", is_int=True)
    maxGrantFrames = XMLProperty("./@maxGrantFrames", is_int=True)

    index = XMLProperty("./@index", is_int=True)


    ##################
    # Default config #
    ##################

    def set_defaults(self, _guest):
        if self.index is None:
            self.index = 0
