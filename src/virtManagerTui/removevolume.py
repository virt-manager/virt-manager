# removevolume.py - Copyright (C) 2009 Red Hat, Inc.
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

from storagelistconfigscreen import StorageListConfigScreen
from volumeconfig import StorageVolumeConfig

SELECT_POOL_PAGE   = 1
SELECT_VOLUME_PAGE = 2
CONFIRM_PAGE       = 3

class RemoveVolumeConfigScreen(StorageListConfigScreen):
    def __init__(self):
        StorageListConfigScreen.__init__(self, "Add A New Storage Volume")
        self.__config = StorageVolumeConfig()
        self.__confirm = None

    def get_elements_for_page(self, screen, page):
        if   page is SELECT_POOL_PAGE:
            return self.get_storage_pool_list_page(screen)
        elif page is SELECT_VOLUME_PAGE:
            return self.get_storage_volume_list_page(screen)
        elif page is CONFIRM_PAGE:
            return self.get_confirm_page(screen)

    def page_has_next(self, page):
        if   page is SELECT_POOL_PAGE:
            return self.has_selectable_pools()
        elif page is SELECT_VOLUME_PAGE:
            return self.has_selectable_volumes()
        return False

    def validate_input(self, page, errors):
        if   page is SELECT_POOL_PAGE:
            return self.get_selected_pool() is not None
        elif page is SELECT_VOLUME_PAGE:
            return self.get_selected_volume() is not None
        elif page is CONFIRM_PAGE:
            if self.__confirm.value():
                return True
            else:
                errors.append("You must confirm deleting a storage volume.")
        return False

    def process_input(self, page):
        if page is CONFIRM_PAGE:
            self.get_libvirt().remove_storage_volume(self.get_selected_pool(), self.get_selected_volume())
            self.set_finished()

    def page_has_back(self, page):
        return page > SELECT_POOL_PAGE

    def page_has_finish(self, page):
        return page is CONFIRM_PAGE

    def get_confirm_page(self, screen):
        ignore = screen
        self.__confirm = snack.Checkbox("Check here to confirm deleting volume: %s" % self.get_selected_volume())
        grid = snack.Grid(1, 1)
        grid.setField(self.__confirm, 0, 0)
        return [snack.Label("Remove Selected Storage Volume"),
                grid]

def RemoveStorageVolume():
    screen = RemoveVolumeConfigScreen()
    screen.start()
