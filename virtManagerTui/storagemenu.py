# storagemenu.py - Copyright (C) 2009 Red Hat, Inc.
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

from addpool       import AddStoragePool
from startpool     import StartStoragePool
from stoppool      import StopStoragePool
from removepool    import RemoveStoragePool
from addvolume     import AddStorageVolume
from removevolume  import RemoveStorageVolume
from listpools     import ListStoragePools

ADD_POOL      = 1
START_POOL    = 2
STOP_POOL     = 3
REMOVE_POOL   = 4
ADD_VOLUME    = 5
REMOVE_VOLUME = 6
LIST_POOLS    = 7

class StoragePoolMenuScreen(MenuScreen):
    def __init__(self):
        MenuScreen.__init__(self, "Storage Pool Administration")

    def get_menu_items(self):
        return (("Add A Storage Pool",      ADD_POOL),
                ("Start A Storage Pool",    START_POOL),
                ("Stop A Storage Pool",     STOP_POOL),
                ("Remove A Storage Pool",   REMOVE_POOL),
                ("Add A Storage Volume",    ADD_VOLUME),
                ("Remove A Storage Volume", REMOVE_VOLUME),
                ("List Storage Pools",      LIST_POOLS))

    def handle_selection(self, item):
        if   item is ADD_POOL:
            AddStoragePool()
        elif item is START_POOL:
            StartStoragePool()
        elif item is STOP_POOL:
            StopStoragePool()
        elif item is REMOVE_POOL:
            RemoveStoragePool()
        elif item is ADD_VOLUME:
            AddStorageVolume()
        elif item is REMOVE_VOLUME:
            RemoveStorageVolume()
        elif item is LIST_POOLS:
            ListStoragePools()

def StoragePoolMenu():
    screen = StoragePoolMenuScreen()
    screen.start()
