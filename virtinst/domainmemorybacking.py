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


class DomainMemorybacking(XMLBuilder):
    """
    Class for generating <memoryBacking> XML
    """

    _XML_ROOT_NAME = "memoryBacking"
    _XML_PROP_ORDER = ["hugepages", "nosharepages", "locked"]

    hugepages = XMLProperty("./hugepages", is_bool=True)
    page_size = XMLProperty("./hugepages/page/@size")
    page_unit = XMLProperty("./hugepages/page/@unit")
    page_nodeset = XMLProperty("./hugepages/page/@nodeset")
    nosharepages = XMLProperty("./nosharepages", is_bool=True)
    locked = XMLProperty("./locked", is_bool=True)
