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

from snack import *
import traceback

from menuscreen      import MenuScreen
from definenet       import DefineNetwork
from createnetwork   import CreateNetwork
from destroynetwork  import DestroyNetwork
from undefinenetwork import UndefineNetwork
from listnetworks    import ListNetworks

import utils
import logging

DEFINE_NETWORK   = 1
CREATE_NETWORK   = 2
DESTROY_NETWORK  = 3
UNDEFINE_NETWORK = 4
LIST_NETWORKS    = 5

class NetworkMenuScreen(MenuScreen):
    def __init__(self):
        MenuScreen.__init__(self, "Network Administration")

    def get_menu_items(self):
        return (("Define A Network",   DEFINE_NETWORK),
                ("Create A Network",   CREATE_NETWORK),
                ("Destroy A Network",  DESTROY_NETWORK),
                ("Undefine A Network", UNDEFINE_NETWORK),
                ("List Networks",      LIST_NETWORKS))

    def handle_selection(self, item):
        if   item is DEFINE_NETWORK:   DefineNetwork()
        elif item is CREATE_NETWORK:   CreateNetwork()
        elif item is DESTROY_NETWORK:  DestroyNetwork()
        elif item is UNDEFINE_NETWORK: UndefineNetwork()
        elif item is LIST_NETWORKS:    ListNetworks()

def NetworkMenu():
    screen = NetworkMenuScreen()
    screen.start()
