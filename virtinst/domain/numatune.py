#
# Copyright 2010, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


class _Numatune(XMLBuilder):

    XML_NAME = "memnode"
    _XML_PROP_ORDER = ["cellid", "mode", "nodeset"]

    cellid = XMLProperty("./@cellid", is_int=True)
    mode = XMLProperty("./@mode")
    nodeset = XMLProperty("./@nodeset")


class DomainNumatune(XMLBuilder):
    """
    Class for generating <numatune> XML
    """
    XML_NAME = "numatune"
    _XML_PROP_ORDER = ["memory_mode", "memory_nodeset", "memory_placement", "memnode"]

    memory_nodeset = XMLProperty("./memory/@nodeset")
    memory_mode = XMLProperty("./memory/@mode")
    memory_placement = XMLProperty("./memory/@placement")
    memnode = XMLChildProperty(_Numatune)
