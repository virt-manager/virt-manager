#!/usr/bin/env python
#
# startnetwork.py - Copyright (C) 2009 Red Hat, Inc.
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
from networklistconfigscreen import NetworkListConfigScreen

LIST_PAGE   = 1
START_PAGE = 2

class StartNetworkConfigScreen(NetworkListConfigScreen):
    def __init__(self):
        NetworkListConfigScreen.__init__(self, "Start A Network")

    def get_elements_for_page(self, screen, page):
        if   page is LIST_PAGE:
            return self.get_network_list_page(screen, started=False)
        elif page is START_PAGE:
            return self.get_start_network_page(screen)

    def page_has_next(self, page):
        if page is LIST_PAGE:
            return self.has_selectable_networks()

    def page_has_back(self, page):
        return (page is START_PAGE)

    def validate_input(self, page, errors):
        if page is LIST_PAGE:
            network = self.get_selected_network()
            if network.is_active():
                errors.append("%s is already started." % network.get_name())
            else:
                network.start()
                return True

    def get_start_network_page(self, screen):
        ignore = screen
        network = self.get_selected_network()
        return [Label("%s was successfully started." % network.get_name())]

def StartNetwork():
    screen = StartNetworkConfigScreen()
    screen.start()
