#
# Copyright 2009, 2013 Red Hat, Inc.
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

import logging

import libvirt

from virtinst.xmlbuilder import XMLBuilder
from virtinst.xmlbuilder import XMLProperty as OrigXMLProperty


# We had a pre-existing set of parse tests when this was converted to
# XMLBuilder. We do this to appease the check in xmlparse.py without
# moving all the nodedev.py tests to one file. Should find a way to
# drop it.
class XMLProperty(OrigXMLProperty):
    def __init__(self, *args, **kwargs):
        kwargs["track"] = False
        OrigXMLProperty.__init__(self, *args, **kwargs)


def _lookupNodeName(conn, name):
    try:
        nodedev = conn.nodeDeviceLookupByName(name)
    except libvirt.libvirtError, e:
        raise libvirt.libvirtError(
            _("Did not find node device '%s': %s" %
            (name, str(e))))

    xml = nodedev.XMLDesc(0)
    return NodeDevice.parse(conn, xml)


class NodeDevice(XMLBuilder):
    CAPABILITY_TYPE_SYSTEM = "system"
    CAPABILITY_TYPE_NET = "net"
    CAPABILITY_TYPE_PCI = "pci"
    CAPABILITY_TYPE_USBDEV = "usb_device"
    CAPABILITY_TYPE_USBBUS = "usb"
    CAPABILITY_TYPE_STORAGE = "storage"
    CAPABILITY_TYPE_SCSIBUS = "scsi_host"
    CAPABILITY_TYPE_SCSIDEV = "scsi"

    (HOSTDEV_ADDR_TYPE_LIBVIRT,
    HOSTDEV_ADDR_TYPE_PCI,
    HOSTDEV_ADDR_TYPE_USB_BUSADDR,
    HOSTDEV_ADDR_TYPE_USB_VENPRO) = range(1, 5)

    @staticmethod
    def lookupNodeName(conn, name):
        """
        Convert the passed libvirt node device name to a NodeDevice
        instance, with proper error reporting. If the name is name is not
        found, we will attempt to parse the name as would be passed to
        devAddressToNodeDev

        @param conn: libvirt.virConnect instance to perform the lookup on
        @param name: libvirt node device name to lookup, or address for
                     _devAddressToNodedev

        @rtype: L{NodeDevice} instance
        """
        if not conn.check_support(conn.SUPPORT_CONN_NODEDEV):
            raise ValueError(_("Connection does not support host device "
                               "enumeration."))

        try:
            return _lookupNodeName(conn, name)
        except libvirt.libvirtError, e:
            ret = _isAddressStr(name)
            if not ret:
                raise e

            return _devAddressToNodedev(conn, name)

    @staticmethod
    def parse(conn, xml):
        tmpdev = NodeDevice(conn, parsexml=xml, allow_node_instantiate=True)
        cls = _typeToDeviceClass(tmpdev.device_type)
        return cls(conn, parsexml=xml, allow_node_instantiate=True)

    def __init__(self, *args, **kwargs):
        instantiate = kwargs.pop("allow_node_instantiate", False)
        if self.__class__ is NodeDevice and not instantiate:
            raise RuntimeError("Can not instantiate NodeDevice directly")

        self.addr_type = None

        XMLBuilder.__init__(self, *args, **kwargs)

    _XML_ROOT_NAME = "device"

    name = XMLProperty("./name")
    parent = XMLProperty("./parent")
    device_type = XMLProperty("./capability/@type")

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


class SystemDevice(NodeDevice):
    hw_vendor = XMLProperty("./capability/hardware/vendor")
    hw_version = XMLProperty("./capability/hardware/version")
    hw_serial = XMLProperty("./capability/hardware/serial")
    hw_uuid = XMLProperty("./capability/hardware/uuid")

    fw_vendor = XMLProperty("./capability/firmware/vendor")
    fw_version = XMLProperty("./capability/firmware/version")
    fw_date = XMLProperty("./capability/firmware/release_date")

    def pretty_name(self, child_dev=None):
        ignore = child_dev
        desc = _("System")
        if self.hw_vendor:
            desc += ": %s" % self.hw_vendor
            if self.hw_version:
                desc += " %s" % self.hw_version

        return desc


class NetDevice(NodeDevice):
    interface = XMLProperty("./capability/interface")
    address = XMLProperty("./capability/address")
    capability_type = XMLProperty("./capability/capability/@type")

    def pretty_name(self, child_dev=None):
        ignore = child_dev
        desc = self.name
        if self.interface:
            desc = _("Interface %s") % self.interface

        return desc


class PCIDevice(NodeDevice):
    domain = XMLProperty("./capability/domain")
    bus = XMLProperty("./capability/bus")
    slot = XMLProperty("./capability/slot")
    function = XMLProperty("./capability/function")

    product_name = XMLProperty("./capability/product")
    product_id = XMLProperty("./capability/product/@id")
    vendor_name = XMLProperty("./capability/vendor")
    vendor_id = XMLProperty("./capability/vendor/@id")

    iommu_group = XMLProperty("./capability/iommuGroup/@number", is_int=True)

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
    bus = XMLProperty("./capability/bus")
    device = XMLProperty("./capability/device")

    product_name = XMLProperty("./capability/product")
    product_id = XMLProperty("./capability/product/@id")
    vendor_name = XMLProperty("./capability/vendor")
    vendor_id = XMLProperty("./capability/vendor/@id")

    def pretty_name(self, child_dev=None):
        ignore = child_dev
        devstr = "%.3d:%.3d" % (int(self.bus), int(self.device))
        desc = "%s %s %s" % (devstr, str(self.vendor_name),
                             str(self.product_name))
        return desc


class StorageDevice(NodeDevice):
    block = XMLProperty("./capability/block")
    bus = XMLProperty("./capability/bus")
    drive_type = XMLProperty("./capability/drive_type")
    size = XMLProperty("./capability/size", is_int=True)

    model = XMLProperty("./capability/model")
    vendor = XMLProperty("./capability/vendor")

    hotpluggable = XMLProperty(
        "./capability/capability[@type='hotpluggable']", is_bool=True)
    removable = XMLProperty(
        "./capability/capability[@type='removable']", is_bool=True)

    media_size = XMLProperty(
        "./capability/capability[@type='removable']/media_size", is_int=True)
    media_label = XMLProperty(
        "./capability/capability[@type='removable']/media_label")
    _media_available = XMLProperty(
            "./capability/capability[@type='removable']/media_available",
            is_int=True)
    def _get_media_available(self):
        m = self._media_available
        if m is None:
            return None
        return bool(m)
    def _set_media_available(self, val):
        self._media_available = val
    media_available = property(_get_media_available, _set_media_available)

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
    number = XMLProperty("./capability/number")
    classval = XMLProperty("./capability/class")
    subclass = XMLProperty("./capability/subclass")
    protocol = XMLProperty("./capability/protocol")


class SCSIDevice(NodeDevice):
    host = XMLProperty("./capability/host")
    bus = XMLProperty("./capability/bus")
    target = XMLProperty("./capability/target")
    lun = XMLProperty("./capability/lun")
    type = XMLProperty("./capability/type")


class SCSIBus(NodeDevice):
    host = XMLProperty("./capability/host")

    vport_ops = XMLProperty(
        "./capability/capability[@type='vport_ops']", is_bool=True)

    fc_host = XMLProperty(
        "./capability/capability[@type='fc_host']", is_bool=True)
    wwnn = XMLProperty("./capability/capability[@type='fc_host']/wwnn")
    wwpn = XMLProperty("./capability/capability[@type='fc_host']/wwpn")


def _isAddressStr(addrstr):
    cmp_func = None
    addr_type = None

    try:
        # Determine addrstr type
        if addrstr.count(":") in [1, 2] and addrstr.count("."):
            devtype = NodeDevice.CAPABILITY_TYPE_PCI
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
            addr_type = NodeDevice.HOSTDEV_ADDR_TYPE_PCI

        elif addrstr.count(":"):
            devtype = NodeDevice.CAPABILITY_TYPE_USBDEV
            vendor, product = addrstr.split(":")
            vendor = int(vendor, 16)
            product = int(product, 16)

            def usbprod_cmp(nodedev):
                return ((int(nodedev.vendor_id, 16) == vendor) and
                        (int(nodedev.product_id, 16) == product))
            cmp_func = usbprod_cmp
            addr_type = NodeDevice.HOSTDEV_ADDR_TYPE_USB_VENPRO

        elif addrstr.count("."):
            devtype = NodeDevice.CAPABILITY_TYPE_USBDEV
            bus, addr = addrstr.split(".", 1)
            bus = int(bus)
            addr = int(addr)

            def usbaddr_cmp(nodedev):
                return ((int(nodedev.bus) == bus) and
                        (int(nodedev.device) == addr))
            cmp_func = usbaddr_cmp
            addr_type = NodeDevice.HOSTDEV_ADDR_TYPE_USB_BUSADDR
        else:
            return None
    except:
        logging.exception("Error parsing node device string.")
        return None

    return cmp_func, devtype, addr_type


def _devAddressToNodedev(conn, addrstr):
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
        nodedev.addr_type = addr_type
        return nodedev
    elif count > 1:
        raise ValueError(_("%s corresponds to multiple node devices") %
                         addrstr)
    elif count < 1:
        raise ValueError(_("Did not find a matching node device for '%s'") %
                         addrstr)


def _typeToDeviceClass(t):
    if t == NodeDevice.CAPABILITY_TYPE_SYSTEM:
        return SystemDevice
    elif t == NodeDevice.CAPABILITY_TYPE_NET:
        return NetDevice
    elif t == NodeDevice.CAPABILITY_TYPE_PCI:
        return PCIDevice
    elif t == NodeDevice.CAPABILITY_TYPE_USBDEV:
        return USBDevice
    elif t == NodeDevice.CAPABILITY_TYPE_USBBUS:
        return USBBus
    elif t == NodeDevice.CAPABILITY_TYPE_STORAGE:
        return StorageDevice
    elif t == NodeDevice.CAPABILITY_TYPE_SCSIBUS:
        return SCSIBus
    elif t == NodeDevice.CAPABILITY_TYPE_SCSIDEV:
        return SCSIDevice
    else:
        return NodeDevice
