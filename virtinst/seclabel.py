#
# Copyright 2010, 2012-2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

from .xmlbuilder import XMLBuilder, XMLProperty


class Seclabel(XMLBuilder):
    """
    Class for generating <seclabel> XML
    """

    TYPE_DYNAMIC = "dynamic"
    TYPE_STATIC = "static"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_DYNAMIC, TYPE_STATIC]

    MODEL_DEFAULT = "default"

    MODEL_TEST = "testSecurity"
    MODEL_SELINUX = "selinux"
    MODEL_DAC = "dac"
    MODEL_NONE = "none"
    MODELS = [MODEL_SELINUX, MODEL_DAC, MODEL_NONE]

    _XML_ROOT_NAME = "seclabel"
    _XML_PROP_ORDER = ["type", "model", "relabel", "label", "imagelabel"]

    def _guess_secmodel(self):
        # We always want the testSecurity model when running tests
        if (self.MODEL_TEST in
            [x.model for x in self.conn.caps.host.secmodels]):
            return self.MODEL_TEST

        label = self.label
        imagelabel = self.imagelabel

        if not label and not imagelabel:
            for model in self.MODELS:
                if model in [x.model for x in self.conn.caps.host.secmodels]:
                    return model
            raise RuntimeError("No supported model found in capabilities")

        lab_len = imglab_len = None
        if label:
            lab_len = min(3, len(label.split(':')))
        if imagelabel:
            imglab_len = min(3, len(imagelabel.split(':')))
        if lab_len and imglab_len and lab_len != imglab_len:
            raise ValueError(_("Label and Imagelabel are incompatible"))

        lab_len = lab_len or imglab_len
        if lab_len == 3:
            return self.MODEL_SELINUX
        elif lab_len == 2:
            return self.MODEL_DAC
        else:
            raise ValueError(_("Unknown model type for label '%s'") % self.label)
    def _get_default_model(self):
        if self.type is None or self.type == self.TYPE_DEFAULT:
            return None
        return self._guess_secmodel()
    model = XMLProperty("./@model",
                        default_cb=_get_default_model,
                        default_name=MODEL_DEFAULT)

    def _get_default_type(self):
        if self.model is None or self.model == self.MODEL_DEFAULT:
            return None
        return self.TYPE_DYNAMIC
    type = XMLProperty("./@type",
                       default_cb=_get_default_type,
                       default_name=TYPE_DEFAULT)

    label = XMLProperty("./label")
    imagelabel = XMLProperty("./imagelabel")
    baselabel = XMLProperty("./baselabel")
    relabel = XMLProperty("./@relabel", is_yesno=True)
