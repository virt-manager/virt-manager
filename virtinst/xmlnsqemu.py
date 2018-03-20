# Copyright 2017 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2.
# See the COPYING file in the top-level directory.

from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _XMLNSQemuArg(XMLBuilder):
    _XML_ROOT_NAME = "qemu:arg"

    value = XMLProperty("./@value")


class _XMLNSQemuEnv(XMLBuilder):
    _XML_ROOT_NAME = "qemu:env"

    name = XMLProperty("./@name")
    value = XMLProperty("./@value")


class XMLNSQemu(XMLBuilder):
    """
    Class for generating <qemu:commandline> XML
    """
    _XML_ROOT_NAME = "qemu:commandline"
    _XML_PROP_ORDER = ["args", "envs"]

    args = XMLChildProperty(_XMLNSQemuArg)
    envs = XMLChildProperty(_XMLNSQemuEnv)
