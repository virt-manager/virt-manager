#
# Copyright 2017 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.


from .device import Device
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _DeviceMemoryTarget(XMLBuilder):
    XML_NAME = "target"

    size = XMLProperty("./size", is_int=True)
    node = XMLProperty("./node", is_int=True)
    label_size = XMLProperty("./label/size", is_int=True)
    readonly = XMLProperty("./readonly", is_bool=True)


class _DeviceMemorySource(XMLBuilder):
    XML_NAME = "source"

    pagesize = XMLProperty("./pagesize", is_int=True)
    nodemask = XMLProperty("./nodemask")
    path = XMLProperty("./path")
    alignsize = XMLProperty("./alignsize", is_int=True)
    pmem = XMLProperty("./pmem", is_bool=True)


class DeviceMemory(Device):
    XML_NAME = "memory"

    MODEL_DIMM = "dimm"
    MODEL_NVDIMM = "nvdimm"
    models = [MODEL_DIMM, MODEL_NVDIMM]

    ACCESS_SHARED = "shared"
    ACCESS_PRIVATE = "private"
    accesses = [ACCESS_SHARED, ACCESS_PRIVATE]

    model = XMLProperty("./@model")
    access = XMLProperty("./@access")
    discard = XMLProperty("./@discard", is_yesno=True)

    source = XMLChildProperty(_DeviceMemorySource, is_single=True)
    target = XMLChildProperty(_DeviceMemoryTarget, is_single=True)
