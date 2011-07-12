#!/usr/bin/env python
#
# removepool.py - Copyright (C) 2009 Red Hat, Inc.
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

LIST_POOLS_PAGE    = 1
CONFIRM_PAGE       = 2

class RemoveStoragePoolConfigScreen(StorageListConfigScreen):
    def __init__(self):
        StorageListConfigScreen.__init__(self, "Remove A Storage Pool")
        self.__confirm = None

    def get_elements_for_page(self, screen, page):
        if   page is LIST_POOLS_PAGE:
            return self.get_storage_pool_list_page(screen)
        elif page is CONFIRM_PAGE:
            return self.get_confirm_page(screen)

    def page_has_next(self, page):
        return page is LIST_POOLS_PAGE and self.has_selectable_pools()

    def page_has_back(self, page):
        ignore = page
        return False

    def page_has_finish(self, page):
        return page is CONFIRM_PAGE

    def validate_input(self, page, errors):
        if page is LIST_POOLS_PAGE:
            if self.get_selected_pool() is not None:
                return True
            else:
                errors.append("Please select a storage pool to be removed.")
        elif page is CONFIRM_PAGE:
            if self.__confirm.value():
                return True
            else:
                errors.append("You must confirm removing a storage pool.")
        return False

    def process_input(self, page):
        if page is CONFIRM_PAGE:
            self.get_libvirt().destroy_storage_pool(self.get_selected_pool())
            self.get_libvirt().undefine_storage_pool(self.get_selected_pool())
            self.set_finished()

    def get_confirm_page(self, screen):
        ignore = screen
        self.__confirm = snack.Checkbox("Check here to confirm deleting pool: %s" % self.get_selected_pool())
        grid = snack.Grid(1, 1)
        grid.setField(self.__confirm, 0, 0)
        return [snack.Label("Remove Selected Storage Pool"),
                grid]

def RemoveStoragePool():
    screen = RemoveStoragePoolConfigScreen()
    screen.start()
