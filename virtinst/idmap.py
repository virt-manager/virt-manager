#
# Copyright 2014 Fujitsu Limited.
# Chen Hanxiao <chenhanxiao at cn.fujitsu.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

from .xmlbuilder import XMLBuilder, XMLProperty


class IdMap(XMLBuilder):
    """
    Class for generating user namespace related XML
    """
    _XML_ROOT_NAME = "idmap"
    _XML_PROP_ORDER = ["uid_start", "uid_target", "uid_count",
            "gid_start", "gid_target", "gid_count"]

    uid_start = XMLProperty("./uid/@start", is_int=True)
    uid_target = XMLProperty("./uid/@target", is_int=True)
    uid_count = XMLProperty("./uid/@count", is_int=True)

    gid_start = XMLProperty("./gid/@start", is_int=True)
    gid_target = XMLProperty("./gid/@target", is_int=True)
    gid_count = XMLProperty("./gid/@count", is_int=True)
