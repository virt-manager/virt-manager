#
# Copyright 2010, 2012-2013 Red Hat, Inc.
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
    _XML_PROP_ORDER = ["type", "model", "relabel", "label"]

    def _guess_secmodel(self):
        caps_models = [x.model for x in self.conn.caps.host.secmodels]

        # We always want the testSecurity model when running tests
        if self.MODEL_TEST in caps_models:
            return self.MODEL_TEST
        if not self.label:
            return caps_models and caps_models[0] or None

        lab_len = None
        if self.label:
            lab_len = min(3, len(self.label.split(':')))

        if lab_len == 3:
            return self.MODEL_SELINUX
        elif lab_len == 2:
            return self.MODEL_DAC
    model = XMLProperty("./@model")
    type = XMLProperty("./@type")

    label = XMLProperty("./label")
    baselabel = XMLProperty("./baselabel")
    relabel = XMLProperty("./@relabel", is_yesno=True)


    ##################
    # Default config #
    ##################

    def set_defaults(self, _guest):
        if not self.type and not self.model:
            # Let libvirt fill it in
            return
        if self.type is None:
            self.type = self.TYPE_DYNAMIC
        if self.model is None:
            self.model = self._guess_secmodel()
