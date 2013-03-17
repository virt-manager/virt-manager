# vmmconfigscreen.py - Copyright (C) 2011 Red Hat, Inc.
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

from snack import Grid
from snack import Label

from types import StringType

from newt_syrup import configscreen
from libvirtworker import LibvirtWorker, VirtManagerConfig

BACK_BUTTON   = "back"
NEXT_BUTTON   = "next"
CANCEL_BUTTON = "cancel"
FINISH_BUTTON = "finish"

class VmmTuiConfigScreen(configscreen.ConfigScreen):
    '''Enables the creation of navigable, multi-paged configuration screens.'''

    def __init__(self, title):
        configscreen.ConfigScreen.__init__(self, title)
        self.__libvirt = LibvirtWorker()
        self.__vm_config = VirtManagerConfig()

    def get_libvirt(self):
        return self.__libvirt

    def get_virt_manager_config(self):
        return self.__vm_config

    def create_grid_from_fields(self, fields):
        '''
        Takes a series of fields names and values and returns a Grid composed
        of Labels for that screen.

        If the value element is specified, it can be either a String or else
        one of the UI widgets.

        Keyword arguments:
        fields -- A two-dimensional array of label and value pairs.
        '''
        grid = Grid(2, len(fields))
        row = 0
        for field in fields:
            if field[1] is not None:
                grid.setField(Label("%s : " % field[0]), 0, row, anchorRight=1)
                # if the value is a String, then wrap it in a Label
                # otherwise just add it
                value = field[1]
                if type(value) == StringType:
                    value = Label(field[1])
                grid.setField(value, 1, row, anchorLeft=1)
            else:
                # here the label itself might be a string or a widget
                value = field[0]
                if type(value) == StringType:
                    value = Label(field[0])
                grid.setField(value, 0, row)
            row += 1

        return grid
