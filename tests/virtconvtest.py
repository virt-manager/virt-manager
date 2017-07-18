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

from __future__ import print_function

import glob
import os
import StringIO
import unittest

from virtconv import VirtConverter

from tests import utils

base_dir = os.getcwd() + "/tests/virtconv-files/"
out_dir = base_dir + "libvirt_output"


class TestVirtConv(unittest.TestCase):
    def _convert_helper(self, infile, outfile, in_type, disk_format):
        outbuf = StringIO.StringIO()
        def print_cb(msg):
            print(msg, file=outbuf)

        conn = utils.open_kvm()
        converter = VirtConverter(conn, infile, print_cb=print_cb)

        if converter.parser.name != in_type:
            raise AssertionError("find_parser_by_file for '%s' returned "
                                 "wrong parser type.\n"
                                 "Expected: %s\n"
                                 "Received: %s\n" %
                                 (infile, in_type, converter.parser.name))

        converter.convert_disks(disk_format, dry=True)
        guest = converter.get_guest()
        ignore, out_xml = guest.start_install(return_xml=True)
        out_expect = out_xml
        if outbuf.getvalue():
            out_expect += ("\n\n" + outbuf.getvalue().replace(base_dir, ""))

        if not conn.check_support(conn.SUPPORT_CONN_VMPORT):
            self.skipTest("Not comparing XML because vmport isn't supported")

        utils.diff_compare(out_expect, outfile)
        utils.test_create(conn, out_xml)

    def _compare_single_file(self, in_path, in_type, disk_format=None):
        cwd = os.getcwd()
        base = in_type + "2libvirt"
        in_base = os.path.basename(in_path).rsplit(".", 1)[0]
        out_path = "%s/%s_%s.%s" % (out_dir, base, in_base, "libvirt")
        if disk_format:
            out_path += ".disk_%s" % disk_format

        try:
            os.chdir(os.path.dirname(in_path))
            self._convert_helper(in_path, out_path, in_type, disk_format)
        finally:
            os.chdir(cwd)

    def _compare_files(self, in_type):
        in_dir = base_dir + in_type + "_input"

        if not os.path.exists(in_dir):
            raise RuntimeError("Directory does not exist: %s" % in_dir)

        for in_path in glob.glob(os.path.join(in_dir, "*")):
            self._compare_single_file(in_path, in_type)

    def testOVF2Libvirt(self):
        self._compare_files("ovf")
    def testVMX2Libvirt(self):
        self._compare_files("vmx")

    def testDiskConvert(self):
        self._compare_single_file(
            base_dir + "ovf_input/test1.ovf", "ovf", disk_format="qcow2")
        self._compare_single_file(
            base_dir + "vmx_input/test1.vmx", "vmx", disk_format="raw")
        self._compare_single_file(
            base_dir + "ovf_input/test_gzip.ovf", "ovf", disk_format="raw")
