#
# Copyright 2010, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainNumatune(XMLBuilder):
    """
    Class for generating <numatune> XML
    """
    XML_NAME = "numatune"
    _XML_PROP_ORDER = ["memory_mode", "memory_nodeset"]

    memory_nodeset = XMLProperty("./memory/@nodeset")
    memory_mode = XMLProperty("./memory/@mode")
