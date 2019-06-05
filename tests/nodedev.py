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


    def testUSBDevDevice(self):
        devname = "usb_device_781_5151_2004453082054CA1BEEE"
        dev = self._nodeDevFromName(devname)
        self.assertEqual(dev.pretty_name(),
                "001:004 SanDisk Corp. Cruzer Micro 256/512MB Flash Drive")

        devname = "usb_device_483_2016_noserial"
        dev = self._nodeDevFromName(devname)
        self.assertEqual(dev.pretty_name(),
                "003:002 SGS Thomson Microelectronics Fingerprint Reader")

        devname = "usb_device_1d6b_1_0000_00_1a_0"
        dev = self._nodeDevFromName(devname)
        self.assertTrue(dev.is_usb_linux_root_hub())

    def testSCSIDevice(self):
        devname = "pci_8086_2829_scsi_host_scsi_device_lun0"
        dev = self._nodeDevFromName(devname)
        self.assertEqual(dev.host, "0")
        self.assertEqual(dev.bus, "0")
        self.assertEqual(dev.target, "0")

    def testStorageDevice(self):
        devname = "storage_serial_SATA_WDC_WD1600AAJS__WD_WCAP95119685"
        dev = self._nodeDevFromName(devname)
        self.assertEqual(dev.block, "/dev/sda")
        self.assertEqual(dev.drive_type, "disk")
        self.assertEqual(dev.media_available, None)

        devname = "storage_model_DVDRAM_GSA_U1200N"
        dev = self._nodeDevFromName(devname)
        self.assertEqual(dev.media_label, "Fedora12_media")
        self.assertEqual(dev.media_available, 1)

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
