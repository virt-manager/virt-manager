#
# Copyright 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from .char import CharSource
from ..xmlbuilder import XMLChildProperty, XMLProperty


class DeviceRng(Device):
    XML_NAME = "rng"

    TYPE_RANDOM = "random"
    TYPE_EGD = "egd"

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

    model = XMLProperty("./@model")

    backend_model = XMLProperty("./backend/@model")
    backend_type = XMLProperty("./backend/@type")

    source = XMLChildProperty(CharSource, is_single=True,
            relative_xpath="./backend")

    rate_bytes = XMLProperty("./rate/@bytes")
    rate_period = XMLProperty("./rate/@period")

    device = XMLProperty("./backend[@model='random']")


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if not self.model:
            self.model = "virtio"
