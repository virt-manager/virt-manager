#
# migratedomain.py - Copyright (C) 2009 Red Hat, Inc.
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
from domainlistconfigscreen import DomainListConfigScreen

LIST_DOMAINS  = 1
SELECT_TARGET = 2
CONFIRM_PAGE  = 3

class MigrateDomainConfigScreen(DomainListConfigScreen):
    def __init__(self):
        DomainListConfigScreen.__init__(self, "Migrate Virtual Machine")
        self.__configured = False
        self.__confirm = None
        self.__targets = None

    def get_elements_for_page(self, screen, page):
        if   page is LIST_DOMAINS:
            return self.get_domain_list_page(screen)
        elif page is SELECT_TARGET:
            return self.get_target_page(screen)
        elif page is CONFIRM_PAGE:
            return self.get_confirm_page(screen)

    def page_has_next(self, page):
        if   page is LIST_DOMAINS:
            return self.has_selectable_domains()
        else:
            return page < CONFIRM_PAGE

    def page_has_back(self, page):
        return page < CONFIRM_PAGE

    def page_has_finish(self, page):
        return page is CONFIRM_PAGE

    def validate_input(self, page, errors):
        if   page is LIST_DOMAINS:
            return self.get_selected_domain() is not None
        elif page is SELECT_TARGET:
            if self.__targets.current() is None:
                errors.append("Please enter a target hostname or IP address.")
                return False
        elif page is CONFIRM_PAGE:
            if not self.__confirm.value():
                errors.append("You must confirm migrating this virtual machine to proceed.")
                return False
        return True

    def process_input(self, page):
        if page is CONFIRM_PAGE:
            self.get_libvirt().migrate_domain(self.get_selected_domain(), self.__targets.current())
            self.set_finished()

    def get_target_page(self, screen):
        ignore = screen
        self.__targets = snack.Listbox(0)
        for connection in self.get_virt_manager_config().get_connection_list():
            self.__targets.append(connection, connection)
        return [snack.Label("Select A Target Host"),
                self.__targets]

    def get_confirm_page(self, screen):
        ignore = screen
        self.__confirm = snack.Checkbox("Confirm migrating this virtual machine.")
        grid = snack.Grid(1, 1)
        grid.setField(self.__confirm, 0, 0)
        return [grid]

def MigrateDomain():
    screen = MigrateDomainConfigScreen()
    screen.start()
