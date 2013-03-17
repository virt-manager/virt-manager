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

from snack import Label
from networklistconfigscreen import NetworkListConfigScreen

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
        if   page is LIST_PAGE:
            return self.get_network_list_page(screen)
        elif page is DETAILS_PAGE:
            return self.get_network_details_page(screen)

    def get_network_details_page(self, screen):
        ignore = screen
        network = self.get_selected_network()
        fields = []

        fields.append(("Basic details", None))
        fields.append(("Name", network.get_name()))
        fields.append(("Device", network.get_bridge_device()))
        fields.append(("Autostart", "Yes" if network.get_autostart() else "No"))
        fields.append(("State", "Active" if network.is_active() else "Inactive"))
        fields.append(("Autostart", "On Boot" if network.get_autostart() else "Never"))

        fields.append(("IPv4 configuration", None))
        fields.append(("Network", network.get_ipv4_network().strNormal()))

        if network.get_ipv4_dhcp_range() is not None:
            (dhcp_start, dhcp_end) = network.get_ipv4_dhcp_range()
            dhcp_start = dhcp_start.strNormal()
            dhcp_end   = dhcp_end.strNormal()
        else:
            dhcp_start = "Disabled"
            dhcp_end   = "Disabled"

        fields.append(("DHCP start", dhcp_start))
        fields.append(("DHCP end", dhcp_end))

        fields.append(("Forwarding", network.pretty_forward_mode()))

        return [Label("Network Interface Details"),
                self.create_grid_from_fields(fields)]

def ListNetworks():
    screen = ListNetworksConfigScreen()
    screen.start()
