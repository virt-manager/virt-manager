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

import logging

from .cpu import CPU as DomainCPU
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


###################################
# capabilities host <cpu> parsing #
###################################

class _CapsCPU(DomainCPU):
    arch = XMLProperty("./arch")

    # capabilities used to just expose these properties as bools
    _svm_bool = XMLProperty("./features/svm", is_bool=True)
    _vmx_bool = XMLProperty("./features/vmx", is_bool=True)


    ##############
    # Public API #
    ##############

    def has_feature(self, name):
        if name == "svm" and self._svm_bool:
            return True
        if name == "vmx" and self._vmx_bool:
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

    _XML_ROOT_NAME = "domain"
    hypervisor_type = XMLProperty("./@type")
    emulator = XMLProperty("./emulator")
    _machines = XMLChildProperty(_CapsMachine)


class _CapsGuestFeatures(XMLBuilder):
    _XML_ROOT_NAME = "features"

    pae = XMLProperty("./pae", is_bool=True)
    acpi = XMLProperty("./acpi/@default", is_onoff=True)
    apic = XMLProperty("./apic/@default", is_onoff=True)


class _CapsGuest(XMLBuilder):
    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)

        machines = []
        for m in self._machines:
            machines.append(m.name)
            if m.canonical:
                machines.append(m.canonical)

        for d in self.domains:
            if not d.emulator:
                d.emulator = self._emulator
            if not d.machines:
                d.machines = machines


    _XML_ROOT_NAME = "guest"

    os_type = XMLProperty("./os_type")
    arch = XMLProperty("./arch/@name")
    loader = XMLProperty("./arch/loader")
    _emulator = XMLProperty("./arch/emulator")

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
            if dtype and d.hypervisor_type != dtype.lower():
                continue
            if machine and machine not in d.machines:
                continue

            domains.append(d)

        if not domains:
            return None

        priority = ["kvm", "xen", "qemu"]

        for t in priority:
            for d in domains:
                if d.hypervisor_type == t:
                    return d

        # Fallback, just return last item in list
        return domains[-1]

    def has_install_options(self):
        """
        Return True if there are any install options available
        """
        return bool(len(self.domains) > 0)

    def is_kvm_available(self):
        """
        Return True if kvm guests can be installed
        """
        if self.os_type != "hvm":
            return False

        for d in self.domains:
            if d.hypervisor_type == "kvm":
                return True

        return False

    def supports_pae(self):
        """
        Return True if capabilities report support for PAE
        """
        return bool(self.features.pae)

    def supports_acpi(self):
        """
        Return Tree if capabilities report support for ACPI
        """
        return bool(self.features.acpi)

    def supports_apic(self):
        """
        Return Tree if capabilities report support for APIC
        """
        return bool(self.features.apic)


############################
# Main capabilities object #
############################

class _CapsInfo(object):
    """
    Container object to hold the results of guest_lookup, so users don't
    need to juggle two objects
    """
    def __init__(self, conn, guest, domain, requested_machine):
        self.conn = conn
        self.guest = guest
        self.domain = domain
        self._requested_machine = requested_machine

        self.hypervisor_type = self.domain.hypervisor_type
        self.os_type = self.guest.os_type
        self.arch = self.guest.arch
        self.loader = self.guest.loader

        self.emulator = self.domain.emulator
        self.machines = self.domain.machines[:]

    def get_recommended_machine(self):
        """
        Return the recommended machine type.

        However, if the user already requested an explicit machine type,
        via guest_lookup, return that instead.
        """
        if self._requested_machine:
            return self._requested_machine

        # For any other HV just let libvirt get us the default, these
        # are the only ones we've tested.
        if (not self.conn.is_test() and
            not self.conn.is_qemu() and
            not self.conn.is_xen()):
            return None

        if self.conn.is_xen() and len(self.machines):
            return self.machines[0]

        if (self.arch in ["ppc64", "ppc64le"] and
            "pseries" in self.machines):
            return "pseries"

        if self.arch in ["armv7l", "aarch64"]:
            if "virt" in self.machines:
                return "virt"
            if "vexpress-a15" in self.machines:
                return "vexpress-a15"

        if self.arch in ["s390x"]:
            if "s390-ccw-virtio" in self.machines:
                return "s390-ccw-virtio"

        return None


class Capabilities(XMLBuilder):
    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)
        self._cpu_models_cache = {}

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

    def get_cpu_values(self, arch):
        if not arch:
            return []
        if not self.conn.check_support(self.conn.SUPPORT_CONN_CPU_MODEL_NAMES):
            return []
        if arch in self._cpu_models_cache:
            return self._cpu_models_cache[arch]

        try:
            names = self.conn.getCPUModelNames(arch, 0)
            if names == -1:
                names = []
        except Exception as e:
            logging.debug("Error fetching CPU model names for arch=%s: %s",
                          arch, e)
            names = []

        self._cpu_models_cache[arch] = names
        return names


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

        @returns: A _CapsInfo object containing the found guest and domain
        """
        # F22 libxl xen still puts type=linux in the XML, so we need
        # to handle it for caps lookup
        if os_type == "linux":
            os_type = "xen"

        guest = self._guestForOSType(os_type, arch)
        if not guest:
            archstr = _("for arch '%s'") % arch
            if not arch:
                archstr = ""

            osstr = _("virtualization type '%s'") % os_type
            if not os_type:
                osstr = _("any virtualization options")

            raise ValueError(_("Host does not support %(virttype)s %(arch)s") %
                               {'virttype': osstr, 'arch': archstr})

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

        capsinfo = _CapsInfo(self.conn, guest, domain, machine)
        return capsinfo

    def build_virtinst_guest(self, capsinfo):
        """
        Fill in a new Guest() object from the results of guest_lookup
        """
        from .guest import Guest
        gobj = Guest(self.conn)
        gobj.type = capsinfo.hypervisor_type
        gobj.os.os_type = capsinfo.os_type
        gobj.os.arch = capsinfo.arch
        gobj.os.loader = capsinfo.loader
        gobj.emulator = capsinfo.emulator

        gobj.os.machine = capsinfo.get_recommended_machine()

        gobj.capsinfo = capsinfo

        return gobj

    def lookup_virtinst_guest(self, *args, **kwargs):
        """
        Call guest_lookup and pass the results to build_virtinst_guest.

        This is a shortcut for API users that don't need to do anything
        with the output from guest_lookup
        """
        capsinfo = self.guest_lookup(*args, **kwargs)
        return self.build_virtinst_guest(capsinfo)
