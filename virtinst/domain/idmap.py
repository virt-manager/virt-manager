#
# Copyright 2014 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainIdmap(XMLBuilder):
    """
    Class for generating user namespace related XML
    """
    XML_NAME = "idmap"
    _XML_PROP_ORDER = ["uid_start", "uid_target", "uid_count",
            "gid_start", "gid_target", "gid_count"]

    uid_start = XMLProperty("./uid/@start", is_int=True)
    uid_target = XMLProperty("./uid/@target", is_int=True)
    uid_count = XMLProperty("./uid/@count", is_int=True)

    gid_start = XMLProperty("./gid/@start", is_int=True)
    gid_target = XMLProperty("./gid/@target", is_int=True)
    gid_count = XMLProperty("./gid/@count", is_int=True)
