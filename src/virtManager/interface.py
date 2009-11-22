#
# Copyright (C) 2009 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
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

import gobject

import virtinst

class vmmInterface(gobject.GObject):
    __gsignals__ = { }

    def __init__(self, config, connection, interface, name, active):
        self.__gobject_init__()
        self.config = config
        self.connection = connection
        self.interface = interface  # Libvirt virInterface object
        self.name = name            # String name
        self.active = active        # bool indicating if it is running

        self._xml = None            # xml cache
        self._update_xml()

    def set_active(self, state):
        self.active = state
        self._update_xml()

    def is_active(self):
        return self.active

    def get_connection(self):
        return self.connection

    def get_name(self):
        return self.name

    def get_mac(self):
        return self.interface.MACString()

    def start(self):
        self.interface.create(0)
        self._update_xml()

    def stop(self):
        self.interface.destroy(0)
        self._update_xml()

    def delete(self):
        self.interface.undefine()

    def _update_xml(self):
        self._xml = self.interface.XMLDesc(0)

    def get_xml(self):
        if self._xml is None:
            self._update_xml()
        return self._xml


    def get_type(self):
        return virtinst.util.get_xml_path(self.get_xml(), "/interface/@type")

gobject.type_register(vmmInterface)
