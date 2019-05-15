#
# Copyright 2014 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _BlkiotuneDevice(XMLBuilder):
    XML_NAME = "device"
    _XML_PROP_ORDER = ["path", "weight"]

    path = XMLProperty("./path")
    weight = XMLProperty("./weight")


class DomainBlkiotune(XMLBuilder):
    """
    Class for generating <blkiotune> XML
    """

    XML_NAME = "blkiotune"
    _XML_PROP_ORDER = ["weight"]

    weight = XMLProperty("./weight", is_int=True)
    devices = XMLChildProperty(_BlkiotuneDevice)
