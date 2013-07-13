# coding=utf-8
#
# Copyright 2011  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
# Marc-André Lureau <marcandre.lureau@redhat.com>
#
# Copyright 2013  IBM Corporation
# Author: Stefan Berger <stefanb@linux.vnet.ibm.com>
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
from virtinst.xmlbuilder import XMLProperty


class VirtualTPMDevice(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_TPM

    # backend types
    TPM_PASSTHROUGH = "passthrough"

    # device models
    TPM_TIS = "tpm-tis"

    # Default backend type and list of choices
    TYPE_DEFAULT = TPM_PASSTHROUGH
    _types = [TPM_PASSTHROUGH]

    # Default device model and list of choices
    MODEL_DEFAULT = TPM_TIS
    _models = [TPM_TIS]

    def get_dev_instance(conn, tpm_type):
        """
        Set up the class attributes for the passed tpm_type
        """

        if tpm_type == VirtualTPMDevice.TPM_PASSTHROUGH:
            c = VirtualTPMPassthroughDevice
        else:
            raise ValueError(_("Unknown TPM device type '%s'.") %
                             tpm_type)

        return c(conn, tpm_type)
    get_dev_instance = staticmethod(get_dev_instance)

    def __init__(self, conn, typ=TYPE_DEFAULT,
                 parsexml=None, parsexmlnode=None):
        VirtualDevice.__init__(self, conn, parsexml, parsexmlnode)

        self._type = None
        self._model = self.TPM_TIS
        self._device_path = None

        if self._is_parse():
            return

        self.type = typ

    def get_types(self):
        return self._types[:]
    types = property(get_types)

    def get_type(self):
        return self._type
    def set_type(self, val):
        if val not in self.types:
            raise ValueError(_("Unknown TPM type '%s'") % val)
        self._type = val
    type = XMLProperty(get_type, set_type,
                         xpath="./backend/@type")

    def get_models(self):
        return self._models[:]
    models = property(get_models)

    def get_model(self):
        return self._model
    def set_model(self, val):
        if val not in self.models:
            raise ValueError(_("Unknown TPM model '%s'") % val)
        self._model = val
    model = XMLProperty(get_model, set_model,
                          xpath="./@model")

    def get_device_path(self):
        return self._device_path
    def set_device_path(self, val):
        self._device_path = val
    device_path = XMLProperty(get_device_path, set_device_path,
                                xpath="./backend/device/@path")

    def supports_property(self, propname):
        """
        Whether the TPM dev type supports the passed property name
        """
        users = {
            "device_path"     : [self.TPM_PASSTHROUGH],
        }

        if users.get(propname):
            return self.type in users[propname]

        return hasattr(self, propname)

    def _get_xml_config(self):
        device = "/dev/tpm0"
        if self._device_path is not None:
            device = self._device_path

        xml  = "    <tpm model='%s'>\n" % self.model
        xml += "      <backend type='%s'>\n" % self.type
        if self.type == "passthrough":
            xml += "        <device path='%s'/>\n" % device
        xml += "      </backend>\n"
        xml += "    </tpm>"

        return xml


class VirtualTPMPassthroughDevice(VirtualTPMDevice):
    _tpm_type = VirtualTPMDevice.TPM_PASSTHROUGH
