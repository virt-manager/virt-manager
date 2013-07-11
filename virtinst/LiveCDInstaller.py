#
# An installer class for LiveCD images
#
# Copyright 2007  Red Hat, Inc.
# Mark McLoughlin <markmc@redhat.com>
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

from virtinst import Installer
from virtinst.VirtualDisk import VirtualDisk


class LiveCDInstaller(Installer.Installer):
    _has_install_phase = False

    # LiveCD specific methods/overwrites
    def _validate_location(self, val):
        if not val:
            return None
        return VirtualDisk(self.conn,
                           path=val,
                           device=VirtualDisk.DEVICE_CDROM,
                           readOnly=True)
    def _get_location(self):
        return self._location
    def _set_location(self, val):
        self._validate_location(val)
        self._location = val
        self.cdrom = True
    location = property(_get_location, _set_location)


    # General Installer methods
    def prepare(self, guest, meter):
        self.cleanup()

        disk = self._validate_location(self.location)

        if not disk:
            raise ValueError(_("CDROM media must be specified for the live "
                               "CD installer."))

        self.install_devices.append(disk)

    # Internal methods
    def _get_bootdev(self, isinstall, guest):
        return self.bootconfig.BOOT_DEVICE_CDROM
