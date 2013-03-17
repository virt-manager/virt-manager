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

import os.path
import unittest
import virtinst.CapabilitiesParser as capabilities

def build_host_feature_dict(feature_list):
    fdict = {}
    for f in feature_list:
        fdict[f] = capabilities.FEATURE_ON

    return fdict

class TestCapabilities(unittest.TestCase):

    def _compareGuest(self, (arch, os_type, domains, features), guest):
        self.assertEqual(arch,            guest.arch)
        self.assertEqual(os_type,         guest.os_type)
        self.assertEqual(len(domains), len(guest.domains))
        for n in range(len(domains)):
            self.assertEqual(domains[n][0], guest.domains[n].hypervisor_type)
            self.assertEqual(domains[n][1], guest.domains[n].emulator)
            self.assertEqual(domains[n][2], guest.domains[n].machines)

        for n in features:
            self.assertEqual(features[n],        guest.features[n])

    def _buildCaps(self, filename):
        path = os.path.join("tests/capabilities-xml", filename)
        xml = file(path).read()

        return capabilities.parse(xml)

    def _testCapabilities(self, path, (host_arch, host_features), guests,
                          secmodel=None):
        caps = self._buildCaps(path)

        if host_arch:
            self.assertEqual(host_arch,     caps.host.arch)
            for n in host_features:
                self.assertEqual(host_features[n], caps.host.features[n])

        if secmodel:
            self.assertEqual(secmodel[0], caps.host.secmodel.model)
            self.assertEqual(secmodel[1], caps.host.secmodel.doi)

        map(self._compareGuest, guests, caps.guests)

    def testCapabilities1(self):
        host = ( 'x86_64', {'vmx': capabilities.FEATURE_ON})

        guests = [
            ( 'x86_64', 'xen',
              [['xen', None, []]], {} ),
            ( 'i686',   'xen',
              [['xen', None, []]], { 'pae': capabilities.FEATURE_ON } ),
            ( 'i686',   'hvm',
              [['xen', "/usr/lib64/xen/bin/qemu-dm", ['pc', 'isapc']]], { 'pae': capabilities.FEATURE_ON | capabilities.FEATURE_OFF } ),
            ( 'x86_64', 'hvm',
              [['xen', "/usr/lib64/xen/bin/qemu-dm", ['pc', 'isapc']]], {} )
        ]

        self._testCapabilities("capabilities-xen.xml", host, guests)

    def testCapabilities2(self):
        host = ( 'x86_64', {})
        secmodel = ('selinux', '0')

        guests = [
            ( 'x86_64', 'hvm',
              [['qemu', '/usr/bin/qemu-system-x86_64', ['pc', 'isapc']]], {} ),
            ( 'i686',   'hvm',
              [['qemu', '/usr/bin/qemu', ['pc', 'isapc']]], {} ),
            ( 'mips',   'hvm',
              [['qemu', '/usr/bin/qemu-system-mips', ['mips']]], {} ),
            ( 'mipsel', 'hvm',
              [['qemu', '/usr/bin/qemu-system-mipsel', ['mips']]], {} ),
            ( 'sparc',  'hvm',
              [['qemu', '/usr/bin/qemu-system-sparc', ['sun4m']]], {} ),
            ( 'ppc',    'hvm',
              [['qemu', '/usr/bin/qemu-system-ppc',
               ['g3bw', 'mac99', 'prep']]], {} ),
        ]

        self._testCapabilities("capabilities-qemu.xml", host, guests, secmodel)

    def testCapabilities3(self):
        host = ( 'i686', {})

        guests = [
            ( 'i686',   'hvm',
              [['qemu', '/usr/bin/qemu', ['pc', 'isapc']],
               ['kvm', '/usr/bin/qemu-kvm', ['pc', 'isapc']]], {} ),
            ( 'x86_64', 'hvm',
              [['qemu', '/usr/bin/qemu-system-x86_64', ['pc', 'isapc']]], {} ),
            ( 'mips',   'hvm',
              [['qemu', '/usr/bin/qemu-system-mips', ['mips']]], {} ),
            ( 'mipsel', 'hvm',
              [['qemu', '/usr/bin/qemu-system-mipsel', ['mips']]], {} ),
            ( 'sparc',  'hvm',
              [['qemu', '/usr/bin/qemu-system-sparc', ['sun4m']]], {} ),
            ( 'ppc',    'hvm',
              [['qemu', '/usr/bin/qemu-system-ppc',
               ['g3bw', 'mac99', 'prep']]], {} ),
        ]

        self._testCapabilities("capabilities-kvm.xml", host, guests)

    def testCapabilities4(self):
        host = ( 'i686',
                 { 'pae': capabilities.FEATURE_ON | capabilities.FEATURE_OFF })

        guests = [
            ( 'i686', 'linux',
              [['test', None, []]],
              { 'pae': capabilities.FEATURE_ON | capabilities.FEATURE_OFF } ),
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
        feature_dict = build_host_feature_dict(host_feature_list)

        caps = self._buildCaps(filename)
        for f in feature_dict.keys():
            self.assertEquals(caps.host.features[f], feature_dict[f])

    def testCapsCPUFeaturesOldSyntaxSVM(self):
        filename = "rhel5.4-xen-caps.xml"
        host_feature_list = ["svm"]
        feature_dict = build_host_feature_dict(host_feature_list)

        caps = self._buildCaps(filename)
        for f in feature_dict.keys():
            self.assertEquals(caps.host.features[f], feature_dict[f])

    def testCapsCPUFeaturesNewSyntax(self):
        filename = "libvirt-0.7.6-qemu-caps.xml"
        host_feature_list = ['lahf_lm', 'xtpr', 'cx16', 'tm2', 'est', 'vmx',
                             'ds_cpl', 'pbe', 'tm', 'ht', 'ss', 'acpi', 'ds']
        feature_dict = build_host_feature_dict(host_feature_list)

        caps = self._buildCaps(filename)
        for f in feature_dict.keys():
            self.assertEquals(caps.host.features[f], feature_dict[f])

        self.assertEquals(caps.host.cpu.model, "core2duo")
        self.assertEquals(caps.host.cpu.vendor, "Intel")
        self.assertEquals(caps.host.cpu.threads, "3")
        self.assertEquals(caps.host.cpu.cores, "5")
        self.assertEquals(caps.host.cpu.sockets, "7")

    def testCapsUtilFuncs(self):
        new_caps = self._buildCaps("libvirt-0.7.6-qemu-caps.xml")
        new_caps_no_kvm = self._buildCaps(
                                    "libvirt-0.7.6-qemu-no-kvmcaps.xml")
        empty_caps = self._buildCaps("empty-caps.xml")
        rhel_xen_enable_hvm_caps = self._buildCaps(
                                    "rhel5.4-xen-caps-virt-enabled.xml")
        rhel_xen_caps = self._buildCaps("rhel5.4-xen-caps.xml")
        rhel_kvm_caps = self._buildCaps("rhel5.4-kvm-caps.xml")

        def test_utils(caps, no_guests, is_hvm, is_kvm, is_bios_disable,
                       is_xenner):
            self.assertEquals(caps.no_install_options(), no_guests)
            self.assertEquals(caps.hw_virt_supported(), is_hvm)
            self.assertEquals(caps.is_kvm_available(), is_kvm)
            self.assertEquals(caps.is_bios_virt_disabled(), is_bios_disable)
            self.assertEquals(caps.is_xenner_available(), is_xenner)

        test_utils(new_caps, False, True, True, False, True)
        test_utils(empty_caps, True, False, False, False, False)
        test_utils(rhel_xen_enable_hvm_caps, False, True, False, False, False)
        test_utils(rhel_xen_caps, False, True, False, True, False)
        test_utils(rhel_kvm_caps, False, True, True, False, False)
        test_utils(new_caps_no_kvm, False, True, False, False, False)

    def testCPUMap(self):
        caps = self._buildCaps("libvirt-0.7.6-qemu-caps.xml")
        cpu_64 = caps.get_cpu_values("x86_64")
        cpu_32 = caps.get_cpu_values("i486")
        cpu_random = caps.get_cpu_values("mips")

        def test_cpu_map(cpumap, vendors, features, cpus):
            cpunames = sorted(map(lambda c: c.model, cpumap.cpus),
                              key=str.lower)

            for v in vendors:
                self.assertTrue(v in cpumap.vendors)
            for f in features:
                self.assertTrue(f in cpumap.features)
            for c in cpus:
                self.assertTrue(c in cpunames)

        def test_single_cpu(cpumap, model, vendor, features):
            cpu = cpumap.get_cpu(model)
            self.assertEquals(cpu.vendor, vendor)
            self.assertEquals(cpu.features, features)

        self.assertEquals(cpu_64, cpu_32)

        x86_vendors = ["AMD", "Intel"]
        x86_features = [
            '3dnow', '3dnowext', '3dnowprefetch', 'abm', 'acpi', 'apic',
            'cid', 'clflush', 'cmov', 'cmp_legacy', 'cr8legacy', 'cx16',
            'cx8', 'dca', 'de', 'ds', 'ds_cpl', 'est', 'extapic', 'fpu',
            'fxsr', 'fxsr_opt', 'ht', 'hypervisor', 'ia64', 'lahf_lm', 'lm',
            'mca', 'mce', 'misalignsse', 'mmx', 'mmxext', 'monitor', 'msr',
            'mtrr', 'nx', 'osvw', 'pae', 'pat', 'pbe', 'pdpe1gb', 'pge', 'pn',
            'pni', 'popcnt', 'pse', 'pse36', 'rdtscp', 'sep', 'skinit', 'ss',
            'sse', 'sse2', 'sse4.1', 'sse4.2', 'sse4a', 'ssse3', 'svm',
            'syscall', 'tm', 'tm2', 'tsc', 'vme', 'vmx', 'wdt', 'x2apic',
            'xtpr']
        x86_cpunames = [
            '486', 'athlon', 'Conroe', 'core2duo', 'coreduo', 'n270',
            'Nehalem', 'Opteron_G1', 'Opteron_G2', 'Opteron_G3', 'Penryn',
            'pentium', 'pentium2', 'pentium3', 'pentiumpro', 'phenom',
            'qemu32', 'qemu64']

        test_cpu_map(cpu_64, x86_vendors, x86_features, x86_cpunames)
        test_cpu_map(cpu_random, [], [], [])

        athlon_features = [
            '3dnow', '3dnowext', 'apic', 'cmov', 'cx8', 'de', 'fpu', 'fxsr',
            'mce', 'mmx', 'mmxext', 'msr', 'mtrr', 'pae', 'pat', 'pge', 'pse',
            'pse36', 'sep', 'sse', 'sse2', 'tsc', 'vme']
        test_single_cpu(cpu_64, "athlon", "AMD", athlon_features)

if __name__ == "__main__":
    unittest.main()
