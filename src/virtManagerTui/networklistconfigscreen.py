# networklistconfigscreen.py - Copyright (C) 2011 Red Hat, Inc.
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

class NetworkListConfigScreen(VmmTuiConfigScreen):
    '''Provides a base class for all config screens that require a network list.'''

    def __init__(self, title):
        VmmTuiConfigScreen.__init__(self, title)
        self.__has_networks = None
        self.__network_list = None

    def get_network_list_page(self, screen, defined=True, started=True):
        ignore = screen
        uuids = self.get_libvirt().list_networks(defined, started)
        result = None

        if len(uuids) > 0:
            self.__has_networks = True
            self.__network_list = snack.Listbox(0)
            for uuid in uuids:
                network = self.get_libvirt().get_network(uuid)
                self.__network_list.append(uuid, network.get_name())
            result = self.__network_list
        else:
            self.__has_networks = False
            result = snack.Label("There are no networks available.")
        grid = snack.Grid(1, 1)
        grid.setField(result, 0, 0)
        return [snack.Label("Network List"),
                grid]

    def get_selected_network(self):
        uuid = self.__network_list.current()
        return self.get_libvirt().get_network(uuid)

    def has_selectable_networks(self):
        return self.__has_networks
