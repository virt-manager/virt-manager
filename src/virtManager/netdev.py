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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import gobject

class vmmNetDevice(gobject.GObject):
        __gsignals__ = {}

        def __init__(self, config, connection, name, mac, shared):
            self.__gobject_init__()

            self.conn = connection
            self.name = name
            self.mac = mac
            self.shared = shared

        def get_connection(self):
            return self.conn

        def get_name(self):
            return self.name

        def is_shared(self):
            return self.shared

        def get_mac(self):
            return self.mac

gobject.type_register(vmmNetDevice)
