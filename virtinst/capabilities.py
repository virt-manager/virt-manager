#
# Some code for parsing libvirt's capabilities XML
#
# Copyright 2007, 2012-2014 Red Hat, Inc.
# Mark McLoughlin <markmc@redhat.com>
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

import re

from . import util
from .cpu import CPU as DomainCPU
from .xmlbuilder import XMLBuilder, XMLChildProperty
from .xmlbuilder import XMLProperty as _XMLProperty


# Disable test suite property tracking
class XMLProperty(_XMLProperty):
    _track = False


class CPUValuesModel(object):
    """
    Single CPU model
    """
    def __init__(self, model):
        self.model = model


class CPUValuesArch(object):
    """
    Single <arch> instance of valid CPUs
    """
    def __init__(self, arch, node=None):
        self.arch = arch
        self.vendors = []
        self.cpus = []

        if node:
            self._parseXML(node)

    def _parseXML(self, node):
        child = node.children
        while child:
            if child.name == "vendor":
                self.vendors.append(child.prop("name"))
            if child.name == "model":
                newcpu = CPUValuesModel(child.prop("name"))
                self.cpus.append(newcpu)

            child = child.next

        self.vendors.sort()

    def get_cpu(self, model):
        for c in self.cpus:
            if c.model == model:
                return c
        raise ValueError(_("Unknown CPU model '%s'") % model)


class _CPUAPIValues(object):
    """
    Lists valid values for cpu models obtained trough libvirt's getCPUModelNames
    """
    def __init__(self):
        self._cpus = None

    def get_cpus(self, arch, conn):
        if self._cpus is not None:
            return self._cpus

        if (conn and conn.check_support(conn.SUPPORT_CONN_CPU_MODEL_NAMES)):
            names = conn.getCPUModelNames(arch, 0)

            # Bindings were broke for a long time, so catch -1
            if names != -1:
                self._cpus = [CPUValuesModel(i) for i in names]
                return self._cpus

        return []


class _CPUMapFileValues(_CPUAPIValues):
    """
    Fallback method to lists cpu models, parsed directly from libvirt's local
    cpu_map.xml
    """
    _cpu_filename = "/usr/share/libvirt/cpu_map.xml"

    def __init__(self):
        _CPUAPIValues.__init__(self)
        self.archmap = {}
        xml = file(self._cpu_filename).read()

        util.parse_node_helper(xml, "cpus",
                                self._parseXML,
                                RuntimeError)

    @staticmethod
    def update_cpu_filename(name):
        _CPUMapFileValues._cpu_filename = name

    def _parseXML(self, node):
        child = node.children
        while child:
            if child.name == "arch":
                arch = child.prop("name")
                self.archmap[arch] = CPUValuesArch(arch, child)

            child = child.next

    def get_cpus(self, arch, conn):
        ignore = conn
        if re.match(r'i[4-9]86', arch):
            arch = "x86"
        elif arch == "x86_64":
            arch = "x86"

        cpumap = self.archmap.get(arch)
        if not cpumap:
            cpumap = CPUValuesArch(arch)
            self.archmap[arch] = cpumap

        return cpumap.cpus


class _CapsCPU(DomainCPU):
    arch = XMLProperty("./arch")

    # capabilities used to just expose these properties as bools
    _svm_bool = XMLProperty("./features/svm", is_bool=True)
    _vmx_bool = XMLProperty("./features/vmx", is_bool=True)
    _pae_bool = XMLProperty("./features/pae", is_bool=True)
    _nonpae_bool = XMLProperty("./features/nonpae", is_bool=True)

    has_feature_block = XMLProperty("./features", is_bool=True)


    ##############
    # Public API #
    ##############

    def has_feature(self, name):
        if name == "svm" and self._svm_bool:
            return True
        if name == "vmx" and self._vmx_bool:
            return True
        if name == "pae" and self._pae_bool:
            return True
        if name == "nonpae" and self._nonpae_bool:
            return True

        return name in [f.name for f in self.features]


###########################
# Caps <topology> parsers #
###########################

class _CapsTopologyCPU(XMLBuilder):
    _XML_ROOT_NAME = "cpu"
    id = XMLProperty("./@id")


class _TopologyCell(XMLBuilder):
    _XML_ROOT_NAME = "cell"
    id = XMLProperty("./@id")
    cpus = XMLChildProperty(_CapsTopologyCPU, relative_xpath="./cpus")


class _CapsTopology(XMLBuilder):
    _XML_ROOT_NAME = "topology"
    cells = XMLChildProperty(_TopologyCell, relative_xpath="./cells")


######################################
# Caps <host> and <secmodel> parsers #
######################################

class _CapsSecmodelBaselabel(XMLBuilder):
    _XML_ROOT_NAME = "baselabel"
    type = XMLProperty("./@type")
    content = XMLProperty(".")


class _CapsSecmodel(XMLBuilder):
    _XML_ROOT_NAME = "secmodel"
    model = XMLProperty("./model")
    baselabels = XMLChildProperty(_CapsSecmodelBaselabel)


class _CapsHost(XMLBuilder):
    _XML_ROOT_NAME = "host"
    secmodels = XMLChildProperty(_CapsSecmodel)
    cpu = XMLChildProperty(_CapsCPU, is_single=True)
    topology = XMLChildProperty(_CapsTopology, is_single=True)


################################
# <guest> and <domain> parsers #
################################

class _CapsMachine(XMLBuilder):
    _XML_ROOT_NAME = "machine"
    name = XMLProperty(".")
    canonical = XMLProperty("./@canonical")


class _CapsDomain(XMLBuilder):
    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)

        self.machines = []
        for m in self._machines:
            self.machines.append(m.name)
            if m.canonical:
                self.machines.append(m.canonical)

        self._recommended_machine = None

    _XML_ROOT_NAME = "domain"
    hypervisor_type = XMLProperty("./@type")
    emulator = XMLProperty("./emulator")
    _machines = XMLChildProperty(_CapsMachine)


    ###############
    # Public APIs #
    ###############

    def get_recommended_machine(self, conn, capsguest):
        if self._recommended_machine:
            return self._recommended_machine

        if not conn.is_test() and not conn.is_qemu():
            return None

        if capsguest.arch in ["ppc64", "ppc64le"] and "pseries" in self.machines:
            return "pseries"
        if capsguest.arch in ["armv7l", "aarch64"]:
            if "virt" in self.machines:
                return "virt"
            if "vexpress-a15" in self.machines:
                return "vexpress-a15"

        return None

    def set_recommended_machine(self, machine):
        self._recommended_machine = machine

    def is_accelerated(self):
        return self.hypervisor_type in ["kvm", "kqemu"]


class _CapsGuestFeatures(XMLBuilder):
    _XML_ROOT_NAME = "features"

    pae = XMLProperty("./pae", is_bool=True)
    nonpae = XMLProperty("./nonpae", is_bool=True)
    acpi = XMLProperty("./acpi", is_bool=True)
    apic = XMLProperty("./apci", is_bool=True)


class _CapsGuest(XMLBuilder):
    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)

        self.machines = []
        for m in self._machines:
            self.machines.append(m.name)
            if m.canonical:
                self.machines.append(m.canonical)

        for d in self.domains:
            if not d.emulator:
                d.emulator = self.emulator
            if not d.machines:
                d.machines = self.machines


    _XML_ROOT_NAME = "guest"

    os_type = XMLProperty("./os_type")
    arch = XMLProperty("./arch/@name")
    loader = XMLProperty("./arch/loader")
    emulator = XMLProperty("./arch/emulator")

    domains = XMLChildProperty(_CapsDomain, relative_xpath="./arch")
    features = XMLChildProperty(_CapsGuestFeatures, is_single=True)
    _machines = XMLChildProperty(_CapsMachine, relative_xpath="./arch")


    ###############
    # Public APIs #
    ###############

    def bestDomainType(self, dtype=None, machine=None):
        """
        Return the recommended domain for use if the user does not explicitly
        request one.
        """
        domains = []
        for d in self.domains:
            d.set_recommended_machine(None)

            if dtype and d.hypervisor_type != dtype.lower():
                continue
            if machine and machine not in d.machines:
                continue

            if machine:
                d.set_recommended_machine(machine)
            domains.append(d)

        if not domains:
            return None

        priority = ["kvm", "xen", "kqemu", "qemu"]

        for t in priority:
            for d in domains:
                if d.hypervisor_type == t:
                    return d

        # Fallback, just return last item in list
        return domains[-1]


############################
# Main capabilities object #
############################

class Capabilities(XMLBuilder):
    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)
        self._cpu_values = None

    _XML_ROOT_NAME = "capabilities"

    host = XMLChildProperty(_CapsHost, is_single=True)
    guests = XMLChildProperty(_CapsGuest)


    ###################
    # Private helpers #
    ###################

    def _is_xen(self):
        for g in self.guests:
            if g.os_type != "xen":
                continue

            for d in g.domains:
                if d.hypervisor_type == "xen":
                    return True

        return False


    ##############
    # Public API #
    ##############

    def no_install_options(self):
        """
        Return True if there are no install options available
        """
        for g in self.guests:
            if len(g.domains) > 0:
                return False

        return True

    def hw_virt_supported(self):
        """
        Return True if the machine supports hardware virtualization.

        For some cases (like qemu caps pre libvirt 0.7.4) this info isn't
        sufficiently provided, so we will return True in cases that we
        aren't sure.
        """
        # Obvious case of feature being specified
        if (self.host.cpu.has_feature("vmx") or
            self.host.cpu.has_feature("svm")):
            return True

        has_hvm_guests = False
        for g in self.guests:
            if g.os_type == "hvm":
                has_hvm_guests = True
                break

        # Xen seems to block the vmx/svm feature bits from cpuinfo?
        # so make sure no hvm guests are listed
        if self._is_xen() and has_hvm_guests:
            return True

        # If there is other features, but no virt bit, then HW virt
        # isn't supported
        if self.host.cpu.has_feature_block:
            return False

        # Xen caps have always shown this info, so if we didn't find any
        # features, the host really doesn't have the nec support
        if self._is_xen():
            return False

        # Otherwise, we can't be sure, because there was a period for along
        # time that qemu caps gave no indication one way or the other.
        return True

    def is_kvm_available(self):
        """
        Return True if kvm guests can be installed
        """
        for g in self.guests:
            if g.os_type != "hvm":
                continue

            for d in g.domains:
                if d.hypervisor_type == "kvm":
                    return True

        return False

    def is_xenner_available(self):
        """
        Return True if xenner install option is available
        """
        for g in self.guests:
            if g.os_type != "xen":
                continue

            for d in g.domains:
                if d.hypervisor_type == "kvm":
                    return True

        return False

    def is_bios_virt_disabled(self):
        """
        Try to determine if fullvirt may be disabled in the bios.

        Check is basically:
            - We support HW virt
            - We appear to be xen
            - There are no HVM install options

        We don't do this check for KVM, since no KVM options may mean
        KVM isn't installed or the module isn't loaded (and loading the
        module will give an appropriate error
        """
        if not self.hw_virt_supported():
            return False

        if not self._is_xen():
            return False

        for g in self.guests:
            if g.os_type == "hvm":
                return False

        return True

    def supports_pae(self):
        """
        Return True if capabilities report support for PAE
        """
        for g in self.guests:
            if g.features.pae:
                return True
        return False

    def get_cpu_values(self, conn, arch):
        if not arch:
            return []
        if self._cpu_values:
            return self._cpu_values.get_cpus(arch, conn)

        # Iterate over the available methods until a set of CPU models is found
        for mode in (_CPUAPIValues, _CPUMapFileValues):
            cpu_values = mode()
            cpus = cpu_values.get_cpus(arch, conn)
            if len(cpus) > 0:
                self._cpu_values = cpu_values
                return cpus

        return []


    ############################
    # Public XML building APIs #
    ############################

    def _guestForOSType(self, typ=None, arch=None):
        if self.host is None:
            return None

        archs = [arch]
        if arch is None:
            archs = [self.host.cpu.arch, None]

        for a in archs:
            for g in self.guests:
                if ((typ is None or g.os_type == typ) and
                    (a is None or g.arch == a)):
                    return g

    def guest_lookup(self, os_type=None, arch=None, typ=None, machine=None):
        """
        Simple virtualization availability lookup

        Convenience function for looking up 'Guest' and 'Domain' capabilities
        objects for the desired virt type. If type, arch, or os_type are none,
        we return the default virt type associated with those values. These are
        typically:

            - os_type : hvm, then xen
            - typ     : kvm over plain qemu
            - arch    : host arch over all others

        Otherwise the default will be the first listed in the capabilities xml.
        This function throws C{ValueError}s if any of the requested values are
        not found.

        @param typ: Virtualization type ('hvm', 'xen', ...)
        @param arch: Guest architecture ('x86_64', 'i686' ...)
        @param os_type: Hypervisor name ('qemu', 'kvm', 'xen', ...)
        @param machine: Optional machine type to emulate

        @returns: A (Capabilities Guest, Capabilities Domain) tuple
        """
        guest = self._guestForOSType(os_type, arch)
        if not guest:
            archstr = _("for arch '%s'") % arch
            if not arch:
                archstr = ""

            osstr = _("virtualization type '%s'") % os_type
            if not os_type:
                osstr = _("any virtualization options")

            raise ValueError(_("Host does not support %(virttype)s %(arch)s") %
                               {'virttype' : osstr, 'arch' : archstr})

        domain = guest.bestDomainType(dtype=typ, machine=machine)
        if domain is None:
            machinestr = " with machine '%s'" % machine
            if not machine:
                machinestr = ""
            raise ValueError(_("Host does not support domain type %(domain)s"
                               "%(machine)s for virtualization type "
                               "'%(virttype)s' arch '%(arch)s'") %
                               {'domain': typ, 'virttype': guest.os_type,
                                'arch': guest.arch, 'machine': machinestr})

        return (guest, domain)

    def build_virtinst_guest(self, conn, guest, domain):
        from .guest import Guest
        gobj = Guest(conn)
        gobj.type = domain.hypervisor_type
        gobj.os.os_type = guest.os_type
        gobj.os.arch = guest.arch
        gobj.os.loader = guest.loader
        gobj.emulator = domain.emulator
        gobj.os.machine = domain.get_recommended_machine(conn, guest)

        return gobj
