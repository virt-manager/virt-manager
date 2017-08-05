#
# Copyright 2011, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
# Marc-Andre Lureau <marcandre.lureau@redhat.com>
#
# Copyright 2013 IBM Corporation
# Author: Stefan Berger <stefanb@linux.vnet.ibm.com>
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

from .device import VirtualDevice
from .xmlbuilder import XMLProperty


class VirtualTPMDevice(VirtualDevice):

    virtual_device_type = VirtualDevice.VIRTUAL_DEV_TPM

    TYPE_PASSTHROUGH = "passthrough"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_PASSTHROUGH]

    MODEL_TIS = "tpm-tis"
    MODEL_DEFAULT = "default"
    MODELS = [MODEL_TIS]

    @staticmethod
    def get_pretty_type(tpm_type):
        if tpm_type == VirtualTPMDevice.TYPE_PASSTHROUGH:
            return _("Passthrough device")
        return tpm_type

    def supports_property(self, propname):
        """
        Whether the TPM dev type supports the passed property name
        """
        users = {
            "device_path": [self.TYPE_PASSTHROUGH],
        }

        if users.get(propname):
            return self.type in users[propname]

        return hasattr(self, propname)

    type = XMLProperty("./backend/@type",
                       default_cb=lambda s: s.TYPE_PASSTHROUGH)
    model = XMLProperty("./@model",
                       default_cb=lambda s: s.MODEL_TIS)
    device_path = XMLProperty("./backend/device/@path",
                              default_cb=lambda s: "/dev/tpm0")


VirtualTPMDevice.register_type()
