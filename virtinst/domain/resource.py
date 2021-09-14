#
# Copyright 2014 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainResource(XMLBuilder):
    """
    Class for generating <resource> XML
    """

    XML_NAME = "resource"
    _XML_PROP_ORDER = ["partition", "fibrechannel_appid"]

    partition = XMLProperty("./partition")
    fibrechannel_appid = XMLProperty("./fibrechannel/@appid")
