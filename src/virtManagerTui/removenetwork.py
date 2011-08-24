#
# removenetwork.py - Copyright (C) 2009 Red Hat, Inc.
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

from snack import Checkbox
from snack import Label
from networklistconfigscreen import NetworkListConfigScreen

LIST_PAGE     = 1
CONFIRM_PAGE  = 2
REMOVE_PAGE   = 3

class RemoveNetworkConfigScreen(NetworkListConfigScreen):
    def __init__(self):
        NetworkListConfigScreen.__init__(self, "Remove A Network")
        self.__deleted_network_name = None
        self.__confirm_remove = None

    def get_elements_for_page(self, screen, page):
        if   page is LIST_PAGE:
            return self.get_network_list_page(screen, started=False)
        elif page is CONFIRM_PAGE:
            return self.get_confirm_page(screen)
        elif page is REMOVE_PAGE:
            return self.get_remove_network_page(screen)

    def page_has_next(self, page):
        if page is LIST_PAGE:
            return self.has_selectable_networks()
        if page is CONFIRM_PAGE:
            return True
        return False

    def page_has_back(self, page):
        if page is CONFIRM_PAGE:
            return True
        if page is REMOVE_PAGE:
            return True
        return False

    def get_back_page(self, page):
        if   page is CONFIRM_PAGE:
            return LIST_PAGE
        elif page is REMOVE_PAGE:
            return LIST_PAGE

    def validate_input(self, page, errors):
        if   page is LIST_PAGE:
            return True
        elif page is CONFIRM_PAGE:
            network = self.get_selected_network()
            if self.__confirm_remove.value():
                self.__deleted_network_name = network.get_name()
                network.delete()
                return True
            else:
                errors.append("You must confirm undefining %s." % network.get_name())
        elif page is REMOVE_PAGE:
            return True
        return False

    def get_confirm_page(self, screen):
        ignore = screen
        network = self.get_selected_network()
        self.__confirm_remove = Checkbox("Check here to confirm undefining %s." % network.get_name())
        fields = []
        fields.append((self.__confirm_remove, None))
        return [self.create_grid_from_fields(fields)]

    def get_remove_network_page(self, screen):
        ignore = screen
        network_name = self.__deleted_network_name
        return [Label("Network has been removed: %s" % network_name)]

def RemoveNetwork():
    screen = RemoveNetworkConfigScreen()
    screen.start()
