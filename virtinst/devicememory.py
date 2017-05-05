#
# Copyright 2017 Red Hat, Inc.
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


from .device import VirtualDevice
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class VirtualMemoryTarget(XMLBuilder):
    _XML_ROOT_NAME = "target"

    size = XMLProperty("./size", is_int=True)
    node = XMLProperty("./node", is_int=True)
    label_size = XMLProperty("./label/size", is_int=True)


class VirtualMemorySource(XMLBuilder):
    _XML_ROOT_NAME = "source"

    pagesize = XMLProperty("./pagesize", is_int=True)
    nodemask = XMLProperty("./nodemask")
    path = XMLProperty("./path")


class VirtualMemoryDevice(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_MEMORY

    MODEL_DIMM = "dimm"
    MODEL_NVDIMM = "nvdimm"
    models = [MODEL_DIMM, MODEL_NVDIMM]

    ACCESS_SHARED = "shared"
    ACCESS_PRIVATE = "private"
    accesses = [ACCESS_SHARED, ACCESS_PRIVATE]

    model = XMLProperty("./@model")
    access = XMLProperty("./@access")

    source = XMLChildProperty(VirtualMemorySource, is_single=True)
    target = XMLChildProperty(VirtualMemoryTarget, is_single=True)


VirtualMemoryDevice.register_type()
