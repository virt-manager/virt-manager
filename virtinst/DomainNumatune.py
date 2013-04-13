#
# Copyright 2010  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

import re

from virtinst import XMLBuilderDomain
from virtinst.XMLBuilderDomain import _xml_property


def get_phy_cpus(conn):
    """
    Get number of physical CPUs.
    """
    hostinfo = conn.getInfo()
    pcpus = hostinfo[4] * hostinfo[5] * hostinfo[6] * hostinfo[7]
    return pcpus


class DomainNumatune(XMLBuilderDomain.XMLBuilderDomain):
    """
    Class for generating <numatune> XML
    """

    @staticmethod
    def validate_cpuset(conn, val):
        if val is None or val == "":
            return

        if not isinstance(val, str) or len(val) == 0:
            raise ValueError(_("cpuset must be string"))
        if re.match("^[0-9,-^]*$", val) is None:
            raise ValueError(_("cpuset can only contain numeric, ',', '^', or "
                               "'-' characters"))

        pcpus = get_phy_cpus(conn)
        for c in val.split(','):
            # Redundant commas
            if not c:
                continue

            if "-" in c:
                (x, y) = c.split('-', 1)
                x = int(x)
                y = int(y)
                if x > y:
                    raise ValueError(_("cpuset contains invalid format."))
                if x >= pcpus or y >= pcpus:
                    raise ValueError(_("cpuset's pCPU numbers must be less "
                                       "than pCPUs."))
            else:
                if c.startswith("^"):
                    c = c[1:]
                c = int(c)

                if c >= pcpus:
                    raise ValueError(_("cpuset's pCPU numbers must be less "
                                       "than pCPUs."))

    @staticmethod
    def cpuset_str_to_tuple(conn, cpuset):
        DomainNumatune.validate_cpuset(conn, cpuset)
        pinlist = [False] * get_phy_cpus(conn)

        entries = cpuset.split(",")
        for e in entries:
            series = e.split("-", 1)

            if len(series) == 1:
                pinlist[int(series[0])] = True
                continue

            start = int(series[0])
            end = int(series[1])

            for i in range(start, end + 1):
                pinlist[i] = True

        return tuple(pinlist)

    _dumpxml_xpath = "/domain/numatune"

    MEMORY_MODES = ["interleave", "strict", "preferred"]

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        self._memory_nodeset = None
        self._memory_mode = None

        XMLBuilderDomain.XMLBuilderDomain.__init__(self, conn, parsexml,
                                                   parsexmlnode, caps)
        if self._is_parse():
            return

    def _get_memory_nodeset(self):
        return self._memory_nodeset
    def _set_memory_nodeset(self, val):
        self._memory_nodeset = val
    memory_nodeset = _xml_property(_get_memory_nodeset,
                                   _set_memory_nodeset,
                                   xpath="./numatune/memory/@nodeset")

    def _get_memory_mode(self):
        return self._memory_mode
    def _set_memory_mode(self, val):
        self._memory_mode = val
    memory_mode = _xml_property(_get_memory_mode,
                                _set_memory_mode,
                                xpath="./numatune/memory/@mode")

    def _get_memory_xml(self):
        if not self.memory_nodeset:
            return ""

        xml = "    <memory"
        if self.memory_mode:
            xml += " mode='%s'" % self.memory_mode
        if self.memory_nodeset:
            xml += " nodeset='%s'" % self.memory_nodeset
        xml += "/>\n"
        return xml

    def _get_xml_config(self):
        mem_xml = self._get_memory_xml()
        if not mem_xml:
            return ""

        xml = "  <numatune>\n"
        xml += mem_xml
        xml += "  </numatune>"
        return xml
