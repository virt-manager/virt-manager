# listpools.py - Copyright (C) 2009 Red Hat, Inc.
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

from newt_syrup import utils

LIST_PAGE    = 1
DETAILS_PAGE = 2

class ListStoragePoolsConfigScreen(StorageListConfigScreen):
    def __init__(self):
        StorageListConfigScreen.__init__(self, "List Storage Pools")

    def get_elements_for_page(self, screen, page):
        if   page is LIST_PAGE:
            return self.get_storage_pool_list_page(screen)
        elif page is DETAILS_PAGE:
            return self.get_pool_details_page(screen)

    def page_has_next(self, page):
        if page is LIST_PAGE and self.has_selectable_pools():
            return True
        return False

    def page_has_back(self, page):
        if page is DETAILS_PAGE:
            return True
        return False

    def get_pool_details_page(self, screen):
        ignore = screen
        pool = self.get_libvirt().get_storage_pool(self.get_selected_pool())
        volumes = snack.Listbox(0)
        for name in pool.listVolumes():
            volume = pool.storageVolLookupByName(name)
            volumes.append("%s (%s)" % (name, utils.size_as_mb_or_gb(volume.info()[1])), name)
        grid = snack.Grid(2, 3)
        grid.setField(snack.Label("Name:"), 0, 0, anchorRight=1)
        grid.setField(snack.Label(pool.name()), 1, 0, anchorLeft=1)
        grid.setField(snack.Label("Volumes:"), 0, 1, anchorRight=1)
        grid.setField(volumes, 1, 1, anchorLeft=1)
        grid.setField(snack.Label("Autostart:"), 0, 2, anchorRight=1)
        label = "No"
        if pool.autostart():
            label = "Yes"
        grid.setField(snack.Label(label), 1, 2, anchorLeft=1)
        return [snack.Label("Details For Storage Pool: %s" % self.get_selected_pool()),
                grid]

def ListStoragePools():
    screen = ListStoragePoolsConfigScreen()
    screen.start()
