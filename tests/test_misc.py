# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import virtinst

from tests import utils


# Misc tests for various virtinst special behavior. These should only aim for
# testing any particularly tricky bits, general XML generation should
# be through virt-install examples in test_cli


def test_misc_cpu_topology():
    """
    Various topology calculation corner cases
    """
    conn = utils.URIs.open_testdefault_cached()
    cpu = virtinst.DomainCpu(conn)
    cpu.set_topology_defaults(6)
    assert cpu.topology.sockets is None

    cpu.topology.sockets = "2"
    cpu.set_topology_defaults(6)
    def get_top(_c):
        return [_c.topology.sockets, _c.topology.cores, _c.topology.threads]
    assert get_top(cpu) == [2, 3, 1]

    cpu = virtinst.DomainCpu(conn)
    cpu.topology.cores = "4"
    cpu.set_topology_defaults(9)
    assert get_top(cpu) == [2, 4, 1]

    cpu = virtinst.DomainCpu(conn)
    cpu.topology.threads = "3"
    cpu.set_topology_defaults(14)
    assert get_top(cpu) == [4, 1, 3]

    cpu = virtinst.DomainCpu(conn)
    cpu.topology.sockets = 5
    cpu.topology.cores = 2
    assert cpu.vcpus_from_topology() == 10

    cpu = virtinst.DomainCpu(conn)
    assert cpu.vcpus_from_topology() == 1


def test_misc_guest_osinfo_metadata():
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


def test_misc_nonpredicatble_generate():
    """
    Bypass our testsuite 'predicatable' handling to test actual random output
    """
    from virtinst import cli
    predconn = utils.URIs.open_testdefault_cached()
    kvm_uri = utils.URIs.kvm.replace(",predictable", "")
    kvmconn = cli.getConnection(kvm_uri)
    testconn = cli.getConnection("test:///default")

    testuuid = virtinst.Guest.generate_uuid(predconn)
    randomuuid = virtinst.Guest.generate_uuid(testconn)
    assert randomuuid != testuuid
    assert len(randomuuid) == len(testuuid)

    testmac = virtinst.DeviceInterface.generate_mac(predconn)
    randommac = virtinst.DeviceInterface.generate_mac(testconn)
    qemumac = virtinst.DeviceInterface.generate_mac(kvmconn)
    assert randommac != testmac
    assert qemumac != testmac
    assert len(randommac) == len(testmac)

    # Ensure check_mac_in_use doesn't error on None
    virtinst.DeviceInterface.check_mac_in_use(predconn, None)


def test_misc_support_cornercases():
    """
    Test support.py corner cases
    """
    conn = utils.URIs.open_testdefault_cached()
    try:
        conn.lookupByName("foobar-idontexist")
    except Exception as e:
        if not conn.support.is_libvirt_error_no_domain(e):
            raise


def test_misc_osxml_cornercases():
    """
    Test OSXML corner cases
    """
    conn = utils.URIs.open_testdefault_cached()
    guest = virtinst.Guest(conn)
    guest.os.set_initargs_string("foo bar")
    guest.os.set_initargs_string("baz wibble")
    assert [i.val for i in guest.os.initargs] == ["baz", "wibble"]


def test_misc_cpu_cornercases():
    """
    Hit the validation paths for default HOST_MODEL_ONLY
    """
    kvmconn = utils.URIs.open_kvm()
    guest = virtinst.Guest(kvmconn)
    guest.x86_cpu_default = guest.cpu.SPECIAL_MODE_HOST_MODEL_ONLY
    guest.set_defaults(guest)
    assert guest.cpu.model == "Opteron_G4"

    # pylint: disable=protected-access
    guest.cpu.model = "idontexist"
    guest.cpu._validate_default_host_model_only(guest)
    assert guest.cpu.model is None
