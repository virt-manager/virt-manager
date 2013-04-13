# coding=utf-8
#
# Copyright 2011  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
# Marc-André Lureau <marcandre.lureau@redhat.com>
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

from virtinst.VirtualDevice import VirtualDevice
from virtinst.XMLBuilderDomain import _xml_property


class VirtualSmartCardDevice(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_SMARTCARD

    # Default models list
    MODE_DEFAULT = "passthrough"
    _modes = ["passthrough", "host-certificates", "host"]

    TYPE_DEFAULT = "tcp"
    _types = ["tcp", "spicevmc", None]

    def __init__(self, conn, mode=MODE_DEFAULT,
                 parsexml=None, parsexmlnode=None, caps=None):
        VirtualDevice.__init__(self, conn,
                                             parsexml, parsexmlnode, caps)

        self._mode = None
        self._type = None

        if self._is_parse():
            return

        self.mode = mode

    def get_modes(self):
        return self._modes[:]
    modes = property(get_modes)

    def get_mode(self):
        return self._mode
    def set_mode(self, val):
        if val not in self.modes:
            raise ValueError(_("Unknown smartcard mode '%s'") % val)
        self._mode = val
    mode = _xml_property(get_mode, set_mode,
                         xpath="./@mode")

    def get_types(self):
        return self._types[:]
    types = property(get_types)

    def get_type(self):
        if self._type is None and self.mode == "passthrough":
            return "spicevmc"
        return self._type
    def set_type(self, val):
        if val not in self.types:
            raise ValueError(_("Unknown smartcard type '%s'") % val)
        self._type = val
    type = _xml_property(get_type, set_type,
                         xpath="./@type")

    def _get_xml_config(self):
        mode = self.mode

        xml = "    <smartcard mode='%s'" % mode
        if self.type:
            xml += " type='%s'" % self.type
        xml += ">\n"
        xml += "    </smartcard>"

        return xml
