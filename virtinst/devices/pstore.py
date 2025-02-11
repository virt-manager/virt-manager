# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DevicePstore(Device):
    XML_NAME = "pstore"

    backend = XMLProperty("./@backend")
    path = XMLProperty("./path")
    size = XMLProperty("./size", is_int=True)
