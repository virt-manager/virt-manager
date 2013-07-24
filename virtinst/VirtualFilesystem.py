#
# Copyright 2011  Red Hat, Inc.
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

import os

from virtinst.VirtualDevice import VirtualDevice
from virtinst.xmlbuilder import XMLProperty


class VirtualFilesystem(VirtualDevice):
    virtual_device_type = VirtualDevice.VIRTUAL_DEV_FILESYSTEM

    _target_props = ["dir", "name", "file", "dev"]

    TYPE_MOUNT = "mount"
    TYPE_TEMPLATE = "template"
    TYPE_FILE = "file"
    TYPE_BLOCK = "block"
    TYPE_DEFAULT = "default"
    TYPES = [TYPE_MOUNT, TYPE_TEMPLATE, TYPE_FILE, TYPE_BLOCK, TYPE_DEFAULT]

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
    DRIVER_PROXY = "proxy"
    DRIVER_DEFAULT = "default"
    DRIVERS = [DRIVER_PATH, DRIVER_HANDLE, DRIVER_PROXY, DRIVER_DEFAULT]

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
        return "dir"


    type = XMLProperty(xpath="./@type",
                       default_cb=lambda s: None,
                       default_name=TYPE_DEFAULT)
    mode = XMLProperty(xpath="./@accessmode",
                       default_cb=lambda s: None,
                       default_name=MODE_DEFAULT)
    wrpolicy = XMLProperty(xpath="./driver/@wrpolicy",
                           default_cb=lambda s: None,
                           default_name=WRPOLICY_DEFAULT)
    driver = XMLProperty(xpath="./driver/@type",
                         default_cb=lambda s: None,
                         default_name=DRIVER_DEFAULT)

    readonly = XMLProperty(xpath="./readonly", is_bool=True)


    def _xml_get_source_xpath(self):
        xpath = None
        ret = "./source/@dir"
        for prop in self._target_props:
            xpath = "./source/@" + prop
            if self._xml_ctx.xpathEval(self.fix_relative_xpath(xpath)):
                ret = xpath
        return ret
    def _xml_set_source_xpath(self):
        ret = "./source/@" + self.type_to_source_prop(self.type)
        return ret
    source = XMLProperty(name="filesystem source",
                         make_getter_xpath_cb=_xml_get_source_xpath,
                         make_setter_xpath_cb=_xml_set_source_xpath)

    def _validate_set_target(self, val):
        # In case of qemu for default fs type (mount) target is not
        # actually a directory, it is merely a arbitrary string tag
        # that is exported to the guest as a hint for where to mount
        if (self.conn.is_qemu() and
            (self.type == self.TYPE_DEFAULT or
             self.type == self.TYPE_MOUNT)):
            pass
        elif not os.path.isabs(val):
            raise ValueError(_("Filesystem target '%s' must be an absolute "
                               "path") % val)
        return val
    target = XMLProperty(xpath="./target/@dir",
                         set_converter=_validate_set_target)


VirtualFilesystem.register_type()
