#
# adddomain.py - Copyright (C) 2009 Red Hat, Inc.
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

import snack
import os

from vmmconfigscreen import VmmTuiConfigScreen
from createmeter  import CreateMeter
from domainconfig import DomainConfig

from virtinst import Guest

VM_DETAILS_PAGE      = 1
LOCAL_INSTALL_PAGE   = 2
SELECT_CDROM_PAGE    = 3
SELECT_ISO_PAGE      = 4
NETWORK_INSTALL_PAGE = 5
OS_TYPE_PAGE         = 6
OS_VARIANT_PAGE      = 7
RAM_CPU_PAGE         = 8
ENABLE_STORAGE_PAGE  = 9
LOCAL_STORAGE_PAGE   = 10
SELECT_POOL_PAGE     = 11
SELECT_VOLUME_PAGE   = 12
BRIDGE_PAGE          = 13
VIRT_DETAILS_PAGE    = 14
CONFIRM_PAGE         = 15

LOCATION = "location"
KICKSTART = "kickstart"
KERNELOPTS = "kernel.options"
OS_TYPE = "os.type"
OS_VARIANT = "os.variant"
MEMORY = "memory"
CPUS = "cpus"

class DomainConfigScreen(VmmTuiConfigScreen):
    def __init__(self):
        VmmTuiConfigScreen.__init__(self, "Create A New Virtual Machine")
        self.__config = DomainConfig()
        self.__config.set_architecture(self.get_libvirt().get_default_architecture())
        self.__config.set_virt_type(self.get_libvirt().get_default_virt_type())

        self.__guest_name = None
        self.__install_url = None
        self.__storage_volume = None
        self.__network_bridges = None
        self.__os_types = None
        self.__os_variants = None
        self.__virt_types = None
        self.__storage_size = None
        self.__storage_type = None
        self.__storage_pool = None
        self.__kickstart_url = None
        self.__kernel_options = None
        self.__install_type = None
        self.__cpus = None
        self.__memory = None
        self.__allocate_storage = None
        self.__enable_storage = None
        self.__has_volumes = None
        self.__install_media = None
        self.__has_pools = None
        self.__mac_address = None
        self.__architectures = None
        self.__iso_path = None
        self.__install_source = None
        self.__has_install_media = None

    def get_elements_for_page(self, screen, page):
        if page is VM_DETAILS_PAGE:
            return self.get_vm_details_page(screen)
        elif page is LOCAL_INSTALL_PAGE:
            return self.get_local_install_page(screen)
        elif page is SELECT_CDROM_PAGE:
            return self.get_select_cdrom_page(screen)
        elif page is SELECT_ISO_PAGE:
            return self.get_select_iso_page(screen)
        elif page is NETWORK_INSTALL_PAGE:
            return self.get_network_install_page(screen)
        elif page is OS_TYPE_PAGE:
            return self.get_os_type_page(screen)
        elif page is OS_VARIANT_PAGE:
            return self.get_os_variant_page(screen)
        elif page is RAM_CPU_PAGE:
            return self.get_ram_and_cpu_page(screen)
        elif page is ENABLE_STORAGE_PAGE:
            return self.get_enable_storage_page(screen)
        elif page is LOCAL_STORAGE_PAGE:
            return self.get_local_storage_page(screen)
        elif page is SELECT_POOL_PAGE:
            return self.get_select_pool_page(screen)
        elif page is SELECT_VOLUME_PAGE:
            return self.get_select_volume_page(screen)
        elif page is BRIDGE_PAGE:
            return self.get_bridge_page(screen)
        elif page is VIRT_DETAILS_PAGE:
            return self.get_virt_details_page(screen)
        elif page is CONFIRM_PAGE:
            return self.get_confirm_page(screen)
        return []

    def get_page_list(self):
        return ["Virtual Machine Details",
                "Local Installation Details",
                "Setup CD-ROM Device",
                "Setup ISO File",
                "Setup Network Installation",
                "Select Operating System Type",
                "Select Operating System Variant",
                "Set Memory Size",
                "Enable Storage",
                "Setup Local Storage",
                "Select Storage Pool",
                "Select Storage Volume",
                "Setup Bridge",
                "Review Virtual Machine Details",
                "Confirm Virtual Machine"]

    def validate_input(self, page, errors):
        if page is VM_DETAILS_PAGE:
            if len(self.__guest_name.value()) > 0:
                if self.get_libvirt().domain_exists(self.__guest_name.value()):
                    errors.append("Guest name '%s' is already in use." % self.__guest_name.value())
                else:
                    return True
            else:
                errors.append("Guest name must be a string between 0 and 50 characters.")
        elif page is LOCAL_INSTALL_PAGE:
            if self.__install_source.getSelection() == DomainConfig.INSTALL_SOURCE_CDROM:
                return True
            elif self.__install_source.getSelection() == DomainConfig.INSTALL_SOURCE_ISO:
                return True
        elif page is SELECT_CDROM_PAGE:
            if self.__install_media.getSelection() != None:
                if len(self.get_libvirt().list_installable_volumes()) == 0:
                    errors.append("No installable media detected.")
                else:
                    return True
            else:
                errors.append("You must select an install media.")
        elif page is SELECT_ISO_PAGE:
            if len(self.__iso_path.value()) > 0:
                if os.path.exists(self.__iso_path.value()):
                    if os.path.isfile(self.__iso_path.value()):
                        return True
                    else:
                        errors.append("%s is not a file." % self.__iso_path.value())
                else:
                    errors.append("No such install media exists:")
                    errors.append(self.__iso_path.value())
            else:
                errors.append("An install media selection is required.")
        elif page is NETWORK_INSTALL_PAGE:
            if len(self.__install_url.value()) > 0:
                return True
            else:
                errors.append("An install tree is required.")
        elif page is OS_TYPE_PAGE:
            return True
        elif page is OS_VARIANT_PAGE:
            return True
        elif page is RAM_CPU_PAGE:
            if (len(self.__memory.value()) > 0 and len(self.__cpus.value()) > 0) \
                    and  (int(self.__memory.value()) > 0 and int(self.__cpus.value()) > 0):
                return True
            else:
                if len(self.__memory.value()) == 0:
                    errors.append("A value must be entered for memory.")
                elif int(self.__memory.value()) <= 0:
                    errors.append("A positive integer value must be entered for memory.")
                if len(self.__cpus.value()) == 0:
                    errors.append("A value must be entered for CPUs.")
                elif int(self.__cpus.value()) <= 0:
                    errors.append("A positive integer value must be entered for memory.")
        elif page is ENABLE_STORAGE_PAGE:
            return True
        elif page is LOCAL_STORAGE_PAGE:
            if len(self.__storage_size.value()) > 0:
                if float(self.__storage_size.value()) > 0:
                    return True
                else:
                    errors.append("A positive value must be entered for the storage size.")
            else:
                errors.append("A value must be entered for the storage size.")
        elif page is SELECT_POOL_PAGE:
            if self.__storage_pool.getSelection() is not None:
                return True
            else:
                errors.append("Please select a storage pool.")
        elif page is SELECT_VOLUME_PAGE:
            if self.__storage_volume.getSelection() is not None:
                return True
            else:
                errors.append("Please select a storage volume.")
        elif page is BRIDGE_PAGE:
            if self.__network_bridges.getSelection() != None:
                if len(self.__mac_address.value()) > 0:
                    # TODO: regex check the format
                    return True
                else:
                    errors.append("MAC address must be supplied.")
            else:
                errors.append("A network bridge must be selected.")
        elif page is VIRT_DETAILS_PAGE:
            if self.__virt_types.getSelection() != None and self.__architectures.getSelection() != None:
                return True
            if self.__virt_types.getSelection() is None:
                errors.append("Please select a virtualization type.")
            if self.__architectures.getSelection() is None:
                errors.append("Please selection an architecture.")
        elif page is CONFIRM_PAGE:
            return True
        return False

    def process_input(self, page):
        if page is VM_DETAILS_PAGE:
            self.__config.set_guest_name(self.__guest_name.value())
            self.__config.set_install_type(self.__install_type.getSelection())
        elif page is LOCAL_INSTALL_PAGE:
            self.__config.set_use_cdrom_source(self.__install_source.getSelection() == DomainConfig.INSTALL_SOURCE_CDROM)
        elif page is SELECT_CDROM_PAGE:
            self.__config.set_install_media(self.__install_media.getSelection())
        elif page is SELECT_ISO_PAGE:
            self.__config.set_iso_path(self.__iso_path.value())
        elif page is NETWORK_INSTALL_PAGE:
            self.__config.set_install_url(self.__install_url.value())
            self.__config.set_kickstart_url(self.__kickstart_url.value())
            self.__config.set_kernel_options(self.__kernel_options.value())
        elif page is OS_TYPE_PAGE:
            self.__config.set_os_type(self.__os_types.getSelection())
        elif page is OS_VARIANT_PAGE:
            self.__config.set_os_variant(self.__os_variants.getSelection())
        elif page is RAM_CPU_PAGE:
            self.__config.set_memory(int(self.__memory.value()))
            self.__config.set_cpus(int(self.__cpus.value()))
        elif page is ENABLE_STORAGE_PAGE:
            self.__config.set_enable_storage(self.__enable_storage.value())
            if self.__storage_type.getSelection() == DomainConfig.NEW_STORAGE:
                self.__config.set_use_local_storage(True)
            elif self.__storage_type.getSelection() == DomainConfig.EXISTING_STORAGE:
                self.__config.set_use_local_storage(False)
        elif page is LOCAL_STORAGE_PAGE:
            self.__config.set_storage_size(float(self.__storage_size.value()))
            self.__config.set_allocate_storage(self.__allocate_storage.value())
        elif page is SELECT_POOL_PAGE:
            self.__config.set_use_local_storage(False)
            self.__config.set_storage_pool(self.__storage_pool.getSelection())
        elif page is SELECT_VOLUME_PAGE:
            self.__config.set_storage_volume(self.__storage_volume.getSelection())
            volume = self.get_libvirt().get_storage_volume(self.__config.get_storage_pool(),
                                                           self.__config.get_storage_volume())
            self.__config.set_storage_size(volume.info()[1] / 1024.0 ** 3)
        elif page is BRIDGE_PAGE:
            self.__config.set_network_bridge(self.__network_bridges.getSelection())
        elif page is VIRT_DETAILS_PAGE:
            self.__config.set_virt_type(self.__virt_types.getSelection())
            self.__config.set_architecture(self.__architectures.getSelection())
        elif page is CONFIRM_PAGE:
            self.get_libvirt().define_domain(self.__config, CreateMeter())
            self.set_finished()

    def get_back_page(self, page):
        result = page
        if page is OS_TYPE_PAGE:
            install_type = self.__config.get_install_type()
            if install_type == DomainConfig.LOCAL_INSTALL:
                if self.__config.get_use_cdrom_source():
                    result = SELECT_CDROM_PAGE
                else:
                    result = SELECT_ISO_PAGE
            elif install_type == DomainConfig.NETWORK_INSTALL:
                result = NETWORK_INSTALL_PAGE
            elif install_type == DomainConfig.PXE_INSTALL:
                result = VM_DETAILS_PAGE
        elif page is LOCAL_STORAGE_PAGE or page is SELECT_VOLUME_PAGE:
            result = ENABLE_STORAGE_PAGE
        elif page is SELECT_POOL_PAGE:
            result = ENABLE_STORAGE_PAGE
        elif page is NETWORK_INSTALL_PAGE:
            result = VM_DETAILS_PAGE
        elif page is SELECT_CDROM_PAGE or page == SELECT_ISO_PAGE:
            result = LOCAL_INSTALL_PAGE
        elif page is BRIDGE_PAGE:
            if self.__config.get_use_local_storage():
                result = LOCAL_STORAGE_PAGE
            else:
                result = SELECT_VOLUME_PAGE
        else:
            if page > 1:
                result = page - 1
        return result

    def get_next_page(self, page):
        result = page
        if page is VM_DETAILS_PAGE:
            install_type = self.__config.get_install_type()
            if install_type == DomainConfig.LOCAL_INSTALL:
                result = LOCAL_INSTALL_PAGE
            elif install_type == DomainConfig.NETWORK_INSTALL:
                result = NETWORK_INSTALL_PAGE
            elif install_type == DomainConfig.PXE_INSTALL:
                result = OS_TYPE_PAGE
        elif page is LOCAL_INSTALL_PAGE:
            if self.__config.get_use_cdrom_source():
                result = SELECT_CDROM_PAGE
            else:
                result = SELECT_ISO_PAGE
        elif page is SELECT_CDROM_PAGE or page == SELECT_ISO_PAGE:
            result = OS_TYPE_PAGE
        elif page is NETWORK_INSTALL_PAGE:
            result = OS_TYPE_PAGE
        elif page is ENABLE_STORAGE_PAGE:
            result = BRIDGE_PAGE
            if self.__config.get_enable_storage():
                if self.__config.get_use_local_storage():
                    result = LOCAL_STORAGE_PAGE
                else:
                    result = SELECT_POOL_PAGE
        elif page is LOCAL_STORAGE_PAGE:
            result = BRIDGE_PAGE
        else:
            result = page + 1
        return result

    def page_has_finish(self, page):
        if page is CONFIRM_PAGE:
            return True
        return False

    def page_has_next(self, page):
        if   page is SELECT_POOL_PAGE:
            return self.__has_pools
        elif page is SELECT_VOLUME_PAGE:
            return self.__has_volumes
        elif page is SELECT_CDROM_PAGE:
            return self.__has_install_media
        elif page < CONFIRM_PAGE:
            return True

    def get_vm_details_page(self, screen):
        self.__guest_name = snack.Entry(50, self.__config.get_guest_name())
        self.__install_type = snack.RadioBar(screen, (("Local install media (ISO image or CDROM)",
                                                 DomainConfig.LOCAL_INSTALL,
                                                 self.__config.is_install_type(DomainConfig.LOCAL_INSTALL)),
                                                ("Network Install (HTTP, FTP, or NFS)",
                                                 DomainConfig.NETWORK_INSTALL,
                                                 self.__config.is_install_type(DomainConfig.NETWORK_INSTALL)),
                                                ("Network Boot (PXE)",
                                                 DomainConfig.PXE_INSTALL,
                                                 self.__config.is_install_type(DomainConfig.PXE_INSTALL))))
        grid = snack.Grid(2, 3)
        grid.setField(snack.Label("Name:"), 0, 0, anchorRight=1)
        grid.setField(self.__guest_name, 1, 0, anchorLeft=1)
        grid.setField(snack.Label("Choose how you would like to install the operating system"), 1, 1, anchorLeft=1, anchorTop=1)
        grid.setField(self.__install_type, 1, 2, anchorLeft=1)
        return [snack.Label("Enter your machine details"),
                grid]

    def get_local_install_page(self, screen):
        self.__install_source = snack.RadioBar(screen, (("Use CDROM or DVD",
                                                   DomainConfig.INSTALL_SOURCE_CDROM,
                                                   self.__config.get_use_cdrom_source()),
                                                  ("Use ISO image",
                                                   DomainConfig.INSTALL_SOURCE_ISO,
                                                   self.__config.get_use_cdrom_source() is False)))
        grid = snack.Grid(1, 1)
        grid.setField(self.__install_source, 0, 0, anchorLeft=1)
        return [snack.Label("Locate your install media"),
                grid]

    def get_select_cdrom_page(self, screen):
        fields = []
        self.__has_install_media = False
        devs = self.get_libvirt().list_installable_volumes()
        if len(devs) > 0:
            drives = []
            for dev in devs:
                row = [dev.pretty_label(), dev.get_path(),
                       self.__config.is_install_media(dev.get_path())]
                drives.append(row)
            if len(drives) > 0:
                self.__has_install_media = True
                self.__install_media = snack.RadioBar(screen, (drives))
                fields.append((self.__install_media, None))
        if self.__has_install_media == False:
            fields.append(("No media detected.", None))
        return [snack.Label("Select the install media"),
                self.create_grid_from_fields(fields)]

    def get_select_iso_page(self, screen):
        ignore = screen
        self.__iso_path = snack.Entry(50, self.__config.get_iso_path())
        grid = snack.Grid(1, 2)
        grid.setField(snack.Label("Enter ISO path:"), 0, 0, anchorLeft=1)
        grid.setField(self.__iso_path, 0, 1, anchorLeft=1)
        return [snack.Label("Enter the full path to an install ISO"),
                grid]

    def get_network_install_page(self, screen):
        ignore = screen
        self.__install_url    = snack.Entry(50, self.__config.get_install_url())
        self.__kickstart_url  = snack.Entry(50, self.__config.get_kickstart_url())
        self.__kernel_options = snack.Entry(50, self.__config.get_kernel_options())
        grid = snack.Grid(2, 3)
        grid.setField(snack.Label("URL:"), 0, 0, anchorRight=1)
        grid.setField(self.__install_url, 1, 0, anchorLeft=1)
        grid.setField(snack.Label("Kickstart URL:"), 0, 1, anchorRight=1)
        grid.setField(self.__kickstart_url, 1, 1, anchorLeft=1)
        grid.setField(snack.Label("Kernel Options:"), 0, 2, anchorRight=1)
        grid.setField(self.__kernel_options, 1, 2, anchorLeft=1)
        return [snack.Label("Provide the operating system URL"),
                grid]

    def get_os_type_page(self, screen):
        types = []
        for typ in Guest.list_os_types():
            types.append([Guest.get_os_type_label(typ), typ, self.__config.is_os_type(typ)])
        self.__os_types = snack.RadioBar(screen, types)
        grid = snack.Grid(1, 1)
        grid.setField(self.__os_types, 0, 0, anchorLeft=1)
        return [snack.Label("Choose the operating system type"),
                grid]

    def get_os_variant_page(self, screen):
        variants = []
        typ = self.__config.get_os_type()
        for variant in Guest.list_os_variants(typ):
            variants.append([Guest.get_os_variant_label(typ, variant), variant, self.__config.is_os_variant(variant)])
        self.__os_variants = snack.RadioBar(screen, variants)
        grid = snack.Grid(1, 1)
        grid.setField(self.__os_variants, 0, 0, anchorLeft=1)
        return [snack.Label("Choose the operating system version"),
                grid]

    def get_ram_and_cpu_page(self, screen):
        ignore = screen
        self.__memory = snack.Entry(10, str(self.__config.get_memory()))
        self.__cpus   = snack.Entry(10, str(self.__config.get_cpus()))
        grid = snack.Grid(2, 2)
        grid.setField(snack.Label("Memory (RAM):"), 0, 0, anchorRight=1)
        grid.setField(self.__memory, 1, 0, anchorLeft=1)
        grid.setField(snack.Label("CPUs:"), 0, 1, anchorRight=1)
        grid.setField(self.__cpus, 1, 1, anchorLeft=1)
        return [snack.Label("Choose memory and CPU settings"),
                grid]

    def get_enable_storage_page(self, screen):
        self.__enable_storage = snack.Checkbox("Enable storage for this virtual machine", self.__config.get_enable_storage())
        self.__storage_type     = snack.RadioBar(screen, ((["Create a disk image on the computer's hard disk",
                                                     DomainConfig.NEW_STORAGE,
                                                     self.__config.get_use_local_storage()]),
                                                   (["Select managed or other existing storage",
                                                     DomainConfig.EXISTING_STORAGE,
                                                     self.__config.get_use_local_storage() is False])))
        grid = snack.Grid(1, 2)
        grid.setField(self.__enable_storage, 0, 0, anchorLeft=1)
        grid.setField(self.__storage_type, 0, 1, anchorLeft=1)
        return [snack.Label("Configure storage"),
                grid]

    def get_local_storage_page(self, screen):
        ignore = screen
        self.__storage_size     = snack.Entry(6, str(self.__config.get_storage_size()))
        self.__allocate_storage = snack.Checkbox("Allocate entire disk now", self.__config.get_allocate_storage())
        grid = snack.Grid(2, 2)
        grid.setField(self.__allocate_storage, 0, 0, growx=1, anchorLeft=1)
        grid.setField(snack.Label("Storage size (GB):"), 0, 1, anchorLeft=1)
        grid.setField(self.__storage_size, 1, 1)
        return [snack.Label("Configure local storage"),
                grid]

    def get_select_pool_page(self, screen):
        pools = []
        for pool in self.get_libvirt().list_storage_pools():
            pools.append([pool, pool, pool == self.__config.get_storage_pool()])
        if len(pools) > 0:
            self.__storage_pool = snack.RadioBar(screen, (pools))
            grid = snack.Grid(2, 1)
            grid.setField(snack.Label("Storage pool:"), 0, 0, anchorTop=1)
            grid.setField(self.__storage_pool, 1, 0)
            self.__has_pools = True
        else:
            grid = snack.Label("There are no storage pools available.")
            self.__has_pools = False
        return [snack.Label("Configure Managed Storage: Select A Pool"),
                grid]

    def get_select_volume_page(self, screen):
        volumes = []
        for volume in self.get_libvirt().list_storage_volumes(self.__config.get_storage_pool()):
            volumes.append([volume, volume, volume == self.__config.get_storage_volume()])
        if len(volumes) > 0:
            self.__storage_volume = snack.RadioBar(screen, (volumes))
            grid = snack.Grid(2, 1)
            grid.setField(snack.Label("Storage volumes:"), 0, 0, anchorTop=1)
            grid.setField(self.__storage_volume, 1, 0)
            self.__has_volumes = True
        else:
            grid = snack.Label("This storage pool has no defined volumes.")
            self.__has_volumes = False
        return [snack.Label("Configure Managed Storage: Select A Volume"),
                grid]

    def get_bridge_page(self, screen):
        bridges = []
        for bridge in self.get_libvirt().list_bridges():
            bridges.append(["Virtual network '%s'" % bridge.name(), bridge.name(), self.__config.get_network_bridge() is bridge.name()])
        self.__network_bridges = snack.RadioBar(screen, (bridges))
        if self.__config.get_mac_address() is None:
            self.__config.set_mac_address(self.get_libvirt().generate_mac_address())
        self.__mac_address = snack.Entry(20, self.__config.get_mac_address())
        grid = snack.Grid(1, 1)
        grid.setField(self.__network_bridges, 0, 0)
        return [snack.Label("Select an existing bridge"),
                grid]

    def get_virt_details_page(self, screen):
        virt_types = []
        for typ in self.get_libvirt().list_virt_types():
            virt_types.append([typ, typ, self.__config.is_virt_type(typ)])
        self.__virt_types = snack.RadioBar(screen, (virt_types))
        archs = []
        for arch in self.get_libvirt().list_architectures():
            archs.append([arch, arch, self.__config.is_architecture(arch)])
        self.__architectures = snack.RadioBar(screen, (archs))
        grid = snack.Grid(2, 2)
        grid.setField(snack.Label("Virt Type:"), 0, 0, anchorRight=1, anchorTop=1)
        grid.setField(self.__virt_types, 1, 0, anchorLeft=1)
        grid.setField(snack.Label("Architecture:"), 0, 1, anchorRight=1, anchorTop=1)
        grid.setField(self.__architectures, 1, 1, anchorLeft=1)
        return [snack.Label("Configure virtualization details"),
                grid]

    def get_confirm_page(self, screen):
        ignore = screen
        grid = snack.Grid(2, 6)
        grid.setField(snack.Label("OS:"), 0, 0, anchorRight=1)
        grid.setField(snack.Label(Guest.get_os_variant_label(self.__config.get_os_type(),
                                                       self.__config.get_os_variant())), 1, 0, anchorLeft=1)
        grid.setField(snack.Label("Install:"), 0, 1, anchorRight=1)
        grid.setField(snack.Label(self.__config.get_install_type_text()), 1, 1, anchorLeft=1)
        grid.setField(snack.Label("Memory:"), 0, 2, anchorRight=1)
        grid.setField(snack.Label("%s MB" % self.__config.get_memory()), 1, 2, anchorLeft=1)
        grid.setField(snack.Label("CPUs:"), 0, 3, anchorRight=1)
        grid.setField(snack.Label("%d" % self.__config.get_cpus()), 1, 3, anchorLeft=1)
        grid.setField(snack.Label("Storage:"), 0, 4, anchorRight=1)
        grid.setField(snack.Label("%s (on %s)" % (self.__config.get_storage_volume(),
                                            self.__config.get_storage_pool())),
                      1, 4, anchorLeft=1)
        grid.setField(snack.Label("Network:"), 0, 5, anchorRight=1)
        grid.setField(snack.Label(self.__config.get_network_bridge()), 1, 5, anchorLeft=1)
        return [snack.Label("Ready to begin installation of %s" % self.__config.get_guest_name()),
                grid]

def AddDomain():
    screen = DomainConfigScreen()
    screen.start()
