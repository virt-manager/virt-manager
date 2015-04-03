# Copyright (C) 2013, 2014 Red Hat, Inc.
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

import os
import unittest

from tests import utils

from virtinst import Capabilities
from virtinst import DomainCapabilities
from virtinst.capabilities import _CPUMapFileValues


conn = utils.open_testdriver()


class TestCapabilities(unittest.TestCase):
    def _buildCaps(self, filename):
        path = os.path.join("tests/capabilities-xml", filename)
        return Capabilities(conn, file(path).read())

    def _compareGuest(self, (arch, os_type, domains, features), guest):
        self.assertEqual(arch,            guest.arch)
        self.assertEqual(os_type,         guest.os_type)
        self.assertEqual(len(domains), len(guest.domains))
        for n in range(len(domains)):
            self.assertEqual(domains[n][0], guest.domains[n].hypervisor_type)
            self.assertEqual(domains[n][1], guest.domains[n].emulator)
            self.assertEqual(domains[n][2], guest.domains[n].machines)

        for n in features:
            self.assertEqual(features[n], getattr(guest.features, n))

    def _testCapabilities(self, path, (host_arch, host_features), guests,
                          secmodel=None):
        caps = self._buildCaps(path)

        if host_arch:
            self.assertEqual(host_arch, caps.host.cpu.arch)
            for n in host_features:
                self.assertEqual(host_features[n], caps.host.cpu.has_feature(n))

        if secmodel:
            self.assertEqual(secmodel[0], caps.host.secmodels[0].model)
            if secmodel[1]:
                for idx, (t, v) in enumerate(secmodel[1].items()):
                    self.assertEqual(t,
                        caps.host.secmodels[0].baselabels[idx].type)
                    self.assertEqual(v,
                        caps.host.secmodels[0].baselabels[idx].content)

        for idx in range(len(guests)):
            self._compareGuest(guests[idx], caps.guests[idx])

    def testCapabilities1(self):
        host = ('x86_64', {'vmx': True})

        guests = [
            ('x86_64', 'xen',
              [['xen', None, []]], {}),
            ('i686',   'xen',
                [['xen', None, []]], {'pae': True, 'nonpae': False}),
            ('i686',   'hvm',
              [['xen', "/usr/lib64/xen/bin/qemu-dm", ['pc', 'isapc']]],
              {'pae': True, 'nonpae': True}),
            ('x86_64', 'hvm',
              [['xen', "/usr/lib64/xen/bin/qemu-dm", ['pc', 'isapc']]], {})
       ]

        self._testCapabilities("capabilities-xen.xml", host, guests)

    def testCapabilities2(self):
        host = ('x86_64', {})
        secmodel = ('selinux', None)

        guests = [
            ('x86_64', 'hvm',
              [['qemu', '/usr/bin/qemu-system-x86_64', ['pc', 'isapc']]], {}),
            ('i686',   'hvm',
              [['qemu', '/usr/bin/qemu', ['pc', 'isapc']]], {}),
            ('mips',   'hvm',
              [['qemu', '/usr/bin/qemu-system-mips', ['mips']]], {}),
            ('mipsel', 'hvm',
              [['qemu', '/usr/bin/qemu-system-mipsel', ['mips']]], {}),
            ('sparc',  'hvm',
              [['qemu', '/usr/bin/qemu-system-sparc', ['sun4m']]], {}),
            ('ppc',    'hvm',
              [['qemu', '/usr/bin/qemu-system-ppc',
               ['g3bw', 'mac99', 'prep']]], {}),
       ]

        self._testCapabilities("capabilities-qemu.xml", host, guests, secmodel)

    def testCapabilities3(self):
        host = ('i686', {})

        guests = [
            ('i686',   'hvm',
              [['qemu', '/usr/bin/qemu', ['pc', 'isapc']],
               ['kvm', '/usr/bin/qemu-kvm', ['pc', 'isapc']]], {}),
            ('x86_64', 'hvm',
              [['qemu', '/usr/bin/qemu-system-x86_64', ['pc', 'isapc']]], {}),
            ('mips',   'hvm',
              [['qemu', '/usr/bin/qemu-system-mips', ['mips']]], {}),
            ('mipsel', 'hvm',
              [['qemu', '/usr/bin/qemu-system-mipsel', ['mips']]], {}),
            ('sparc',  'hvm',
              [['qemu', '/usr/bin/qemu-system-sparc', ['sun4m']]], {}),
            ('ppc',    'hvm',
              [['qemu', '/usr/bin/qemu-system-ppc',
               ['g3bw', 'mac99', 'prep']]], {}),
       ]

        secmodel = ('dac', {"kvm" : "+0:+0", "qemu" : "+0:+0"})

        self._testCapabilities("capabilities-kvm.xml", host, guests, secmodel)

    def testCapabilities4(self):
        host = ('i686', {'pae': True, 'nonpae': True})

        guests = [
            ('i686', 'linux',
              [['test', None, []]],
              {'pae': True, 'nonpae': True}),
       ]

        self._testCapabilities("capabilities-test.xml", host, guests)

    def testCapsLXC(self):
        guests = [
            ("x86_64", "exe", [["lxc", "/usr/libexec/libvirt_lxc", []]], {}),
            ("i686", "exe", [["lxc", "/usr/libexec/libvirt_lxc", []]], {}),
       ]

        self._testCapabilities("capabilities-lxc.xml",
                               (None, None), guests)

    def testCapsTopology(self):
        filename = "capabilities-test.xml"
        caps = self._buildCaps(filename)

        self.assertTrue(bool(caps.host.topology))
        self.assertTrue(len(caps.host.topology.cells) == 2)
        self.assertTrue(len(caps.host.topology.cells[0].cpus) == 8)
        self.assertTrue(len(caps.host.topology.cells[0].cpus) == 8)

    def testCapsCPUFeaturesOldSyntax(self):
        filename = "rhel5.4-xen-caps-virt-enabled.xml"
        host_feature_list = ["vmx"]

        caps = self._buildCaps(filename)
        for f in host_feature_list:
            self.assertEquals(caps.host.cpu.has_feature(f), True)

    def testCapsCPUFeaturesOldSyntaxSVM(self):
        filename = "rhel5.4-xen-caps.xml"
        host_feature_list = ["svm"]

        caps = self._buildCaps(filename)
        for f in host_feature_list:
            self.assertEquals(caps.host.cpu.has_feature(f), True)

    def testCapsCPUFeaturesNewSyntax(self):
        filename = "libvirt-0.7.6-qemu-caps.xml"
        host_feature_list = ['lahf_lm', 'xtpr', 'cx16', 'tm2', 'est', 'vmx',
            'ds_cpl', 'pbe', 'tm', 'ht', 'ss', 'acpi', 'ds']

        caps = self._buildCaps(filename)
        for f in host_feature_list:
            self.assertEquals(caps.host.cpu.has_feature(f), True)

        self.assertEquals(caps.host.cpu.model, "core2duo")
        self.assertEquals(caps.host.cpu.vendor, "Intel")
        self.assertEquals(caps.host.cpu.threads, 3)
        self.assertEquals(caps.host.cpu.cores, 5)
        self.assertEquals(caps.host.cpu.sockets, 7)

    def testCapsUtilFuncs(self):
        new_caps = self._buildCaps("libvirt-0.7.6-qemu-caps.xml")
        new_caps_no_kvm = self._buildCaps(
                                    "libvirt-0.7.6-qemu-no-kvmcaps.xml")
        empty_caps = self._buildCaps("empty-caps.xml")
        rhel_xen_enable_hvm_caps = self._buildCaps(
                                    "rhel5.4-xen-caps-virt-enabled.xml")
        rhel_xen_caps = self._buildCaps("rhel5.4-xen-caps.xml")
        rhel_kvm_caps = self._buildCaps("rhel5.4-kvm-caps.xml")

        def test_utils(caps, has_guests, is_kvm):
            self.assertEquals(caps.has_install_options(), has_guests)
            self.assertEquals(caps.is_kvm_available(), is_kvm)

        test_utils(new_caps, True, True)
        test_utils(empty_caps, False, False)
        test_utils(rhel_xen_enable_hvm_caps, True, False)
        test_utils(rhel_xen_caps, True, False)
        test_utils(rhel_kvm_caps, True, True)
        test_utils(new_caps_no_kvm, True, False)

    def _testCPUMap(self, api):
        caps = self._buildCaps("libvirt-0.7.6-qemu-caps.xml")

        setattr(_CPUMapFileValues, "_cpu_filename",
            "tests/capabilities-xml/cpu_map.xml")
        setattr(caps, "_force_cpumap", not api)

        cpu_64 = caps.get_cpu_values("x86_64")
        cpu_32 = caps.get_cpu_values("i486")
        cpu_random = caps.get_cpu_values("mips")

        def test_cpu_map(cpumap, cpus):
            cpunames = sorted(cpumap, key=str.lower)

            for c in cpus:
                self.assertTrue(c in cpunames)

        self.assertEquals(cpu_64, cpu_32)

        x86_cpunames = [
            '486', 'athlon', 'Conroe', 'core2duo', 'coreduo', 'n270',
            'Nehalem', 'Opteron_G1', 'Opteron_G2', 'Opteron_G3', 'Penryn',
            'pentium', 'pentium2', 'pentium3', 'pentiumpro', 'phenom',
            'qemu32', 'qemu64']

        test_cpu_map(cpu_64, x86_cpunames)
        test_cpu_map(cpu_random, [])

        cpu_64 = caps.get_cpu_values("x86_64")
        self.assertTrue(len(cpu_64) > 0)

    def testCPUMapFile(self):
        self._testCPUMap(api=True)

    def testCPUMapAPI(self):
        self._testCPUMap(api=False)

    def testDomainCapabilities(self):
        xml = file("tests/capabilities-xml/domain-capabilities.xml").read()
        caps = DomainCapabilities(utils.open_testdriver(), xml)

        self.assertEqual(caps.os.loader.supported, True)
        self.assertEquals(caps.os.loader.get_values(),
            ["/foo/bar", "/tmp/my_path"])
        self.assertEquals(caps.os.loader.enum_names(), ["type", "readonly"])
        self.assertEquals(caps.os.loader.get_enum("type").get_values(),
            ["rom", "pflash"])


if __name__ == "__main__":
    unittest.main()
