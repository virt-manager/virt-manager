# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import unittest

import virtinst

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

    def test_nonpredicatble_generate(self):
        from virtinst import cli
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
