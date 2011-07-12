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

from newt_syrup import configscreen
from halworker import HALWorker
from libvirtworker import LibvirtWorker, VirtManagerConfig

BACK_BUTTON   = "back"
NEXT_BUTTON   = "next"
CANCEL_BUTTON = "cancel"
FINISH_BUTTON = "finish"

class VmmTuiConfigScreen(configscreen.ConfigScreen):
    '''Enables the creation of navigable, multi-paged configuration screens.'''

    def __init__(self, title):
        configscreen.ConfigScreen.__init__(self, title)
        self.__hal = HALWorker()
        self.__libvirt = LibvirtWorker()
        self.__vm_config = VirtManagerConfig()

    def get_hal(self):
        return self.__hal

    def get_libvirt(self):
        return self.__libvirt

    def get_virt_manager_config(self):
        return self.__vm_config

