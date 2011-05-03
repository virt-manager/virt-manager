# listnetworks.py - Copyright (C) 2009 Red Hat, Inc.
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

from configscreen import *

LIST_PAGE    = 1
DETAILS_PAGE = 2

class ListNetworksConfigScreen(NetworkListConfigScreen):
    def __init__(self):
        NetworkListConfigScreen.__init__(self, "List Networks")

    def page_has_next(self, page):
        return (page is LIST_PAGE) and self.has_selectable_networks()

    def page_has_back(self, page):
        return (page is DETAILS_PAGE)

    def get_elements_for_page(self, screen, page):
        if   page is LIST_PAGE:    return self.get_network_list_page(screen)
        elif page is DETAILS_PAGE: return self.get_network_details_page(screen)

    def get_network_details_page(self, screen):
        network = self.get_libvirt().get_network(self.get_selected_network())
        grid = Grid(2, 3)
        grid.setField(Label("Name:"), 0, 0, anchorRight = 1)
        grid.setField(Label(network.name()), 1, 0, anchorLeft = 1)
        grid.setField(Label("Autostart:"), 0, 1, anchorRight = 1)
        label = "No"
        if network.autostart(): label = "Yes"
        grid.setField(Label(label), 1, 1, anchorLeft = 1)
        if network.bridgeName() is not "":
            grid.setField(Label("Bridge:"), 0, 2, anchorRight = 1)
            grid.setField(Label(network.bridgeName()), 1, 2, anchorLeft = 1)
        return [Label("Network Interface Details"),
                grid]

def ListNetworks():
    screen = ListNetworksConfigScreen()
    screen.start()
