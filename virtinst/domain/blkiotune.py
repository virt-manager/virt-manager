#
# Copyright 2014 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This work is licensed under the GNU GPLv2.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainBlkiotune(XMLBuilder):
    """
    Class for generating <blkiotune> XML
    """

    _XML_ROOT_NAME = "blkiotune"
    _XML_PROP_ORDER = ["weight", "device_path", "device_weight"]

    weight = XMLProperty("./weight", is_int=True)
    device_path = XMLProperty("./device/path")
    device_weight = XMLProperty("./device/weight", is_int=True)
