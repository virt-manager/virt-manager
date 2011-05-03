#!/usr/bin/env python
#
# destroynetwork.py - Copyright (C) 2009 Red Hat, Inc.
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

LIST_PAGE    = 1
DESTROY_PAGE = 2

class DestroyNetworkConfigScreen(NetworkListConfigScreen):
    def __init__(self):
        NetworkListConfigScreen.__init__(self, "Destroy A Network")

    def get_elements_for_page(self, screen, page):
        if   page is LIST_PAGE:    return self.get_network_list_page(screen, defined = False)
        elif page is DESTROY_PAGE: return self.get_destroy_network_page(screen)

    def page_has_next(self, page):
        if page is LIST_PAGE: return self.has_selectable_networks()
        return False

    def page_has_back(self, page):
        if page is DESTROY_PAGE: return True
        return False

    def validate_input(self, page, errors):
        if page is LIST_PAGE:
            network = self.get_selected_network()
            self.get_libvirt().destroy_network(network)
            return True
        return False

    def get_destroy_network_page(self, screen):
        return [Label("Network Destroyed"),
                Label("%s has been destroyed." % self.get_selected_network())]

def DestroyNetwork():
    screen = DestroyNetworkConfigScreen()
    screen.start()
