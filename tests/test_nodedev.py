# encoding=utf-8
#
# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os.path

import pytest

from virtinst import Guest
from virtinst import NodeDevice
from virtinst import DeviceHostdev

from tests import utils

# Requires XML_SANITIZE to parse correctly, see bug 1184131
funky_chars_xml = """
<device>
  <name>L3B2616</name>
  <capability type='LENOVOá'/>
</device>
"""

DATADIR = utils.DATADIR + "/nodedev/"


def _nodeDevFromName(conn, devname):
    node = conn.nodeDeviceLookupByName(devname)
    xml = node.XMLDesc(0)
    return NodeDevice(conn, xml)


def _testNode2DeviceCompare(conn, nodename, devfile, nodedev=None):
    devfile = os.path.join(DATADIR, "devxml", devfile)
    if not nodedev:
        nodedev = _nodeDevFromName(conn, nodename)

    dev = DeviceHostdev(conn)
    dev.set_from_nodedev(nodedev)
    dev.set_defaults(Guest(conn))
    utils.diff_compare(dev.get_xml() + "\n", devfile)


def check_version(conn, version):
    # pylint: disable=protected-access
    if conn.support._check_version(version):
        return

    msg = f"Skipping check due to version < {version}"
    raise pytest.skip(msg)


def testFunkyChars():
    # Ensure parsing doesn't fail
    conn = utils.URIs.open_testdriver_cached()
    dev = NodeDevice(conn, funky_chars_xml)
    assert dev.name == "L3B2616"
    assert dev.device_type == "LENOVO"


def testNetDevice():
    conn = utils.URIs.open_testdriver_cached()
    devname = "net_00_1c_25_10_b1_e4"
    dev = _nodeDevFromName(conn, devname)
    assert dev.name == devname
    assert dev.parent == "pci_8086_1049"
    assert dev.device_type == "net"
    assert dev.interface == "eth0"


def testPCIDevice():
    conn = utils.URIs.open_testdriver_cached()
    nodename = "pci_8086_10fb"
    obj = _nodeDevFromName(conn, nodename)
    assert obj.is_pci_sriov() is True
    nodename = "pci_8086_2448"
    obj = _nodeDevFromName(conn, nodename)
    assert obj.is_pci_bridge() is True



def testUSBDevDevice():
    conn = utils.URIs.open_testdriver_cached()
    devname = "usb_device_781_5151_2004453082054CA1BEEE"
    dev = _nodeDevFromName(conn, devname)
    assert dev.vendor_name == "SanDisk Corp."
    assert dev.product_name == "Cruzer Micro 256/512MB Flash Drive"

    devname = "usb_device_1d6b_1_0000_00_1a_0"
    dev = _nodeDevFromName(conn, devname)
    assert dev.is_usb_linux_root_hub() is True


def testSCSIDevice():
    conn = utils.URIs.open_testdriver_cached()
    devname = "pci_8086_2829_scsi_host_scsi_device_lun0"
    dev = _nodeDevFromName(conn, devname)
    assert dev.host == "0"
    assert dev.bus == "0"
    assert dev.target == "0"


def testStorageDevice():
    conn = utils.URIs.open_testdriver_cached()
    devname = "storage_serial_SATA_WDC_WD1600AAJS__WD_WCAP95119685"
    dev = _nodeDevFromName(conn, devname)
    assert dev.block == "/dev/sda"
    assert dev.drive_type == "disk"
    assert dev.media_available is None

    devname = "storage_model_DVDRAM_GSA_U1200N"
    dev = _nodeDevFromName(conn, devname)
    assert dev.media_label == "Fedora12_media"
    assert dev.media_available == 1


def testSCSIBus():
    conn = utils.URIs.open_testdriver_cached()
    devname = "pci_8086_2829_scsi_host_1"
    dev = _nodeDevFromName(conn, devname)
    assert dev.host == "2"


def testDRMDevice():
    conn = utils.URIs.open_testdriver_cached()
    devname = "drm_renderD129"
    dev = _nodeDevFromName(conn, devname)
    assert dev.devnodes[0].path == "/dev/dri/renderD129"
    assert dev.devnodes[0].node_type == "dev"
    assert dev.devnodes[1].path == "/dev/dri/by-path/pci-0000:00:02.0-render"
    assert dev.devnodes[1].node_type == "link"
    assert dev.is_drm_render() is True
    assert dev.get_devnode("frob")


def testDASDMdev():
    conn = utils.URIs.open_testdriver_cached()
    check_version(conn, "10.4.0")
    devname = "mdev_8e37ee90_2b51_45e3_9b25_bf8283c03110"
    dev = _nodeDevFromName(conn, devname)
    assert dev.name == devname
    assert dev.parent == "css_0_0_0023"
    assert dev.device_type == "mdev"
    assert dev.type_id == "vfio_ccw-io"


def testAPQNMdev():
    conn = utils.URIs.open_testdriver_cached()
    check_version(conn, "10.4.0")
    devname = "mdev_11f92c9d_b0b0_4016_b306_a8071277f8b9"
    dev = _nodeDevFromName(conn, devname)
    assert dev.name == devname
    assert dev.parent == "ap_matrix"
    assert dev.device_type == "mdev"
    assert dev.type_id == "vfio_ap-passthrough"


def testPCIMdev():
    conn = utils.URIs.open_testdriver_cached()
    check_version(conn, "10.4.0")
    devname = "mdev_4b20d080_1b54_4048_85b3_a6a62d165c01"
    dev = _nodeDevFromName(conn, devname)
    assert dev.name == devname
    assert dev.parent == "pci_0000_06_00_0"
    assert dev.device_type == "mdev"
    assert dev.type_id == "nvidia-11"
    assert dev.get_mdev_uuid() == "4b20d080-1b54-4048-85b3-a6a62d165c01"


def testPCIMdevNewFormat():
    conn = utils.URIs.open_testdriver_cached()
    check_version(conn, "10.4.0")
    devname = "mdev_35ceae7f_eea5_4f28_b7f3_7b12a3e62d3c_0000_06_00_0"
    dev = _nodeDevFromName(conn, devname)
    assert dev.name == devname
    assert dev.parent == "pci_0000_06_00_0"
    assert dev.device_type == "mdev"
    assert dev.type_id == "nvidia-11"
    assert dev.get_mdev_uuid() == "35ceae7f-eea5-4f28-b7f3-7b12a3e62d3c"


# NodeDevice 2 Device XML tests

def testNodeDev2USB1():
    conn = utils.URIs.open_testdriver_cached()
    nodename = "usb_device_781_5151_2004453082054CA1BEEE"
    devfile = "usbdev1.xml"
    _testNode2DeviceCompare(conn, nodename, devfile)


def testNodeDev2USB2():
    conn = utils.URIs.open_testdriver_cached()
    nodename = "usb_device_1d6b_2_0000_00_1d_7"
    devfile = "usbdev2.xml"
    nodedev = _nodeDevFromName(conn, nodename)

    _testNode2DeviceCompare(conn, nodename, devfile, nodedev=nodedev)


def testNodeDev2PCI():
    conn = utils.URIs.open_testdriver_cached()
    nodename = "pci_1180_592"
    devfile = "pcidev.xml"
    _testNode2DeviceCompare(conn, nodename, devfile)


def testNodeDevFail():
    conn = utils.URIs.open_testdriver_cached()
    nodename = "usb_device_1d6b_1_0000_00_1d_1_if0"
    devfile = ""

    # This should exist, since usbbus is not a valid device to
    # pass to a guest.
    with pytest.raises(ValueError):
        _testNode2DeviceCompare(conn, nodename, devfile)
