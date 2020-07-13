# Copyright (C) 2013, 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest
import os

from tests import utils

from virtinst import Cloner
from virtinst import log

ORIG_NAME  = "clone-orig"
CLONE_NAME = "clone-new"

# Create some files to use as test images
FILE1 = "/tmp/virtinst-test1.img"
FILE2 = "/tmp/virtinst-test2.img"
P1_VOL1  = "/dev/default-pool/testvol1.img"
P1_VOL2  = "/dev/default-pool/testvol2.img"
P2_VOL1  = "/dev/cross-pool/testvol1.img"
P2_VOL2  = "/dev/cross-pool/testvol2.img"

POOL1 = "/dev/default-pool"
POOL2 = "/dev/cross-pool"
DISKPOOL = "/dev/disk-pool"

local_files = [FILE1, FILE2]

clonexml_dir = os.path.join(os.getcwd(), "tests/data/clone")


class TestClone(unittest.TestCase):

    def setUp(self):
        for f in local_files:
            open(f, "w").write("")

    def tearDown(self):
        for f in local_files:
            os.unlink(f)

    def _clone(self, filebase, disks=None, force_list=None,
               skip_list=None, compare=True, conn=None,
               clone_disks_file=None):
        """Helper for comparing clone input/output from 2 xml files"""
        infile = os.path.join(clonexml_dir, filebase + "-in.xml")
        in_content = open(infile).read()

        if not conn:
            conn = utils.URIs.open_testdriver_cached()
        cloneobj = Cloner(conn)
        cloneobj.original_xml = in_content

        force_list = force_list or []
        for force in force_list:
            cloneobj.force_target = force
        self.assertEqual(cloneobj.force_target, force_list)
        cloneobj.force_target = force_list
        self.assertEqual(cloneobj.force_target, force_list)

        skip_list = skip_list or []
        for skip in skip_list:
            cloneobj.skip_target = skip
        self.assertEqual(cloneobj.skip_target, skip_list)
        cloneobj.skip_target = skip_list
        self.assertEqual(cloneobj.skip_target, skip_list)

        cloneobj = self._default_clone_values(cloneobj, disks)

        if compare:
            self._clone_compare(cloneobj, filebase,
                                clone_disks_file=clone_disks_file)
            self._clone_define(filebase)
        else:
            cloneobj.setup_original()
            cloneobj.setup_clone()

    def _default_clone_values(self, cloneobj, disks=None):
        """Sets default values for the cloned VM."""
        cloneobj.clone_name = "clone-new"

        uuid = "12345678-1234-1234-1234-123456789012"
        cloneobj.clone_uuid = uuid
        self.assertEqual(cloneobj.clone_uuid, uuid)

        macs = ["22:23:45:67:89:00", "22:23:45:67:89:01"]
        cloneobj.clone_macs = macs
        self.assertEqual(cloneobj.clone_macs, macs)

        if disks is None:
            disks = ["/dev/disk-pool/disk-vol1", "/tmp/clone2.img",
                     "/clone3", "/tmp/clone4.img",
                     "/tmp/clone5.img", None]

        cloneobj.clone_paths = disks
        self.assertEqual(cloneobj.clone_paths, disks)
        return cloneobj

    def _clone_compare(self, cloneobj, outbase, clone_disks_file=None):
        """Helps compare output from passed clone instance with an xml file"""
        outfile = os.path.join(clonexml_dir, outbase + "-out.xml")

        cloneobj.setup_original()
        cloneobj.setup_clone()

        utils.diff_compare(cloneobj.clone_xml, outfile)
        if clone_disks_file:
            xml_clone_disks = ""
            for i in cloneobj.clone_disks:
                xml_clone_disks += i.get_vol_install().get_xml()
            utils.diff_compare(xml_clone_disks, clone_disks_file)

    def _clone_define(self, filebase):
        """Take the valid output xml and attempt to define it on the
           connection to ensure we don't get any errors"""
        outfile = os.path.join(clonexml_dir, filebase + "-out.xml")
        outxml = open(outfile).read()
        conn = utils.URIs.open_testdriver_cached()
        utils.test_create(conn, outxml)

    def testRemoteNoStorage(self):
        """Test remote clone where VM has no storage that needs cloning"""
        conn = utils.URIs.open_test_remote()
        self._clone("nostorage", conn=conn)
        self._clone("noclone-storage", conn=conn)

    def testRemoteWithStorage(self):
        """
        Test remote clone with storage needing cloning. Should fail,
        since libvirt has no storage clone api.
        """
        conn = utils.URIs.open_test_remote()
        disks = ["%s/1.img" % POOL1, "%s/2.img" % POOL1]
        try:
            self._clone("general-cfg", disks=disks, conn=conn)
            # We shouldn't succeed, so test fails
            raise AssertionError("Remote clone with storage passed "
                                 "when it shouldn't.")
        except (ValueError, RuntimeError) as e:
            # Exception expected
            log.debug("Received expected exception: %s", str(e))

    def testCloneStorageManaged(self):
        disks = ["%s/new1.img" % POOL1, "%s/new2.img" % DISKPOOL]
        self._clone("managed-storage", disks=disks)

    def testCloneStorageCrossPool(self):
        conn = utils.URIs.open_test_remote()
        clone_disks_file = os.path.join(
                clonexml_dir, "cross-pool-disks-out.xml")
        disks = ["%s/new1.img" % POOL2, "%s/new2.img" % POOL1]
        self._clone("cross-pool", disks=disks,
                clone_disks_file=clone_disks_file, conn=conn)

    def testCloneStorageForce(self):
        disks = ["/dev/default-pool/1234.img", None, "/clone2.img"]
        self._clone("force", disks=disks, force_list=["hda", "fdb", "sdb"])

    def testCloneStorageSkip(self):
        disks = ["/dev/default-pool/1234.img", None, "/tmp/clone2.img"]
        skip_list = ["hda", "fdb"]
        self._clone("skip", disks=disks, skip_list=skip_list)

    def testCloneFullPool(self):
        with self.assertRaises(Exception):
            self._clone("fullpool",
                    disks=["/full-pool/test.img"], compare=False)

    def testCloneNvramAuto(self):
        self._clone("nvram-auto")

    def testCloneNvramNewpool(self):
        self._clone("nvram-newpool")

    def testCloneNvramMissing(self):
        self._clone("nvram-missing")

    def testCloneGraphicsPassword(self):
        self._clone("graphics-password")

    def testCloneChannelSource(self):
        self._clone("channel-source")

    def testCloneMisc(self):
        conn = utils.URIs.open_testdriver_cached()

        with self.assertRaises(RuntimeError) as err:
            cloner = Cloner(conn)
            # Add this bit here for coverage testing
            cloner.clone_xml = None
            cloner.setup_original()
        self.assertTrue("Original guest name or XML" in str(err.exception))

        with self.assertRaises(RuntimeError) as err:
            cloner = Cloner(conn)
            cloner.original_guest = "test-snapshots"
            cloner.setup_original()
        self.assertTrue("must be shutoff" in str(err.exception))

        with self.assertRaises(ValueError) as err:
            cloner = Cloner(conn)
            cloner.original_guest = "test-clone-simple"
            cloner.setup_original()
            cloner.setup_clone()
        self.assertTrue("More disks to clone" in str(err.exception))

        cloner = Cloner(conn)
        self.assertEqual(
                cloner.generate_clone_name("test-clone5"), "test-clone6")
