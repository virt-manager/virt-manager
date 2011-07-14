# volumeconfig.py - Copyright (C) 2009 Red Hat, Inc.
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

import virtinst
from virtinst import Storage

class StorageVolumeConfig:
    def __init__(self):
        self.__pool = None
        self.__name = ""
        self.__formats = None
        self.__format = None
        self.__max_capacity = 10000
        self.__allocation = 0
        self.__pool_type = None
        self.__volume_class = None

    def set_pool(self, pool):
        self.__pool = pool
        self.__formats = None
        self.__pool_type = virtinst.util.get_xml_path(self.__pool.XMLDesc(0), '/pool/@type')
        self.__volume_class = Storage.StoragePool.get_volume_for_pool(self.__pool_type)

    def get_pool(self):
        return self.__pool

    def create_volume(self):
        volume = self.__volume_class(name=self.__name + ".img",
                                     allocation=self.__allocation * (1024 ** 2),
                                     capacity=self.__max_capacity * (1024 ** 2),
                                     pool=self.__pool)
        volume.pool = self.__pool
        if self.needs_format():
            volume.format = self.__format
        return volume

    def set_name(self, name):
        self.__name = name

    def get_name(self):
        return self.__name

    def needs_format(self):
        if self.__pool.__dict__.keys().count("get_formats_for_pool") > 0:
            return self.__pool.get_formats_for_pool() is not 0
        else:
            return False

    def get_formats_for_pool(self):
        if self.__formats is None:
            self.__formats = self.__volume_class.formats
        return self.__formats

    def set_format(self, fmt):
        self.__format = fmt

    def get_format(self):
        return self.__format

    def set_max_capacity(self, capacity):
        self.__max_capacity = capacity

    def get_max_capacity(self):
        return self.__max_capacity

    def set_allocation(self, allocation):
        self.__allocation = allocation

    def get_allocation(self):
        return self.__allocation
