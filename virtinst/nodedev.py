#
# Copyright 2009, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from .logger import log
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
    XML_NAME = "devnode"

    node_type = XMLProperty("./@type")
    path = XMLProperty(".")


class NodeDevice(XMLBuilder):
    CAPABILITY_TYPE_NET = "net"
    CAPABILITY_TYPE_PCI = "pci"
    CAPABILITY_TYPE_USBDEV = "usb_device"
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

        :param conn: libvirt.virConnect instance to perform the lookup on
        :param idstring: libvirt node device name to lookup, or address
            of the form:
            - bus.addr (ex. 001.003 for a usb device)
            - vendor:product (ex. 0x1234:0x5678 for a usb device
            - (domain:)bus:slot.func (ex. 00:10.0 for a pci device)

        :returns: NodeDevice instance
        """
        # First try and see if this is a libvirt nodedev name
        for nodedev in conn.fetch_all_nodedevs():
            if nodedev.name == idstring:
                return nodedev

        try:
            return _AddressStringToNodedev(conn, idstring)
        except Exception:
            log.debug("Error looking up nodedev from idstring=%s",
                idstring, exc_info=True)
            raise


    XML_NAME = "device"

    # Libvirt can generate bogus 'system' XML:
    # https://bugzilla.redhat.com/show_bug.cgi?id=1184131
    _XML_SANITIZE = True

    name = XMLProperty("./name")
    parent = XMLProperty("./parent")
    device_type = XMLProperty("./capability/@type")

    def compare_to_hostdev(self, hostdev):
        if self.device_type == "pci":
            if hostdev.type != "pci":
                return False

            return (_compare_int(self.domain, hostdev.domain) and
                _compare_int(self.bus, hostdev.bus) and
                _compare_int(self.slot, hostdev.slot) and
                _compare_int(self.function, hostdev.function))

        if self.device_type == "usb_device":
            if hostdev.type != "usb":
                return False

            return (_compare_int(self.product_id, hostdev.product) and
                _compare_int(self.vendor_id, hostdev.vendor) and
                _compare_int(self.bus, hostdev.bus) and
                _compare_int(self.device, hostdev.device))

        return False


    ########################
    # XML helper functions #
    ########################

    def is_pci_sriov(self):
        return self._capability_type == "virt_functions"
    def is_pci_bridge(self):
        return self._capability_type == "pci-bridge"

    def is_usb_linux_root_hub(self):
        return (self.vendor_id == "0x1d6b" and
                self.product_id in ["0x0001", "0x0002", "0x0003"])

    def is_drm_render(self):
        return self.device_type == "drm" and self.drm_type == "render"


    ##################
    # XML properties #
    ##################

    # type='net' options
    interface = XMLProperty("./capability/interface")

    # type='pci' options
    domain = XMLProperty("./capability/domain")
    bus = XMLProperty("./capability/bus")
    slot = XMLProperty("./capability/slot")
    function = XMLProperty("./capability/function")
    product_name = XMLProperty("./capability/product")
    vendor_name = XMLProperty("./capability/vendor")
    _capability_type = XMLProperty("./capability/capability/@type")

    # type='usb' options
    device = XMLProperty("./capability/device")
    product_id = XMLProperty("./capability/product/@id")
    vendor_id = XMLProperty("./capability/vendor/@id")

    # type='scsi' options
    host = XMLProperty("./capability/host")
    target = XMLProperty("./capability/target")
    lun = XMLProperty("./capability/lun")

    # type='storage' options
    block = XMLProperty("./capability/block")
    drive_type = XMLProperty("./capability/drive_type")

    media_label = XMLProperty(
        "./capability/capability[@type='removable']/media_label")
    media_available = XMLProperty(
            "./capability/capability[@type='removable']/media_available",
            is_int=True)

    # type='drm' options
    drm_type = XMLProperty("./capability/type")
    devnodes = XMLChildProperty(DevNode)

    def get_devnode(self, parent="by-path"):
        for d in self.devnodes:
            paths = d.path.split(os.sep)
            if len(paths) > 2 and paths[-2] == parent:
                return d
        if len(self.devnodes) > 0:
            return self.devnodes[0]


def _AddressStringToHostdev(conn, addrstr):
    from .devices import DeviceHostdev
    hostdev = DeviceHostdev(conn)

    try:
        # Determine addrstr type
        if addrstr.count(":") in [1, 2] and "." in addrstr:
            addrstr, func = addrstr.split(".", 1)
            addrstr, slot = addrstr.rsplit(":", 1)
            domain = "0"
            if ":" in addrstr:
                domain, bus = addrstr.split(":", 1)
            else:
                bus = addrstr

            hostdev.type = "pci"
            hostdev.domain = "0x%.4X" % int(domain, 16)
            hostdev.function = "0x%.2X" % int(func, 16)
            hostdev.slot = "0x%.2X" % int(slot, 16)
            hostdev.bus = "0x%.2X" % int(bus, 16)

        elif ":" in addrstr:
            vendor, product = addrstr.split(":")

            hostdev.type = "usb"
            hostdev.vendor = "0x%.4X" % int(vendor, 16)
            hostdev.product = "0x%.4X" % int(product, 16)

        elif "." in addrstr:
            bus, device = addrstr.split(".", 1)

            hostdev.type = "usb"
            hostdev.bus = bus
            hostdev.device = device
        else:
            raise RuntimeError("Unknown address type")
    except Exception:
        log.debug("Error parsing node device string.", exc_info=True)
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
