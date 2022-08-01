#
# Some code for parsing libvirt's capabilities XML
#
# Copyright 2007, 2012-2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import pwd

from .logger import log
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


###################################
# capabilities host <cpu> parsing #
###################################

class _CapsCPU(XMLBuilder):
    XML_NAME = "cpu"
    arch = XMLProperty("./arch")
    model = XMLProperty("./model")


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
                continue  # pragma: no cover

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
                log.debug("Exception parsing qemu dac baselabel=%s",
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
        the guest+domain combo but avoiding duplicates
        """
        mobjs = (domain and domain.machines) or self.machines
        ret = []
        for m in mobjs:
            ret.append(m.name)
            if m.canonical and m.canonical not in ret:
                ret.append(m.canonical)
        return ret

    def is_machine_alias(self, domain, src, tgt):
        """
        Determine if machine @src is an alias for machine @tgt
        """
        mobjs = (domain and domain.machines) or self.machines
        for m in mobjs:
            if m.name == src and m.canonical == tgt:
                return True
        return False

    def is_kvm_available(self):
        """
        Return True if kvm guests can be installed
        """
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

    def is_machine_alias(self, src, tgt):
        return self.guest.is_machine_alias(self.domain, src, tgt)


class Capabilities(XMLBuilder):
    def __init__(self, *args, **kwargs):
        XMLBuilder.__init__(self, *args, **kwargs)
        self._cpu_models_cache = {}

    XML_NAME = "capabilities"

    host = XMLChildProperty(_CapsHost, is_single=True)
    guests = XMLChildProperty(_CapsGuest)


    ############################
    # Public XML building APIs #
    ############################

    def _guestForOSType(self, os_type, arch):
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

    def has_install_options(self):
        """
        Return True if there are any install options available
        """
        for guest in self.guests:
            if guest.domains:
                return True
        return False

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
            if arch and os_type:
                msg = (_("Host does not support virtualization type "
                         "'%(virttype)s' for architecture '%(arch)s'") %
                         {'virttype': os_type, 'arch': arch})
            elif arch:
                msg = (_("Host does not support any virtualization options "
                         "for architecture '%(arch)s'") %
                         {'arch': arch})
            elif os_type:
                msg = (_("Host does not support virtualization type "
                         "'%(virttype)s'") %
                         {'virttype': os_type})
            else:
                msg = _("Host does not support any virtualization options")
            raise ValueError(msg)

        domain = self._bestDomainType(guest, typ, machine)
        if domain is None:
            if machine:
                msg = (_("Host does not support domain type %(domain)s with "
                         "machine '%(machine)s' for virtualization type "
                         "'%(virttype)s' with architecture '%(arch)s'") %
                         {'domain': typ, 'virttype': guest.os_type,
                         'arch': guest.arch, 'machine': machine})
            else:
                msg = (_("Host does not support domain type %(domain)s for "
                         "virtualization type '%(virttype)s' with "
                         "architecture '%(arch)s'") %
                         {'domain': typ, 'virttype': guest.os_type,
                         'arch': guest.arch})
            raise ValueError(msg)

        capsinfo = _CapsInfo(self.conn, guest, domain)
        return capsinfo
