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
from virtinst import NodeDeviceParser
import logging

from virtinst.XMLBuilderDomain import _xml_property


class VirtualHostDevice(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_HOSTDEV

    def device_from_node(conn, name=None, nodedev=None, is_dup=False):
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
            raise ValueError(_("'name' or 'nodedev' required."))

        if nodedev:
            nodeinst = nodedev
        else:
            nodeinst, addr_type = NodeDeviceParser.lookupNodeName(conn, name)
            if addr_type == NodeDeviceParser.HOSTDEV_ADDR_TYPE_USB_BUSADDR:
                is_dup = True

        if isinstance(nodeinst, NodeDeviceParser.PCIDevice):
            return VirtualHostDevicePCI(conn, nodedev=nodeinst)
        elif isinstance(nodeinst, NodeDeviceParser.USBDevice):
            return VirtualHostDeviceUSB(conn, nodedev=nodeinst, is_dup=is_dup)
        elif isinstance(nodeinst, NodeDeviceParser.NetDevice):
            parentname = nodeinst.parent
            try:
                return VirtualHostDevice.device_from_node(conn,
                                                          name=parentname)
            except:
                logging.exception("Fetching net parent device failed.")

        raise ValueError(_("Node device type '%s' cannot be attached to "
                           " guest.") % nodeinst.device_type)

    device_from_node = staticmethod(device_from_node)

    def __init__(self, conn, nodedev=None,
                 parsexml=None, parsexmlnode=None, caps=None):
        """
        @param conn: Connection the device/guest will be installed on
        @type conn: libvirt.virConnect
        @param nodedev: Optional NodeDevice instance for device being
                         attached to the guest
        @type nodedev: L{virtinst.NodeDeviceParser.NodeDevice}
        """
        VirtualDevice.__init__(self, conn, parsexml,
                                             parsexmlnode, caps)

        self._mode = None
        self._type = None
        self._managed = None
        self._nodedev = nodedev
        self._vendor = None
        self._product = None
        self._bus = None
        self._device = None
        self._domain = "0x0"
        self._slot = None
        self._function = None

        if self._is_parse():
            return

        self.managed = True
        if self.is_xen():
            self.managed = False


    def get_mode(self):
        return self._mode
    def set_mode(self, val):
        self._mode = val
    mode = _xml_property(get_mode, set_mode,
                         xpath="./@mode")

    def get_type(self):
        return self._type
    def set_type(self, val):
        self._type = val
    type = _xml_property(get_type, set_type,
                         xpath="./@type")

    def get_managed(self):
        return self._managed
    def set_managed(self, val):
        self._managed = bool(val)
    managed = _xml_property(get_managed, set_managed,
                            get_converter=lambda s, x: bool(x == "yes"),
                            set_converter=lambda s, x: x and "yes" or "no",
                            xpath="./@managed")

    def get_vendor(self):
        return self._vendor
    def set_vendor(self, val):
        self._vendor = val
    vendor = _xml_property(get_vendor, set_vendor,
                           xpath="./source/vendor/@id")

    def get_product(self):
        return self._product
    def set_product(self, val):
        self._product = val
    product = _xml_property(get_product, set_product,
                            xpath="./source/product/@id")

    def get_device(self):
        return self._device
    def set_device(self, val):
        self._device = val
    device = _xml_property(get_device, set_device,
                           xpath="./source/address/@device")

    def get_bus(self):
        return self._bus
    def set_bus(self, val):
        self._bus = val
    bus = _xml_property(get_bus, set_bus,
                        xpath="./source/address/@bus")

    def get_function(self):
        return self._function
    def set_function(self, val):
        self._function = val
    function = _xml_property(get_function, set_function,
                             xpath="./source/address/@function")

    def get_domain(self):
        return self._domain
    def set_domain(self, val):
        self._domain = val
    domain = _xml_property(get_domain, set_domain,
                             xpath="./source/address/@domain")

    def get_slot(self):
        return self._slot
    def set_slot(self, val):
        self._slot = val
    slot = _xml_property(get_slot, set_slot,
                         xpath="./source/address/@slot")

    def _get_source_xml(self):
        raise NotImplementedError("Must be implemented in subclass")

    def setup(self, conn=None):
        """
        Unused

        @param conn: libvirt virConnect instance to use (defaults to devices
                     connection)
        """
        ignore = conn

    def _get_xml_config(self):
        xml  = ("    <hostdev mode='%s' type='%s' managed='%s'>\n" %
                (self.mode, self.type, self.managed and "yes" or "no"))
        xml += "      <source>\n"
        xml += self._get_source_xml()
        xml += "      </source>\n"
        xml += "    </hostdev>"
        return xml


class VirtualHostDeviceUSB(VirtualHostDevice):

    def __init__(self, conn, nodedev=None, is_dup=False):
        VirtualHostDevice.__init__(self, conn, nodedev)

        self.mode = "subsystem"
        self.type = "usb"
        self.is_dup = is_dup

        self._set_from_nodedev(self._nodedev)


    def _set_from_nodedev(self, nodedev):
        if not nodedev:
            return

        if not isinstance(nodedev, NodeDeviceParser.USBDevice):
            raise ValueError(_("'nodedev' must be a USBDevice instance."))

        self.vendor = nodedev.vendor_id
        self.product = nodedev.product_id

        if self.is_dup:
            self.bus = nodedev.bus
            self.device = nodedev.device

    def _get_source_xml(self):
        xml = ""
        found = False

        if self.vendor and self.product:
            xml += "        <vendor id='%s'/>\n" % self.vendor
            xml += "        <product id='%s'/>\n" % self.product
            found = True

        if self.bus and self.device:
            xml += "        <address bus='%s' device='%s'/>\n" % (self.bus,
                                                                  self.device)
            found = True

        if not found:
            raise RuntimeError(_("'vendor' and 'product', or 'bus' and "
                                 " 'device' are required."))
        return xml


class VirtualHostDevicePCI(VirtualHostDevice):

    def __init__(self, conn, nodedev=None):
        VirtualHostDevice.__init__(self, conn, nodedev)

        self.mode = "subsystem"
        self.type = "pci"

        self._set_from_nodedev(self._nodedev)


    def _set_from_nodedev(self, nodedev):
        if not nodedev:
            return

        if not isinstance(nodedev, NodeDeviceParser.PCIDevice):
            raise ValueError(_("'nodedev' must be a PCIDevice instance."))

        self.domain = nodedev.domain
        self.bus = nodedev.bus
        self.slot = nodedev.slot
        self.function = nodedev.function

    def _get_source_xml(self):
        if not (self.domain and self.bus and self.slot and self.function):
            raise RuntimeError(_("'domain', 'bus', 'slot', and 'function' "
                                 "must be specified."))

        xml = "        <address domain='%s' bus='%s' slot='%s' function='%s'/>\n"
        return xml % (self.domain, self.bus, self.slot, self.function)
