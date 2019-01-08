# Copyright 2017 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


XMLBuilder.register_namespace(
        "libosinfo", "http://libosinfo.org/xmlns/libvirt/domain/1.0")


class _XMLNSLibosinfo(XMLBuilder):
    XML_NAME = "libosinfo:libosinfo"

    os_id = XMLProperty("./libosinfo:os/@id")


class DomainMetadata(XMLBuilder):
    """
    Class for generating <metadata> XML
    """
    XML_NAME = "metadata"

    libosinfo = XMLChildProperty(_XMLNSLibosinfo, is_single=True)
