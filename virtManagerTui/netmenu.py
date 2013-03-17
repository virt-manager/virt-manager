# mainmenu.py - Copyright (C) 2009 Red Hat, Inc.
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

from newt_syrup.menuscreen import MenuScreen

from addnetwork      import AddNetwork
from startnetwork    import StartNetwork
from stopnetwork     import StopNetwork
from removenetwork   import RemoveNetwork
from listnetworks    import ListNetworks

ADD_NETWORK      = 1
START_NETWORK    = 2
STOP_NETWORK     = 3
REMOVE_NETWORK   = 4
LIST_NETWORKS    = 5

class NetworkMenuScreen(MenuScreen):
    def __init__(self):
        MenuScreen.__init__(self, "Network Administration")

    def get_menu_items(self):
        return (("Add A Network",      ADD_NETWORK),
                ("Start A Network",    START_NETWORK),
                ("Stop A Network",     STOP_NETWORK),
                ("Remove A Network",   REMOVE_NETWORK),
                ("List Networks",      LIST_NETWORKS))

    def handle_selection(self, item):
        if   item is ADD_NETWORK:
            AddNetwork()
        elif item is START_NETWORK:
            StartNetwork()
        elif item is STOP_NETWORK:
            StopNetwork()
        elif item is REMOVE_NETWORK:
            RemoveNetwork()
        elif item is LIST_NETWORKS:
            ListNetworks()

def NetworkMenu():
    screen = NetworkMenuScreen()
    screen.start()
