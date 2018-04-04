# Copyright (C) 2013, 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest
import os
import logging

from tests import utils

from virtinst import Cloner

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

clonexml_dir = os.path.join(os.getcwd(), "tests/clone-xml")


class TestClone(unittest.TestCase):

    def setUp(self):
        for f in local_files:
            os.system("touch %s" % f)

    def tearDown(self):
        for f in local_files:
            os.unlink(f)

    def _clone(self, filebase, disks=None, force_list=None,
               skip_list=None, compare=True, conn=None,
               clone_disks_file=None):
        """Helper for comparing clone input/output from 2 xml files"""
        infile = os.path.join(clonexml_dir, filebase + "-in.xml")
        in_content = utils.read_file(infile)

        if not conn:
            conn = utils.URIs.open_testdriver_cached()
        cloneobj = Cloner(conn)
        cloneobj.original_xml = in_content
        for force in force_list or []:
            cloneobj.force_target = force
        for skip in skip_list or []:
            cloneobj.skip_target = skip

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
        cloneobj.clone_uuid = "12345678-1234-1234-1234-123456789012"

        cloneobj.clone_macs = ["22:23:45:67:89:00", "22:23:45:67:89:01"]

        if disks is None:
            disks = ["/dev/disk-pool/disk-vol1", "/tmp/clone2.img",
                     "/clone3", "/tmp/clone4.img",
                     "/tmp/clone5.img", None]

        cloneobj.clone_paths = disks
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
                xml_clone_disks += i.get_vol_install().get_xml_config()
            utils.diff_compare(xml_clone_disks, clone_disks_file)

    def _clone_define(self, filebase):
        """Take the valid output xml and attempt to define it on the
           connection to ensure we don't get any errors"""
        outfile = os.path.join(clonexml_dir, filebase + "-out.xml")
        outxml = utils.read_file(outfile)
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
            logging.debug("Received expected exception: %s", str(e))

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
        try:
            self._clone("fullpool",
                    disks=["/full-pool/test.img"], compare=False)
        except Exception:
            return

        raise AssertionError("Expected exception, but none raised.")

    def testCloneNvramAuto(self):
        self._clone("nvram-auto")

    def testCloneNvramNewpool(self):
        self._clone("nvram-newpool")

    def testCloneGraphicsPassword(self):
        self._clone("graphics-password")
