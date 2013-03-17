#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

import os
import unittest

import virtinst.Storage
from virtinst.Storage import StoragePool, StorageVolume
import utils

import libvirt

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
    numstr = numstr[0:32]

    return numstr

def _findFreePoolName(conn, namebase):

    i = 0
    while True:
        poolname = namebase + "-%d" % i
        try:
            StorageVolume.lookup_pool_by_name(conn=conn, pool_name=poolname)
            i += 1
        except:
            return poolname

def createPool(conn, ptype, poolname=None, fmt=None, target_path=None,
               source_path=None, source_name=None, uuid=None, iqn=None):
    poolclass = StoragePool.get_pool_class(ptype)

    if poolname is None:
        poolname = _findFreePoolName(conn, str(ptype) + "-pool")

    if uuid is None:
        uuid = generate_uuid_from_string(poolname)

    pool_inst = poolclass(conn=conn, name=poolname, uuid=uuid)

    if hasattr(pool_inst, "host"):
        pool_inst.host = "some.random.hostname"
    if hasattr(pool_inst, "source_path"):
        pool_inst.source_path = source_path or "/some/source/path"
    if hasattr(pool_inst, "target_path"):
        pool_inst.target_path = target_path or "/some/target/path"
    if fmt and hasattr(pool_inst, "format"):
        pool_inst.format = fmt
    if source_name and hasattr(pool_inst, "source_name"):
        pool_inst.source_name = source_name
    if iqn and hasattr(pool_inst, "iqn"):
        pool_inst.iqn = iqn

    return poolCompare(pool_inst)

def poolCompare(pool_inst):
    filename = os.path.join(basepath, pool_inst.name + ".xml")
    out_expect = pool_inst.get_xml_config()

    if not os.path.exists(filename):
        open(filename, "w").write(out_expect)
    utils.diff_compare(out_expect, filename)

    return pool_inst.install(build=True, meter=None, create=True)

def createVol(poolobj, volname=None, input_vol=None, clone_vol=None):
    volclass = StorageVolume.get_volume_for_pool(pool_object=poolobj)

    if volname == None:
        volname = poolobj.name() + "-vol"

    alloc = 5 * 1024 * 1024 * 1024
    cap = 10 * 1024 * 1024 * 1024
    vol_inst = volclass(name=volname, capacity=cap, allocation=alloc,
                        pool=poolobj)

    perms = {}
    perms["mode"] = 0700
    perms["owner"] = 10736
    perms["group"] = 10736

    vol_inst.perms = perms
    if input_vol or clone_vol:
        if not virtinst.Storage.is_create_vol_from_supported(poolobj._conn):
            return

    if input_vol:
        vol_inst.input_vol = input_vol
    elif clone_vol:
        vol_inst = virtinst.Storage.CloneVolume(volname, clone_vol)

    filename = os.path.join(basepath, vol_inst.name + ".xml")

    # Make sure permissions are properly set
    utils.diff_compare(vol_inst.get_xml_config(), filename)

    return vol_inst.install(meter=False)

class TestStorage(unittest.TestCase):

    def setUp(self):
        self.conn = libvirt.open("test:///default")

    def testDirPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_DIR, "pool-dir")
        invol = createVol(poolobj)
        createVol(poolobj, volname=invol.name() + "input", input_vol=invol)
        createVol(poolobj, volname=invol.name() + "clone", clone_vol=invol)

    def testFSPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_FS, "pool-fs")
        invol = createVol(poolobj)
        createVol(poolobj, volname=invol.name() + "input", input_vol=invol)
        createVol(poolobj, volname=invol.name() + "clone", clone_vol=invol)

    def testNetFSPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_NETFS, "pool-netfs")
        invol = createVol(poolobj)
        createVol(poolobj, volname=invol.name() + "input", input_vol=invol)
        createVol(poolobj, volname=invol.name() + "clone", clone_vol=invol)

    def testLVPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_LOGICAL,
                             "pool-logical")
        invol = createVol(poolobj)
        createVol(poolobj, volname=invol.name() + "input", input_vol=invol)
        createVol(poolobj, volname=invol.name() + "clone", clone_vol=invol)

        # Test parsing source name for target path
        createPool(self.conn, StoragePool.TYPE_LOGICAL,
                   "pool-logical-target-srcname",
                   target_path="/dev/vgfoobar")

        # Test with source name
        createPool(self.conn, StoragePool.TYPE_LOGICAL, "pool-logical-srcname",
                   source_name="vgname")

        # Test creating with many devices
        createPool(self.conn, StoragePool.TYPE_LOGICAL, "pool-logical-manydev",
                   source_path=[ "/tmp/path1", "/tmp/path2", "/tmp/path3" ],
                   target_path=None)

    def testDiskPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_DISK,
                             "pool-disk", fmt="dos")
        invol = createVol(poolobj)
        createVol(poolobj, volname=invol.name() + "input", input_vol=invol)
        createVol(poolobj, volname=invol.name() + "clone", clone_vol=invol)

    def testISCSIPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_ISCSI, "pool-iscsi")
        # Not supported
        #volobj = createVol(poolobj)
        self.assertRaises(RuntimeError, createVol, poolobj)

        createPool(self.conn, StoragePool.TYPE_ISCSI, "pool-iscsi-iqn",
                   iqn="foo.bar.baz.iqn")

    def testSCSIPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_SCSI, "pool-scsi")
        # Not supported
        #volobj = createVol(poolobj)
        self.assertRaises(RuntimeError, createVol, poolobj)

    def testMpathPool(self):
        poolobj = createPool(self.conn, StoragePool.TYPE_MPATH, "pool-mpath")
        # Not supported
        #volobj = createVol(poolobj)
        self.assertRaises(RuntimeError, createVol, poolobj)

    def _enumerateCompare(self, pool_list):
        for pool in pool_list:
            pool.name = pool.name + str(pool_list.index(pool))
            pool.uuid = generate_uuid_from_string(pool.name)
            poolCompare(pool)

    def testEnumerateLogical(self):
        name = "pool-logical-list"

        lst = StoragePool.pool_list_from_sources(self.conn, name,
                                                 StoragePool.TYPE_LOGICAL)
        self._enumerateCompare(lst)

    def testEnumerateNetFS(self):
        name = "pool-netfs-list"
        host = "example.com"

        lst = StoragePool.pool_list_from_sources(self.conn, name,
                                                 StoragePool.TYPE_NETFS,
                                                 host=host)
        self._enumerateCompare(lst)

    def testEnumerateiSCSI(self):
        name = "pool-iscsi-list"
        host = "example.com"

        lst = StoragePool.pool_list_from_sources(self.conn, name,
                                                 StoragePool.TYPE_ISCSI,
                                                 host=host)
        self.assertTrue(len(lst) == 0)

if __name__ == "__main__":
    unittest.main()
