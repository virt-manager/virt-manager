#
# Copyright 2012
# Eiichi Tsukata  <devel@etsukata.com>
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

import VirtualDevice
from virtinst import _gettext as _
from XMLBuilderDomain import _xml_property

class VirtualMemballoon(VirtualDevice.VirtualDevice):

    _virtual_device_type = VirtualDevice.VirtualDevice.VIRTUAL_DEV_MEMBALLOON

    MODEL_DEFAULT = "virtio"
    MODELS = [ "xen", "none", MODEL_DEFAULT ]

    def __init__(self, conn=None, model=MODEL_DEFAULT,
                 parsexml=None, parsexmlnode=None, caps=None):
        VirtualDevice.VirtualDevice.__init__(self, conn, parsexml,
                                             parsexmlnode, caps)

        self._model = None

        if self._is_parse():
            return

        self.model = model

    def get_model(self):
        return self._model
    def set_model(self, new_model):
        if type(new_model) != str:
            raise ValueError(_("'model' must be a string, "
                                " was '%s'." % type(new_model)))
        if not self.MODELS.count(new_model):
            raise ValueError(_("Unsupported memballoon model '%s'" % new_model))
        self._model = new_model
    model = _xml_property(get_model, set_model,
                          xpath="./@model")

    def _get_xml_config(self):
        xml = "    <memballoon model='%s'" % self.model
        xml += "/>"
        return xml
