#
# Copyright 2010, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

from .xmlbuilder import XMLBuilder, XMLProperty


class DomainFeatures(XMLBuilder):
    """
    Class for generating <features> XML
    """
    _XML_ROOT_NAME = "features"
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

    hyperv_vapic = XMLProperty("./hyperv/vapic/@state", is_onoff=True)
    hyperv_relaxed = XMLProperty("./hyperv/relaxed/@state", is_onoff=True)
    hyperv_spinlocks = XMLProperty("./hyperv/spinlocks/@state", is_onoff=True)
    hyperv_spinlocks_retries = XMLProperty("./hyperv/spinlocks/@retries",
                                           is_int=True)

    vmport = XMLProperty("./vmport/@state", is_onoff=True,
                         default_name="default", default_cb=lambda s: False)
    kvm_hidden = XMLProperty("./kvm/hidden/@state", is_onoff=True)
    pvspinlock = XMLProperty("./pvspinlock/@state", is_onoff=True)
