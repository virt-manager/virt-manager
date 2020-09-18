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


class TestXMLMisc(unittest.TestCase):
    """
    Misc tests for various XML special behavior. These should only aim for
    testing any particularly tricky bits, general XML generation should
    be through virt-install examples in test_cli
    """
    @property
    def conn(self):
        return utils.URIs.open_testdefault_cached()

    def testDiskNumbers(self):
        # Various testing our target generation
        #
        # Note: using single quotes in strings to avoid
        # codespell flagging the 'ba' assert
        assert DeviceDisk.num_to_target(1) == 'a'
        assert DeviceDisk.num_to_target(2) == 'b'
        assert DeviceDisk.num_to_target(26) == 'z'
        assert DeviceDisk.num_to_target(27) == 'aa'
        assert DeviceDisk.num_to_target(28) == 'ab'
        assert DeviceDisk.num_to_target(52) == 'az'
        assert DeviceDisk.num_to_target(53) == 'ba'
        assert DeviceDisk.num_to_target(27 * 26) == 'zz'
        assert DeviceDisk.num_to_target(27 * 26 + 1) == 'aaa'

        assert DeviceDisk.target_to_num('hda') == 0
        assert DeviceDisk.target_to_num('hdb') == 1
        assert DeviceDisk.target_to_num('sdz') == 25
        assert DeviceDisk.target_to_num('sdaa') == 26
        assert DeviceDisk.target_to_num('vdab') == 27
        assert DeviceDisk.target_to_num('vdaz') == 51
        assert DeviceDisk.target_to_num('xvdba') == 52
        assert DeviceDisk.target_to_num('xvdzz') == 26 * (25 + 1) + 25
        assert DeviceDisk.target_to_num('xvdaaa') == 26 * 26 * 1 + 26 * 1 + 0

        disk = virtinst.DeviceDisk(self.conn)
        disk.bus = 'ide'

        assert disk.generate_target([]) == 'hda'
        assert disk.generate_target(['hda']) == 'hdb'
        assert disk.generate_target(['hdb', 'sda']) == 'hdc'
        assert disk.generate_target(['hda', 'hdd']) == 'hdb'

    def testCPUTopology(self):
        # Test CPU topology determining
        cpu = virtinst.DomainCpu(self.conn)
        cpu.set_topology_defaults(6)
        assert cpu.topology.sockets is None

        cpu.topology.sockets = "2"
        cpu.set_topology_defaults(6)
        def get_top(_c):
            return [_c.topology.sockets, _c.topology.cores, _c.topology.threads]
        assert get_top(cpu) == [2, 3, 1]

        cpu = virtinst.DomainCpu(self.conn)
        cpu.topology.cores = "4"
        cpu.set_topology_defaults(9)
        assert get_top(cpu) == [2, 4, 1]

        cpu = virtinst.DomainCpu(self.conn)
        cpu.topology.threads = "3"
        cpu.set_topology_defaults(14)
        assert get_top(cpu) == [4, 1, 3]

        cpu = virtinst.DomainCpu(self.conn)
        cpu.topology.sockets = 5
        cpu.topology.cores = 2
        assert cpu.vcpus_from_topology() == 10

        cpu = virtinst.DomainCpu(self.conn)
        assert cpu.vcpus_from_topology() == 1

    def test_set_defaults_double(self):
        """
        Check that a common config has idempotent set_defaults
        """
        g = _make_guest(conn=utils.URIs.open_kvm(), os_variant="fedora-unknown")

        g.set_defaults(None)
        xml1 = g.get_xml()
        g.set_defaults(None)
        xml2 = g.get_xml()
        assert xml1 == xml2

    def test_guest_osinfo_metadata(self):
        """
        Test that reading an unknown OS ID from guest XML will not blow up
        """
        # pylint: disable=protected-access
        g = virtinst.Guest(utils.URIs.open_testdefault_cached())
        g._metadata.libosinfo.os_id = "http://fedoraproject.org/fedora/20"
        assert g.osinfo.name == "fedora20"

        g = virtinst.Guest(utils.URIs.open_testdefault_cached())
        g._metadata.libosinfo.os_id = "http://example.com/idontexit"
        assert g.osinfo.name == "generic"

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
            assert searchdata.uid is None

            # Use our uid, verify it shows we have expected access
            _set_caps_baselabel_uid(os.getuid())
            searchdata = virtinst.DeviceDisk.check_path_search(conn,
                    tmpdir + "/footest")
            assert searchdata.uid == os.getuid()
            assert searchdata.fixlist == []

            # Remove perms on the tmpdir, now it should report failures
            os.chmod(tmpdir, 0o000)
            searchdata = virtinst.DeviceDisk.check_path_search(conn, tmpdir)
            assert searchdata.fixlist == [tmpdir]

            errdict = virtinst.DeviceDisk.fix_path_search(searchdata)
            assert not bool(errdict)

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
        assert randomuuid != testuuid
        assert len(randomuuid) == len(testuuid)

        testmac = virtinst.DeviceInterface.generate_mac(self.conn)
        randommac = virtinst.DeviceInterface.generate_mac(testconn)
        qemumac = virtinst.DeviceInterface.generate_mac(kvmconn)
        assert randommac != testmac
        assert qemumac != testmac
        assert len(randommac) == len(testmac)

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

        newdisk = virtinst.DeviceDisk(conn)
        newdisk.type = "block"
        newdisk.path = "/dev/foo/idontexist"
        assert newdisk.get_size() == 0

        conn = utils.URIs.open_testdriver_cached()
        volpath = "/dev/default-pool/test-clone-simple.img"
        assert virtinst.DeviceDisk.path_definitely_exists(conn, volpath)
        disk = virtinst.DeviceDisk(conn)
        disk.path = volpath
        assert disk.get_size()
