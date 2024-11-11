#
# Copyright 2010, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainFeatures(XMLBuilder):
    """
    Class for generating <features> XML
    """
    XML_NAME = "features"
    _XML_PROP_ORDER = ["acpi", "apic", "pae", "gic_version"]

    acpi = XMLProperty("./acpi", is_bool=True)
    apic = XMLProperty("./apic", is_bool=True)
    pae = XMLProperty("./pae", is_bool=True)
    gic_version = XMLProperty("./gic/@version")

    hap = XMLProperty("./hap", is_bool=True)
    viridian = XMLProperty("./viridian", is_bool=True)
    privnet = XMLProperty("./privnet", is_bool=True)

    pmu = XMLProperty("./pmu/@state", is_onoff=True)
    eoi = XMLProperty("./apic/@eoi", is_onoff=True)

    hyperv_relaxed = XMLProperty("./hyperv/relaxed/@state", is_onoff=True)
    hyperv_vapic = XMLProperty("./hyperv/vapic/@state", is_onoff=True)
    hyperv_spinlocks = XMLProperty("./hyperv/spinlocks/@state", is_onoff=True)
    hyperv_spinlocks_retries = XMLProperty("./hyperv/spinlocks/@retries",
                                           is_int=True)
    hyperv_vpindex = XMLProperty("./hyperv/vpindex/@state", is_onoff=True)
    hyperv_runtime = XMLProperty("./hyperv/runtime/@state", is_onoff=True)
    hyperv_synic = XMLProperty("./hyperv/synic/@state", is_onoff=True)
    hyperv_stimer = XMLProperty("./hyperv/stimer/@state", is_onoff=True)
    hyperv_stimer_direct = XMLProperty("./hyperv/stimer/direct/@state", is_onoff=True)
    hyperv_reset = XMLProperty("./hyperv/reset/@state", is_onoff=True)
    hyperv_frequencies = XMLProperty("./hyperv/frequencies/@state", is_onoff=True)
    hyperv_reenlightenment = XMLProperty("./hyperv/reenlightenment/@state", is_onoff=True)
    hyperv_tlbflush = XMLProperty("./hyperv/tlbflush/@state", is_onoff=True)
    hyperv_ipi = XMLProperty("./hyperv/ipi/@state", is_onoff=True)
    hyperv_evmcs = XMLProperty("./hyperv/evmcs/@state", is_onoff=True)
    hyperv_avic = XMLProperty("./hyperv/avic/@state", is_onoff=True)

    vmport = XMLProperty("./vmport/@state", is_onoff=True)
    kvm_hidden = XMLProperty("./kvm/hidden/@state", is_onoff=True)
    kvm_hint_dedicated = XMLProperty("./kvm/hint-dedicated/@state", is_onoff=True)
    kvm_poll_control = XMLProperty("./kvm/poll-control/@state", is_onoff=True)
    kvm_pv_ipi = XMLProperty("./kvm/pv-ipi/@state", is_onoff=True)
    pvspinlock = XMLProperty("./pvspinlock/@state", is_onoff=True)

    smm = XMLProperty("./smm/@state", is_onoff=True)
    vmcoreinfo = XMLProperty("./vmcoreinfo/@state", is_onoff=True)
    ioapic_driver = XMLProperty("./ioapic/@driver")
    msrs_unknown = XMLProperty("./msrs/@unknown")


    ##################
    # Default config #
    ##################

    def _set_hyperv_defaults(self, guest):
        if not guest.hyperv_supported():
            return

        features = guest.lookup_domcaps().supported_hyperv_features()

        def _enable(name, requires=None, feature=None, value=True):
            feature = feature or name
            if feature not in features:
                return
            if getattr(self, f"hyperv_{name}") is not None:
                return
            if requires:
                for val in requires:
                    if getattr(self, f"hyperv_{val}") is not True:
                        return
            setattr(self, f"hyperv_{name}", value)

        _enable("relaxed")
        _enable("vapic")
        _enable("spinlocks")
        _enable("spinlocks_retries", feature="spinlocks", value=8191)
        _enable("vpindex")
        _enable("runtime")
        _enable("synic", requires=["vpindex"])

        # Both hyperv_stimer and hyperv_stimer requires hv-timer to be enabled
        # which libvirt hides under hypervclock timer.
        if guest.clock.has_hyperv_timer():
            _enable("stimer", requires=["vpindex", "synic"])
            _enable("stimer_direct", requires=["vpindex", "synic", "stimer"])

        _enable("frequencies")

        _enable("tlbflush", requires=["vpindex"])
        _enable("ipi", requires=["vpindex"])

        if guest.conn.caps.host.cpu.vendor == "Intel":
            _enable("evmcs", requires=["vapic"])

        if self.apic is True:
            _enable("avic")

    def set_defaults(self, guest):
        if guest.os.is_container():
            self.acpi = None
            self.apic = None
            self.pae = None
            if guest.is_full_os_container() and guest.type != "vz":
                self.privnet = True
            return

        if not guest.os.is_hvm():
            return

        capsinfo = guest.lookup_capsinfo()
        if self._prop_is_unset("acpi"):
            self.acpi = capsinfo.guest.supports_acpi()
        if self._prop_is_unset("apic"):
            self.apic = capsinfo.guest.supports_apic()
        if self._prop_is_unset("pae"):
            if (guest.os.is_hvm() and
                guest.type == "xen" and
                guest.os.arch == "x86_64"):
                self.pae = True
            else:
                self.pae = capsinfo.guest.supports_pae()

        self._set_hyperv_defaults(guest)
