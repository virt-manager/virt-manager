# hostlistconfigscreen.py - Copyright (C) 2011 Red Hat, Inc.
# Written by Darryl L. Pierce <dpierce@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.  A copy of the GNU General Public License is
# also available at http://www.gnu.org/copyleft/gpl.html.

import snack

from vmmconfigscreen import VmmTuiConfigScreen

class HostListConfigScreen(VmmTuiConfigScreen):
    '''Provides a base class for working with lists of libvirt hosts.'''

    def __init__(self, title):
        VmmTuiConfigScreen.__init__(self, title)
        self.__has_connections = None
        self.__connection_list = None

    def get_connection_list_page(self, screen):
        ignore = screen
        connections = self.get_virt_manager_config().get_connection_list()
        result = None

        if len(connections) > 0:
            self.__has_connections = True
            self.__connection_list = snack.Listbox(0)
            for connection in connections:
                self.__connection_list.append(connection, connection)
            result = self.__connection_list
        else:
            self.__has_connections = False
            result = snack.Label("There are no defined connections.")
        grid = snack.Grid(1, 1)
        grid.setField(result, 0, 0)
        return [snack.Label("Host List"),
                grid]

    def get_selected_connection(self):
        return self.__connection_list.current()

    def has_selectable_connections(self):
        return self.__has_connections
