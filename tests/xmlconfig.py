# Copyright (C) 2013, 2014 Red Hat, Inc.
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

import unittest
import os

import virtinst
from virtinst import VirtualDisk
from virtcli import CLIConfig

from tests import utils


_default_conn = utils.open_testdriver()


def _make_guest(installer=None, conn=None):
    if conn is None:
        conn = _default_conn

    g = conn.caps.lookup_virtinst_guest()
    g.type = "kvm"
    g.name = "TestGuest"
    g.memory = int(200 * 1024)
    g.maxmemory = int(400 * 1024)
    g.uuid = "12345678-1234-1234-1234-123456789012"
    gdev = virtinst.VirtualGraphics(conn)
    gdev.type = "vnc"
    gdev.keymap = "ja"
    g.add_device(gdev)
    g.features.pae = False
    g.vcpus = 5

    if not installer:
        installer = _make_installer(conn=conn)
    g.installer = installer
    g.emulator = "/usr/lib/xen/bin/qemu-dm"
    g.os.arch = "i686"
    g.os.os_type = "hvm"

    g.add_default_input_device()
    g.add_default_console_device()
    g.add_device(virtinst.VirtualAudio(g.conn))

    # Floppy disk
    path = "/dev/default-pool/testvol1.img"
    d = VirtualDisk(conn)
    d.path = path
    d.device = d.DEVICE_FLOPPY
    d.validate()
    g.add_device(d)

    # File disk
    path = "/dev/default-pool/new-test-suite.img"
    d = virtinst.VirtualDisk(conn)
    d.path = path

    if d.wants_storage_creation():
        parent_pool = d.get_parent_pool()
        vol_install = virtinst.VirtualDisk.build_vol_install(conn,
            os.path.basename(path), parent_pool, .0000001, True)
        d.set_vol_install(vol_install)

    d.validate()
    g.add_device(d)

    # Block disk
    path = "/dev/disk-pool/diskvol1"
    d = virtinst.VirtualDisk(conn)
    d.path = path
    d.validate()
    g.add_device(d)

    # Network device
    dev = virtinst.VirtualNetworkInterface(conn)
    dev.macaddr = "22:22:33:44:55:66"
    dev.type = virtinst.VirtualNetworkInterface.TYPE_VIRTUAL
    dev.source = "default"
    g.add_device(dev)

    return g


def _make_installer(location=None, conn=None):
    conn = conn or _default_conn
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
    def _compare(self, guest, filebase, do_install):
        filename = os.path.join("tests/xmlconfig-xml", filebase + ".xml")

        inst_xml, boot_xml = guest.start_install(return_xml=True, dry=True)
        if do_install:
            actualXML = inst_xml
        else:
            actualXML = boot_xml

        utils.diff_compare(actualXML, filename)
        utils.test_create(guest.conn, actualXML)

    def testDefaultBridge(self):
        # Test our handling of the default bridge routines
        origfunc = None
        util = None
        try:
            util = getattr(virtinst, "util")
            origfunc = util.default_bridge

            def newbridge(ignore_conn):
                return "bzz0"
            util.default_bridge = newbridge

            dev1 = virtinst.VirtualNetworkInterface(_default_conn)
            dev1.macaddr = "22:22:33:44:55:66"

            dev2 = virtinst.VirtualNetworkInterface(_default_conn,
                                    parsexml=dev1.get_xml_config())
            dev2.source = None
            dev2.source = "foobr0"
            dev2.macaddr = "22:22:33:44:55:67"

            dev3 = virtinst.VirtualNetworkInterface(_default_conn,
                                    parsexml=dev1.get_xml_config())
            dev3.source = None
            dev3.macaddr = "22:22:33:44:55:68"

            utils.diff_compare(dev1.get_xml_config(), None,
                               "<interface type=\"bridge\">\n"
                               "  <source bridge=\"bzz0\"/>\n"
                               "  <mac address=\"22:22:33:44:55:66\"/>\n"
                               "</interface>\n")
            utils.diff_compare(dev2.get_xml_config(), None,
                               "<interface type=\"bridge\">\n"
                               "  <source bridge=\"foobr0\"/>\n"
                               "  <mac address=\"22:22:33:44:55:67\"/>\n"
                               "</interface>\n")
            utils.diff_compare(dev3.get_xml_config(), None,
                               "<interface type=\"bridge\">\n"
                               "  <mac address=\"22:22:33:44:55:68\"/>\n"
                               "</interface>\n")
        finally:
            if util and origfunc:
                util.default_bridge = origfunc

    def testCpustrToTuple(self):
        # Various testing our cpustr handling
        conn = _default_conn
        base = [False] * 16

        expect = base[:]
        expect[1] = expect[2] = expect[3] = True
        self.assertEquals(tuple(expect),
            virtinst.DomainNumatune.cpuset_str_to_tuple(conn, "1-3"))

        expect = base[:]
        expect[1] = expect[3] = expect[5] = expect[10] = expect[11] = True
        self.assertEquals(tuple(expect),
            virtinst.DomainNumatune.cpuset_str_to_tuple(conn, "1,3,5,10-11"))

        self.assertRaises(ValueError,
            virtinst.DomainNumatune.cpuset_str_to_tuple,
            conn, "16")

    def testDiskNumbers(self):
        # Various testing our target generation
        self.assertEquals("a", VirtualDisk.num_to_target(1))
        self.assertEquals("b", VirtualDisk.num_to_target(2))
        self.assertEquals("z", VirtualDisk.num_to_target(26))
        self.assertEquals("aa", VirtualDisk.num_to_target(27))
        self.assertEquals("ab", VirtualDisk.num_to_target(28))
        self.assertEquals("az", VirtualDisk.num_to_target(52))
        self.assertEquals("ba", VirtualDisk.num_to_target(53))
        self.assertEquals("zz", VirtualDisk.num_to_target(27 * 26))
        self.assertEquals("aaa", VirtualDisk.num_to_target(27 * 26 + 1))

        self.assertEquals(VirtualDisk.target_to_num("hda"), 0)
        self.assertEquals(VirtualDisk.target_to_num("hdb"), 1)
        self.assertEquals(VirtualDisk.target_to_num("sdz"), 25)
        self.assertEquals(VirtualDisk.target_to_num("sdaa"), 26)
        self.assertEquals(VirtualDisk.target_to_num("vdab"), 27)
        self.assertEquals(VirtualDisk.target_to_num("vdaz"), 51)
        self.assertEquals(VirtualDisk.target_to_num("xvdba"), 52)
        self.assertEquals(VirtualDisk.target_to_num("xvdzz"),
            26 * (25 + 1) + 25)
        self.assertEquals(VirtualDisk.target_to_num("xvdaaa"),
            26 * 26 * 1 + 26 * 1 + 0)

        disk = virtinst.VirtualDisk(_default_conn)
        disk.bus = "ide"

        self.assertEquals("hda", disk.generate_target([]))
        self.assertEquals("hdb", disk.generate_target(["hda"]))
        self.assertEquals("hdc", disk.generate_target(["hdb", "sda"]))
        self.assertEquals("hdb", disk.generate_target(["hda", "hdd"]))

        disk.bus = "virtio-scsi"
        self.assertEquals("sdb",
            disk.generate_target(["sda", "sdg", "sdi"], 0))
        self.assertEquals("sdh", disk.generate_target(["sda", "sdg"], 1))

    def testQuickTreeinfo(self):
        # Simple sanity test to make sure detect_distro works. test-urls
        # does much more exhaustive testing but it's only run occasionally
        i = _make_installer(
            location="tests/cli-test-xml/fakefedoratree")
        g = _make_guest(i)
        v = i.detect_distro(g)
        self.assertEquals(v, "fedora17")

        i = _make_installer(
            location="tests/cli-test-xml/fakerhel6tree")
        g = _make_guest(i)
        v = i.detect_distro(g)
        self.assertEquals(v, "rhel6.0")

    def testCPUTopology(self):
        # Test CPU topology determining
        cpu = virtinst.CPU(_default_conn)
        cpu.sockets = "2"
        cpu.set_topology_defaults(6)
        self.assertEquals([cpu.sockets, cpu.cores, cpu.threads], [2, 3, 1])

        cpu = virtinst.CPU(_default_conn)
        cpu.cores = "4"
        cpu.set_topology_defaults(9)
        self.assertEquals([cpu.sockets, cpu.cores, cpu.threads], [2, 4, 1])

        cpu = virtinst.CPU(_default_conn)
        cpu.threads = "3"
        cpu.set_topology_defaults(14)
        self.assertEquals([cpu.sockets, cpu.cores, cpu.threads], [4, 1, 3])

        cpu = virtinst.CPU(_default_conn)
        cpu.sockets = 5
        cpu.cores = 2
        self.assertEquals(cpu.vcpus_from_topology(), 10)

        cpu = virtinst.CPU(_default_conn)
        self.assertEquals(cpu.vcpus_from_topology(), 1)

    def testAC97(self):
        # Test setting ac97 version given various version combos
        def has_ac97(conn):
            g = _make_guest(conn=conn)

            g.os_variant = "fedora11"

            # pylint: disable=unpacking-non-sequence
            xml, ignore = g.start_install(return_xml=True, dry=True)
            return "ac97" in xml

        self.assertTrue(has_ac97(utils.open_kvm(connver=11000)))
        self.assertFalse(has_ac97(utils.open_kvm(libver=5000)))
        self.assertFalse(has_ac97(utils.open_kvm(libver=7000, connver=7000)))

    def testOSDeviceDefaultChange(self):
        """
        Make sure device defaults are properly changed if we change OS
        distro/variant mid process
        """
        # Use connver=12005 so that non-rhel displays ac97
        conn = utils.open_kvm_rhel(connver=12005)

        g = _make_guest(conn=conn)
        g.os_variant = "fedora11"
        self._compare(g, "install-f11-norheldefaults", False)

        try:
            CLIConfig.stable_defaults = True

            g = _make_guest(conn=conn)
            g.os_variant = "fedora11"
            origemu = g.emulator
            g.emulator = "/usr/libexec/qemu-kvm"
            self.assertTrue(g.conn.stable_defaults())

            setattr(g.conn, "_support_cache", {})
            self._compare(g, "install-f11-rheldefaults", False)
            g.emulator = origemu
            setattr(g.conn, "_support_cache", {})
        finally:
            CLIConfig.stable_defaults = False

    def test_no_vmvga_RHEL(self):
        # Test that vmvga is not used on RHEL
        conn = utils.open_kvm_rhel()
        def _make():
            g = _make_guest(conn=conn)
            g.emulator = "/usr/libexec/qemu-kvm"
            g.add_default_video_device()
            g.os_variant = "ubuntu13.10"
            return g

        try:
            g = _make()
            self._compare(g, "install-novmvga-rhel", True)

            CLIConfig.stable_defaults = True
            g = _make()
            self._compare(g, "install-novmvga-rhel", True)
        finally:
            CLIConfig.stable_defaults = False

    def test_hyperv_clock(self):
        def _make(connver):
            conn = utils.open_kvm(libver=1002002, connver=connver)
            g = _make_guest(conn=conn)
            g.os_variant = "win7"
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
