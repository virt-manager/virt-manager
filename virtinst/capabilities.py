#
# Some code for parsing libvirt's capabilities XML
#
# Copyright 2007, 2012-2014 Red Hat, Inc.
# Mark McLoughlin <markmc@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import pwd

from .domain import DomainCpu
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


###################################
# capabilities host <cpu> parsing #
###################################

class _CapsCPU(DomainCpu):
    arch = XMLProperty("./arch")


###########################
# Caps <topology> parsers #
###########################

class _CapsTopologyCPU(XMLBuilder):
    XML_NAME = "cpu"
    id = XMLProperty("./@id")


class _TopologyCell(XMLBuilder):
    XML_NAME = "cell"
    cpus = XMLChildProperty(_CapsTopologyCPU, relative_xpath="./cpus")


class _CapsTopology(XMLBuilder):
    XML_NAME = "topology"
    cells = XMLChildProperty(_TopologyCell, relative_xpath="./cells")


######################################
# Caps <host> and <secmodel> parsers #
######################################

class _CapsSecmodelBaselabel(XMLBuilder):
    XML_NAME = "baselabel"
    type = XMLProperty("./@type")
    content = XMLProperty(".")


class _CapsSecmodel(XMLBuilder):
    XML_NAME = "secmodel"
    model = XMLProperty("./model")
    baselabels = XMLChildProperty(_CapsSecmodelBaselabel)


class _CapsHost(XMLBuilder):
    XML_NAME = "host"
    secmodels = XMLChildProperty(_CapsSecmodel)
    cpu = XMLChildProperty(_CapsCPU, is_single=True)
    topology = XMLChildProperty(_CapsTopology, is_single=True)

    def get_qemu_baselabel(self):
        for secmodel in self.secmodels:
            if secmodel.model != "dac":
                continue

            label = None
            for baselabel in secmodel.baselabels:
                if baselabel.type in ["qemu", "kvm"]:
                    label = baselabel.content
                    break
            if not label:
                continue

            # XML we are looking at is like:
            #
            # <secmodel>
            #   <model>dac</model>
            #   <doi>0</doi>
            #   <baselabel type='kvm'>+107:+107</baselabel>
            #   <baselabel type='qemu'>+107:+107</baselabel>
            # </secmodel>
            try:
                uid = int(label.split(":")[0].replace("+", ""))
                user = pwd.getpwuid(uid)[0]
                return user, uid
            except Exception:
                logging.debug("Exception parsing qemu dac baselabel=%s",
                    label, exc_info=True)
        return None, None


################################
# <guest> and <domain> parsers #
################################

class _CapsMachine(XMLBuilder):
    XML_NAME = "machine"
    name = XMLProperty(".")
    canonical = XMLProperty("./@canonical")


class _CapsDomain(XMLBuilder):
    XML_NAME = "domain"
    hypervisor_type = XMLProperty("./@type")
    emulator = XMLProperty("./emulator")
    machines = XMLChildProperty(_CapsMachine)


class _CapsGuestFeatures(XMLBuilder):
    XML_NAME = "features"

    pae = XMLProperty("./pae", is_bool=True)
    acpi = XMLProperty("./acpi/@default", is_onoff=True)
    apic = XMLProperty("./apic/@default", is_onoff=True)


class _CapsGuest(XMLBuilder):
    XML_NAME = "guest"

    os_type = XMLProperty("./os_type")
    arch = XMLProperty("./arch/@name")
    loader = XMLProperty("./arch/loader")
    emulator = XMLProperty("./arch/emulator")

    domains = XMLChildProperty(_CapsDomain, relative_xpath="./arch")
    features = XMLChildProperty(_CapsGuestFeatures, is_single=True)
    machines = XMLChildProperty(_CapsMachine, relative_xpath="./arch")


    ###############
    # Public APIs #
    ###############

    def all_machine_names(self, domain):
        """
        Return all machine string names, including canonical aliases for
        the guest+domain combo
        """
        mobjs = (domain and domain.machines) or self.machines
        ret = []
        for m in mobjs:
            ret.append(m.name)
            if m.canonical:
                ret.append(m.canonical)
        return ret

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
    def __init__(self, conn, guest, domain):
        self.conn = conn
        self.guest = guest
        self.domain = domain

        self.hypervisor_type = self.domain.hypervisor_type
        self.os_type = self.guest.os_type
        self.arch = self.guest.arch
        self.loader = self.guest.loader

        self.emulator = self.domain.emulator or self.guest.emulator
        self.machines = self.guest.all_machine_names(self.domain)


class Capabilities(XMLBuilder):
    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)
        self._cpu_models_cache = {}

    XML_NAME = "capabilities"

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

    def _guestForOSType(self, os_type, arch):
        if self.host is None:
            return None

        archs = [arch]
        if arch is None:
            archs = [self.host.cpu.arch, None]

        for a in archs:
            for g in self.guests:
                if ((os_type is None or g.os_type == os_type) and
                    (a is None or g.arch == a)):
                    return g

    def _bestDomainType(self, guest, dtype, machine):
        """
        Return the recommended domain for use if the user does not explicitly
        request one.
        """
        domains = []
        for d in guest.domains:
            if dtype and d.hypervisor_type != dtype.lower():
                continue
            if machine and machine not in guest.all_machine_names(d):
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

        :param typ: Virtualization type ('hvm', 'xen', ...)
        :param arch: Guest architecture ('x86_64', 'i686' ...)
        :param os_type: Hypervisor name ('qemu', 'kvm', 'xen', ...)
        :param machine: Optional machine type to emulate

        :returns: A _CapsInfo object containing the found guest and domain
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

        domain = self._bestDomainType(guest, typ, machine)
        if domain is None:
            machinestr = " with machine '%s'" % machine
            if not machine:
                machinestr = ""
            raise ValueError(_("Host does not support domain type %(domain)s"
                               "%(machine)s for virtualization type "
                               "'%(virttype)s' arch '%(arch)s'") %
                               {'domain': typ, 'virttype': guest.os_type,
                                'arch': guest.arch, 'machine': machinestr})

        capsinfo = _CapsInfo(self.conn, guest, domain)
        return capsinfo
