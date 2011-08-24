#
# stoppool.py - Copyright (C) 2009 Red Hat, Inc.
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

from snack import Label
from storagelistconfigscreen import StorageListConfigScreen

LIST_POOLS_PAGE    = 1
FINAL_PAGE         = 2

class StopStoragePoolConfigScreen(StorageListConfigScreen):
    def __init__(self):
        StorageListConfigScreen.__init__(self, "Stop A Storage Pool")

    def get_elements_for_page(self, screen, page):
        if   page is LIST_POOLS_PAGE:
            return self.get_storage_pool_list_page(screen, defined=False)
        elif page is FINAL_PAGE:
            return self.get_final_page(screen)

    def page_has_next(self, page):
        return page is LIST_POOLS_PAGE and self.has_selectable_pools()

    def page_has_finish(self, page):
        return page is FINAL_PAGE

    def validate_input(self, page, errors):
        if page is LIST_POOLS_PAGE:
            if self.get_selected_pool() is not None:
                return True
            else:
                errors.append("Please select a storage pool to be stopped.")
        return False

    def process_input(self, page):
        if page is LIST_POOLS_PAGE:
            self.get_libvirt().destroy_storage_pool(self.get_selected_pool())

    def get_final_page(self, screen):
        ignore = screen
        self.set_finished()
        return [Label("Storage pool stopped: %s" % self.get_selected_pool())]

def StopStoragePool():
    screen = StopStoragePoolConfigScreen()
    screen.start()
