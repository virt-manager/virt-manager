# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os
import unittest

from virtinst import StoragePool, StorageVolume

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

    if pool_inst.supports_property("hosts"):
        hostobj = pool_inst.hosts.add_new()
        hostobj.name = "some.random.hostname"
    if pool_inst.supports_property("source_path"):
        pool_inst.source_path = source_path or "/some/source/path"
    if pool_inst.supports_property("target_path"):
        pool_inst.target_path = target_path or "/some/target/path"
    if fmt and pool_inst.supports_property("format"):
        pool_inst.format = fmt
    if source_name and pool_inst.supports_property("source_name"):
        pool_inst.source_name = source_name
    if iqn and pool_inst.supports_property("iqn"):
        pool_inst.iqn = iqn

    pool_inst.validate()
    return poolCompare(pool_inst)


def removePool(poolobj):
    poolobj.destroy()
    poolobj.undefine()


def poolCompare(pool_inst):
    filename = os.path.join(basepath, pool_inst.name + ".xml")
    out_expect = pool_inst.get_xml_config()

    if not os.path.exists(filename):
        open(filename, "w").write(out_expect)
    utils.diff_compare(out_expect, filename)

    return pool_inst.install(build=True, meter=None, create=True)


def createVol(conn, poolobj, volname=None, input_vol=None, clone_vol=None):
    if volname is None:
        volname = poolobj.name() + "-vol"

    # Format here depends on libvirt-1.2.0 and later
    if clone_vol and conn.local_libvirt_version() < 1002000:
        logging.debug("skip clone compare")
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
    utils.diff_compare(vol_inst.get_xml_config(), filename)
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
                             target_path="/dev/pool-logical")
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
                             "pool-disk", fmt="dos")
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
        if not self.conn.check_support(self.conn.SUPPORT_CONN_POOL_GLUSTERFS):
            raise unittest.SkipTest("Gluster pools not supported with this "
                "libvirt version.")

        poolobj = createPool(self.conn,
                StoragePool.TYPE_GLUSTER, "pool-gluster")
        removePool(poolobj)


    ##############################
    # Tests for pool-sources API #
    ##############################

    def _enumerateCompare(self, name, pool_list):
        for pool in pool_list:
            pool.name = name + str(pool_list.index(pool))
            poolobj = poolCompare(pool)
            removePool(poolobj)

    def testEnumerateLogical(self):
        name = "pool-logical-list"
        lst = StoragePool.pool_list_from_sources(self.conn,
                                                 StoragePool.TYPE_LOGICAL)
        self._enumerateCompare(name, lst)

    def testEnumerateNetFS(self):
        name = "pool-netfs-list"
        host = "example.com"
        lst = StoragePool.pool_list_from_sources(self.conn,
                                                 StoragePool.TYPE_NETFS,
                                                 host=host)
        self._enumerateCompare(name, lst)

    def testEnumerateiSCSI(self):
        host = "example.com"
        lst = StoragePool.pool_list_from_sources(self.conn,
                                                 StoragePool.TYPE_ISCSI,
                                                 host=host)
        self.assertTrue(len(lst) == 0)
