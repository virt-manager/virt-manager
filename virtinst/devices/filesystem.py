#
# Copyright 2011, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceFilesystem(Device):
    XML_NAME = "filesystem"

    TYPE_MOUNT = "mount"
    TYPE_TEMPLATE = "template"
    TYPE_FILE = "file"
    TYPE_BLOCK = "block"
    TYPE_RAM = "ram"

    MODE_PASSTHROUGH = "passthrough"
    MODE_MAPPED = "mapped"
    MODE_SQUASH = "squash"
    MODES = [MODE_PASSTHROUGH, MODE_MAPPED, MODE_SQUASH]

    WRPOLICY_IMM = "immediate"
    WRPOLICIES = [WRPOLICY_IMM]

    DRIVER_PATH = "path"
    DRIVER_HANDLE = "handle"
    DRIVER_LOOP = "loop"
    DRIVER_NBD = "nbd"


    _type_prop = XMLProperty("./@type")
    accessmode = XMLProperty("./@accessmode")
    wrpolicy = XMLProperty("./driver/@wrpolicy")
    driver = XMLProperty("./driver/@type")
    format = XMLProperty("./driver/@format")

    readonly = XMLProperty("./readonly", is_bool=True)

    units = XMLProperty("./source/@units")
    target = XMLProperty("./target/@dir")

    _source_dir = XMLProperty("./source/@dir")
    _source_name = XMLProperty("./source/@name")
    _source_file = XMLProperty("./source/@file")
    _source_dev = XMLProperty("./source/@dev")
    _source_usage = XMLProperty("./source/@usage")
    def _type_to_source_prop(self):
        if self.type == DeviceFilesystem.TYPE_TEMPLATE:
            return "_source_name"
        elif self.type == DeviceFilesystem.TYPE_FILE:
            return "_source_file"
        elif self.type == DeviceFilesystem.TYPE_BLOCK:
            return "_source_dev"
        elif self.type == DeviceFilesystem.TYPE_RAM:
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
        # Get type/value of the attribute of "source" property
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


    ##############
    # Validation #
    ##############

    def validate_target(self, target):
        # In case of qemu for default fs type (mount) target is not
        # actually a directory, it is merely a arbitrary string tag
        # that is exported to the guest as a hint for where to mount
        if ((self.conn.is_qemu() or self.conn.is_test()) and
            (self.type is None or
             self.type == self.TYPE_MOUNT)):
            return

        if not os.path.isabs(target):
            raise ValueError(_("Filesystem target '%s' must be an absolute "
                               "path") % target)

    def validate(self):
        if self.target:
            self.validate_target(self.target)


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        ignore = guest

        if self.conn.is_qemu() or self.conn.is_lxc() or self.conn.is_test():
            # type=mount is the libvirt default. But hardcode it
            # here since we need it for the accessmode check
            if self.type is None:
                self.type = self.TYPE_MOUNT

            # libvirt qemu defaults to accessmode=passthrough, but that
            # really only works well for qemu running as root, which is
            # not the common case. so use mode=mapped
            if self.accessmode is None:
                self.accessmode = self.MODE_MAPPED
