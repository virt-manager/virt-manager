#
# Copyright 2014 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _HugepagesPage(XMLBuilder):
    """
    Class representing <memoryBacking><hugepages><page> elements
    """
    XML_NAME = "page"

    size = XMLProperty("./@size")
    unit = XMLProperty("./@unit")
    nodeset = XMLProperty("./@nodeset")


class DomainMemoryBacking(XMLBuilder):
    """
    Class for generating <memoryBacking> XML
    """

    XML_NAME = "memoryBacking"
    _XML_PROP_ORDER = ["hugepages", "nosharepages", "locked", "pages"]

    hugepages = XMLProperty("./hugepages", is_bool=True)
    nosharepages = XMLProperty("./nosharepages", is_bool=True)
    locked = XMLProperty("./locked", is_bool=True)
    discard = XMLProperty("./discard", is_bool=True)
    access_mode = XMLProperty("./access/@mode")
    source_type = XMLProperty("./source/@type")
    allocation_mode = XMLProperty("./allocation/@mode")
    allocation_threads = XMLProperty("./allocation/@threads", is_int=True)

    pages = XMLChildProperty(_HugepagesPage, relative_xpath="./hugepages")
