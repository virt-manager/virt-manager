#
# Copyright 2011, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
# Marc-Andre Lureau <marcandre.lureau@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceRedirdev(Device):
    XML_NAME = "redirdev"

    BUS_DEFAULT = "default"
    BUSES = ["usb"]

    TYPE_DEFAULT = "default"
    TYPES = ["tcp", "spicevmc"]

    @staticmethod
    def pretty_type(typ):
        if typ == "tcp":
            return "TCP"
        if typ == "spicevmc":
            return "SpiceVMC"
        return typ and typ.capitalize()

    def parse_friendly_server(self, serverstr):
        if serverstr.count(":") != 1:
            raise ValueError(_("Could not determine or unsupported "
                               "format of '%s'") % serverstr)
        self.host, self.service = serverstr.split(":")


    _XML_PROP_ORDER = ["bus", "type"]

    bus = XMLProperty("./@bus",
                      default_cb=lambda s: "usb",
                      default_name=BUS_DEFAULT)
    type = XMLProperty("./@type",
                       default_cb=lambda s: "spicevmc",
                       default_name=TYPE_DEFAULT)

    host = XMLProperty("./source/@host")
    service = XMLProperty("./source/@service", is_int=True)
