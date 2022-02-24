# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceAudio(Device):
    XML_NAME = "audio"

    type = XMLProperty("./@type")
    id = XMLProperty("./@id")
