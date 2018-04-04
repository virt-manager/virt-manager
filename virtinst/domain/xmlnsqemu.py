# Copyright 2017 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _XMLNSQemuArg(XMLBuilder):
    XML_NAME = "qemu:arg"

    value = XMLProperty("./@value")


class _XMLNSQemuEnv(XMLBuilder):
    XML_NAME = "qemu:env"

    name = XMLProperty("./@name")
    value = XMLProperty("./@value")


class DomainXMLNSQemu(XMLBuilder):
    """
    Class for generating <qemu:commandline> XML
    """
    XML_NAME = "qemu:commandline"
    _XML_PROP_ORDER = ["args", "envs"]

    args = XMLChildProperty(_XMLNSQemuArg)
    envs = XMLChildProperty(_XMLNSQemuEnv)
