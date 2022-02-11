#
# Copyright 2009, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import re

from ..logger import log

from .device import Device
from ..nodedev import NodeDevice
from ..xmlbuilder import XMLProperty


class DeviceHostdev(Device):
    XML_NAME = "hostdev"

    def set_from_nodedev(self, nodedev):
        log.debug("set_from_nodedev xml=\n%s", nodedev.get_xml())

        if nodedev.device_type == NodeDevice.CAPABILITY_TYPE_PCI:
            self.type = "pci"
            self.domain = nodedev.domain
            self.bus = nodedev.bus
            self.slot = nodedev.slot
            self.function = nodedev.function

        elif nodedev.device_type == NodeDevice.CAPABILITY_TYPE_USBDEV:
            self.type = "usb"
            self.vendor = nodedev.vendor_id
            self.product = nodedev.product_id

            count = 0
            for dev in self.conn.fetch_all_nodedevs():
                if (dev.device_type == NodeDevice.CAPABILITY_TYPE_USBDEV and
                    dev.vendor_id == self.vendor and
                    dev.product_id == self.product):
                    count += 1

            if count > 1:
                self.bus = nodedev.bus
                self.device = nodedev.device

        elif nodedev.device_type == nodedev.CAPABILITY_TYPE_NET:
            founddev = None
            for checkdev in self.conn.fetch_all_nodedevs():
                if checkdev.name == nodedev.parent:
                    founddev = checkdev
                    break

            self.set_from_nodedev(founddev)

        elif nodedev.device_type == nodedev.CAPABILITY_TYPE_SCSIDEV:
            self.type = "scsi"
            self.scsi_adapter = "scsi_host%s" % nodedev.host
            self.scsi_bus = nodedev.bus
            self.scsi_target = nodedev.target
            self.scsi_unit = nodedev.lun
            self.managed = False

        elif nodedev.device_type == nodedev.CAPABILITY_TYPE_MDEV:
            self.type = "mdev"

            if nodedev.type_id == "vfio_ccw-io":
                self.model = "vfio-ccw"
                self.managed = "no"

            elif nodedev.type_id == "vfio_ap-passthrough":
                self.model = "vfio-ap"
                self.managed = "no"

            elif (re.match("^nvidia-[0-9]{2}", nodedev.type_id) or
                  re.match("^i915-GVTg_V[0-9]_[0-9]", nodedev.type_id)):
                self.model = "vfio-pci"
                self.managed = "yes"
                self.display = "off"
                self.ramfb = "off"

            else:
                raise ValueError(  # pragma: no cover
                        _("Don't know how to generate nodedev for mdev type id '%s'") %
                        nodedev.type_id)

            self.uuid = nodedev.get_mdev_uuid()

        else:
            raise ValueError(_("Unsupported node device type '%s'") %
                    nodedev.device_type)


    _XML_PROP_ORDER = ["mode", "type", "managed", "vendor", "product",
                       "domain", "bus", "slot", "function", "model",
                       "display", "ramfb"]

    mode = XMLProperty("./@mode")
    type = XMLProperty("./@type")
    managed = XMLProperty("./@managed", is_yesno=True)
    model = XMLProperty("./@model")
    display = XMLProperty("./@display")
    ramfb = XMLProperty("./@ramfb")

    vendor = XMLProperty("./source/vendor/@id")
    product = XMLProperty("./source/product/@id")

    device = XMLProperty("./source/address/@device")
    bus = XMLProperty("./source/address/@bus")

    domain = XMLProperty("./source/address/@domain")
    function = XMLProperty("./source/address/@function")
    slot = XMLProperty("./source/address/@slot")

    driver_name = XMLProperty("./driver/@name")
    rom_bar = XMLProperty("./rom/@bar", is_onoff=True)

    # type=scsi handling
    scsi_adapter = XMLProperty("./source/adapter/@name")
    scsi_bus = XMLProperty("./source/address/@bus", is_int=True)
    scsi_target = XMLProperty("./source/address/@target", is_int=True)
    scsi_unit = XMLProperty("./source/address/@unit", is_int=True)

    # type=net handling
    net_interface = XMLProperty("./source/interface")

    # type=misc handling
    misc_char = XMLProperty("./source/char")

    # type=misc handling
    storage_block = XMLProperty("./source/block")

    # type=mdev
    uuid = XMLProperty("./source/address/@uuid")


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if self.managed is None:
            self.managed = self.conn.is_xen() and "no" or "yes"
        if not self.mode:
            self.mode = "subsystem"
