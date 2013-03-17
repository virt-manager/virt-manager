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

import unittest
import os
import logging

import utils

from virtinst import CloneManager
CloneDesign = CloneManager.CloneDesign

ORIG_NAME  = "clone-orig"
CLONE_NAME = "clone-new"

# Create some files to use as test images
FILE1 = "/tmp/virtinst-test1.img"
FILE2 = "/tmp/virtinst-test2.img"
P1_VOL1  = "/default-pool/testvol1.img"
P1_VOL2  = "/default-pool/testvol2.img"
P2_VOL1  = "/cross-pool/testvol1.img"
P2_VOL2  = "/cross-pool/testvol2.img"

POOL1 = "/default-pool"
POOL2 = "/cross-pool"
DISKPOOL = "/disk-pool"

local_files = [ FILE1, FILE2]

clonexml_dir = os.path.join(os.getcwd(), "tests/clone-xml")
clone_files = []

for tmpf in os.listdir(clonexml_dir):
    black_list = [ "managed-storage", "cross-pool", "force", "skip",
                   "fullpool"]
    if tmpf.endswith("-out.xml"):
        tmpf = tmpf[0:(len(tmpf) - len("-out.xml"))]
        if tmpf not in clone_files and tmpf not in black_list:
            clone_files.append(tmpf)

conn = utils.open_testdriver()

class TestClone(unittest.TestCase):

    def setUp(self):
        for f in local_files:
            os.system("touch %s" % f)

    def tearDown(self):
        for f in local_files:
            os.unlink(f)

    def _clone_helper(self, filebase, disks=None, force_list=None,
                      skip_list=None, compare=True, useconn=None):
        """Helper for comparing clone input/output from 2 xml files"""
        infile = os.path.join(clonexml_dir, filebase + "-in.xml")
        in_content = utils.read_file(infile)

        cloneobj = CloneDesign(conn=useconn or conn)
        cloneobj.original_xml = in_content
        for force in force_list or []:
            cloneobj.force_target = force
        for skip in skip_list or []:
            cloneobj.skip_target = skip

        cloneobj = self._default_clone_values(cloneobj, disks)

        if compare:
            self._clone_compare(cloneobj, filebase)
            self._clone_define(filebase)
        else:
            cloneobj.setup()

    def _default_clone_values(self, cloneobj, disks=None):
        """Sets default values for the cloned VM."""
        cloneobj.clone_name = "clone-new"
        cloneobj.clone_uuid = "12345678-1234-1234-1234-123456789012"

        cloneobj.clone_mac = "22:23:45:67:89:00"
        cloneobj.clone_mac = "22:23:45:67:89:01"

        if disks != None:
            for disk in disks:
                cloneobj.clone_devices = disk
        else:
            cloneobj.clone_devices = "/dev/loop0"
            cloneobj.clone_devices = "/tmp/clone2.img"
            cloneobj.clone_devices = "/tmp/clone3.img"
            cloneobj.clone_devices = "/tmp/clone4.img"
            cloneobj.clone_devices = "/tmp/clone5.img"
            cloneobj.clone_devices = None

        return cloneobj

    def _clone_compare(self, cloneobj, outbase):
        """Helps compare output from passed clone instance with an xml file"""
        outfile = os.path.join(clonexml_dir, outbase + "-out.xml")

        cloneobj.setup()

        utils.diff_compare(cloneobj.clone_xml, outfile)

    def _clone_define(self, filebase):
        """Take the valid output xml and attempt to define it on the
           connection to ensure we don't get any errors"""
        outfile = os.path.join(clonexml_dir, filebase + "-out.xml")
        outxml = utils.read_file(outfile)
        utils.test_create(conn, outxml)


    # Skip this test, since libvirt can add new XML elements to the defined
    # XML (<video>) that make roundtrip a pain
    def notestCloneGuestLookup(self):
        """Test using a vm name lookup for cloning"""
        for base in clone_files:
            infile = os.path.join(clonexml_dir, base + "-in.xml")

            vm = None
            try:
                vm = conn.defineXML(utils.read_file(infile))

                cloneobj = CloneDesign(conn=conn)
                cloneobj.original_guest = ORIG_NAME

                cloneobj = self._default_clone_values(cloneobj)
                self._clone_compare(cloneobj, base)
            finally:
                if vm:
                    vm.undefine()

    def testCloneFromFile(self):
        """Test using files for input and output"""
        for base in clone_files:
            self._clone_helper(base)

    def testRemoteNoStorage(self):
        """Test remote clone where VM has no storage that needs cloning"""
        useconn = utils.open_test_remote()
        for base in [ "nostorage", "noclone-storage" ] :
            self._clone_helper(base, disks=[], useconn=useconn)

    def testRemoteWithStorage(self):
        """
        Test remote clone with storage needing cloning. Should fail,
        since libvirt has no storage clone api.
        """
        useconn = utils.open_test_remote()
        for base in [ "general-cfg" ] :
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

    def testCloneStorage(self):
        base = "managed-storage"
        self._clone_helper(base, ["%s/new1.img" % POOL1,
                                  "%s/new2.img" % DISKPOOL])

    def testCloneStorageCrossPool(self):
        base = "cross-pool"
        self._clone_helper(base, ["%s/new1.img" % POOL2,
                                  "%s/new2.img" % POOL2])

    def testCloneStorageForce(self):
        base = "force"
        self._clone_helper(base,
                           disks=["/dev/loop0", None, "/tmp/clone2.img"],
                           force_list=["hda", "fdb", "sdb"])

    def testCloneStorageSkip(self):
        base = "skip"
        self._clone_helper(base,
                           disks=["/dev/loop0", None, "/tmp/clone2.img"],
                           skip_list=["hda", "fdb"])

    def testCloneFullPool(self):
        base = "fullpool"
        try:
            self._clone_helper(base, disks=["/full-pool/test.img"],
                               compare=False)
        except Exception:
            return

        raise AssertionError("Expected exception, but none raised.")

    def testCloneManagedToUnmanaged(self):
        base = "managed-storage"

        # We are trying to clone from a pool (/default-pool) to unmanaged
        # storage. For this case, the cloning needs to fail back to manual
        # operation (no libvirt calls), but since /default-pool doesn't exist,
        # this should fail.
        try:
            self._clone_helper(base, ["/tmp/new1.img", "/tmp/new2.img"])

            raise AssertionError("Managed to unmanaged succeeded, expected "
                                 "failure.")
        except (ValueError, RuntimeError), e:
            logging.debug("Received expected exception: %s", str(e))
