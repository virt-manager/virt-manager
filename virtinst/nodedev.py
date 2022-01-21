#
# Copyright 2009, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import uuid

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


def _compare_uuid(nodedev_val, hostdev_val):
    try:
        nodedev_val = uuid.UUID(nodedev_val)
        hostdev_val = uuid.UUID(hostdev_val)
    except Exception:  # pragma: no cover
        return -1

    return (nodedev_val == hostdev_val)


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
    CAPABILITY_TYPE_MDEV = "mdev"

    @staticmethod
    def lookupNodedevByName(conn, name):
        """
        Search the nodedev list cache for a matching name, and return the
        result.

        :param conn: libvirt.virConnect instance to perform the lookup on
        :param conn: nodedev name
        :returns: NodeDevice instance
        """
        for nodedev in conn.fetch_all_nodedevs():
            if nodedev.name == name:
                return nodedev


    XML_NAME = "device"

    # Libvirt can generate bogus 'system' XML:
    # https://bugzilla.redhat.com/show_bug.cgi?id=1184131
    _XML_SANITIZE = True

    name = XMLProperty("./name")
    parent = XMLProperty("./parent")
    device_type = XMLProperty("./capability/@type")

    def get_mdev_uuid(self):
        # libvirt 7.3.0 added a <uuid> element to the nodedev xml for mdev
        # types. For older versions, we unfortunately have to parse the nodedev
        # name, which uses the format "mdev_$UUID_WITH_UNDERSCORES"
        if self.uuid is not None:
            return self.uuid

        return self.name[5:].replace('_', '-')

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

        if self.device_type == "mdev":
            if hostdev.type != "mdev":
                return False

            return _compare_uuid(self.get_mdev_uuid(), hostdev.uuid)

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

    # type='mdev' options
    type_id = XMLProperty("./capability/type/@id")
    uuid = XMLProperty("./capability/uuid")
