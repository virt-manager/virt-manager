# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import unittest

from virtinst import StoragePool, StorageVolume
from virtinst import log

from tests import utils

# pylint: disable=protected-access
# Access to protected member, needed to unittest stuff

basepath = os.path.join(os.getcwd(), "tests", "storage-xml")


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
    filename = os.path.join(basepath, pool_inst.name + ".xml")
    out_expect = pool_inst.get_xml()

    if not os.path.exists(filename):
        open(filename, "w").write(out_expect)
    utils.diff_compare(out_expect, filename)

    return pool_inst.install(build=True, meter=None, create=True)


def createVol(conn, poolobj, volname=None, input_vol=None, clone_vol=None):
    if volname is None:
        volname = poolobj.name() + "-vol"

    # Format here depends on libvirt-1.2.0 and later
    if clone_vol and conn.local_libvirt_version() < 1002000:
        log.debug("skip clone compare")
        return

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
        vol_inst.input_vol = input_vol
        vol_inst.sync_input_vol()
    elif clone_vol:
        vol_inst = StorageVolume(conn, parsexml=clone_vol.XMLDesc(0))
        vol_inst.input_vol = clone_vol
        vol_inst.sync_input_vol()
        vol_inst.name = volname

    vol_inst.validate()
    filename = os.path.join(basepath, vol_inst.name + ".xml")
    utils.diff_compare(vol_inst.get_xml(), filename)
    return vol_inst.install(meter=False)


class TestStorage(unittest.TestCase):
    @property
    def conn(self):
        return utils.URIs.open_testdefault_cached()

    def testDirPool(self):
        poolobj = createPool(self.conn,
                             StoragePool.TYPE_DIR, "pool-dir")
        invol = createVol(self.conn, poolobj)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "input", input_vol=invol)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "clone", clone_vol=invol)
        removePool(poolobj)

    def testFSPool(self):
        poolobj = createPool(self.conn,
                             StoragePool.TYPE_FS, "pool-fs")
        invol = createVol(self.conn, poolobj)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "input", input_vol=invol)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "clone", clone_vol=invol)
        removePool(poolobj)

    def testNetFSPool(self):
        poolobj = createPool(self.conn,
                             StoragePool.TYPE_NETFS, "pool-netfs")
        invol = createVol(self.conn, poolobj)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "input", input_vol=invol)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "clone", clone_vol=invol)
        removePool(poolobj)

    def testLVPool(self):
        poolobj = createPool(self.conn,
                             StoragePool.TYPE_LOGICAL,
                             "pool-logical",
                             source_name="pool-logical")
        invol = createVol(self.conn, poolobj)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "input", input_vol=invol)
        createVol(self.conn,
                  poolobj, volname=invol.name() + "clone", clone_vol=invol)
        removePool(poolobj)

        # Test parsing source name for target path
        poolobj = createPool(self.conn, StoragePool.TYPE_LOGICAL,
                   "pool-logical-target-srcname",
                   target_path="/dev/vgfoobar")
        removePool(poolobj)

        # Test with source name
        poolobj = createPool(self.conn,
                   StoragePool.TYPE_LOGICAL, "pool-logical-srcname",
                   source_name="vgname")
        removePool(poolobj)

    def testDiskPool(self):
        poolobj = createPool(self.conn,
                             StoragePool.TYPE_DISK,
                             "pool-disk", fmt="auto",
                             target_path="/some/target/path")
        invol = createVol(self.conn, poolobj)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "input", input_vol=invol)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "clone", clone_vol=invol)
        removePool(poolobj)

    def testISCSIPool(self):
        poolobj = createPool(self.conn,
                   StoragePool.TYPE_ISCSI, "pool-iscsi",
                   iqn="foo.bar.baz.iqn")
        removePool(poolobj)

    def testSCSIPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_SCSI, "pool-scsi")
        removePool(poolobj)

    def testMpathPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_MPATH, "pool-mpath")
        removePool(poolobj)

    def testGlusterPool(self):
        poolobj = createPool(self.conn,
                StoragePool.TYPE_GLUSTER, "pool-gluster")
        removePool(poolobj)

    def testRBDPool(self):
        poolobj = createPool(self.conn,
                StoragePool.TYPE_RBD, "pool-rbd")
        removePool(poolobj)

    def testMisc(self):
        # Misc coverage testing
        vol = StorageVolume(self.conn)
        self.assertTrue(vol.is_size_conflict()[0] is False)

        fullconn = utils.URIs.open_testdriver_cached()
        glusterpool = fullconn.storagePoolLookupByName("gluster-pool")
        diskpool = fullconn.storagePoolLookupByName("disk-pool")

        glustervol = StorageVolume(fullconn)
        glustervol.pool = glusterpool
        self.assertTrue(glustervol.supports_format() is True)

        diskvol = StorageVolume(fullconn)
        diskvol.pool = diskpool
        self.assertTrue(diskvol.supports_format() is False)

        glusterpool.destroy()
        StoragePool.ensure_pool_is_running(glusterpool)

        # Check pool collision detection
        self.assertEqual(
                StoragePool.find_free_name(fullconn, "gluster-pool"),
                "gluster-pool-1")

    def testEnumerateLogical(self):
        lst = StoragePool.pool_list_from_sources(self.conn,
                                                 StoragePool.TYPE_LOGICAL)
        self.assertEqual(lst, ["testvg1", "testvg2"])
