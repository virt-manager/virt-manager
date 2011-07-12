# hostmenu.py - Copyright (C) 2009 Red Hat, Inc.
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

from changehost import ChangeHost
from addhost    import AddHost
from removehost import RemoveHost

SELECT_HOST = 1
ADD_HOST    = 2
REMOVE_HOST = 3

class HostMenuScreen(MenuScreen):
    def __init__(self):
        MenuScreen.__init__(self, "Host Menu Screen")

    def get_menu_items(self):
        return (("Select A Host", SELECT_HOST),
                ("Add A Host",    ADD_HOST),
                ("Remove A Host", REMOVE_HOST))

    def handle_selection(self, item):
        if   item is SELECT_HOST:
            ChangeHost()
        elif item is ADD_HOST:
            AddHost()
        elif item is REMOVE_HOST:
            RemoveHost()

def HostMenu():
    screen = HostMenuScreen()
    screen.start()
