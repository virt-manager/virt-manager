# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import unittest

from tests import utils

from virtinst import Capabilities
from virtinst import DomainCapabilities


class TestCapabilities(unittest.TestCase):
    def _buildCaps(self, filename):
        path = os.path.join("tests/capabilities-xml", filename)
        conn = utils.URIs.open_testdefault_cached()
        return Capabilities(conn, open(path).read())

    def testCapsCPUFeaturesOldSyntax(self):
        filename = "test-old-vmx.xml"
        host_feature_list = ["vmx"]

        caps = self._buildCaps(filename)
        for f in host_feature_list:
            self.assertEqual(caps.host.cpu.has_feature(f), True)

    def testCapsCPUFeaturesOldSyntaxSVM(self):
        filename = "test-old-svm.xml"
        host_feature_list = ["svm"]

        caps = self._buildCaps(filename)
        for f in host_feature_list:
            self.assertEqual(caps.host.cpu.has_feature(f), True)

    def testCapsCPUFeaturesNewSyntax(self):
        filename = "test-qemu-with-kvm.xml"
        host_feature_list = ['lahf_lm', 'xtpr', 'cx16', 'tm2', 'est', 'vmx',
            'ds_cpl', 'pbe', 'tm', 'ht', 'ss', 'acpi', 'ds']

        caps = self._buildCaps(filename)
        for f in host_feature_list:
            self.assertEqual(caps.host.cpu.has_feature(f), True)

        self.assertEqual(caps.host.cpu.model, "core2duo")
        self.assertEqual(caps.host.cpu.vendor, "Intel")
        self.assertEqual(caps.host.cpu.threads, 3)
        self.assertEqual(caps.host.cpu.cores, 5)
        self.assertEqual(caps.host.cpu.sockets, 7)

    def testCapsUtilFuncs(self):
        caps_with_kvm = self._buildCaps("test-qemu-with-kvm.xml")
        caps_no_kvm = self._buildCaps("test-qemu-no-kvm.xml")
        caps_empty = self._buildCaps("test-old-vmx.xml")

        def test_utils(caps, has_guests, is_kvm):
            if caps.guests:
                self.assertEqual(caps.guests[0].has_install_options(), has_guests)
                self.assertEqual(caps.guests[0].is_kvm_available(), is_kvm)

        test_utils(caps_empty, False, False)
        test_utils(caps_with_kvm, True, True)
        test_utils(caps_no_kvm, True, False)

    def testCapsNuma(self):
        cells = self._buildCaps("lxc.xml").host.topology.cells
        self.assertEqual(len(cells), 1)
        self.assertEqual(len(cells[0].cpus), 8)
        self.assertEqual(cells[0].cpus[3].id, '3')


    ####################################
    # Test getCPUModel output handling #
    ####################################

    def testCPUAPI(self):
        caps = self._buildCaps("test-qemu-with-kvm.xml")

        cpu_64 = caps.get_cpu_values("x86_64")
        cpu_32 = caps.get_cpu_values("i686")
        cpu_random = caps.get_cpu_values("mips")

        def test_cpu_map(cpumap, cpus):
            cpunames = sorted(cpumap, key=str.lower)

            for c in cpus:
                self.assertTrue(c in cpunames)

        self.assertEqual(cpu_64, cpu_32)

        x86_cpunames = [
            '486', 'athlon', 'Conroe', 'core2duo', 'coreduo', 'n270',
            'Nehalem', 'Opteron_G1', 'Opteron_G2', 'Opteron_G3', 'Penryn',
            'pentium', 'pentium2', 'pentium3', 'pentiumpro', 'phenom',
            'qemu32', 'qemu64']

        test_cpu_map(cpu_64, x86_cpunames)
        test_cpu_map(cpu_random, [])

        cpu_64 = caps.get_cpu_values("x86_64")
        self.assertTrue(len(cpu_64) > 0)


    ##############################
    # domcapabilities.py testing #
    ##############################

    def testDomainCapabilities(self):
        xml = open("tests/capabilities-xml/test-domcaps.xml").read()
        caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

        self.assertEqual(caps.os.loader.supported, True)
        self.assertEqual(caps.os.loader.get_values(),
            ["/foo/bar", "/tmp/my_path"])
        self.assertEqual(caps.os.loader.enum_names(), ["type", "readonly"])
        self.assertEqual(caps.os.loader.get_enum("type").get_values(),
            ["rom", "pflash"])

    def testDomainCapabilitiesx86(self):
        xml = open("tests/capabilities-xml/kvm-x86_64-domcaps.xml").read()
        caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

        custom_mode = caps.cpu.get_mode("custom")
        self.assertTrue(bool(custom_mode))
        cpu_model = custom_mode.get_model("Opteron_G4")
        self.assertTrue(bool(cpu_model))
        self.assertTrue(cpu_model.usable)
