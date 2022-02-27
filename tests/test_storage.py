# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from virtinst import StoragePool, StorageVolume
from virtinst import log

from tests import utils

# pylint: disable=protected-access

BASEPATH = os.path.join(utils.DATADIR, "storage")


def createPool(conn, ptype, poolname=None, fmt=None, target_path=None,
               source_path=None, source_name=None, iqn=None):

    if poolname is None:
        poolname = StoragePool.find_free_name(conn, "%s-pool" % ptype)

    pool_inst = StoragePool(conn)
    pool_inst.name = poolname
    pool_inst.type = ptype

    if pool_inst.supports_hosts():
        hostobj = pool_inst.hosts.add_new()
        hostobj.name = "some.random.hostname"
    if pool_inst.supports_source_path():
        pool_inst.source_path = source_path or "/some/source/path"
    if pool_inst.supports_target_path():
        pool_inst.target_path = (target_path or
                pool_inst.default_target_path())
    if fmt and pool_inst.supports_format():
        pool_inst.format = fmt
    if pool_inst.supports_source_name():
        pool_inst.source_name = (source_name or
                pool_inst.default_source_name())
    if iqn and pool_inst.supports_iqn():
        pool_inst.iqn = iqn

    return poolCompare(pool_inst)


def removePool(poolobj):
    poolobj.destroy()
    poolobj.undefine()


def poolCompare(pool_inst):
    pool_inst.validate()
    filename = os.path.join(BASEPATH, pool_inst.name + ".xml")
    out_expect = pool_inst.get_xml()

    if not os.path.exists(filename):
        open(filename, "w").write(out_expect)
    utils.diff_compare(out_expect, filename)

    return pool_inst.install(build=True, meter=None, create=True)


def createVol(conn, poolobj, volname=None, input_vol=None, clone_vol=None):
    if volname is None:
        volname = poolobj.name() + "-vol"

    alloc = 5 * 1024 * 1024 * 1024
    cap = 10 * 1024 * 1024 * 1024
    vol_inst = StorageVolume(conn)
    vol_inst.pool = poolobj
    vol_inst.name = volname
    vol_inst.capacity = cap
    vol_inst.allocation = alloc

    vol_inst.permissions.mode = "0700"
    vol_inst.permissions.owner = "10736"
    vol_inst.permissions.group = "10736"

    if input_vol:
        vol_inst.set_input_vol(input_vol)
    elif clone_vol:
        vol_inst = StorageVolume(conn, parsexml=clone_vol.XMLDesc(0))
        vol_inst.set_input_vol(clone_vol)
        vol_inst.name = volname

    vol_inst.validate()
    filename = os.path.join(BASEPATH, vol_inst.name + ".xml")

    # Format here depends on libvirt-7.2.0 and later
    if clone_vol and conn.local_libvirt_version() < 7002000:
        log.debug("skip clone compare")
        return

    utils.diff_compare(vol_inst.get_xml(), filename)
    return vol_inst.install(meter=False)


##############
# Test cases #
##############

def testDirPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn,
                         StoragePool.TYPE_DIR, "pool-dir2")
    invol = createVol(conn, poolobj)
    createVol(conn, poolobj,
              volname=invol.name() + "input", input_vol=invol)
    createVol(conn, poolobj,
              volname=invol.name() + "clone", clone_vol=invol)
    removePool(poolobj)


def testFSPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn,
                         StoragePool.TYPE_FS, "pool-fs")
    invol = createVol(conn, poolobj)
    createVol(conn, poolobj,
              volname=invol.name() + "input", input_vol=invol)
    createVol(conn, poolobj,
              volname=invol.name() + "clone", clone_vol=invol)
    removePool(poolobj)


def testNetFSPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn,
                         StoragePool.TYPE_NETFS, "pool-netfs")
    invol = createVol(conn, poolobj)
    createVol(conn, poolobj,
              volname=invol.name() + "input", input_vol=invol)
    createVol(conn, poolobj,
              volname=invol.name() + "clone", clone_vol=invol)
    removePool(poolobj)


def testLVPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn,
                         StoragePool.TYPE_LOGICAL,
                         "pool-logical",
                         source_name="pool-logical")
    invol = createVol(conn, poolobj)
    createVol(conn, poolobj,
              volname=invol.name() + "input", input_vol=invol)
    createVol(conn,
              poolobj, volname=invol.name() + "clone", clone_vol=invol)
    removePool(poolobj)

    # Test parsing source name for target path
    poolobj = createPool(conn, StoragePool.TYPE_LOGICAL,
               "pool-logical-target-srcname",
               target_path="/dev/vgfoobar")
    removePool(poolobj)

    # Test with source name
    poolobj = createPool(conn,
               StoragePool.TYPE_LOGICAL, "pool-logical-srcname",
               source_name="vgname")
    removePool(poolobj)


def testDiskPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn,
                         StoragePool.TYPE_DISK,
                         "pool-disk", fmt="auto",
                         target_path="/some/target/path")
    invol = createVol(conn, poolobj)
    createVol(conn, poolobj,
              volname=invol.name() + "input", input_vol=invol)
    createVol(conn, poolobj,
              volname=invol.name() + "clone", clone_vol=invol)
    removePool(poolobj)


def testISCSIPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn,
               StoragePool.TYPE_ISCSI, "pool-iscsi",
               iqn="foo.bar.baz.iqn")
    removePool(poolobj)


def testSCSIPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn, StoragePool.TYPE_SCSI, "pool-scsi")
    removePool(poolobj)


def testMpathPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn, StoragePool.TYPE_MPATH, "pool-mpath")
    removePool(poolobj)


def testGlusterPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn,
            StoragePool.TYPE_GLUSTER, "pool-gluster")
    removePool(poolobj)


def testRBDPool():
    conn = utils.URIs.open_testdefault_cached()
    poolobj = createPool(conn,
            StoragePool.TYPE_RBD, "pool-rbd")
    removePool(poolobj)


def testMisc():
    conn = utils.URIs.open_testdefault_cached()
    # Misc coverage testing
    vol = StorageVolume(conn)
    assert vol.is_size_conflict()[0] is False

    fullconn = utils.URIs.open_testdriver_cached()
    glusterpool = fullconn.storagePoolLookupByName("pool-gluster")
    diskpool = fullconn.storagePoolLookupByName("pool-logical")

    glustervol = StorageVolume(fullconn)
    glustervol.pool = glusterpool
    assert glustervol.supports_format() is False

    diskvol = StorageVolume(fullconn)
    diskvol.pool = diskpool
    assert diskvol.supports_format() is False

    glusterpool.destroy()
    StoragePool.ensure_pool_is_running(glusterpool)

    # Check pool collision detection
    name = StoragePool.find_free_name(fullconn, "pool-gluster")
    assert name == "pool-gluster-1"


def testEnumerateLogical():
    conn = utils.URIs.open_testdefault_cached()
    lst = StoragePool.pool_list_from_sources(conn,
                                             StoragePool.TYPE_LOGICAL)
    assert lst == ["testvg1", "testvg2"]
