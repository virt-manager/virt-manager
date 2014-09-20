#
# Copyright 2009, 2013 Red Hat, Inc.
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
from .nodedev import NodeDevice
from .xmlbuilder import XMLProperty


class VirtualHostDevice(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_HOSTDEV

    def set_from_nodedev(self, nodedev, use_full_usb=None):
        """
        @use_full_usb: If set, and nodedev is USB, specify both
            vendor and product. Used if user requests bus/add on virt-install
            command line, or if virt-manager detects a dup USB device
            and we need to differentiate
        """
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

            if use_full_usb:
                self.bus = nodedev.bus
                self.device = nodedev.device

        elif nodedev.device_type == nodedev.CAPABILITY_TYPE_NET:
            founddev = None
            for checkdev in self.conn.fetch_all_nodedevs():
                if checkdev.name == nodedev.parent:
                    founddev = checkdev
                    break

            self.set_from_nodedev(founddev, use_full_usb=use_full_usb)

        else:
            raise ValueError("Unknown node device type %s" % nodedev)

    def pretty_name(self):
        def dehex(val):
            if val.startswith("0x"):
                val = val[2:]
            return val

        def safeint(val, fmt="%.3d"):
            try:
                int(val)
            except:
                return str(val)
            return fmt % int(val)

        label = self.type.upper()

        if self.vendor and self.product:
            label += " %s:%s" % (dehex(self.vendor), dehex(self.product))

        elif self.bus and self.device:
            label += " %s:%s" % (safeint(self.bus), safeint(self.device))

        elif self.bus and self.slot and self.function and self.domain:
            label += (" %s:%s:%s.%s" %
                      (dehex(self.domain), dehex(self.bus),
                       dehex(self.slot), dehex(self.function)))

        return label


    _XML_PROP_ORDER = ["mode", "type", "managed", "vendor", "product",
                       "domain", "bus", "slot", "function"]

    mode = XMLProperty("./@mode", default_cb=lambda s: "subsystem")
    type = XMLProperty("./@type")

    def _get_default_managed(self):
        return self.conn.is_xen() and "no" or "yes"
    managed = XMLProperty("./@managed", is_yesno=True,
                          default_cb=_get_default_managed)

    vendor = XMLProperty("./source/vendor/@id")
    product = XMLProperty("./source/product/@id")

    device = XMLProperty("./source/address/@device")
    bus = XMLProperty("./source/address/@bus")

    def _get_default_domain(self):
        if self.type == "pci":
            return "0x0"
        return None
    domain = XMLProperty("./source/address/@domain",
                         default_cb=_get_default_domain)
    function = XMLProperty("./source/address/@function")
    slot = XMLProperty("./source/address/@slot")

    driver_name = XMLProperty("./driver/@name")
    rom_bar = XMLProperty("./rom/@bar", is_onoff=True)


VirtualHostDevice.register_type()
