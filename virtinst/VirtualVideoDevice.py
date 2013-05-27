#
# Copyright 2009  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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


class VirtualVideoDevice(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_VIDEO

    # Default models list
    MODEL_DEFAULT = "default"
    _model_types = ["cirrus", "vga", "vmvga", "xen", "qxl", MODEL_DEFAULT]

    @staticmethod
    def pretty_model(model):
        if model in ["qxl", "vmvga"]:
            return model.upper()
        return model.capitalize()

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        VirtualDevice.__init__(self, conn,
                                             parsexml, parsexmlnode, caps)

        self._model_type    = None
        self._vram          = None
        self._heads         = None

        if self._is_parse():
            return

        self.model_type = self.MODEL_DEFAULT

    def get_model_types(self):
        return self._model_types[:]
    model_types = property(get_model_types)

    def get_model_type(self):
        return self._model_type
    def set_model_type(self, val):
        self._model_type = val
    model_type = _xml_property(get_model_type, set_model_type,
                               xpath="./model/@type")

    def get_vram(self):
        return self._vram
    def set_vram(self, val):
        self._vram = val
    vram = _xml_property(get_vram, set_vram,
                         xpath="./model/@vram")
    ram = _xml_property(lambda o: None, lambda o, v: None,
                        xpath="./model/@ram")


    def get_heads(self):
        return self._heads
    def set_heads(self, val):
        self._heads = val
    heads = _xml_property(get_heads, set_heads,
                          xpath="./model/@heads")

    def _get_xml_config(self):
        model = self.model_type
        if self.model_type == self.MODEL_DEFAULT:
            model = "cirrus"

        model_xml = "      <model"
        if self.model_type:
            model_xml += " type='%s'" % model
        if self.vram:
            model_xml += " vram='%s'" % self.vram
        if self.heads:
            model_xml += " heads='%s'" % self.heads
        model_xml += "/>\n"

        xml = ("    <video>\n" +
               model_xml +
               "    </video>")
        return xml
