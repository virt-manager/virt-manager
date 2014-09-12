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


class DomainMemorytune(XMLBuilder):
    """
    Class for generating <memtune> XML
    """

    _XML_ROOT_NAME = "memtune"
    _XML_PROP_ORDER = ["hard_limit", "soft_limit", "swap_hard_limit",
            "min_guarantee"]

    hard_limit = XMLProperty("./hard_limit", is_int=True)
    soft_limit = XMLProperty("./soft_limit", is_int=True)
    swap_hard_limit = XMLProperty("./swap_hard_limit", is_int=True)
    min_guarantee = XMLProperty("./min_guarantee", is_int=True)
