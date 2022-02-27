# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import tempfile

import pytest

import virtinst
from virtinst import DeviceDisk

from tests import utils


def test_disk_numtotarget():
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

    conn = utils.URIs.open_testdefault_cached()
    disk = virtinst.DeviceDisk(conn)
    disk.bus = 'ide'

    assert disk.generate_target([]) == 'hda'
    assert disk.generate_target(['hda']) == 'hdb'
    assert disk.generate_target(['hdb', 'sda']) == 'hdc'
    assert disk.generate_target(['hda', 'hdd']) == 'hdb'


def test_disk_dir_searchable(monkeypatch):
    # Normally the dir searchable test is skipped in the test suite,
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
        # path="" should trigger early return
        searchdata = virtinst.DeviceDisk.check_path_search(conn, "")
        assert searchdata.uid is None
        # path=None should trigger early return
        searchdata = virtinst.DeviceDisk.check_path_search(conn, None)
        assert searchdata.uid is None

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
        with monkeypatch.context() as m:
            m.setattr("virtinst.diskbackend.SETFACL", "getfacl")
            errdict = virtinst.DeviceDisk.fix_path_search(searchdata)

    finally:
        # Reset changes we made
        conn.invalidate_caps()
        os.chmod(tmpdir, 0o777)


def test_disk_path_in_use_kernel():
    # Extra tests for DeviceDisk.path_in_use
    conn = utils.URIs.open_kvm()

    # Comparing against kernel
    vms = virtinst.DeviceDisk.path_in_use_by(
            conn, "/pool-dir/test-arm-kernel")
    assert vms == ["test-arm-kernel"]


def test_disk_diskbackend_misc():
    # Test get_size() with vol_install
    conn = utils.URIs.open_testdefault_cached()
    disk = virtinst.DeviceDisk(conn)
    pool = conn.storagePoolLookupByName("pool-dir")
    vol_install = disk.build_vol_install(conn, "newvol1.img", pool, 1, False)
    disk.set_vol_install(vol_install)
    assert disk.get_size() == 1.0

    # Test some blockdev inspecting
    conn = utils.URIs.openconn("test:///default")
    if os.path.exists("/dev/loop0"):
        disk = virtinst.DeviceDisk(conn)
        disk.set_source_path("/dev/loop0")
        assert disk.type == "block"
        disk.get_size()

    # Test sparse cloning
    tmpinput = tempfile.NamedTemporaryFile()
    open(tmpinput.name, "wb").write(b'\0' * 10000)

    srcdisk = virtinst.DeviceDisk(conn)
    srcdisk.set_source_path(tmpinput.name)

    newdisk = virtinst.DeviceDisk(conn)
    tmpoutput = tempfile.NamedTemporaryFile()
    os.unlink(tmpoutput.name)
    newdisk.set_source_path(tmpoutput.name)
    newdisk.set_local_disk_to_clone(srcdisk, True)
    newdisk.build_storage(None)

    # Test cloning onto existing disk
    newdisk = virtinst.DeviceDisk(conn, parsexml=newdisk.get_xml())
    newdisk.set_source_path(newdisk.get_source_path())
    newdisk.set_local_disk_to_clone(srcdisk, True)
    newdisk.build_storage(None)

    newdisk = virtinst.DeviceDisk(conn)
    newdisk.type = "block"
    newdisk.set_source_path("/dev/foo/idontexist")
    assert newdisk.get_size() == 0

    conn = utils.URIs.open_testdriver_cached()
    volpath = "/pool-dir/test-clone-simple.img"
    assert virtinst.DeviceDisk.path_definitely_exists(conn, volpath)
    disk = virtinst.DeviceDisk(conn)
    disk.set_source_path(volpath)
    assert disk.get_size()


def test_disk_diskbackend_parse():
    # Test that calling validate() on parsed disk XML doesn't attempt
    # to verify the path exists. Assume it's a working config
    conn = utils.URIs.open_testdriver_cached()
    xml = ("<disk type='file' device='disk'>"
        "<source file='/A/B/C/D/NOPE'/>"
        "</disk>")
    disk = virtinst.DeviceDisk(conn, parsexml=xml)
    disk.validate()
    disk.is_size_conflict()
    disk.build_storage(None)
    assert getattr(disk, "_storage_backend").is_stub() is True

    # Stub backend coverage testing
    backend = getattr(disk, "_storage_backend")
    assert disk.get_parent_pool() is None
    assert disk.get_vol_object() is None
    assert disk.get_vol_install() is None
    assert disk.get_size() == 0
    assert backend.get_vol_xml() is None
    assert backend.get_dev_type() == "file"
    assert backend.get_driver_type() is None
    assert backend.get_parent_pool() is None

    disk.set_backend_for_existing_path()
    assert getattr(disk, "_storage_backend").is_stub() is False

    with pytest.raises(ValueError):
        disk.validate()

    # Ensure set_backend_for_existing_path resolves a path
    # to its existing storage volume
    xml = ("<disk type='file' device='disk'>"
        "<source file='/pool-dir/default-vol'/>"
        "</disk>")
    disk = virtinst.DeviceDisk(conn, parsexml=xml)
    disk.set_backend_for_existing_path()
    assert disk.get_vol_object()

    # Verify set_backend_for_existing_path doesn't error
    # for a variety of disks
    dom = conn.lookupByName("test-many-devices")
    guest = virtinst.Guest(conn, parsexml=dom.XMLDesc(0))
    for disk in guest.devices.disk:
        disk.set_backend_for_existing_path()


def test_disk_rbd_path():
    conn = utils.URIs.open_testdriver_cached()
    diskxml1 = """
    <disk type="network" device="disk">
      <source protocol="rbd" name="rbd-sourcename/some-rbd-vol">
        <host name="ceph-mon-1.example.com" port="6789"/>
        <host name="ceph-mon-2.example.com" port="6789"/>
        <host name="ceph-mon-3.example.com" port="6789"/>
      </source>
      <target dev="vdag" bus="virtio"/>
    </disk>
    """

    disk1 = virtinst.DeviceDisk(conn, parsexml=diskxml1)
    disk1.set_backend_for_existing_path()
    assert disk1.get_vol_object().name() == "some-rbd-vol"
