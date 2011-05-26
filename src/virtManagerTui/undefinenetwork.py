#!/usr/bin/env python
#
# undefinenetwork.py - Copyright (C) 2009 Red Hat, Inc.
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

from snack import *
from configscreen import *

LIST_PAGE     = 1
CONFIRM_PAGE  = 2
UNDEFINE_PAGE = 3

class UndefineNetworkConfigScreen(NetworkListConfigScreen):
    def __init__(self):
        NetworkListConfigScreen.__init__(self, "Undefine A Network")

    def get_elements_for_page(self, screen, page):
        if   page is LIST_PAGE:     return self.get_network_list_page(screen, started = False)
        elif page is CONFIRM_PAGE:  return self.get_confirm_page(screen)
        elif page is UNDEFINE_PAGE: return self.get_undefine_network_page(screen)

    def page_has_next(self, page):
        if page is LIST_PAGE:    return self.has_selectable_networks()
        if page is CONFIRM_PAGE: return True
        return False

    def page_has_back(self, page):
        if page is CONFIRM_PAGE: return True
        if page is UNDEFINE_PAGE: return True
        return False

    def get_back_page(self, page):
        if   page is CONFIRM_PAGE: return LIST_PAGE
        elif page is UNDEFINE_PAGE: return LIST_PAGE

    def validate_input(self, page, errors):
        if   page is LIST_PAGE: return True
        elif page is CONFIRM_PAGE:
            network = self.get_selected_network()
            if self.__confirm_undefine.value():
                self.__deleted_network_name = network.get_name()
                network.delete()
                return True
            else:
                errors.append("You must confirm undefining %s." % network.get_name())
        elif page is UNDEFINE_PAGE: return True
        return False

    def get_confirm_page(self, screen):
        network = self.get_selected_network()
        self.__confirm_undefine = Checkbox("Check here to confirm undefining %s." % network.get_name())
        grid = Grid(1, 1)
        grid.setField(self.__confirm_undefine, 0, 0)
        return [grid]

    def get_undefine_network_page(self, screen):
        network_name = self.__deleted_network_name
        return [Label("Network has been undefined: %s" % network_name)]

def UndefineNetwork():
    screen = UndefineNetworkConfigScreen()
    screen.start()
