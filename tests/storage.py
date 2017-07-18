# Copyright (C) 2013 Red Hat, Inc.
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

import logging
import os
import unittest

from virtinst import StoragePool, StorageVolume

from tests import utils

# pylint: disable=protected-access
# Access to protected member, needed to unittest stuff

basepath = os.path.join(os.getcwd(), "tests", "storage-xml")


def generate_uuid_from_string(msg):
    res = msg.split("-", 1)
    if len(res) > 1:
        # Split off common prefix
        msg = res[1]

    numstr = ""
    for c in msg:
        numstr += str(ord(c))

    numstr *= 32
    return "-".join([numstr[0:8], numstr[8:12], numstr[12:16], numstr[16:20],
                     numstr[20:32]])


def createPool(conn, ptype, poolname=None, fmt=None, target_path=None,
               source_path=None, source_name=None, uuid=None, iqn=None):

    if poolname is None:
        poolname = StoragePool.find_free_name(conn, "%s-pool" % ptype)

    if uuid is None:
        uuid = generate_uuid_from_string(poolname)

    pool_inst = StoragePool(conn)
    pool_inst.name = poolname
    pool_inst.type = ptype
    pool_inst.uuid = uuid

    if pool_inst.supports_property("hosts"):
        pool_inst.add_host("some.random.hostname")
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

    def setUp(self):
        self.conn = utils.open_testdefault()

    def testDirPool(self):
        poolobj = createPool(self.conn,
                             StoragePool.TYPE_DIR, "pool-dir")
        invol = createVol(self.conn, poolobj)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "input", input_vol=invol)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "clone", clone_vol=invol)

    def testFSPool(self):
        poolobj = createPool(self.conn,
                             StoragePool.TYPE_FS, "pool-fs")
        invol = createVol(self.conn, poolobj)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "input", input_vol=invol)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "clone", clone_vol=invol)

    def testNetFSPool(self):
        poolobj = createPool(self.conn,
                             StoragePool.TYPE_NETFS, "pool-netfs")
        invol = createVol(self.conn, poolobj)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "input", input_vol=invol)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "clone", clone_vol=invol)

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

        # Test parsing source name for target path
        createPool(self.conn, StoragePool.TYPE_LOGICAL,
                   "pool-logical-target-srcname",
                   target_path="/dev/vgfoobar")

        # Test with source name
        createPool(self.conn,
                   StoragePool.TYPE_LOGICAL, "pool-logical-srcname",
                   source_name="vgname")

        # Test creating with many devices
        # XXX: Need to wire this up
        # createPool(self.conn,
        #            StoragePool.TYPE_LOGICAL, "pool-logical-manydev",
        #            source_path=["/tmp/path1", "/tmp/path2", "/tmp/path3"],
        #            target_path=None)

    def testDiskPool(self):
        poolobj = createPool(self.conn,
                             StoragePool.TYPE_DISK,
                             "pool-disk", fmt="dos")
        invol = createVol(self.conn, poolobj)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "input", input_vol=invol)
        createVol(self.conn, poolobj,
                  volname=invol.name() + "clone", clone_vol=invol)

    def testISCSIPool(self):
        createPool(self.conn,
                   StoragePool.TYPE_ISCSI, "pool-iscsi",
                   iqn="foo.bar.baz.iqn")

    def testSCSIPool(self):
        createPool(self.conn, StoragePool.TYPE_SCSI, "pool-scsi")

    def testMpathPool(self):
        createPool(self.conn, StoragePool.TYPE_MPATH, "pool-mpath")

    def testGlusterPool(self):
        if not self.conn.check_support(self.conn.SUPPORT_CONN_POOL_GLUSTERFS):
            raise unittest.SkipTest("Gluster pools not supported with this "
                "libvirt version.")

        createPool(self.conn, StoragePool.TYPE_GLUSTER, "pool-gluster")


    ##############################
    # Tests for pool-sources API #
    ##############################

    def _enumerateCompare(self, name, pool_list):
        for pool in pool_list:
            pool.name = name + str(pool_list.index(pool))
            pool.uuid = generate_uuid_from_string(pool.name)
            poolCompare(pool)

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

if __name__ == "__main__":
    unittest.main()
