#
# Copyright 2009 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

import Installer
from VirtualDisk import VirtualDisk

class ImportInstaller(Installer.Installer):
    """
    Create a Guest around an existing disk device, and perform no 'install'
    stage.

    ImportInstaller sets the Guest's boot device to that of the first disk
    attached to the Guest (so, one of 'hd', 'cdrom', or 'fd'). All the
    user has to do is fill in the Guest object with the desired parameters.
    """

    # General Installer methods
    def prepare(self, guest, meter):
        pass

    def post_install_check(self, guest):
        return True

    def has_install_phase(self):
        return False

    # Private methods
    def _get_bootdev(self, isinstall, guest):
        if not guest.disks:
            return self.bootconfig.BOOT_DEVICE_HARDDISK
        return self._disk_to_bootdev(guest.disks[0])

    def _disk_to_bootdev(self, disk):
        if disk.device == VirtualDisk.DEVICE_DISK:
            return self.bootconfig.BOOT_DEVICE_HARDDISK
        elif disk.device == VirtualDisk.DEVICE_CDROM:
            return self.bootconfig.BOOT_DEVICE_CDROM
        elif disk.device == VirtualDisk.DEVICE_FLOPPY:
            return self.bootconfig.BOOT_DEVICE_FLOPPY
        else:
            return self.bootconfig.BOOT_DEVICE_HARDDISK
