#
# Copyright 2014 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainMemtune(XMLBuilder):
    """
    Class for generating <memtune> XML
    """

    XML_NAME = "memtune"
    _XML_PROP_ORDER = ["hard_limit", "soft_limit", "swap_hard_limit",
            "min_guarantee"]

    hard_limit = XMLProperty("./hard_limit", is_int=True)
    soft_limit = XMLProperty("./soft_limit", is_int=True)
    swap_hard_limit = XMLProperty("./swap_hard_limit", is_int=True)
    min_guarantee = XMLProperty("./min_guarantee", is_int=True)
