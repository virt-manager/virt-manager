#
# Copyright (C) 2007 Red Hat, Inc.
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

class vmmNetDevice(gobject.GObject):
    __gsignals__ = {}

    def __init__(self, config, connection, name, mac, shared, bridge=None):
        self.__gobject_init__()

        self.conn = connection
        self.name = name
        self.mac = mac
        self.shared = shared
        self.bridge = bridge

    def get_connection(self):
        return self.conn

    def get_name(self):
        return self.name

    def is_shared(self):
        return self.shared

    def get_bridge(self):
        return self.bridge

    def get_mac(self):
        return self.mac

    def get_info(self):
        return (self.name, self.mac, self.shared, self.bridge)

gobject.type_register(vmmNetDevice)
