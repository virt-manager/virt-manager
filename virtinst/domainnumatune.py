#
# Copyright 2010, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

import re

from .xmlbuilder import XMLBuilder, XMLProperty


def get_phy_cpus(conn):
    """
    Get number of physical CPUs.
    """
    hostinfo = conn.getInfo()
    pcpus = hostinfo[4] * hostinfo[5] * hostinfo[6] * hostinfo[7]
    return pcpus


class DomainNumatune(XMLBuilder):
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


    MEMORY_MODES = ["interleave", "strict", "preferred"]

    _XML_ROOT_NAME = "numatune"
    _XML_PROP_ORDER = ["memory_mode", "memory_nodeset"]

    memory_nodeset = XMLProperty("./memory/@nodeset")
    memory_mode = XMLProperty("./memory/@mode")
