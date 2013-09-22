#
# Copyright (C) 2011 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
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
#

from virtinst import NodeDevice

from virtManager.libvirtobject import vmmLibvirtObject


class vmmNodeDevice(vmmLibvirtObject):
    def __init__(self, conn, backend, key):
        vmmLibvirtObject.__init__(self, conn, backend, key)

        self._name = key
        self._virtinst_obj = None

        self.get_virtinst_obj()

    def _XMLDesc(self, flags):
        return self._backend.XMLDesc(flags)
    def get_name(self):
        return self._name
    def is_active(self):
        return True

    def get_virtinst_obj(self):
        if not self._virtinst_obj:
            self._virtinst_obj = NodeDevice.parse(self.conn.get_backend(),
                self._backend.XMLDesc(0))
        return self._virtinst_obj

    def tick(self):
        pass
