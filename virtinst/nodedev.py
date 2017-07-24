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

import logging
import os

from .xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


def _compare_int(nodedev_val, hostdev_val):
    def _intify(val):
        try:
            if "0x" in str(val):
                return int(val or '0x00', 16)
            else:
                return int(val)
        except Exception:
            return -1

    nodedev_val = _intify(nodedev_val)
    hostdev_val = _intify(hostdev_val)
    return (nodedev_val == hostdev_val or hostdev_val == -1)


class DevNode(XMLBuilder):
    _XML_ROOT_NAME = "devnode"

    node_type = XMLProperty("./@type")
    path = XMLProperty(".")


class NodeDevice(XMLBuilder):
    CAPABILITY_TYPE_SYSTEM = "system"
    CAPABILITY_TYPE_NET = "net"
    CAPABILITY_TYPE_PCI = "pci"
    CAPABILITY_TYPE_USBDEV = "usb_device"
    CAPABILITY_TYPE_USBBUS = "usb"
    CAPABILITY_TYPE_STORAGE = "storage"
    CAPABILITY_TYPE_SCSIBUS = "scsi_host"
    CAPABILITY_TYPE_SCSIDEV = "scsi"
    CAPABILITY_TYPE_DRM = "drm"

    @staticmethod
    def lookupNodedevFromString(conn, idstring):
        """
        Convert the passed libvirt node device name to a NodeDevice
        instance, with proper error reporting. If the name is name is not
        found, we will attempt to parse the name as would be passed to
        devAddressToNodeDev

        @param conn: libvirt.virConnect instance to perform the lookup on
        @param idstring: libvirt node device name to lookup, or address
            of the form:
            - bus.addr (ex. 001.003 for a usb device)
            - vendor:product (ex. 0x1234:0x5678 for a usb device
            - (domain:)bus:slot.func (ex. 00:10.0 for a pci device)

        @rtype: L{NodeDevice} instance
        """
        if not conn.check_support(conn.SUPPORT_CONN_NODEDEV):
            raise ValueError(_("Connection does not support host device "
                               "enumeration."))

        # First try and see if this is a libvirt nodedev name
        for nodedev in conn.fetch_all_nodedevs():
            if nodedev.name == idstring:
                return nodedev

        try:
            return _AddressStringToNodedev(conn, idstring)
        except Exception:
            logging.debug("Error looking up nodedev from idstring=%s",
                idstring, exc_info=True)
            raise


    @staticmethod
    def parse(conn, xml):
        tmpdev = NodeDevice(conn, parsexml=xml, allow_node_instantiate=True)
        cls = _typeToDeviceClass(tmpdev.device_type)
        return cls(conn, parsexml=xml, allow_node_instantiate=True)

    def __init__(self, *args, **kwargs):
        instantiate = kwargs.pop("allow_node_instantiate", False)
        if self.__class__ is NodeDevice and not instantiate:
            raise RuntimeError("Can not instantiate NodeDevice directly")

        XMLBuilder.__init__(self, *args, **kwargs)

    _XML_ROOT_NAME = "device"

    # Libvirt can generate bogus 'system' XML:
    # https://bugzilla.redhat.com/show_bug.cgi?id=1184131
    _XML_SANITIZE = True

    name = XMLProperty("./name")
    parent = XMLProperty("./parent")
    device_type = XMLProperty("./capability/@type")
    devnodes = XMLChildProperty(DevNode)

    def get_devnode(self, parent="by-path"):
        for d in self.devnodes:
            paths = d.path.split(os.sep)
            if len(paths) > 2 and paths[-2] == parent:
                return d
        if len(self.devnodes) > 0:
            return self.devnodes[0]
        return None

    def pretty_name(self):
        """
        Use device information to attempt to print a human readable device
        name.

        @returns: Device description string
        @rtype C{str}
        """
        return self.name

    def compare_to_hostdev(self, hostdev):
        ignore = hostdev
        return False


class SystemDevice(NodeDevice):
    hw_vendor = XMLProperty("./capability/hardware/vendor")
    hw_version = XMLProperty("./capability/hardware/version")
    hw_serial = XMLProperty("./capability/hardware/serial")
    hw_uuid = XMLProperty("./capability/hardware/uuid")

    fw_vendor = XMLProperty("./capability/firmware/vendor")
    fw_version = XMLProperty("./capability/firmware/version")
    fw_date = XMLProperty("./capability/firmware/release_date")

    def pretty_name(self):
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

    def pretty_name(self):
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

    capability_type = XMLProperty("./capability/capability/@type")

    iommu_group = XMLProperty("./capability/iommuGroup/@number", is_int=True)

    def pretty_name(self):
        devstr = "%.4X:%.2X:%.2X:%X" % (int(self.domain),
                                        int(self.bus),
                                        int(self.slot),
                                        int(self.function))

        return "%s %s %s" % (devstr, self.vendor_name, self.product_name)

    def compare_to_hostdev(self, hostdev):
        if hostdev.type != self.device_type:
            return False

        return (_compare_int(self.domain, hostdev.domain) and
            _compare_int(self.bus, hostdev.bus) and
            _compare_int(self.slot, hostdev.slot) and
            _compare_int(self.function, hostdev.function))


class USBDevice(NodeDevice):
    bus = XMLProperty("./capability/bus")
    device = XMLProperty("./capability/device")

    product_name = XMLProperty("./capability/product")
    product_id = XMLProperty("./capability/product/@id")
    vendor_name = XMLProperty("./capability/vendor")
    vendor_id = XMLProperty("./capability/vendor/@id")

    def pretty_name(self):
        # Hypervisor may return a rather sparse structure, missing
        # some ol all stringular descriptions of the device altogether.
        # Do our best to help user identify the device.

        # Certain devices pad their vendor with trailing spaces,
        # such as "LENOVO       ". It does not look well.
        product = str(self.product_name).strip()
        vendor = str(self.vendor_name).strip()

        if product == "":
            product = str(self.product_id)
            if vendor == "":
                # No stringular descriptions altogether
                vendor = str(self.vendor_id)
                devstr = "%s:%s" % (vendor, product)
            else:
                # Only the vendor is known
                devstr = "%s %s" % (vendor, product)
        else:
            if vendor == "":
                # Sometimes vendor is left out empty, but product is
                # already descriptive enough or contains the vendor string:
                # "Lenovo USB Laser Mouse"
                devstr = product
            else:
                # We know everything. Perfect.
                devstr = "%s %s" % (vendor, product)

        busstr = "%.3d:%.3d" % (int(self.bus), int(self.device))
        desc = "%s %s" % (busstr, devstr)
        return desc

    def compare_to_hostdev(self, hostdev):
        devtype = hostdev.type
        if devtype == "usb":
            devtype = "usb_device"
        if devtype != self.device_type:
            return False

        return (_compare_int(self.product_id, hostdev.product) and
            _compare_int(self.vendor_id, hostdev.vendor) and
            _compare_int(self.bus, hostdev.bus) and
            _compare_int(self.device, hostdev.device))


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

    def pretty_name(self):
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


class DRMDevice(NodeDevice):
    drm_type = XMLProperty("./capability/type")

    def drm_pretty_name(self, conn):
        parent = NodeDevice.lookupNodedevFromString(conn, self.parent)

        return "%s (%s)" % (parent.pretty_name(), self.drm_type)


def _AddressStringToHostdev(conn, addrstr):
    from .devicehostdev import VirtualHostDevice
    hostdev = VirtualHostDevice(conn)

    try:
        # Determine addrstr type
        if addrstr.count(":") in [1, 2] and addrstr.count("."):
            addrstr, func = addrstr.split(".", 1)
            addrstr, slot = addrstr.rsplit(":", 1)
            domain = "0"
            if addrstr.count(":"):
                domain, bus = addrstr.split(":", 1)
            else:
                bus = addrstr

            hostdev.type = "pci"
            hostdev.domain = "0x%.4X" % int(domain, 16)
            hostdev.function = "0x%.2X" % int(func, 16)
            hostdev.slot = "0x%.2X" % int(slot, 16)
            hostdev.bus = "0x%.2X" % int(bus, 16)

        elif addrstr.count(":"):
            vendor, product = addrstr.split(":")

            hostdev.type = "usb"
            hostdev.vendor = "0x%.4X" % int(vendor, 16)
            hostdev.product = "0x%.4X" % int(product, 16)

        elif addrstr.count("."):
            bus, device = addrstr.split(".", 1)

            hostdev.type = "usb"
            hostdev.bus = bus
            hostdev.device = device
        else:
            raise RuntimeError("Unknown address type")
    except Exception:
        logging.debug("Error parsing node device string.", exc_info=True)
        raise

    return hostdev


def _AddressStringToNodedev(conn, addrstr):
    hostdev = _AddressStringToHostdev(conn, addrstr)

    # Iterate over node devices and compare
    count = 0
    nodedev = None

    for xmlobj in conn.fetch_all_nodedevs():
        if xmlobj.compare_to_hostdev(hostdev):
            nodedev = xmlobj
            count += 1

    if count == 1:
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
    elif t == NodeDevice.CAPABILITY_TYPE_DRM:
        return DRMDevice
    else:
        return NodeDevice
