#
# Copyright 2010, 2012-2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainSeclabel(XMLBuilder):
    """
    Class for generating <seclabel> XML
    """

    TYPE_DYNAMIC = "dynamic"
    TYPE_STATIC = "static"

    MODEL_TEST = "testSecurity"
    MODEL_SELINUX = "selinux"
    MODEL_DAC = "dac"
    MODEL_NONE = "none"

    XML_NAME = "seclabel"
    _XML_PROP_ORDER = ["type", "model", "relabel", "label", "imagelabel"]

    def _guess_secmodel(self):
        caps_models = [x.model for x in self.conn.caps.host.secmodels]

        # We always want the testSecurity model when running tests
        if self.MODEL_TEST in caps_models:
            return self.MODEL_TEST
        if not self.label and not self.imagelabel:
            return caps_models and caps_models[0] or None

        lab_len = imglab_len = None
        if self.label:
            lab_len = min(3, len(self.label.split(':')))
        if self.imagelabel:
            imglab_len = min(3, len(self.imagelabel.split(':')))
        if lab_len and imglab_len and lab_len != imglab_len:
            raise ValueError(_("Label and Imagelabel are incompatible"))

        lab_len = lab_len or imglab_len
        if lab_len == 3:
            return self.MODEL_SELINUX
        elif lab_len == 2:
            return self.MODEL_DAC
        else:
            raise ValueError(_("Unknown model type for label '%s'") % self.label)
    model = XMLProperty("./@model")
    type = XMLProperty("./@type")

    label = XMLProperty("./label")
    imagelabel = XMLProperty("./imagelabel")
    baselabel = XMLProperty("./baselabel")
    relabel = XMLProperty("./@relabel", is_yesno=True)


    ##################
    # Default config #
    ##################

    def set_defaults(self, _guest):
        if self.type or self.model:
            if self.type is None:
                self.type = self.TYPE_DYNAMIC
            if self.model is None:
                self.model = self._guess_secmodel()
