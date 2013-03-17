# storagelistconfigscreen.py - Copyright (C) 2011 Red Hat, Inc.
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

class StorageListConfigScreen(VmmTuiConfigScreen):
    '''Provides a base class for any configuration screen that deals with storage pool lists.'''

    def __init__(self, title):
        VmmTuiConfigScreen.__init__(self, title)
        self.__has_pools = None
        self.__pools_list = None
        self.__has_volumes = None
        self.__volumes_list = None

    def get_storage_pool_list_page(self, screen, defined=True, created=True):
        ignore = screen
        pools = self.get_libvirt().list_storage_pools(defined=defined, created=created)
        if len(pools) > 0:
            self.__has_pools = True
            self.__pools_list = snack.Listbox(0)
            for pool in pools:
                self.__pools_list.append(pool, pool)
            result = self.__pools_list
        else:
            self.__has_pools = False
            result = snack.Label("There are no storage pools available.")
        grid = snack.Grid(1, 1)
        grid.setField(result, 0, 0)
        return [snack.Label("Storage Pool List"),
                grid]

    def get_selected_pool(self):
        return self.__pools_list.current()

    def has_selectable_pools(self):
        return self.__has_pools

    def get_storage_volume_list_page(self, screen):
        '''Requires that self.__pools_list have a selected element.'''
        ignore = screen
        pool = self.get_libvirt().get_storage_pool(self.get_selected_pool())
        if len(pool.listVolumes()) > 0:
            self.__has_volumes = True
            self.__volumes_list = snack.Listbox(0)
            for volname in pool.listVolumes():
                volume = pool.storageVolLookupByName(volname)
                self.__volumes_list.append("%s (%0.2f GB)" % (volume.name(), volume.info()[2] / (1024 ** 3)), volume.name())
            result = self.__volumes_list
        else:
            self.__has_volumes = False
            result = snack.Label("There are no storage volumes available.")
        grid = snack.Grid(1, 1)
        grid.setField(result, 0, 0)
        return [snack.Label("Storage Volume List"),
                grid]

    def get_selected_volume(self):
        return self.__volumes_list.current()

    def has_selectable_volumes(self):
        return self.__has_volumes
