#
# Copyright 2008-2009, 2013-2014 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

    MODELS = ["es1370", "sb16", "pcspk", "ac97", "ich6", "ich9"]

    model = XMLProperty("./@model")
    codecs = XMLChildProperty(_Codec)

    @staticmethod
    def pretty_model(model):
        ret = model.upper()
        if model in ["ich6", "ich9"]:
            ret = "HDA (%s)" % model.upper()
        return ret


    ##################
    # Default config #
    ##################

    @staticmethod
    def default_model(guest):
        if guest.os.is_q35():
            return "ich9"
        return "ich6"

    def set_defaults(self, guest):
        if not self.model:
            self.model = self.default_model(guest)
