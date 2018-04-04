#
# Copyright 2010, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

    acpi = XMLProperty("./acpi", is_bool=True,
                       default_name="default", default_cb=lambda s: False)
    apic = XMLProperty("./apic", is_bool=True,
                       default_name="default", default_cb=lambda s: False)
    pae = XMLProperty("./pae", is_bool=True,
                       default_name="default", default_cb=lambda s: False)
    gic_version = XMLProperty("./gic/@version")

    hap = XMLProperty("./hap", is_bool=True)
    viridian = XMLProperty("./viridian", is_bool=True)
    privnet = XMLProperty("./privnet", is_bool=True)

    pmu = XMLProperty("./pmu/@state", is_onoff=True)
    eoi = XMLProperty("./apic/@eoi", is_onoff=True)

    hyperv_reset = XMLProperty("./hyperv/reset/@state", is_onoff=True)
    hyperv_vapic = XMLProperty("./hyperv/vapic/@state", is_onoff=True)
    hyperv_relaxed = XMLProperty("./hyperv/relaxed/@state", is_onoff=True)
    hyperv_spinlocks = XMLProperty("./hyperv/spinlocks/@state", is_onoff=True)
    hyperv_spinlocks_retries = XMLProperty("./hyperv/spinlocks/@retries",
                                           is_int=True)
    hyperv_synic = XMLProperty("./hyperv/synic/@state", is_onoff=True)

    vmport = XMLProperty("./vmport/@state", is_onoff=True,
                         default_name="default", default_cb=lambda s: False)
    kvm_hidden = XMLProperty("./kvm/hidden/@state", is_onoff=True)
    pvspinlock = XMLProperty("./pvspinlock/@state", is_onoff=True)

    smm = XMLProperty("./smm/@state", is_onoff=True)
    vmcoreinfo = XMLProperty("./vmcoreinfo", is_bool=True,
                       default_name="default", default_cb=lambda s: False)
