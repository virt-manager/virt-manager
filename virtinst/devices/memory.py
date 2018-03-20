#
# Copyright 2017 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2.
# See the COPYING file in the top-level directory.


from .device import Device
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _DeviceMemoryTarget(XMLBuilder):
    _XML_ROOT_NAME = "target"

    size = XMLProperty("./size", is_int=True)
    node = XMLProperty("./node", is_int=True)
    label_size = XMLProperty("./label/size", is_int=True)


class _DeviceMemorySource(XMLBuilder):
    _XML_ROOT_NAME = "source"

    pagesize = XMLProperty("./pagesize", is_int=True)
    nodemask = XMLProperty("./nodemask")
    path = XMLProperty("./path")


class DeviceMemory(Device):
    virtual_device_type = Device.DEVICE_MEMORY

    MODEL_DIMM = "dimm"
    MODEL_NVDIMM = "nvdimm"
    models = [MODEL_DIMM, MODEL_NVDIMM]

    ACCESS_SHARED = "shared"
    ACCESS_PRIVATE = "private"
    accesses = [ACCESS_SHARED, ACCESS_PRIVATE]

    model = XMLProperty("./@model")
    access = XMLProperty("./@access")

    source = XMLChildProperty(_DeviceMemorySource, is_single=True)
    target = XMLChildProperty(_DeviceMemoryTarget, is_single=True)


DeviceMemory.register_type()
