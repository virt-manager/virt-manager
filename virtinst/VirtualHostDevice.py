#
# Copyright 2009  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

from virtinst.VirtualDevice import VirtualDevice
from virtinst.xmlbuilder import XMLProperty
from virtinst import NodeDeviceParser


class VirtualHostDevice(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_HOSTDEV

    @staticmethod
    def device_from_node(conn, name=None, nodedev=None, is_dup=False,
                         dev=None):
        """
        Convert the passed device name to a VirtualHostDevice
        instance, with proper error reporting. Name can be any of the
        values accepted by NodeDeviceParser.lookupNodeName. If a node
        device name is not specified, a virtinst.NodeDevice instance can
        be passed in to create a dev from.

        @param conn: libvirt.virConnect instance to perform the lookup on
        @param name: optional libvirt node device name to lookup
        @param nodedev: optional L{virtinst.NodeDevice} instance to use

        @rtype: L{virtinst.VirtualHostDevice} instance
        """
        if not name and not nodedev:
            raise ValueError("'name' or 'nodedev' required.")

        if nodedev:
            nodeinst = nodedev
        else:
            nodeinst, addr_type = NodeDeviceParser.lookupNodeName(conn, name)
            if addr_type == NodeDeviceParser.HOSTDEV_ADDR_TYPE_USB_BUSADDR:
                is_dup = True

        if isinstance(nodeinst, NodeDeviceParser.NetDevice):
            parentname = nodeinst.parent
            return VirtualHostDevice.device_from_node(conn,
                                                      name=parentname)
        if not dev:
            dev = VirtualHostDevice(conn)
        dev.set_from_nodedev(nodeinst, is_dup)
        return dev

    def set_from_nodedev(self, nodedev, is_dup=False):
        if isinstance(nodedev, NodeDeviceParser.PCIDevice):
            self.type = "pci"
            self.domain = nodedev.domain
            self.bus = nodedev.bus
            self.slot = nodedev.slot
            self.function = nodedev.function

        elif isinstance(nodedev, NodeDeviceParser.USBDevice):
            self.type = "usb"
            self.vendor = nodedev.vendor_id
            self.product = nodedev.product_id

            if is_dup:
                self.bus = nodedev.bus
                self.device = nodedev.device
        else:
            raise ValueError("Unknown node device type %s" % nodedev)


    _XML_PROP_ORDER = ["mode", "type", "managed", "vendor", "product",
                       "domain", "bus", "slot", "function"]

    mode = XMLProperty(xpath="./@mode", default_cb=lambda s: "subsystem")
    type = XMLProperty(xpath="./@type")

    def _get_default_managed(self):
        return self.conn.is_xen() and "no" or "yes"
    managed = XMLProperty(xpath="./@managed", is_yesno=True,
                          default_cb=_get_default_managed)

    vendor = XMLProperty(xpath="./source/vendor/@id")
    product = XMLProperty(xpath="./source/product/@id")

    device = XMLProperty(xpath="./source/address/@device")
    bus = XMLProperty(xpath="./source/address/@bus")

    def _get_default_domain(self):
        if self.type == "pci":
            return "0x0"
        return None
    domain = XMLProperty(xpath="./source/address/@domain",
                         default_cb=_get_default_domain)
    function = XMLProperty(xpath="./source/address/@function")
    slot = XMLProperty(xpath="./source/address/@slot")


VirtualHostDevice.register_type()
