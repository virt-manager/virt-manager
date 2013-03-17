# removehost.py - Copyright (C) 2009 Red Hat, Inc.
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

from hostlistconfigscreen import HostListConfigScreen

SELECT_HOST_PAGE    = 1
CONFIRM_REMOVE_PAGE = 2

class RemoveHostConfigScreen(HostListConfigScreen):
    def __init__(self):
        HostListConfigScreen.__init__(self, "Remove Host Connection")
        self.__confirm = None

    def get_elements_for_page(self, screen, page):
        if   page is SELECT_HOST_PAGE:
            return self.get_connection_list_page(screen)
        elif page is CONFIRM_REMOVE_PAGE:
            return self.get_confirm_remove_page(screen)

    def page_has_next(self, page):
        return page is SELECT_HOST_PAGE and self.has_selectable_connections()

    def page_has_back(self, page):
        return page is CONFIRM_REMOVE_PAGE

    def page_has_finish(self, page):
        return page is CONFIRM_REMOVE_PAGE

    def validate_input(self, page, errors):
        if   page is SELECT_HOST_PAGE:
            return True
        elif page is CONFIRM_REMOVE_PAGE:
            if self.__confirm.value():
                return True
            else:
                errors.append("You must confirm removing the connection.")
        return False

    def process_input(self, page):
        if page is CONFIRM_REMOVE_PAGE:
            self.get_virt_manager_config().remove_connection(self.get_selected_connection())
            self.set_finished()

    def get_confirm_remove_page(self, screen):
        ignore = screen
        self.__confirm = snack.Checkbox("Remove this connection: %s" % self.get_selected_connection(), 0)
        grid = snack.Grid(1, 1)
        grid.setField(self.__confirm, 0, 0)
        return [snack.Label("Remove Host Connection"),
                grid]

def RemoveHost():
    screen = RemoveHostConfigScreen()
    screen.start()
