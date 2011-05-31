# domainconfig.py - Copyright (C) 2009 Red Hat, Inc.
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

from virtinst import Guest

class DomainConfig:
    LOCAL_INSTALL   = "local"
    NETWORK_INSTALL = "network"
    PXE_INSTALL     = "pxe"
    INSTALL_TYPE_TEXT = {LOCAL_INSTALL   : "Local CDROM/ISO",
                         NETWORK_INSTALL : "URL INstall Tree",
                         PXE_INSTALL     : "PXE Install"}

    INSTALL_SOURCE_CDROM = "cdrom"
    INSTALL_SOURCE_ISO   = "iso"

    NEW_STORAGE      = "new"
    EXISTING_STORAGE = "existing"

    def __init__(self):
        self.__guest_name = ""
        self.__install_type = DomainConfig.LOCAL_INSTALL
        self.__use_cdrom_source = True
        self.__install_location = ""
        self.__install_media = ""
        self.__iso_path = ""
        self.__install_url = ""
        self.__kickstart_url = ""
        self.__kernel_options = ""
        self.__os_type = "other"
        self.__os_variant = None
        self.__memory = 512
        self.__cpus = 1
        self.__enable_storage = True
        self.__use_local_storage = True
        self.__existing_storage = False
        self.__storage_size = 8.0
        self.__allocate_storage = True
        self.__storage_pool = ""
        self.__storage_volume = ""
        self.__network_bridge = None
        self.__mac_address = None
        self.__virt_type = None
        self.__architecture = None

    def set_guest_name(self, name):
        self.__guest_name = name

    def get_guest_name(self):
        return self.__guest_name

    def set_install_type(self, typ):
        self.__install_type = typ

    def get_install_type(self):
        return self.__install_type

    def get_install_type_text(self):
        return DomainConfig.INSTALL_TYPE_TEXT[self.get_install_type()]

    def is_install_type(self, typ):
        return self.__install_type == typ

    def set_install_location(self, location):
        self.__install_location = location

    def set_use_cdrom_source(self, use):
        self.__use_cdrom_source = use

    def get_use_cdrom_source(self):
        return self.__use_cdrom_source

    def get_install_location(self):
        return self.__install_location

    def is_install_location(self, location):
        return self.__install_location == location

    def set_install_media(self, media):
        self.__install_media = media

    def get_install_media(self):
        return self.__install_media

    def is_install_media(self, media):
        return self.__install_media == media

    def set_iso_path(self, path):
        self.__iso_path = path

    def get_iso_path(self):
        return self.__iso_path

    def set_install_url(self, url):
        self.__install_url = url

    def get_install_url(self):
        return self.__install_url

    def set_kickstart_url(self, url):
        self.__kickstart_url = url

    def get_kickstart_url(self):
        return self.__kickstart_url

    def set_kernel_options(self, options):
        self.__kernel_options = options

    def get_kernel_options(self):
        return self.__kernel_options

    def set_os_type(self, typ):
        self.__os_type = typ
        self.__os_variant = Guest.list_os_variants(typ)[0]

    def get_os_type(self):
        return self.__os_type

    def is_os_type(self, typ):
        return self.__os_type == typ

    def set_os_variant(self, variant):
        self.__os_variant = variant

    def get_os_variant(self):
        return self.__os_variant

    def is_os_variant(self, variant):
        return self.__os_variant == variant

    def set_memory(self, memory):
        self.__memory = int(memory)

    def get_memory(self):
        return self.__memory

    def set_cpus(self, cpus):
        self.__cpus = cpus

    def get_cpus(self):
        return self.__cpus

    def set_enable_storage(self, enable):
        self.__enable_storage = enable

    def get_enable_storage(self):
        return self.__enable_storage

    def set_use_local_storage(self, use):
        self.__use_local_storage = use

    def get_use_local_storage(self):
        return self.__use_local_storage

    def set_storage_size(self, size):
        self.__storage_size = size

    def get_storage_size(self):
        return self.__storage_size

    def set_allocate_storage(self, allocate):
        self.__allocate_storage = allocate

    def get_allocate_storage(self):
        return self.__allocate_storage

    def set_storage_pool(self, pool):
        self.__storage_pool = pool

    def get_storage_pool(self):
        return self.__storage_pool

    def set_storage_volume(self, volume):
        self.__storage_volume = volume

    def get_storage_volume(self):
        return self.__storage_volume

    def is_existing_storage(self, storage):
        return self.__existing_storage == storage

    def set_network_bridge(self, bridge):
        self.__network_bridge = bridge

    def get_network_bridge(self):
        return self.__network_bridge

    def set_mac_address(self, address):
        self.__mac_address = address

    def get_mac_address(self):
        return self.__mac_address

    def set_virt_type(self, typ):
        self.__virt_type = typ

    def get_virt_type(self):
        return self.__virt_type

    def is_virt_type(self, typ):
        return self.__virt_type == typ

    def set_architecture(self, architecture):
        self.__architecture = architecture

    def get_architecture(self):
        return self.__architecture

    def is_architecture(self, architecture):
        return self.__architecture == architecture
