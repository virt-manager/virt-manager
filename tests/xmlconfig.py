# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import tempfile
import unittest

import virtinst
from virtinst import DeviceDisk

from tests import utils


def _make_guest(conn=None, os_variant=None):
    if not conn:
        conn = utils.URIs.open_testdriver_cached()

    g = virtinst.Guest(conn)
    g.name = "TestGuest"
    g.memory = int(200 * 1024)
    g.maxmemory = int(400 * 1024)

    if os_variant:
        g.set_os_name(os_variant)

    # File disk
    d = virtinst.DeviceDisk(conn)
    d.path = "/dev/default-pool/new-test-suite.img"
    if d.wants_storage_creation():
        parent_pool = d.get_parent_pool()
        vol_install = virtinst.DeviceDisk.build_vol_install(conn,
            os.path.basename(d.path), parent_pool, .0000001, True)
        d.set_vol_install(vol_install)
    d.validate()
    g.add_device(d)

    # Block disk
    d = virtinst.DeviceDisk(conn)
    d.path = "/dev/disk-pool/diskvol1"
    d.validate()
    g.add_device(d)

    # Network device
    dev = virtinst.DeviceInterface(conn)
    g.add_device(dev)

    return g


def _make_installer(location=None, conn=None):
    conn = conn or utils.URIs.open_testdriver_cached()
    cdrom = not location and "/dev/null" or None
    inst = virtinst.Installer(conn, location=location, cdrom=cdrom)
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

        installer = _make_installer(conn=guest.conn)
        inst_xml, boot_xml = installer.start_install(
                guest, return_xml=True, dry=True)
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
        g = _make_guest()
        v = i.detect_distro(g)
        self.assertEqual(v, "fedora17")

        i = _make_installer(
            location="tests/cli-test-xml/fakerhel6tree")
        g = _make_guest()
        v = i.detect_distro(g)
        self.assertEqual(v, "rhel6.0")

    def testCDROMInsert(self):
        # After set_install_defaults, cdrom media should be inserted
        i = _make_installer()
        g = _make_guest()
        i.set_install_defaults(g)
        for disk in g.devices.disk:
            if disk.device == "cdrom" and disk.path == "/dev/null":
                return
        raise AssertionError("Didn't find inserted cdrom media")

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

    def test_set_defaults_double(self):
        """
        Check that a common config has idempotent set_defaults
        """
        g = _make_guest(conn=utils.URIs.open_kvm(), os_variant="fedora-unknown")

        g.set_defaults(None)
        xml1 = g.get_xml()
        g.set_defaults(None)
        xml2 = g.get_xml()
        self.assertEqual(xml1, xml2)

    def test_guest_osinfo_metadata(self):
        g = _make_guest()
        self.assertEqual(g.osinfo.name, "generic")
        g.set_os_name("fedora17")
        self.assertEqual(g.osinfo.name, "fedora17")

        g = _make_guest()
        g._metadata.libosinfo.os_id = "http://fedoraproject.org/fedora/20"  # pylint: disable=protected-access
        self.assertEqual(g.osinfo.name, "fedora20")

        g = _make_guest()
        g._metadata.libosinfo.os_id = "http://example.com/idontexit"  # pylint: disable=protected-access
        self.assertEqual(g.osinfo.name, "generic")

    def test_dir_searchable(self):
        # Normally the dir searchable test is skipped in the unittest,
        # but let's contrive an example that should trigger all the code
        # to ensure it isn't horribly broken
        from virtinst import diskbackend
        oldtest = os.environ.pop("VIRTINST_TEST_SUITE")
        try:
            uid = -1
            username = "fakeuser-zzzz"
            with tempfile.TemporaryDirectory() as tmpdir:
                fixlist = diskbackend.is_path_searchable(tmpdir, uid, username)
                self.assertTrue(bool(fixlist))
                errdict = diskbackend.set_dirs_searchable(fixlist, username)
                self.assertTrue(not bool(errdict))


            import getpass
            fixlist = diskbackend.is_path_searchable(
                    os.getcwd(), os.getuid(), getpass.getuser())
            self.assertTrue(not bool(fixlist))
        finally:
            os.environ["VIRTINST_TEST_SUITE"] = oldtest
