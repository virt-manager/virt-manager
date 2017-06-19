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
    TYPES = [TYPE_MOUNT, TYPE_TEMPLATE, TYPE_FILE, TYPE_BLOCK, TYPE_RAM,
        TYPE_DEFAULT]

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
    DRIVERS = [DRIVER_PATH, DRIVER_HANDLE, DRIVER_LOOP, DRIVER_NBD,
        DRIVER_DEFAULT]


    _type_prop = XMLProperty("./@type",
                       default_cb=lambda s: None,
                       default_name=TYPE_DEFAULT)
    accessmode = XMLProperty("./@accessmode",
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

    def _validate_set_target(self, val):
        # In case of qemu for default fs type (mount) target is not
        # actually a directory, it is merely a arbitrary string tag
        # that is exported to the guest as a hint for where to mount
        if ((self.conn.is_qemu() or self.conn.is_test()) and
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

    _source_dir = XMLProperty("./source/@dir")
    _source_name = XMLProperty("./source/@name")
    _source_file = XMLProperty("./source/@file")
    _source_dev = XMLProperty("./source/@dev")
    _source_usage = XMLProperty("./source/@usage")
    def _type_to_source_prop(self):
        if self.type == VirtualFilesystem.TYPE_TEMPLATE:
            return "_source_name"
        elif self.type == VirtualFilesystem.TYPE_FILE:
            return "_source_file"
        elif self.type == VirtualFilesystem.TYPE_BLOCK:
            return "_source_dev"
        elif self.type == VirtualFilesystem.TYPE_RAM:
            return "_source_usage"
        else:
            return "_source_dir"

    def _get_source(self):
        return getattr(self, self._type_to_source_prop())
    def _set_source(self, val):
        return setattr(self, self._type_to_source_prop(), val)
    source = property(_get_source, _set_source)

    def _get_type(self):
        return getattr(self, '_type_prop')
    def _set_type(self, val):
        # Get type/value of the attrubute of "source" property
        old_source_type = self._type_to_source_prop()
        old_source_value = self.source

        # Update "type" property
        new_type = setattr(self, '_type_prop', val)

        # If the attribute type of 'source' property has changed
        # restore the value
        if old_source_type != self._type_to_source_prop():
            self.source = old_source_value

        return new_type

    type = property(_get_type, _set_type)

    def set_defaults(self, guest):
        ignore = guest

        if self.conn.is_qemu() or self.conn.is_lxc() or self.conn.is_test():
            # type=mount is the libvirt default. But hardcode it
            # here since we need it for the accessmode check
            if self.type is None or self.type == self.TYPE_DEFAULT:
                self.type = self.TYPE_MOUNT

            # libvirt qemu defaults to accessmode=passthrough, but that
            # really only works well for qemu running as root, which is
            # not the common case. so use mode=mapped
            if self.accessmode is None or self.accessmode == self.MODE_DEFAULT:
                self.accessmode = self.MODE_MAPPED


VirtualFilesystem.register_type()
