#
# Copyright 2008-2009, 2013-2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


class _Codec(XMLBuilder):
    """
    Class for generating <sound> child <codec> XML
    """
    XML_NAME = "codec"

    type = XMLProperty("./@type")


class DeviceSound(Device):
    XML_NAME = "sound"

    model = XMLProperty("./@model")
    codecs = XMLChildProperty(_Codec)
    audio_id = XMLProperty("./audio/@id")


    ##################
    # Default config #
    ##################

    @staticmethod
    def default_model(guest):
        if guest.defaults_to_pcie():
            return "ich9"
        return "ich6"

    def set_defaults(self, guest):
        if not self.model:
            self.model = self.default_model(guest)
