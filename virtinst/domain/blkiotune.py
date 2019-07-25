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
    read_bytes_sec = XMLProperty("./read_bytes_sec", is_int=True)
    write_bytes_sec = XMLProperty("./write_bytes_sec", is_int=True)
    read_iops_sec = XMLProperty("./read_iops_sec", is_int=True)
    write_iops_sec = XMLProperty("./write_iops_sec", is_int=True)


class DomainBlkiotune(XMLBuilder):
    """
    Class for generating <blkiotune> XML
    """

    XML_NAME = "blkiotune"
    _XML_PROP_ORDER = ["weight"]

    weight = XMLProperty("./weight", is_int=True)
    devices = XMLChildProperty(_BlkiotuneDevice)
