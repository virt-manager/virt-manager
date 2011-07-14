# addvolume.py - Copyright (C) 2009 Red Hat, Inc.
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

from createmeter import CreateMeter
from storagelistconfigscreen import StorageListConfigScreen
from volumeconfig import StorageVolumeConfig

from newt_syrup import utils

SELECT_POOL_PAGE   = 1
VOLUME_NAME_PAGE   = 2
VOLUME_FORMAT_PAGE = 3
MAX_CAPACITY_PAGE  = 4
CONFIRM_PAGE       = 5

class AddVolumeConfigScreen(StorageListConfigScreen):
    def __init__(self):
        StorageListConfigScreen.__init__(self, "Add A New Storage Volume")
        self.__config = StorageVolumeConfig()
        self.__name = None
        self.__capacity = None
        self.__allocation = None
        self.__formats = None

    def get_elements_for_page(self, screen, page):
        if   page is SELECT_POOL_PAGE:
            return self.get_storage_pool_list_page(screen)
        elif page is VOLUME_NAME_PAGE:
            return self.get_volume_name_page(screen)
        elif page is VOLUME_FORMAT_PAGE:
            return self.get_volume_format_page(screen)
        elif page is MAX_CAPACITY_PAGE:
            return self.get_max_capacity_page(screen)
        elif page is CONFIRM_PAGE:
            return self.get_confirm_page(screen)

    def page_has_next(self, page):
        if page is SELECT_POOL_PAGE:
            return self.has_selectable_pools()
        else:
            if page < CONFIRM_PAGE:
                return True
        return False

    def page_has_back(self, page):
        if page > SELECT_POOL_PAGE:
            return True
        return False

    def page_has_finish(self, page):
        return page is CONFIRM_PAGE

    def get_next_page(self, page):
        if page is VOLUME_NAME_PAGE:
            if self.__config.needs_format():
                return VOLUME_FORMAT_PAGE
            else:
                return MAX_CAPACITY_PAGE
        return StorageListConfigScreen.get_next_page(self, page)

    def get_back_page(self, page):
        if page is MAX_CAPACITY_PAGE:
            if self.__config.needs_format():
                return VOLUME_FORMAT_PAGE
            else:
                return VOLUME_NAME_PAGE
        return StorageListConfigScreen.get_back_page(self, page)

    def validate_input(self, page, errors):
        if page is SELECT_POOL_PAGE:
            if self.get_selected_pool() is not None:
                return True
            else:
                errors.append("You must select a storage pool.")
        elif page is VOLUME_NAME_PAGE:
            if utils.string_is_not_blank(self.__name.value()):
                return True
            else:
                errors.append("Storage object name can only contain alphanumeric, '_', '.', or '-' characters.")
        elif page is VOLUME_FORMAT_PAGE:
            if self.__formats.current() is not None:
                return True
            else:
                errors.append("You must select a volume format.")
        elif page is MAX_CAPACITY_PAGE:
            if utils.string_is_not_blank(self.__capacity.value()):
                if utils.string_is_not_blank(self.__allocation.value()):
                    capacity = int(self.__capacity.value())
                    allocation = int(self.__allocation.value())
                    if capacity > 0:
                        if capacity <= self.__config.get_pool().info()[3] / (1024 ** 2):
                            if allocation >= 0:
                                if allocation <= capacity:
                                    return True
                                else:
                                    errors.append("Allocation cannot exceed the maximum capacity.")
                            else:
                                errors.append("The allocation must be greater than or equal to 0.")
                        else:
                            errors.append("The maximum capacity cannot exceed the storage pool size.")
                    else:
                        errors.append("The capacity must be greater than zero.")
                else:
                    errors.append("An allocation value must be entered.")
            else:
                errors.append("A maximum volume capacity must be entered.")
        elif page is CONFIRM_PAGE:
            return True
        return False

    def process_input(self, page):
        if page is SELECT_POOL_PAGE:
            self.__config.set_pool(self.get_libvirt().get_storage_pool(self.get_selected_pool()))
        elif page is VOLUME_NAME_PAGE:
            self.__config.set_name(self.__name.value())
        elif page is VOLUME_FORMAT_PAGE:
            self.__config.set_format(self.__formats.current())
        elif page is MAX_CAPACITY_PAGE:
            self.__config.set_max_capacity(int(self.__capacity.value()))
            self.__config.set_allocation(int(self.__allocation.value()))
        elif page is CONFIRM_PAGE:
            self.get_libvirt().define_storage_volume(self.__config, CreateMeter())
            self.set_finished()

    def get_volume_name_page(self, screen):
        ignore = screen
        self.__name = snack.Entry(50, self.__config.get_name())
        grid = snack.Grid(2, 1)
        grid.setField(snack.Label("Name:"), 0, 0, anchorRight=1)
        grid.setField(self.__name, 1, 0, anchorLeft=1)
        return [snack.Label("New Storage Volume"),
                grid,
                snack.Label("Name of the volume to create. File extension may be appended.")]

    def get_volume_format_page(self, screen):
        ignore = screen
        self.__formats = snack.Listbox(0)
        for fmt in self.__config.get_formats_for_pool():
            self.__formats.append(fmt, fmt)
        grid = snack.Grid(1, 1)
        grid.setField(self.__formats, 0, 0)
        return [snack.Label("Select The Volume Format"),
                grid]

    def get_max_capacity_page(self, screen):
        ignore = screen
        self.__capacity = snack.Entry(6, str(self.__config.get_max_capacity()))
        self.__allocation = snack.Entry(6, str(self.__config.get_allocation()))
        grid = snack.Grid(2, 2)
        grid.setField(snack.Label("Max. Capacity (MB):"), 0, 0, anchorRight=1)
        grid.setField(self.__capacity, 1, 0, anchorLeft=1)
        grid.setField(snack.Label("Allocation (MB):"), 0, 1, anchorRight=1)
        grid.setField(self.__allocation, 1, 1, anchorLeft=1)
        return [snack.Label("Storage Volume Quota"),
                snack.Label("%s's available space: %s" % (self.__config.get_pool().name(),
                                                    utils.size_as_mb_or_gb(self.__config.get_pool().info()[3]))),
                grid]

    def get_confirm_page(self, screen):
        ignore = screen
        grid = snack.Grid(2, 5)
        grid.setField(snack.Label("Volume Name:"), 0, 0, anchorRight=1)
        grid.setField(snack.Label("%s (%s)" % (self.__config.get_name(), self.__config.get_pool().name())), 1, 0, anchorLeft=1)
        if self.__config.needs_format():
            grid.setField(snack.Label("Format:"), 0, 1, anchorRight=1)
            grid.setField(snack.Label(self.__config.get_format()), 1, 1, anchorLeft=1)
        # NOTE: here we multiply the sizes by 1024^2 since the size_as_mb_or_gb is expect bytes
        grid.setField(snack.Label("Max. Capacity:"), 0, 2, anchorRight=1)
        grid.setField(snack.Label("%s" % (utils.size_as_mb_or_gb(self.__config.get_max_capacity() * (1024 ** 2)))), 1, 2, anchorLeft=1)
        grid.setField(snack.Label("Allocation:"), 0, 3, anchorRight=1)
        grid.setField(snack.Label("%s" % (utils.size_as_mb_or_gb(self.__config.get_allocation() * (1024 ** 2)))), 1, 3, anchorLeft=1)
        return [snack.Label("Ready To Allocation New Storage Volume"),
                grid]

def AddStorageVolume():
    screen = AddVolumeConfigScreen()
    screen.start()
