# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import tempfile
import unittest

import virtinst
from virtinst import cli
from virtinst import DeviceDisk

from tests import utils


def _make_guest(conn=None, os_variant=None):
    if not conn:
        conn = utils.URIs.open_testdriver_cached()

    g = virtinst.Guest(conn)
    g.name = "TestGuest"
    g.currentMemory = int(200 * 1024)
    g.memory = int(400 * 1024)

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
    be through virt-install examples in test_cli
    """
    @property
    def conn(self):
        return utils.URIs.open_testdefault_cached()

    def _compare(self, guest, filebase, do_install):
        filename = os.path.join("tests/data/xmlconfig", filebase + ".xml")

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
        #
        # Note: using single quotes in strings to avoid
        # codespell flagging the 'ba' assert
        self.assertEqual('a', DeviceDisk.num_to_target(1))
        self.assertEqual('b', DeviceDisk.num_to_target(2))
        self.assertEqual('z', DeviceDisk.num_to_target(26))
        self.assertEqual('aa', DeviceDisk.num_to_target(27))
        self.assertEqual('ab', DeviceDisk.num_to_target(28))
        self.assertEqual('az', DeviceDisk.num_to_target(52))
        self.assertEqual('ba', DeviceDisk.num_to_target(53))
        self.assertEqual('zz', DeviceDisk.num_to_target(27 * 26))
        self.assertEqual('aaa', DeviceDisk.num_to_target(27 * 26 + 1))

        self.assertEqual(DeviceDisk.target_to_num('hda'), 0)
        self.assertEqual(DeviceDisk.target_to_num('hdb'), 1)
        self.assertEqual(DeviceDisk.target_to_num('sdz'), 25)
        self.assertEqual(DeviceDisk.target_to_num('sdaa'), 26)
        self.assertEqual(DeviceDisk.target_to_num('vdab'), 27)
        self.assertEqual(DeviceDisk.target_to_num('vdaz'), 51)
        self.assertEqual(DeviceDisk.target_to_num('xvdba'), 52)
        self.assertEqual(DeviceDisk.target_to_num('xvdzz'),
            26 * (25 + 1) + 25)
        self.assertEqual(DeviceDisk.target_to_num('xvdaaa'),
            26 * 26 * 1 + 26 * 1 + 0)

        disk = virtinst.DeviceDisk(self.conn)
        disk.bus = 'ide'

        self.assertEqual('hda', disk.generate_target([]))
        self.assertEqual('hdb', disk.generate_target(['hda']))
        self.assertEqual('hdc', disk.generate_target(['hdb', 'sda']))
        self.assertEqual('hdb', disk.generate_target(['hda', 'hdd']))

    def testQuickTreeinfo(self):
        # Simple sanity test to make sure detect_distro works. test-urls
        # does much more exhaustive testing but it's only run occasionally
        i = _make_installer(
            location=utils.DATADIR + "/cli/fakefedoratree")
        g = _make_guest()
        v = i.detect_distro(g)
        self.assertEqual(v, "fedora17")

        i = _make_installer(
            location=utils.DATADIR + "/cli/fakerhel6tree")
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
        cpu.set_topology_defaults(6)
        assert cpu.topology.sockets is None

        cpu.topology.sockets = "2"
        cpu.set_topology_defaults(6)
        def get_top(_c):
            return [_c.topology.sockets, _c.topology.cores, _c.topology.threads]
        self.assertEqual(get_top(cpu), [2, 3, 1])

        cpu = virtinst.DomainCpu(self.conn)
        cpu.topology.cores = "4"
        cpu.set_topology_defaults(9)
        self.assertEqual(get_top(cpu), [2, 4, 1])

        cpu = virtinst.DomainCpu(self.conn)
        cpu.topology.threads = "3"
        cpu.set_topology_defaults(14)
        self.assertEqual(get_top(cpu), [4, 1, 3])

        cpu = virtinst.DomainCpu(self.conn)
        cpu.topology.sockets = 5
        cpu.topology.cores = 2
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
        conn = utils.URIs.open_kvm()

        def _set_caps_baselabel_uid(uid):
            secmodel = [s for s in conn.caps.host.secmodels
                        if s.model == "dac"][0]
            for baselabel in [b for b in secmodel.baselabels
                              if b.type in ["qemu", "kvm"]]:
                baselabel.content = "+%s:+%s" % (uid, uid)

        tmpobj = tempfile.TemporaryDirectory(prefix="virtinst-test-search")
        tmpdir = tmpobj.name
        try:
            # Invalid uid
            _set_caps_baselabel_uid(-1)
            searchdata = virtinst.DeviceDisk.check_path_search(conn, tmpdir)
            self.assertEqual(searchdata.uid, None)

            # Use our uid, verify it shows we have expected access
            _set_caps_baselabel_uid(os.getuid())
            searchdata = virtinst.DeviceDisk.check_path_search(conn,
                    tmpdir + "/footest")
            self.assertEqual(searchdata.uid, os.getuid())
            self.assertEqual(searchdata.fixlist, [])

            # Remove perms on the tmpdir, now it should report failures
            os.chmod(tmpdir, 0o000)
            searchdata = virtinst.DeviceDisk.check_path_search(conn, tmpdir)
            self.assertEqual(searchdata.fixlist, [tmpdir])

            errdict = virtinst.DeviceDisk.fix_path_search(searchdata)
            self.assertTrue(not bool(errdict))

            # Mock setfacl to definitely fail
            with unittest.mock.patch("virtinst.diskbackend.SETFACL",
                    "getfacl"):
                errdict = virtinst.DeviceDisk.fix_path_search(searchdata)

        finally:
            # Reset changes we made
            conn.invalidate_caps()
            os.chmod(tmpdir, 0o777)

    def test_path_in_use(self):
        # Extra tests for DeviceDisk.path_in_use
        conn = utils.URIs.open_kvm()

        # Comparing against kernel
        vms = virtinst.DeviceDisk.path_in_use_by(
                conn, "/dev/default-pool/test-arm-kernel")
        assert vms == ["test-arm-kernel"]

    def test_nonpredicatble_generate(self):
        kvm_uri = utils.URIs.kvm.replace(",predictable", "")
        kvmconn = cli.getConnection(kvm_uri)
        testconn = cli.getConnection("test:///default")

        testuuid = virtinst.Guest.generate_uuid(self.conn)
        randomuuid = virtinst.Guest.generate_uuid(testconn)
        self.assertTrue(randomuuid != testuuid)
        self.assertTrue(len(randomuuid) == len(testuuid))

        testmac = virtinst.DeviceInterface.generate_mac(self.conn)
        randommac = virtinst.DeviceInterface.generate_mac(testconn)
        qemumac = virtinst.DeviceInterface.generate_mac(kvmconn)
        self.assertTrue(randommac != testmac)
        self.assertTrue(qemumac != testmac)
        self.assertTrue(len(randommac) == len(testmac))

        # Ensure check_mac_in_use doesn't error on None
        virtinst.DeviceInterface.check_mac_in_use(self.conn, None)

    def test_support_misc(self):
        try:
            self.conn.lookupByName("foobar-idontexist")
        except Exception as e:
            if not self.conn.support.is_libvirt_error_no_domain(e):
                raise

    def test_disk_backend(self):
        # Test get_size() with vol_install
        disk = virtinst.DeviceDisk(self.conn)
        pool = self.conn.storagePoolLookupByName("default-pool")
        vol_install = disk.build_vol_install(self.conn, "newvol1.img",
                pool, 1, False)
        disk.set_vol_install(vol_install)
        assert disk.get_size() == 1.0

        # Test some blockdev inspecting
        conn = utils.URIs.openconn("test:///default")
        if os.path.exists("/dev/loop0"):
            disk = virtinst.DeviceDisk(conn)
            disk.path = "/dev/loop0"
            assert disk.type == "block"
            disk.get_size()

        # Test sparse cloning
        tmpinput = tempfile.NamedTemporaryFile()
        open(tmpinput.name, "wb").write(b'\0' * 10000)

        srcdisk = virtinst.DeviceDisk(conn)
        srcdisk.path = tmpinput.name

        newdisk = virtinst.DeviceDisk(conn)
        tmpoutput = tempfile.NamedTemporaryFile()
        os.unlink(tmpoutput.name)
        newdisk.path = tmpoutput.name
        newdisk.set_local_disk_to_clone(srcdisk, True)
        newdisk.build_storage(None)

        # Test cloning onto existing disk
        newdisk = virtinst.DeviceDisk(conn, parsexml=newdisk.get_xml())
        newdisk.path = newdisk.path
        newdisk.set_local_disk_to_clone(srcdisk, True)
        newdisk.build_storage(None)
