# halworker.py - Copyright (C) 2009 Red Hat, Inc.
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

import dbus

class HALWorker:
    '''Provides utilities for working with HAL to get hardware information.'''
    def __init__(self):
        self.__bus = dbus.SystemBus()
        hobj = self.__bus.get_object("org.freedesktop.Hal", "/org/freedesktop/Hal/Manager")
        self.__conn = dbus.Interface(hobj, "org.freedesktop.Hal.Manager")

    def list_installable_volumes(self):
        result = {}
        for udi in self.__conn.FindDeviceByCapability("volume"):
            device = self.__bus.get_object("org.freedesktop.Hal", udi)
            info = dbus.Interface(device, "org.freedesktop.Hal.Device")
            if info.GetProperty("volume.is_disc"):
                if info.GetProperty("volume.disc.has_data"):
                    result[str(info.GetProperty("block.device"))] = info.GetProperty("volume.label")
        return result

    def list_network_devices(self):
        result = []
        for udi in self.__conn.FindDeviceByCapability("net"):
            device = self.__bus.get_object("org.freedesktop.Hal", udi)
            info = dbus.Interface(device, "org.freedesktop.Hal.Device")
            result.append(info.GetProperty("net.interface"))
        return result
