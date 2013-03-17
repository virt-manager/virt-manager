# poolconfig.py - Copyright (C) 2009 Red Hat, Inc.
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

from virtinst import Storage

ROOT_TARGET_PATH = "/var/lib/libvirt/images/%s"

class PoolConfig:
    def __init__(self, libvirt):
        self.__libvirt = libvirt
        self.__name = ""
        self.set_type(None)
        self.__format = None
        self.__hostname = ""
        self.__target_path = ""
        self.__source_path = ""
        self.__build_pool  = False

        self.__needs_source_path = None
        self.__needs_target_path = None
        self.__pool = None
        self.__needs_hostname = None
        self.__needs_build_pool = None
        self.__needs_format = None
        self.__type = None

    def get_pool(self):
        return self.__pool

    def set_name(self, name):
        self.__name = name

    def get_name(self):
        return self.__name

    def set_type(self, pooltype):
        self.__type = pooltype
        self.__needs_target_path = False
        self.__needs_format      = False
        self.__needs_target_path = False
        self.__needs_format      = False
        self.__needs_hostname    = False
        self.__needs_source_path = False
        self.__needs_build_pool  = False
        if pooltype is not None:
            if   pooltype is Storage.StoragePool.TYPE_DIR:
                self.__needs_target_path = True
                self.__target_path = ROOT_TARGET_PATH % self.__name
                self.__build_pool = True
            elif pooltype is Storage.StoragePool.TYPE_DISK:
                self.__needs_target_path = True
                self.__needs_format      = True
                self.__needs_source_path = True
                self.__needs_build_pool  = True
            elif pooltype is Storage.StoragePool.TYPE_FS:
                self.__needs_target_path = True
                self.__needs_format      = True
                self.__needs_source_path = True
                self.__build_pool  = True
            elif pooltype is Storage.StoragePool.TYPE_ISCSI:
                self.__needs_target_path = True
                self.__needs_hostname    = True
                self.__needs_source_path = True
                self.__build_pool  = False
            elif pooltype is Storage.StoragePool.TYPE_LOGICAL:
                self.__needs_target_path = True
                self.__needs_source_path = True
                self.__needs_build_pool  = True
            elif pooltype is Storage.StoragePool.TYPE_NETFS:
                self.__needs_target_path = True
                self.__needs_format      = True
                self.__needs_hostname    = True
                self.__needs_source_path = True
                self.__build_pool  = True
            # create pool
            pool_class = Storage.StoragePool.get_pool_class(self.__type)
            self.__pool = pool_class(name=self.__name,
                                     conn=self.__libvirt.get_connection())
            if self.__needs_format:
                self.__format = self.__pool.formats[0]
        else:
            self.__type = Storage.StoragePool.get_pool_types()[0]

    def get_type(self):
        return self.__type

    def needs_target_path(self):
        return self.__needs_target_path

    def needs_format(self):
        return self.__needs_format

    def needs_hostname(self):
        return self.__needs_hostname

    def source_must_be_absolute(self):
        if self.__type is Storage.StoragePool.TYPE_ISCSI:
            return False
        return True

    def needs_source_path(self):
        return self.__needs_source_path

    def needs_build_pool(self):
        return self.__needs_build_pool

    def set_target_path(self, path):
        self.__target_path = path

    def get_target_path(self):
        return self.__target_path

    def get_formats(self):
        return self.__pool.formats

    def set_format(self, fmt):
        self.__format = fmt

    def get_format(self):
        return self.__format

    def set_hostname(self, hostname):
        self.__hostname = hostname

    def get_hostname(self):
        return self.__hostname

    def set_source_path(self, source_path):
        self.__source_path = source_path

    def get_source_path(self):
        return self.__source_path

    def set_build_pool(self, build_pool):
        self.__build_pool = build_pool

    def  get_build_pool(self):
        return self.__build_pool
