#
# Copyright 2011, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceFilesystem(Device):
    XML_NAME = "filesystem"
    _XML_PROP_ORDER = ["_type_prop", "accessmode", "fmode", "dmode"]

    TYPE_MOUNT = "mount"
    TYPE_TEMPLATE = "template"
    TYPE_FILE = "file"
    TYPE_BLOCK = "block"
    TYPE_RAM = "ram"

    MODE_MAPPED = "mapped"
    MODE_SQUASH = "squash"

    DRIVER_LOOP = "loop"
    DRIVER_NBD = "nbd"

    _type_prop = XMLProperty("./@type")
    accessmode = XMLProperty("./@accessmode")
    model = XMLProperty("./@model")
    multidevs = XMLProperty("./@multidevs")
    fmode = XMLProperty("./@fmode")
    dmode = XMLProperty("./@dmode")

    readonly = XMLProperty("./readonly", is_bool=True)
    space_hard_limit = XMLProperty("./space_hard_limit")
    space_soft_limit = XMLProperty("./space_soft_limit")

    driver_wrpolicy = XMLProperty("./driver/@wrpolicy")
    driver_type = XMLProperty("./driver/@type")
    driver_format = XMLProperty("./driver/@format")
    driver_queue = XMLProperty("./driver/@queue")
    driver_name = XMLProperty("./driver/@name")

    target_dir = XMLProperty("./target/@dir")

    source_dir = XMLProperty("./source/@dir")
    source_name = XMLProperty("./source/@name")
    source_file = XMLProperty("./source/@file")
    source_dev = XMLProperty("./source/@dev")
    source_usage = XMLProperty("./source/@usage")
    source_units = XMLProperty("./source/@units")
    source_pool = XMLProperty("./source/@pool")
    source_volume = XMLProperty("./source/@volume")
    source_socket = XMLProperty("./source/socket")

    binary_path = XMLProperty("./binary/@path")
    binary_xattr = XMLProperty("./binary/@xattr", is_onoff=True)
    binary_cache_mode = XMLProperty("./binary/cache/@mode")
    binary_lock_posix = XMLProperty("./binary/lock/@posix", is_onoff=True)
    binary_lock_flock = XMLProperty("./binary/lock/@flock", is_onoff=True)
    binary_sandbox_mode = XMLProperty("./binary/sandbox/@mode")

    def _type_to_source_prop(self):
        if self.type == DeviceFilesystem.TYPE_TEMPLATE:
            return "source_name"
        elif self.type == DeviceFilesystem.TYPE_FILE:
            return "source_file"
        elif self.type == DeviceFilesystem.TYPE_BLOCK:
            return "source_dev"
        elif self.type == DeviceFilesystem.TYPE_RAM:
            return "source_usage"
        else:
            return "source_dir"

    def _get_source(self):
        return getattr(self, self._type_to_source_prop())
    def _set_source(self, val):
        return setattr(self, self._type_to_source_prop(), val)
    source = property(_get_source, _set_source)

    def _get_target(self):
        return self.target_dir
    def _set_target(self, val):
        self.target_dir = val
    target = property(_get_target, _set_target)

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

    def default_accessmode(self):
        if self.driver_type == "virtiofs":
            # let libvirt fill in default accessmode=passthrough
            return None
        # libvirt qemu defaults to accessmode=passthrough, but that
        # really only works well for qemu running as root, which is
        # not the common case. so use mode=mapped
        return self.MODE_MAPPED


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        ignore = guest

        if not (self.conn.is_qemu() or
                self.conn.is_lxc() or
                self.conn.is_test()):
            return

        # type=mount is the libvirt default. But hardcode it since other
        # bits like validation depend on it
        if self.type is None:
            self.type = self.TYPE_MOUNT

        if self.accessmode is None:
            self.accessmode = self.default_accessmode()
