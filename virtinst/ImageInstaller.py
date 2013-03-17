# Installer for images
#
# Copyright 2007  Red Hat, Inc.
# David Lutterkort <dlutter@redhat.com>
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

import os

import Installer
import ImageParser
import CapabilitiesParser as Cap
from VirtualDisk import VirtualDisk
from virtinst import _gettext as _

class ImageInstallerException(Exception):
    def __init__(self, msg):
        Exception.__init__(self, msg)

class ImageInstaller(Installer.Installer):
    """Installer for image-based guests"""
    def __init__(self, image, capabilities=None, boot_index=None, conn=None):
        Installer.Installer.__init__(self, conn=conn, caps=capabilities)

        self._arch = None
        self._image = image

        if not (self.conn or self._get_caps()):
            raise ValueError(_("'conn' or 'capabilities' must be specified."))

        # Set boot _boot_caps/_boot_parameters
        if boot_index is None:
            self._boot_caps = match_boots(self._get_caps(),
                                     self.image.domain.boots)
            if self._boot_caps is None:
                raise ImageInstallerException(_("Could not find suitable boot "
                                                "descriptor for this host"))
        else:
            if (boot_index < 0 or
                (boot_index + 1) > len(image.domain.boots)):
                raise ValueError(_("boot_index out of range."))
            self._boot_caps = image.domain.boots[boot_index]

        # Set up internal caps.guest object
        self._guest = self._get_caps().guestForOSType(self.boot_caps.type,
                                                      self.boot_caps.arch)
        if self._guest is None:
            raise PlatformMatchException(_("Unsupported virtualization type: "
                                           "%s %s" % (self.boot_caps.type,
                                                      self.boot_caps.arch)))

        self.os_type = self.boot_caps.type
        self._domain = self._guest.bestDomainType()
        self.type = self._domain.hypervisor_type
        self.arch = self._guest.arch


    # Custom ImageInstaller methods

    def is_hvm(self):
        if self._boot_caps.type == "hvm":
            return True
        return False

    def get_image(self):
        return self._image
    image = property(get_image)

    def get_boot_caps(self):
        return self._boot_caps
    boot_caps = property(get_boot_caps)


    # General Installer methods

    def prepare(self, guest, meter):
        self.cleanup()

        self._make_disks()

        for f in ['pae', 'acpi', 'apic']:
            if self.boot_caps.features[f] & Cap.FEATURE_ON:
                guest.features[f] = True
            elif self.boot_caps.features[f] & Cap.FEATURE_OFF:
                guest.features[f] = False

        self.bootconfig.kernel = self.boot_caps.kernel
        self.bootconfig.initrd = self.boot_caps.initrd
        self.bootconfig.kernel_args = self.boot_caps.cmdline

    def post_install_check(self, guest):
        return True

    def has_install_phase(self):
        return False

    # Private methods
    def _get_bootdev(self, isinstall, guest):
        return self.boot_caps.bootdev

    def _make_disks(self):
        for drive in self.boot_caps.drives:
            path = self._abspath(drive.disk.file)
            size = None
            if drive.disk.size is not None:
                size = float(drive.disk.size) / 1024

            # FIXME: This is awkward; the image should be able to express
            # whether the disk is expected to be there or not independently
            # of its classification, especially for user disks
            # FIXME: We ignore the target for the mapping in m.target
            if (drive.disk.use == ImageParser.Disk.USE_SYSTEM and
                not os.path.exists(path)):
                raise ImageInstallerException(_("System disk %s does not exist")
                                              % path)

            device = VirtualDisk.DEVICE_DISK
            if drive.disk.format == ImageParser.Disk.FORMAT_ISO:
                device = VirtualDisk.DEVICE_CDROM


            disk = VirtualDisk(conn=self.conn,
                               path=path,
                               size=size,
                               device=device,
                               format=drive.disk.format)
            disk.target = drive.target

            self.install_devices.append(disk)

    def _abspath(self, p):
        return self.image.abspath(p)

class PlatformMatchException(Exception):
    def __init__(self, msg):
        Exception.__init__(self, msg)

def match_boots(capabilities, boots):
    for b in boots:
        for g in capabilities.guests:
            if b.type == g.os_type and b.arch == g.arch:
                found = True
                for bf in b.features.names():
                    if not b.features[bf] & g.features[bf]:
                        found = False
                        break
                if found:
                    return b
    return None
