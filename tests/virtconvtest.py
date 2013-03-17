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
import virtconv
import os
import glob
import utils

BASE = "tests/virtconv-files"

vmx_input  = BASE + "/vmx_input"
vmx_output = BASE + "/vmx_output"

virtimage_input  = BASE + "/virtimage_input"
virtimage_output = BASE + "/virtimage_output"

ovf_input = BASE + "/ovf_input"

class TestVirtConv(unittest.TestCase):

    def setUp(self):
        pass

    def _convert_helper(self, infile, outfile, in_type, out_type):
        inp  = virtconv.formats.find_parser_by_file(infile)
        outp = virtconv.formats.parser_by_name(out_type)

        if not inp or inp.name != in_type:
            raise AssertionError("find_parser_by_file for '%s' returned "
                                 "wrong parser type.\n"
                                 "Expected: %s\n"
                                 "Received: %s\n" % \
                                 (infile, in_type,
                                 str((not inp) and str(inp) or inp.name)))

        vmdef = inp.import_file(infile)
        out_expect = outp.export(vmdef)

        if not os.path.exists(outfile):
            open(outfile, "w").write(out_expect)
        utils.diff_compare(out_expect, outfile)

    def _build_compare_path(self, base, in_path, out_dir, out_type):
        out_path = os.path.basename(in_path).rsplit(".", 1)[0]
        return "%s/%s_%s.%s" % (out_dir, base, out_path, out_type)

    def _compare_files(self, base, in_type, out_type, in_dir, out_dir):
        cwd = os.getcwd()
        in_dir = os.path.join(cwd, in_dir)
        out_dir = os.path.join(cwd, out_dir)

        for in_path in glob.glob(os.path.join(in_dir, "*." + in_type)):
            if in_type != out_type:
                out_path = self._build_compare_path(base, in_path,
                                                    out_dir, out_type)
            else:
                out_path = in_path

            try:
                os.chdir(os.path.dirname(in_path))
                self._convert_helper(in_path, out_path, in_type, out_type)
            finally:
                os.chdir(cwd)

    def testVMX2VirtImage(self):
        base = "vmx2virtimage"
        in_type = "vmx"
        out_type = "virt-image"
        in_dir = vmx_input
        out_dir = virtimage_output

        self._compare_files(base, in_type, out_type, in_dir, out_dir)

    def testVirtImage2VMX(self):
        base = "virtimage2vmx"
        in_type = "virt-image"
        out_type = "vmx"
        in_dir = virtimage_input
        out_dir = vmx_output

        self._compare_files(base, in_type, out_type, in_dir, out_dir)

    def testOVF2VirtImage(self):
        base = "ovf2virtimage"
        in_type = "ovf"
        out_type = "virt-image"
        in_dir = ovf_input
        out_dir = virtimage_output

        self._compare_files(base, in_type, out_type, in_dir, out_dir)

    # For x2x conversion, we want to use already tested output, since ideally
    # we should be able to run a generated config continually through the
    # converter and it will generate the same result
    def testVMX2VMX(self):
        base = None
        in_type = out_type = "vmx"
        in_dir = out_dir = vmx_output

        self._compare_files(base, in_type, out_type, in_dir, out_dir)

    def testVirtImage2VirtImage(self):
        base = None
        in_type = out_type = "virt-image"
        in_dir = out_dir = virtimage_output

        self._compare_files(base, in_type, out_type, in_dir, out_dir)
