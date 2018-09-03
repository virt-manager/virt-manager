# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import io
import os
import unittest

from virtinst import Installer
from virtconv import VirtConverter

from tests import utils

base_dir = os.getcwd() + "/tests/virtconv-files/"
out_dir = base_dir + "libvirt_output"


class TestVirtConv(unittest.TestCase):
    def _convert_helper(self, in_path, out_path, in_type, disk_format):
        outbuf = io.StringIO()

        def print_cb(msg):
            print(msg, file=outbuf)

        conn = utils.URIs.open_kvm()
        converter = VirtConverter(conn, in_path, print_cb=print_cb)

        if converter.parser.name != in_type:
            raise AssertionError("find_parser_by_file for '%s' returned "
                                 "wrong parser type.\n"
                                 "Expected: %s\n"
                                 "Received: %s\n" %
                                 (in_path, in_type, converter.parser.name))

        converter.convert_disks(disk_format, dry=True)
        guest = converter.get_guest()
        installer = Installer(guest.conn)
        ignore, out_xml = installer.start_install(guest, return_xml=True)
        out_expect = out_xml
        if outbuf.getvalue():
            out_expect += ("\n\n" + outbuf.getvalue().replace(base_dir, ""))

        if not conn.check_support(conn.SUPPORT_CONN_VMPORT):
            self.skipTest("Not comparing XML because vmport isn't supported")

        utils.diff_compare(out_expect, out_path)
        utils.test_create(conn, out_xml)

    def _compare(self, in_path, disk_format=None):
        in_type = "ovf"
        if "vmx" in in_path:
            in_type = "vmx"

        in_path = os.path.join(base_dir, in_path)
        base = in_type + "2libvirt"
        in_base = os.path.basename(in_path).rsplit(".", 1)[0]
        out_path = "%s/%s_%s.%s" % (out_dir, base, in_base, "libvirt")
        if disk_format:
            out_path += ".disk_%s" % disk_format

        self._convert_helper(in_path, out_path, in_type, disk_format)


    def testOVF2Libvirt(self):
        self._compare("ovf_input/test1.ovf")
        self._compare("ovf_input/test2.ovf")
        self._compare("ovf_input/test_gzip.ovf")
        self._compare("ovf_input/ovf_directory")

    def testVMX2Libvirt(self):
        self._compare("vmx_input/test1.vmx")
        self._compare("vmx_input/test-nodisks.vmx")
        self._compare("vmx_input/test-vmx-zip.zip")
        self._compare("vmx_input/vmx-dir")

    def testDiskConvert(self):
        self._compare("ovf_input/test1.ovf", disk_format="qcow2")
        self._compare("vmx_input/test1.vmx", disk_format="raw")
        self._compare("ovf_input/test_gzip.ovf", disk_format="raw")
