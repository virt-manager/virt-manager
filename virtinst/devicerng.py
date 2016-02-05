#
# Copyright 2013 Red Hat, Inc.
# Giuseppe Scrivano <gscrivan@redhat.com>
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


class VirtualRNGDevice(VirtualDevice):

    virtual_device_type = VirtualDevice.VIRTUAL_DEV_RNG

    TYPE_RANDOM = "random"
    TYPE_EGD = "egd"
    TYPES = [TYPE_RANDOM, TYPE_EGD]

    BACKEND_TYPE_UDP = "udp"
    BACKEND_TYPE_TCP = "tcp"
    BACKEND_TYPES = [BACKEND_TYPE_UDP, BACKEND_TYPE_TCP]

    BACKEND_MODE_BIND = "bind"
    BACKEND_MODE_CONNECT = "connect"
    BACKEND_MODES = [BACKEND_MODE_BIND, BACKEND_MODE_CONNECT]

    @staticmethod
    def get_pretty_type(rng_type):
        if rng_type == VirtualRNGDevice.TYPE_RANDOM:
            return _("Random")
        if rng_type == VirtualRNGDevice.TYPE_EGD:
            return _("Entropy Gathering Daemon")
        return rng_type

    @staticmethod
    def get_pretty_backend_type(backend_type):
        return {"udp" : "UDP",
                "tcp": "TCP"}.get(backend_type) or backend_type

    @staticmethod
    def get_pretty_mode(mode):
        return {"bind" : _("Bind"),
                "connect": _("Connect")}.get(mode) or mode

    def supports_property(self, propname):
        """
        Whether the rng dev type supports the passed property name
        """
        users = {
            "type"                   : [self.TYPE_EGD, self.TYPE_RANDOM],
            "model"                  : [self.TYPE_EGD, self.TYPE_RANDOM],
            "bind_host"              : [self.TYPE_EGD],
            "bind_service"           : [self.TYPE_EGD],
            "connect_host"           : [self.TYPE_EGD],
            "connect_service"        : [self.TYPE_EGD],
            "backend_type"           : [self.TYPE_EGD],
            "device"                 : [self.TYPE_RANDOM],
            "rate_bytes"             : [self.TYPE_EGD, self.TYPE_RANDOM],
            "rate_period"            : [self.TYPE_EGD, self.TYPE_RANDOM],
        }
        if users.get(propname):
            return self.type in users[propname]

        return hasattr(self, propname)

    def backend_mode(self):
        ret = []
        if self._has_mode_bind:
            ret.append(VirtualRNGDevice.BACKEND_MODE_BIND)
        if self._has_mode_connect:
            ret.append(VirtualRNGDevice.BACKEND_MODE_CONNECT)
        return ret

    _XML_PROP_ORDER = ["_has_mode_bind", "_has_mode_connect"]

    _has_mode_connect = XMLProperty("./backend/source[@mode='connect']/@mode")
    def _set_connect_validate(self, val):
        if val:
            self._has_mode_connect = VirtualRNGDevice.BACKEND_MODE_CONNECT
        return val

    _has_mode_bind = XMLProperty("./backend/source[@mode='bind']/@mode")
    def _set_bind_validate(self, val):
        if val:
            self._has_mode_bind = VirtualRNGDevice.BACKEND_MODE_BIND
        return val

    type = XMLProperty("./backend/@model")
    model = XMLProperty("./@model", default_cb=lambda s: "virtio")

    backend_type = XMLProperty("./backend/@type")

    bind_host = XMLProperty("./backend/source[@mode='bind']/@host",
                            set_converter=_set_bind_validate)
    bind_service = XMLProperty("./backend/source[@mode='bind']/@service",
                               set_converter=_set_bind_validate)

    connect_host = XMLProperty("./backend/source[@mode='connect']/@host",
        set_converter=_set_connect_validate)
    connect_service = XMLProperty("./backend/source[@mode='connect']/@service",
        set_converter=_set_connect_validate)

    rate_bytes = XMLProperty("./rate/@bytes")
    rate_period = XMLProperty("./rate/@period")

    device = XMLProperty("./backend")

VirtualRNGDevice.register_type()
