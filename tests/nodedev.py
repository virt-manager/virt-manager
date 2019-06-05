# encoding=utf-8
#
# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os.path
import unittest

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


class TestNodeDev(unittest.TestCase):
    @property
    def conn(self):
        return utils.URIs.open_testdriver_cached()

    def _nodeDevFromName(self, devname):
        node = self.conn.nodeDeviceLookupByName(devname)
        xml = node.XMLDesc(0)
        return NodeDevice.parse(self.conn, xml)

    def _testCompare(self, devname, vals):
        def _compare(dev, vals, root=""):
            for attr in list(vals.keys()):
                expect = vals[attr]
                actual = getattr(dev, attr)
                if isinstance(expect, list):
                    for adev, exp in zip(actual, expect):
                        _compare(adev, exp, attr + ".")
                else:
                    if expect != actual:
                        raise AssertionError("devname=%s attribute=%s%s did not match:\n"
                            "expect=%s\nactual=%s" % (devname, root, attr, expect, actual))
                    self.assertEqual(vals[attr], getattr(dev, attr))

        dev = self._nodeDevFromName(devname)

        _compare(dev, vals)
        return dev

    def _testNode2DeviceCompare(self, nodename, devfile, nodedev=None):
        devfile = os.path.join("tests/nodedev-xml/devxml", devfile)
        if not nodedev:
            nodedev = self._nodeDevFromName(nodename)

        dev = DeviceHostdev(self.conn)
        dev.set_from_nodedev(nodedev)
        dev.set_defaults(Guest(self.conn))
        utils.diff_compare(dev.get_xml() + "\n", devfile)

    def testFunkyChars(self):
        # Ensure parsing doesn't fail
        dev = NodeDevice.parse(self.conn, funky_chars_xml)
        self.assertEqual(dev.name, "L3B2616")
        self.assertEqual(dev.device_type, "LENOVO")
        self.assertEqual(dev.pretty_name(), dev.name)

    def testNetDevice(self):
        devname = "net_00_1c_25_10_b1_e4"
        dev = self._nodeDevFromName(devname)
        self.assertEqual(dev.name, devname)
        self.assertEqual(dev.parent, "pci_8086_1049")
        self.assertEqual(dev.device_type, "net")
        self.assertEqual(dev.interface, "eth0")
        self.assertEqual(dev.pretty_name(), "Interface eth0")

    def testPCIDevice(self):
        devname = "pci_1180_592"
        dev = self._nodeDevFromName(devname)
        self.assertEqual(dev.pretty_name(),
            "0000:15:00:4 Ricoh Co Ltd R5C592 Memory Stick Bus Host Adapter")

        devname = "pci_8086_1049"
        dev = self._nodeDevFromName(devname)
        self.assertEqual(dev.pretty_name(),
            "0000:00:19:0 Intel Corporation 82566MM Gigabit Network Connection")

        nodename = "pci_8086_10fb"
        obj = self._nodeDevFromName(nodename)
        self.assertEqual(obj.is_pci_sriov(), True)
        nodename = "pci_8086_2448"
        obj = self._nodeDevFromName(nodename)
        self.assertEqual(obj.is_pci_bridge(), True)


    def testUSBDevDevice1(self):
        devname = "usb_device_781_5151_2004453082054CA1BEEE"
        vals = {"name": "usb_device_781_5151_2004453082054CA1BEEE",
                "parent": "usb_device_1d6b_2_0000_00_1a_7",
                "device_type": NodeDevice.CAPABILITY_TYPE_USBDEV,
                "bus": "1", "device": "4", "product_id": '0x5151',
                "vendor_id": '0x0781',
                "vendor_name": "SanDisk Corp.",
                "product_name": "Cruzer Micro 256/512MB Flash Drive"}
        self._testCompare(devname, vals)

    def testUSBDevDevice2(self):
        devname = "usb_device_483_2016_noserial"
        vals = {"name": "usb_device_483_2016_noserial",
                "parent": "usb_device_1d6b_1_0000_00_1a_0",
                "device_type": NodeDevice.CAPABILITY_TYPE_USBDEV,
                "bus": "3", "device": "2", "product_id": '0x2016',
                "vendor_id": '0x0483',
                "vendor_name": "SGS Thomson Microelectronics",
                "product_name": "Fingerprint Reader"}
        self._testCompare(devname, vals)

    def testStorageDevice1(self):
        devname = "storage_serial_SATA_WDC_WD1600AAJS__WD_WCAP95119685"
        vals = {"name": "storage_serial_SATA_WDC_WD1600AAJS__WD_WCAP95119685",
                "parent": "pci_8086_27c0_scsi_host_scsi_device_lun0",
                "devnodes": [
                    {"path": "/dev/sda", "node_type": "dev"}
                ],
                "device_type": NodeDevice.CAPABILITY_TYPE_STORAGE,
                "block": "/dev/sda", "bus": "scsi", "drive_type": "disk",
                "model": "WDC WD1600AAJS-2", "vendor": "ATA",
                "size": 160041885696, "removable": False,
                "hotpluggable": False, "media_available": None,
                "media_size": None, "media_label": None}
        self._testCompare(devname, vals)

    def testStorageDevice2(self):
        devname = "storage_serial_SanDisk_Cruzer_Micro_2004453082054CA1BEEE_0_0"
        vals = {"name": "storage_serial_SanDisk_Cruzer_Micro_2004453082054CA1BEEE_0_0",
                "parent": "usb_device_781_5151_2004453082054CA1BEEE_if0_scsi_host_0_scsi_device_lun0",
                "device_type": NodeDevice.CAPABILITY_TYPE_STORAGE,
                "block": "/dev/sdb", "bus": "usb", "drive_type": "disk",
                "model": "Cruzer Micro", "vendor": "SanDisk", "size": None,
                "removable": True, "hotpluggable": True,
                "media_available": True, "media_size": 12345678}
        self._testCompare(devname, vals)

    def testUSBBus(self):
        devname = "usb_device_1d6b_1_0000_00_1d_1_if0"
        vals = {"name": "usb_device_1d6b_1_0000_00_1d_1_if0",
                "parent": "usb_device_1d6b_1_0000_00_1d_1",
                "device_type": NodeDevice.CAPABILITY_TYPE_USBBUS,
                "number": "0", "classval": "9", "subclass": "0",
                "protocol": "0"}
        self._testCompare(devname, vals)

    def testSCSIBus(self):
        devname = "pci_8086_2829_scsi_host_1"
        vals = {"name": "pci_8086_2829_scsi_host_1",
                "parent": "pci_8086_2829",
                "device_type": NodeDevice.CAPABILITY_TYPE_SCSIBUS,
                "host": "2"}
        self._testCompare(devname, vals)

    def testNPIV(self):
        devname = "pci_10df_fe00_0_scsi_host"
        vals = {"name": "pci_10df_fe00_0_scsi_host",
                "device_type": NodeDevice.CAPABILITY_TYPE_SCSIBUS,
                "host": "4", "fc_host": True, "vport_ops": True,
                "wwnn": "20000000c9848141", "wwpn": "10000000c9848141"}
        self._testCompare(devname, vals)

    def testSCSIDevice(self):
        devname = "pci_8086_2829_scsi_host_scsi_device_lun0"
        vals = {"name": "pci_8086_2829_scsi_host_scsi_device_lun0",
                "parent": "pci_8086_2829_scsi_host",
                "host": "0", "bus": "0", "target": "0", "lun": "0",
                "type": "disk"}
        self._testCompare(devname, vals)

    def testDRMDevice(self):
        devname = "drm_renderD129"
        vals = {"name": "drm_renderD129",
                "parent": "pci_0000_00_02_0",
                "devnodes": [
                    {"path": "/dev/dri/renderD129", "node_type": "dev"},
                    {"path": "/dev/dri/by-path/pci-0000:00:02.0-render", "node_type": "link"},
                    {"path": "/dev/dri/by-id/foo-render", "node_type": "link"}
                ],
                "device_type": NodeDevice.CAPABILITY_TYPE_DRM,
                "drm_type": "render"}
        dev = self._testCompare(devname, vals)
        self.assertEqual(dev.drm_pretty_name(self.conn),
                         "0000:00:02:0 Intel Corporation HD Graphics 530 (render)")


    # NodeDevice 2 Device XML tests
    def testNodeDev2USB1(self):
        nodename = "usb_device_781_5151_2004453082054CA1BEEE"
        devfile = "usbdev1.xml"
        self._testNode2DeviceCompare(nodename, devfile)

    def testNodeDev2USB2(self):
        nodename = "usb_device_1d6b_2_0000_00_1d_7"
        devfile = "usbdev2.xml"
        nodedev = self._nodeDevFromName(nodename)

        self._testNode2DeviceCompare(nodename, devfile, nodedev=nodedev)

    def testNodeDev2PCI(self):
        nodename = "pci_1180_592"
        devfile = "pcidev.xml"
        self._testNode2DeviceCompare(nodename, devfile)

    def testNodeDevFail(self):
        nodename = "usb_device_1d6b_1_0000_00_1d_1_if0"
        devfile = ""

        # This should exist, since usbbus is not a valid device to
        # pass to a guest.
        self.assertRaises(ValueError,
                          self._testNode2DeviceCompare, nodename, devfile)
