#
# Copyright 2011, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
# Marc-Andre Lureau <marcandre.lureau@redhat.com>
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
from .xmlbuilder import XMLProperty


class VirtualSmartCardDevice(VirtualDevice):

    virtual_device_type = VirtualDevice.VIRTUAL_DEV_SMARTCARD

    # Default models list
    MODE_DEFAULT = "default"
    MODES = ["passthrough", "host-certificates", "host"]

    TYPE_DEFAULT = "default"
    TYPES = ["tcp", "spicevmc", "default"]


    _XML_PROP_ORDER = ["mode", "type"]

    mode = XMLProperty("./@mode",
                       default_cb=lambda s: "passthrough",
                       default_name=MODE_DEFAULT)

    def _default_type(self):
        if self.mode == self.MODE_DEFAULT or self.mode == "passthrough":
            return "spicevmc"
        return "tcp"
    type = XMLProperty("./@type",
                       default_cb=_default_type,
                       default_name=TYPE_DEFAULT)


VirtualSmartCardDevice.register_type()
