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

from newt_syrup.menuscreen     import MenuScreen

from adddomain      import AddDomain
from startdomain    import StartDomain
from stopdomain     import StopDomain
from pausedomain    import PauseDomain
from removedomain   import RemoveDomain
from listdomains    import ListDomains
from migratedomain  import MigrateDomain
from createuser     import CreateUser

ADD_DOMAIN     = 1
START_DOMAIN   = 2
STOP_DOMAIN    = 3
PAUSE_DOMAIN   = 4
REMOVE_DOMAIN  = 5
LIST_DOMAINS   = 6
MIGRATE_DOMAIN = 7
CREATE_USER    = 8

class NodeMenuScreen(MenuScreen):
    def __init__(self):
        MenuScreen.__init__(self, "Node Administration")

    def get_menu_items(self):
        return (("Add A Virtual Machine",     ADD_DOMAIN),
                ("Start A Virtual Machine",  START_DOMAIN),
                ("Stop A Virtual Machine",    STOP_DOMAIN),
                ("Pause A Virtual Machine",   PAUSE_DOMAIN),
                ("Remove A Virtual Machine",  REMOVE_DOMAIN),
                ("List All Virtual Machines", LIST_DOMAINS),
                ("Migrate Virtual Machine",   MIGRATE_DOMAIN),
                ("Create A User",             CREATE_USER))

    def handle_selection(self, item):
        if item is ADD_DOMAIN:
            AddDomain()
        elif item is START_DOMAIN:
            StartDomain()
        elif item is STOP_DOMAIN:
            StopDomain()
        elif item is PAUSE_DOMAIN:
            PauseDomain()
        elif item is REMOVE_DOMAIN:
            RemoveDomain()
        elif item is LIST_DOMAINS:
            ListDomains()
        elif item is MIGRATE_DOMAIN:
            MigrateDomain()
        elif item is CREATE_USER:
            CreateUser()

def NodeMenu():
    screen = NodeMenuScreen()
    screen.start()
