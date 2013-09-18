# coding=utf-8
#
# Copyright 2013  Red Hat, Inc.
# Giuseppe Scrivano <gscrivan@redhat.com>
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

from virtinst import VirtualDevice
from virtinst.xmlbuilder import XMLProperty


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
        return {"bind" : "Bind",
                "connect": "Connect"}.get(mode) or mode

    def supports_property(self, propname):
        """
        Whether the rng dev type supports the passed property name
        """
        users = {
            "type"                   : [self.TYPE_EGD, self.TYPE_RANDOM],

            "model"                  : [self.TYPE_EGD, self.TYPE_RANDOM],
            "backend_source_host"    : [self.TYPE_EGD],
            "backend_source_mode"    : [self.TYPE_EGD],
            "backend_source_service" : [self.TYPE_EGD],
            "backend_type"           : [self.TYPE_EGD],
            "device"                 : [self.TYPE_RANDOM],
            "rate_bytes"             : [self.TYPE_EGD, self.TYPE_RANDOM],
            "rate_period"            : [self.TYPE_EGD, self.TYPE_RANDOM],
        }
        if users.get(propname):
            return self.type in users[propname]

        return hasattr(self, propname)

    type = XMLProperty(xpath="./backend/@model")
    model = XMLProperty(xpath="./@model",
                        default_cb=lambda s: "virtio")

    backend_type = XMLProperty(xpath="./backend/@type")
    backend_source_host = XMLProperty(xpath="./backend/source/@host")
    backend_source_service = XMLProperty(xpath="./backend/source/@service")
    backend_source_mode = XMLProperty(xpath="./backend/source/@mode")

    rate_bytes = XMLProperty(xpath="./rate/@bytes")
    rate_period = XMLProperty(xpath="./rate/@period")

    device = XMLProperty(xpath="./backend")

VirtualRNGDevice.register_type()
