#
# Copyright 2013 Red Hat, Inc.
# Giuseppe Scrivano <gscrivan@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceRng(Device):
    XML_NAME = "rng"

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
        if rng_type == DeviceRng.TYPE_RANDOM:
            return _("Random")
        if rng_type == DeviceRng.TYPE_EGD:
            return _("Entropy Gathering Daemon")
        return rng_type

    @staticmethod
    def get_pretty_backend_type(backend_type):
        return {"udp": "UDP",
                "tcp": "TCP"}.get(backend_type) or backend_type

    @staticmethod
    def get_pretty_mode(mode):
        return {"bind": _("Bind"),
                "connect": _("Connect")}.get(mode) or mode

    def supports_property(self, propname):
        """
        Whether the rng dev type supports the passed property name
        """
        users = {
            "type":                  [self.TYPE_EGD, self.TYPE_RANDOM],
            "model":                 [self.TYPE_EGD, self.TYPE_RANDOM],
            "bind_host":             [self.TYPE_EGD],
            "bind_service":          [self.TYPE_EGD],
            "connect_host":          [self.TYPE_EGD],
            "connect_service":       [self.TYPE_EGD],
            "backend_type":          [self.TYPE_EGD],
            "device":                [self.TYPE_RANDOM],
            "rate_bytes":            [self.TYPE_EGD, self.TYPE_RANDOM],
            "rate_period":           [self.TYPE_EGD, self.TYPE_RANDOM],
        }
        if users.get(propname):
            return self.type in users[propname]

        return hasattr(self, propname)

    def backend_mode(self):
        ret = []
        if self._has_mode_bind:
            ret.append(DeviceRng.BACKEND_MODE_BIND)
        if self._has_mode_connect:
            ret.append(DeviceRng.BACKEND_MODE_CONNECT)
        return ret

    _XML_PROP_ORDER = ["_has_mode_bind", "_has_mode_connect"]

    _has_mode_connect = XMLProperty("./backend/source[@mode='connect']/@mode")
    def _set_connect_validate(self, val):
        if val:
            self._has_mode_connect = DeviceRng.BACKEND_MODE_CONNECT
        return val

    _has_mode_bind = XMLProperty("./backend/source[@mode='bind']/@mode")
    def _set_bind_validate(self, val):
        if val:
            self._has_mode_bind = DeviceRng.BACKEND_MODE_BIND
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

    device = XMLProperty("./backend[@model='random']")
