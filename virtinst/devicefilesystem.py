#
# Copyright 2011, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
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

from .device import VirtualDevice
from .xmlbuilder import XMLProperty


class VirtualFilesystem(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_FILESYSTEM

    TYPE_MOUNT = "mount"
    TYPE_TEMPLATE = "template"
    TYPE_FILE = "file"
    TYPE_BLOCK = "block"
    TYPE_RAM = "ram"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_MOUNT, TYPE_TEMPLATE, TYPE_FILE, TYPE_BLOCK, TYPE_RAM, TYPE_DEFAULT]

    MODE_PASSTHROUGH = "passthrough"
    MODE_MAPPED = "mapped"
    MODE_SQUASH = "squash"
    MODE_DEFAULT = "default"
    MODES = [MODE_PASSTHROUGH, MODE_MAPPED, MODE_SQUASH, MODE_DEFAULT]

    WRPOLICY_IMM = "immediate"
    WRPOLICY_DEFAULT = "default"
    WRPOLICIES = [WRPOLICY_IMM, WRPOLICY_DEFAULT]

    DRIVER_PATH = "path"
    DRIVER_HANDLE = "handle"
    DRIVER_LOOP = "loop"
    DRIVER_NBD = "nbd"
    DRIVER_DEFAULT = "default"
    DRIVERS = [DRIVER_PATH, DRIVER_HANDLE, DRIVER_LOOP, DRIVER_NBD, DRIVER_DEFAULT]

    @staticmethod
    def type_to_source_prop(fs_type):
        """
        Convert a value of VirtualFilesystem.type to it's associated XML
        source @prop name
        """
        if (fs_type == VirtualFilesystem.TYPE_MOUNT or
            fs_type == VirtualFilesystem.TYPE_DEFAULT or
            fs_type is None):
            return "dir"
        elif fs_type == VirtualFilesystem.TYPE_TEMPLATE:
            return "name"
        elif fs_type == VirtualFilesystem.TYPE_FILE:
            return "file"
        elif fs_type == VirtualFilesystem.TYPE_BLOCK:
            return "dev"
        elif fs_type == VirtualFilesystem.TYPE_RAM:
            return "usage"
        return "dir"


    type = XMLProperty("./@type",
                       default_cb=lambda s: None,
                       default_name=TYPE_DEFAULT)
    mode = XMLProperty("./@accessmode",
                       default_cb=lambda s: None,
                       default_name=MODE_DEFAULT)
    wrpolicy = XMLProperty("./driver/@wrpolicy",
                           default_cb=lambda s: None,
                           default_name=WRPOLICY_DEFAULT)
    driver = XMLProperty("./driver/@type",
                         default_cb=lambda s: None,
                         default_name=DRIVER_DEFAULT)
    format = XMLProperty("./driver/@format")

    readonly = XMLProperty("./readonly", is_bool=True)

    units = XMLProperty("./source/@units")

    def _make_source_xpath(self):
        return "./source/@" + self.type_to_source_prop(self.type)
    source = XMLProperty(name="filesystem source",
                         make_xpath_cb=_make_source_xpath)

    def _validate_set_target(self, val):
        # In case of qemu for default fs type (mount) target is not
        # actually a directory, it is merely a arbitrary string tag
        # that is exported to the guest as a hint for where to mount
        if (self.conn.is_qemu() and
            (self.type is None or
             self.type == self.TYPE_DEFAULT or
             self.type == self.TYPE_MOUNT)):
            pass
        elif not os.path.isabs(val):
            raise ValueError(_("Filesystem target '%s' must be an absolute "
                               "path") % val)
        return val
    target = XMLProperty("./target/@dir",
                         set_converter=_validate_set_target)


VirtualFilesystem.register_type()
