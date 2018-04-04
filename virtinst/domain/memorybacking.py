#
# Copyright 2014 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainMemoryBacking(XMLBuilder):
    """
    Class for generating <memoryBacking> XML
    """

    XML_NAME = "memoryBacking"
    _XML_PROP_ORDER = ["hugepages", "nosharepages", "locked"]

    hugepages = XMLProperty("./hugepages", is_bool=True)
    page_size = XMLProperty("./hugepages/page/@size")
    page_unit = XMLProperty("./hugepages/page/@unit")
    page_nodeset = XMLProperty("./hugepages/page/@nodeset")
    nosharepages = XMLProperty("./nosharepages", is_bool=True)
    locked = XMLProperty("./locked", is_bool=True)
