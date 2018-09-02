# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import tempfile
import unittest

import virtinst
from virtinst import DeviceDisk
from virtcli import CLIConfig

from tests import utils


def _make_guest(installer=None, conn=None, os_variant=None):
    if not conn:
        if installer:
            conn = installer.conn
        else:
            conn = utils.URIs.open_testdriver_cached()
    if not installer:
        installer = _make_installer(conn=conn)

    g = conn.caps.lookup_virtinst_guest()
    g.type = "kvm"
    g.name = "TestGuest"
    g.memory = int(200 * 1024)
    g.maxmemory = int(400 * 1024)
    g.uuid = "12345678-1234-1234-1234-123456789012"
    gdev = virtinst.DeviceGraphics(conn)
    gdev.type = "vnc"
    gdev.keymap = "ja"
    g.add_device(gdev)
    g.features.pae = False
    g.vcpus = 5

    g.installer = installer
    g.emulator = "/usr/lib/xen/bin/qemu-dm"
    g.os.arch = "i686"
    g.os.os_type = "hvm"

    if os_variant:
        g.os_variant = os_variant
    g.add_default_input_device()
    g.add_default_console_device()
    g.add_device(virtinst.DeviceSound(g.conn))

    # Floppy disk
    path = "/dev/default-pool/testvol1.img"
    d = DeviceDisk(conn)
    d.path = path
    d.device = d.DEVICE_FLOPPY
    d.validate()
    g.add_device(d)

    # File disk
    path = "/dev/default-pool/new-test-suite.img"
    d = virtinst.DeviceDisk(conn)
    d.path = path

    if d.wants_storage_creation():
        parent_pool = d.get_parent_pool()
        vol_install = virtinst.DeviceDisk.build_vol_install(conn,
            os.path.basename(path), parent_pool, .0000001, True)
        d.set_vol_install(vol_install)

    d.validate()
    g.add_device(d)

    # Block disk
    path = "/dev/disk-pool/diskvol1"
    d = virtinst.DeviceDisk(conn)
    d.path = path
    d.validate()
    g.add_device(d)

    # Network device
    dev = virtinst.DeviceInterface(conn)
    dev.macaddr = "22:22:33:44:55:66"
    dev.type = virtinst.DeviceInterface.TYPE_VIRTUAL
    dev.source = "default"
    g.add_device(dev)

    return g


def _make_installer(location=None, conn=None):
    conn = conn or utils.URIs.open_testdriver_cached()
    inst = virtinst.DistroInstaller(conn)
    if location:
        inst.location = location
    else:
        inst.location = "/dev/null"
        inst.cdrom = True
    return inst


class TestXMLMisc(unittest.TestCase):
    """
    Misc tests for various XML special behavior. These should only aim for
    testing any particularly tricky bits, general XML generation should
    be through virt-install examples in clitest
    """
    @property
    def conn(self):
        return utils.URIs.open_testdefault_cached()

    def _compare(self, guest, filebase, do_install):
        filename = os.path.join("tests/xmlconfig-xml", filebase + ".xml")

        inst_xml, boot_xml = guest.start_install(return_xml=True, dry=True)
        if do_install:
            actualXML = inst_xml
        else:
            actualXML = boot_xml

        utils.diff_compare(actualXML, filename)
        utils.test_create(guest.conn, actualXML)

    def testDiskNumbers(self):
        # Various testing our target generation
        self.assertEqual("a", DeviceDisk.num_to_target(1))
        self.assertEqual("b", DeviceDisk.num_to_target(2))
        self.assertEqual("z", DeviceDisk.num_to_target(26))
        self.assertEqual("aa", DeviceDisk.num_to_target(27))
        self.assertEqual("ab", DeviceDisk.num_to_target(28))
        self.assertEqual("az", DeviceDisk.num_to_target(52))
        self.assertEqual("ba", DeviceDisk.num_to_target(53))
        self.assertEqual("zz", DeviceDisk.num_to_target(27 * 26))
        self.assertEqual("aaa", DeviceDisk.num_to_target(27 * 26 + 1))

        self.assertEqual(DeviceDisk.target_to_num("hda"), 0)
        self.assertEqual(DeviceDisk.target_to_num("hdb"), 1)
        self.assertEqual(DeviceDisk.target_to_num("sdz"), 25)
        self.assertEqual(DeviceDisk.target_to_num("sdaa"), 26)
        self.assertEqual(DeviceDisk.target_to_num("vdab"), 27)
        self.assertEqual(DeviceDisk.target_to_num("vdaz"), 51)
        self.assertEqual(DeviceDisk.target_to_num("xvdba"), 52)
        self.assertEqual(DeviceDisk.target_to_num("xvdzz"),
            26 * (25 + 1) + 25)
        self.assertEqual(DeviceDisk.target_to_num("xvdaaa"),
            26 * 26 * 1 + 26 * 1 + 0)

        disk = virtinst.DeviceDisk(self.conn)
        disk.bus = "ide"

        self.assertEqual("hda", disk.generate_target([]))
        self.assertEqual("hdb", disk.generate_target(["hda"]))
        self.assertEqual("hdc", disk.generate_target(["hdb", "sda"]))
        self.assertEqual("hdb", disk.generate_target(["hda", "hdd"]))

        disk.bus = "virtio-scsi"
        self.assertEqual("sdb",
            disk.generate_target(["sda", "sdg", "sdi"], 0))
        self.assertEqual("sdh", disk.generate_target(["sda", "sdg"], 1))

    def testQuickTreeinfo(self):
        # Simple sanity test to make sure detect_distro works. test-urls
        # does much more exhaustive testing but it's only run occasionally
        i = _make_installer(
            location="tests/cli-test-xml/fakefedoratree")
        g = _make_guest(i)
        v = i.detect_distro(g)
        self.assertEqual(v, "fedora17")

        i = _make_installer(
            location="tests/cli-test-xml/fakerhel6tree")
        g = _make_guest(i)
        v = i.detect_distro(g)
        self.assertEqual(v, "rhel6.0")

    def testCPUTopology(self):
        # Test CPU topology determining
        cpu = virtinst.DomainCpu(self.conn)
        cpu.sockets = "2"
        cpu.set_topology_defaults(6)
        self.assertEqual([cpu.sockets, cpu.cores, cpu.threads], [2, 3, 1])

        cpu = virtinst.DomainCpu(self.conn)
        cpu.cores = "4"
        cpu.set_topology_defaults(9)
        self.assertEqual([cpu.sockets, cpu.cores, cpu.threads], [2, 4, 1])

        cpu = virtinst.DomainCpu(self.conn)
        cpu.threads = "3"
        cpu.set_topology_defaults(14)
        self.assertEqual([cpu.sockets, cpu.cores, cpu.threads], [4, 1, 3])

        cpu = virtinst.DomainCpu(self.conn)
        cpu.sockets = 5
        cpu.cores = 2
        self.assertEqual(cpu.vcpus_from_topology(), 10)

        cpu = virtinst.DomainCpu(self.conn)
        self.assertEqual(cpu.vcpus_from_topology(), 1)

    def test_hyperv_clock(self):
        def _make(connver):
            conn = utils.URIs.open_kvm(libver=1002002, connver=connver)
            g = _make_guest(conn=conn, os_variant="win7")
            g.emulator = "/usr/libexec/qemu-kvm"
            return g

        try:
            g = _make(2000000)
            self._compare(g, "install-hyperv-clock", True)

            g = _make(1009000)
            self._compare(g, "install-hyperv-noclock", True)

            CLIConfig.stable_defaults = True

            g = _make(1005003)
            self._compare(g, "install-hyperv-clock", True)

            g = _make(1005002)
            self._compare(g, "install-hyperv-noclock", True)
        finally:
            CLIConfig.stable_defaults = False

    def test_dir_searchable(self):
        # Normally the dir searchable test is skipped in the unittest,
        # but let's contrive an example that should trigger all the code
        from virtinst.devices.disk import _is_dir_searchable
        oldtest = os.environ.pop("VIRTINST_TEST_SUITE")
        try:
            uid = -1
            username = "fakeuser-zzzz"
            with tempfile.TemporaryDirectory() as tmpdir:
                self.assertFalse(_is_dir_searchable(uid, username, tmpdir))
        finally:
            os.environ["VIRTINST_TEST_SUITE"] = oldtest
