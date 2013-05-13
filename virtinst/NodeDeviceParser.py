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

from virtinst import support
from virtinst import util
import libvirt
import logging

# class USBDevice

CAPABILITY_TYPE_SYSTEM = "system"
CAPABILITY_TYPE_NET = "net"
CAPABILITY_TYPE_PCI = "pci"
CAPABILITY_TYPE_USBDEV = "usb_device"
CAPABILITY_TYPE_USBBUS = "usb"
CAPABILITY_TYPE_STORAGE = "storage"
CAPABILITY_TYPE_SCSIBUS = "scsi_host"
CAPABILITY_TYPE_SCSIDEV = "scsi"

HOSTDEV_ADDR_TYPE_LIBVIRT = 0
HOSTDEV_ADDR_TYPE_PCI = 1
HOSTDEV_ADDR_TYPE_USB_BUSADDR = 2
HOSTDEV_ADDR_TYPE_USB_VENPRO = 3


class NodeDevice(object):
    def __init__(self, node):
        self.name = None
        self.parent = None
        self.device_type = None

        self._parseNodeXML(node)

    def pretty_name(self, child_dev=None):
        """
        Use device information to attempt to print a human readable device
        name.

        @param child_dev: Child node device to display in description
        @type child_dev: L{NodeDevice}

        @returns: Device description string
        @rtype C{str}
        """
        ignore = child_dev
        return self.name

    def _parseNodeXML(self, node):
        child = node.children
        while child:
            if child.name == "name":
                self.name = child.content
            elif child.name == "parent":
                self.parent = child.content
            elif child.name == "capability":
                self.device_type = child.prop("type")
            child = child.next

    def _getCapabilityNode(self, node):
        child = node.children
        while child:
            if child.name == "capability":
                return child
            child = child.next
        return None

    def _parseValueHelper(self, node, value_map):
        if node.name in value_map:
            setattr(self, value_map[node.name], node.content)

    def _parseHelper(self, main_node, value_map):
        node = main_node.children
        while node:
            self._parseValueHelper(node, value_map)
            node = node.next


class SystemDevice(NodeDevice):
    def __init__(self, node):
        NodeDevice.__init__(self, node)

        self.hw_vendor = None
        self.hw_version = None
        self.hw_serial = None
        self.hw_uuid = None

        self.fw_vendor = None
        self.fw_version = None
        self.fw_date = None

        self.parseXML(self._getCapabilityNode(node))

    def parseXML(self, node):
        child = node.children
        hardware_map = {"vendor": "hw_vendor",
                        "version": "hw_version",
                        "serial": "hw_serial",
                        "uuid": "hw_uuid"}
        firmware_map = {"vendor": "fw_vendor",
                        "version": "fw_version",
                        "release_date": "fw_date"}
        while child:
            if child.name == "hardware":
                self._parseHelper(child, hardware_map)
            elif child.name == "firmware":
                self._parseHelper(child, firmware_map)
            child = child.next

    def pretty_name(self, child_dev=None):
        ignore = child_dev
        desc = _("System")
        if self.hw_vendor:
            desc += ": %s" % self.hw_vendor
            if self.hw_version:
                desc += " %s" % self.hw_version

        return desc


class NetDevice(NodeDevice):
    def __init__(self, node):
        NodeDevice.__init__(self, node)

        self.interface = None
        self.address = None
        self.capability_type = None

        self.parseXML(self._getCapabilityNode(node))

    def parseXML(self, node):
        value_map = {"interface" : "interface",
                     "address" : "address"}
        child = node.children
        while child:
            if child.name == "capability":
                self.capability_type = child.prop("type")
            else:
                self._parseValueHelper(child, value_map)
            child = child.next

    def pretty_name(self, child_dev=None):
        ignore = child_dev
        desc = self.name
        if self.interface:
            desc = _("Interface %s") % self.interface

        return desc


class PCIDevice(NodeDevice):
    def __init__(self, node):
        NodeDevice.__init__(self, node)

        self.domain = None
        self.bus = None
        self.slot = None
        self.function = None

        self.product_id = None
        self.product_name = None
        self.vendor_id = None
        self.vendor_name = None

        self.parseXML(self._getCapabilityNode(node))

    def parseXML(self, node):
        val_map = {"domain" : "domain",
                    "bus" : "bus",
                    "slot" : "slot",
                    "function" : "function"}
        child = node.children
        while child:
            if child.name == "vendor":
                self.vendor_name = child.content
                self.vendor_id = child.prop("id")

            elif child.name == "product":
                self.product_name = child.content
                self.product_id = child.prop("id")

            else:
                self._parseValueHelper(child, val_map)

            child = child.next

    def pretty_name(self, child_dev=None):
        devstr = "%.2X:%.2X:%X" % (int(self.bus),
                                   int(self.slot),
                                   int(self.function))
        if child_dev:
            desc = "%s %s (%s)" % (devstr, child_dev.pretty_name(),
                                   str(self.product_name))
        else:
            desc = "%s %s" % (devstr, str(self.product_name))
        return desc


class USBDevice(NodeDevice):
    def __init__(self, node):
        NodeDevice.__init__(self, node)

        self.bus = None
        self.device = None

        self.product_id = None
        self.product_name = None
        self.vendor_id = None
        self.vendor_name = None

        self.parseXML(self._getCapabilityNode(node))

    def parseXML(self, node):
        val_map = {"bus": "bus", "device": "device"}
        child = node.children
        while child:
            if child.name == "vendor":
                self.vendor_name = child.content
                self.vendor_id = child.prop("id")

            elif child.name == "product":
                self.product_name = child.content
                self.product_id = child.prop("id")

            else:
                self._parseValueHelper(child, val_map)

            child = child.next

    def pretty_name(self, child_dev=None):
        ignore = child_dev
        devstr = "%.3d:%.3d" % (int(self.bus), int(self.device))
        desc = "%s %s %s" % (devstr, str(self.vendor_name),
                             str(self.product_name))
        return desc


class StorageDevice(NodeDevice):
    def __init__(self, node):
        NodeDevice.__init__(self, node)

        self.block = None
        self.bus = None
        self.drive_type = None
        self.size = 0

        self.model = None
        self.vendor = None

        self.removable = False
        self.media_available = False
        self.media_size = 0
        self.media_label = None

        self.hotpluggable = False

        self.parseXML(self._getCapabilityNode(node))

    def parseXML(self, node):
        val_map = {"block" : "block",
                    "bus" : "bus",
                    "drive_type" : "drive_type",
                    "model" : "model",
                    "vendor" : "vendor"}
        child = node.children
        while child:
            if child.name == "size":
                self.size = int(child.content)
            elif child.name == "capability":

                captype = child.prop("type")
                if captype == "hotpluggable":
                    self.hotpluggable = True
                elif captype == "removable":
                    self.removable = True
                    rmchild = child.children
                    while rmchild:
                        if rmchild.name == "media_available":
                            self.media_available = bool(int(rmchild.content))
                        elif rmchild.name == "media_size":
                            self.media_size = int(rmchild.content)
                        elif rmchild.name == "media_label":
                            self.media_label = rmchild.content
                        rmchild = rmchild.next
            else:
                self._parseValueHelper(child, val_map)

            child = child.next

    def pretty_name(self, child_dev=None):
        ignore = child_dev
        desc = ""
        if self.drive_type:
            desc = self.drive_type

        if self.block:
            desc = ": ".join((desc, self.block))
        elif self.model:
            desc = ": ".join((desc, self.model))
        else:
            desc = ": ".join((desc, self.name))
        return desc


class USBBus(NodeDevice):
    def __init__(self, node):
        NodeDevice.__init__(self, node)

        self.number = None
        self.classval = None
        self.subclass = None
        self.protocol = None

        self.parseXML(self._getCapabilityNode(node))

    def parseXML(self, node):
        val_map = {"number" : "number",
                    "class" : "classval",
                    "subclass" : "subclass",
                    "protocol" : "protocol"}
        self._parseHelper(node, val_map)


class SCSIDevice(NodeDevice):
    def __init__(self, node):
        NodeDevice.__init__(self, node)

        self.host = None
        self.bus = None
        self.target = None
        self.lun = None
        self.disk = None

        self.parseXML(self._getCapabilityNode(node))

    def parseXML(self, node):
        val_map = {"host" : "host",
                    "bus" : "bus",
                    "target": "target",
                    "lun" : "lun",
                    "type" : "type"}
        self._parseHelper(node, val_map)


class SCSIBus(NodeDevice):
    def __init__(self, node):
        NodeDevice.__init__(self, node)

        self.host = None

        self.vport_ops = False

        self.fc_host = False
        self.wwnn = None
        self.wwpn = None

        self.parseXML(self._getCapabilityNode(node))

    def parseXML(self, node):
        val_map = {"host" : "host"}

        child = node.children
        while child:
            if child.name == "capability":
                captype = child.prop("type")

                if captype == "vport_ops":
                    self.vport_ops = True
                elif captype == "fc_host":
                    self.fc_host = True
                    fcchild = child.children
                    while fcchild:
                        if fcchild.name == "wwnn":
                            self.wwnn = fcchild.content
                        elif fcchild.name == "wwpn":
                            self.wwpn = fcchild.content
                        fcchild = fcchild.next
            else:
                self._parseValueHelper(child, val_map)

            child = child.next


def is_nodedev_capable(conn):
    """
    Check if the passed libvirt connection supports host device routines

    @param conn: Connection to check
    @type conn: libvirt.virConnect

    @rtype: C{bool}
    """
    return support.check_conn_support(conn, support.SUPPORT_CONN_NODEDEV)


def is_pci_detach_capable(conn):
    """
    Check if the passed libvirt connection support pci device Detach/Reset

    @param conn: Connection to check
    @type conn: libvirt.virConnect

    @rtype: C{bool}
    """
    return support.check_conn_support(conn,
                                      support.SUPPORT_NODEDEV_PCI_DETACH)


def _lookupNodeName(conn, name):
    nodedev = conn.nodeDeviceLookupByName(name)
    xml = nodedev.XMLDesc(0)
    return parse(xml)


def lookupNodeName(conn, name):
    """
    Convert the passed libvirt node device name to a NodeDevice
    instance, with proper error reporting. If the name is name is not
    found, we will attempt to parse the name as would be passed to
    devAddressToNodeDev

    @param conn: libvirt.virConnect instance to perform the lookup on
    @param name: libvirt node device name to lookup, or address for
                 devAddressToNodedev

    @rtype: L{NodeDevice} instance
    """
    if not is_nodedev_capable(conn):
        raise ValueError(_("Connection does not support host device "
                           "enumeration."))

    try:
        return (_lookupNodeName(conn, name),
                 HOSTDEV_ADDR_TYPE_LIBVIRT)
    except libvirt.libvirtError, e:
        ret = _isAddressStr(name)
        if not ret:
            raise e

        return devAddressToNodedev(conn, name)


def _isAddressStr(addrstr):
    cmp_func = None
    addr_type = None

    try:
        # Determine addrstr type
        if addrstr.count(":") in [1, 2] and addrstr.count("."):
            devtype = CAPABILITY_TYPE_PCI
            addrstr, func = addrstr.split(".", 1)
            addrstr, slot = addrstr.rsplit(":", 1)
            domain = "0"
            if addrstr.count(":"):
                domain, bus = addrstr.split(":", 1)
            else:
                bus = addrstr

            func = int(func, 16)
            slot = int(slot, 16)
            domain = int(domain, 16)
            bus = int(bus, 16)

            def pci_cmp(nodedev):
                return ((int(nodedev.domain) == domain) and
                        (int(nodedev.function) == func) and
                        (int(nodedev.bus) == bus) and
                        (int(nodedev.slot) == slot))
            cmp_func = pci_cmp
            addr_type = HOSTDEV_ADDR_TYPE_PCI

        elif addrstr.count(":"):
            devtype = CAPABILITY_TYPE_USBDEV
            vendor, product = addrstr.split(":")
            vendor = int(vendor, 16)
            product = int(product, 16)

            def usbprod_cmp(nodedev):
                return ((int(nodedev.vendor_id, 16) == vendor) and
                        (int(nodedev.product_id, 16) == product))
            cmp_func = usbprod_cmp
            addr_type = HOSTDEV_ADDR_TYPE_USB_VENPRO

        elif addrstr.count("."):
            devtype = CAPABILITY_TYPE_USBDEV
            bus, addr = addrstr.split(".", 1)
            bus = int(bus)
            addr = int(addr)

            def usbaddr_cmp(nodedev):
                return ((int(nodedev.bus) == bus) and
                        (int(nodedev.device) == addr))
            cmp_func = usbaddr_cmp
            addr_type = HOSTDEV_ADDR_TYPE_USB_BUSADDR
    except:
        logging.exception("Error parsing node device string.")
        return None

    return cmp_func, devtype, addr_type


def devAddressToNodedev(conn, addrstr):
    """
    Look up the passed host device address string as a libvirt node device,
    parse its xml, and return a NodeDevice instance.

    @param conn: libvirt.virConnect instance to perform the lookup on
    @param addrstr: host device string to parse and lookup
        - bus.addr (ex. 001.003 for a usb device)
        - vendor:product (ex. 0x1234:0x5678 for a usb device
        - (domain:)bus:slot.func (ex. 00:10.0 for a pci device)
    @param addrstr: C{str}
    """
    if not is_nodedev_capable(conn):
        raise ValueError(_("Connection does not support host device "
                           "enumeration."))

    ret = _isAddressStr(addrstr)
    if not ret:
        raise ValueError(_("Could not determine format of '%s'") % addrstr)

    cmp_func, devtype, addr_type = ret

    # Iterate over node devices and compare
    count = 0
    nodedev = None

    nodenames = conn.listDevices(devtype, 0)
    for name in nodenames:
        tmpnode = _lookupNodeName(conn, name)
        if cmp_func(tmpnode):
            nodedev = tmpnode
            count += 1

    if count == 1:
        return nodedev, addr_type
    elif count > 1:
        raise ValueError(_("%s corresponds to multiple node devices") %
                         addrstr)
    elif count < 1:
        raise ValueError(_("Did not find a matching node device for '%s'") %
                         addrstr)


def parse(xml):
    """
    Convert the passed libvirt node device xml into a NodeDevice object

    @param xml: libvirt node device xml
    @type xml: C{str}

    @returns: L{NodeDevice} instance
    """
    def _parse_func(root):
        t = _findNodeType(root)
        devclass = _typeToDeviceClass(t)
        device = devclass(root)
        return device

    return util.parse_node_helper(xml, "device", _parse_func)


def _findNodeType(node):
    child = node.children
    while child:
        if child.name == "capability":
            return child.prop("type")
        child = child.next
    return None


def _typeToDeviceClass(t):
    if t == CAPABILITY_TYPE_SYSTEM:
        return SystemDevice
    elif t == CAPABILITY_TYPE_NET:
        return NetDevice
    elif t == CAPABILITY_TYPE_PCI:
        return PCIDevice
    elif t == CAPABILITY_TYPE_USBDEV:
        return USBDevice
    elif t == CAPABILITY_TYPE_USBBUS:
        return USBBus
    elif t == CAPABILITY_TYPE_STORAGE:
        return StorageDevice
    elif t == CAPABILITY_TYPE_SCSIBUS:
        return SCSIBus
    elif t == CAPABILITY_TYPE_SCSIDEV:
        return SCSIDevice
    else:
        return NodeDevice
