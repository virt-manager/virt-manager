#
# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _DomainVCPU(XMLBuilder):
    XML_NAME = "vcpu"
    _XML_PROP_ORDER = ["id", "enabled", "hotpluggable", "order"]

    id = XMLProperty("./@id", is_int=True)
    enabled = XMLProperty("./@enabled", is_yesno=True)
    hotpluggable = XMLProperty("./@hotpluggable", is_yesno=True)
    order = XMLProperty("./@order", is_int=True)


class DomainVCPUs(XMLBuilder):
    """
    Class for generating <vcpus> XML
    """
    XML_NAME = "vcpus"

    vcpu = XMLChildProperty(_DomainVCPU)
