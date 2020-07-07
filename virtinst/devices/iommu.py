#
# Copyright 2020 Oracle Oracle and/or its affiliates. All rights reserved.
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

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceIommu(Device):
    XML_NAME = "iommu"

    model = XMLProperty("./@model")
    aw_bits = XMLProperty("./driver/@aw_bits", is_int=True)
    intremap = XMLProperty("./driver/@intremap", is_onoff=True)
    caching_mode = XMLProperty("./driver/@caching_mode", is_onoff=True)
    eim = XMLProperty("./driver/@eim", is_onoff=True)
    iotlb = XMLProperty("./driver/@iotlb", is_onoff=True)
