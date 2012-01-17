# changehost.py - Copyright (C) 2009 Red Hat, Inc.
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

import logging
from hostlistconfigscreen import HostListConfigScreen

CONNECTION_LIST_PAGE = 1
CONNECTED_PAGE       = 2

class ChangeHostConfigScreen(HostListConfigScreen):
    def __init__(self):
        HostListConfigScreen.__init__(self, "")

    def get_title(self):
        return "Currently: %s" % self.get_libvirt().get_url()

    def get_elements_for_page(self, screen, page):
        if   page is CONNECTION_LIST_PAGE:
            return self.get_connection_list_page(screen)
        elif page is CONNECTED_PAGE:
            return self.get_connected_page(screen)

    def process_input(self, page):
        if   page is CONNECTION_LIST_PAGE:
            logging.info("Changing libvirt connection to %s",
                         self.get_selected_connection())
            self.get_libvirt().open_connection(self.get_selected_connection())
        elif page is CONNECTED_PAGE:
            self.set_finished()

    def page_has_next(self, page):
        if page is CONNECTION_LIST_PAGE:
            return self.has_selectable_connections()
        return False

    def page_has_back(self, page):
        return page > CONNECTION_LIST_PAGE

    def page_has_finish(self, page):
        return page is CONNECTED_PAGE

    def get_connected_page(self, screen):
        ignore = screen
        return [snack.Label("Connected to %s" % self.get_selected_connection())]

def ChangeHost():
    screen = ChangeHostConfigScreen()
    screen.start()
