#
# removedomain.py - Copyright (C) 2009 Red Hat, Inc.
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

class RemoveDomainConfigScreen(DomainListConfigScreen):
    LIST_PAGE     = 1
    CONFIRM_PAGE  = 2
    REMOVE_PAGE = 3

    def __init__(self):
        DomainListConfigScreen.__init__(self, "Remove A Domain")
        self.__confirm_remove = None

    def get_elements_for_page(self, screen, page):
        if   page is self.LIST_PAGE:
            return self.get_domain_list_page(screen)
        elif page is self.CONFIRM_PAGE:
            return self.get_confirm_page(screen)
        elif page is self.REMOVE_PAGE:
            return self.get_remove_page(screen)

    def page_has_next(self, page):
        if   page is self.LIST_PAGE:
            return self.has_selectable_domains()
        elif page is self.CONFIRM_PAGE:
            return True
        return False

    def page_has_back(self, page):
        if   page is self.CONFIRM_PAGE:
            return True
        elif page is self.REMOVE_PAGE:
            return True
        return False

    def get_back_page(self, page):
        if   page is self.CONFIRM_PAGE:
            return self.LIST_PAGE
        elif page is self.REMOVE_PAGE:
            return self.LIST_PAGE

    def validate_input(self, page, errors):
        if page is self.LIST_PAGE:
            if self.get_selected_domain() is not None:
                return True
            else:
                errors.append("You must first select a domain.")
        elif page is self.CONFIRM_PAGE:
            if self.__confirm_remove.value():
                domain = self.get_selected_domain()
                try:
                    domain.delete()
                    return True
                except Exception, error:
                    errors.append("Failed to remove %s." % domain)
                    errors.append(str(error))
            else:
                errors.append("You must confirm undefining the domain to proceed.")
        return False

    def get_confirm_page(self, screen):
        ignore = screen
        self.__confirm_remove = snack.Checkbox("Check here to confirm undefining %s." % self.get_selected_domain().get_name(), 0)
        grid = snack.Grid(1, 1)
        grid.setField(self.__confirm_remove, 0, 0)
        return [grid]

    def get_remove_page(self, screen):
        ignore = screen
        grid = snack.Grid(1, 1)
        grid.setField(snack.Label("%s has been removed." % self.get_selected_domain().get_name()), 0, 0)
        return [grid]

def RemoveDomain():
    screen = RemoveDomainConfigScreen()
    screen.start()
