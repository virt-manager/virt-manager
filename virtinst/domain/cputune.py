# Copyright (c) 2018 Oracle and/or its affiliates. All rights reserved.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


class _VCPUPin(XMLBuilder):
    """
    Class for generating <cputune> child <vcpupin> XML
    """
    XML_NAME = "vcpupin"
    _XML_PROP_ORDER = ["vcpu", "cpuset"]

    vcpu = XMLProperty("./@vcpu", is_int=True)
    cpuset = XMLProperty("./@cpuset")


class DomainCputune(XMLBuilder):
    """
    Class for generating <cpu> XML
    """
    XML_NAME = "cputune"
    vcpus = XMLChildProperty(_VCPUPin)
