#
# Copyright (c) 2018 Oracle and/or its affiliates. All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; If not, see <http://www.gnu.org/licenses/>.

from .xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


class _VCPUPin(XMLBuilder):
    """
    Class for generating <cputune> child <vcpupin> XML
    """
    _XML_ROOT_NAME = "vcpupin"
    _XML_PROP_ORDER = ["vcpu", "cpuset"]

    vcpu = XMLProperty("./@vcpu", is_int=True)
    cpuset = XMLProperty("./@cpuset")


class CPUTune(XMLBuilder):
    """
    Class for generating <cpu> XML
    """
    _XML_ROOT_NAME = "cputune"
    vcpus = XMLChildProperty(_VCPUPin)
    def add_vcpu(self):
        obj = _VCPUPin(self.conn)
        self.add_child(obj)
        return obj
