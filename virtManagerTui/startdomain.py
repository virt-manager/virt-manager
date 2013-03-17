#
# startdomain.py - Copyright (C) 2009 Red Hat, Inc.
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

class StartDomainConfigScreen(DomainListConfigScreen):
    LIST_PAGE  = 1
    START_PAGE = 2

    def __init__(self):
        DomainListConfigScreen.__init__(self, "Start A Domain")

    def get_elements_for_page(self, screen, page):
        if page is self.LIST_PAGE:
            return self.get_domain_list_page(screen, created=False)
        elif page is self.START_PAGE:
            return self.get_start_domain_page(screen)

    def page_has_next(self, page):
        if page is self.LIST_PAGE:
            return self.has_selectable_domains()
        return False

    def page_has_back(self, page):
        if page is self.START_PAGE:
            return True
        return False

    def validate_input(self, page, errors):
        if page is self.LIST_PAGE:
            if self.get_selected_domain() is not None:
                domain = self.get_selected_domain()
                try:
                    if domain.is_unpauseable():
                        domain.resume()
                    else:
                        domain.startup()
                    return True
                except Exception, error:
                    errors.append("There was an error creating the domain: %s" % domain.get_name())
                    errors.append(str(error))
            else:
                errors.append("You must first select a domain to start.")

    def get_start_domain_page(self, screen):
        ignore = screen
        grid = snack.Grid(1, 1)
        grid.setField(snack.Label("%s was successfully started." % self.get_selected_domain().get_name()), 0, 0)
        return [grid]

def StartDomain():
    screen = StartDomainConfigScreen()
    screen.start()
