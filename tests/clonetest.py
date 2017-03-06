# Copyright (C) 2013, 2015 Red Hat, Inc.
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
conn = utils.open_testdriver()


class TestClone(unittest.TestCase):

    def setUp(self):
        for f in local_files:
            os.system("touch %s" % f)

    def tearDown(self):
        for f in local_files:
            os.unlink(f)

    def _clone_helper(self, filebase, disks=None, force_list=None,
                      skip_list=None, compare=True, useconn=None,
                      clone_disks_file=None):
        """Helper for comparing clone input/output from 2 xml files"""
        infile = os.path.join(clonexml_dir, filebase + "-in.xml")
        in_content = utils.read_file(infile)

        cloneobj = Cloner(useconn or conn)
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
            cloneobj.setup()

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

        cloneobj.setup()

        utils.diff_compare(cloneobj.clone_xml, outfile)
        if clone_disks_file:
            xml_clone_disks = ""
            for i in cloneobj.get_clone_disks():
                xml_clone_disks += i.get_vol_install().get_xml_config()
            utils.diff_compare(xml_clone_disks, clone_disks_file)

    def _clone_define(self, filebase):
        """Take the valid output xml and attempt to define it on the
           connection to ensure we don't get any errors"""
        outfile = os.path.join(clonexml_dir, filebase + "-out.xml")
        outxml = utils.read_file(outfile)
        utils.test_create(conn, outxml)

    def testRemoteNoStorage(self):
        """Test remote clone where VM has no storage that needs cloning"""
        useconn = utils.open_test_remote()
        for base in ["nostorage", "noclone-storage"] :
            self._clone_helper(base, disks=[], useconn=useconn)

    def testRemoteWithStorage(self):
        """
        Test remote clone with storage needing cloning. Should fail,
        since libvirt has no storage clone api.
        """
        useconn = utils.open_test_remote()
        for base in ["general-cfg"] :
            try:
                self._clone_helper(base,
                                   disks=["%s/1.img" % POOL1,
                                          "%s/2.img" % POOL1],
                                   useconn=useconn)

                # We shouldn't succeed, so test fails
                raise AssertionError("Remote clone with storage passed "
                                     "when it shouldn't.")
            except (ValueError, RuntimeError), e:
                # Exception expected
                logging.debug("Received expected exception: %s", str(e))

    def testCloneStorageManaged(self):
        base = "managed-storage"
        self._clone_helper(base, ["%s/new1.img" % POOL1,
                                  "%s/new2.img" % DISKPOOL])

    def testCloneStorageCrossPool(self):
        base = "cross-pool"
        useconn = utils.open_test_remote()
        clone_disks_file = os.path.join(clonexml_dir, base + "-disks-out.xml")
        self._clone_helper(base, ["%s/new1.img" % POOL2,
                                  "%s/new2.img" % POOL1],
                           clone_disks_file=clone_disks_file,
                           useconn=useconn)

    def testCloneStorageForce(self):
        base = "force"
        self._clone_helper(base,
                           disks=["/dev/default-pool/1234.img",
                                  None, "/clone2.img"],
                           force_list=["hda", "fdb", "sdb"])

    def testCloneStorageSkip(self):
        base = "skip"
        self._clone_helper(base,
                           disks=["/dev/default-pool/1234.img",
                                  None, "/tmp/clone2.img"],
                           skip_list=["hda", "fdb"])

    def testCloneFullPool(self):
        base = "fullpool"
        try:
            self._clone_helper(base, disks=["/full-pool/test.img"],
                               compare=False)
        except Exception:
            return

        raise AssertionError("Expected exception, but none raised.")

    def testCloneNvramAuto(self):
        base = "nvram-auto"
        self._clone_helper(base)
