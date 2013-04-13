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
from virtinst.XMLBuilderDomain import _xml_property


class VirtualFilesystem(VirtualDevice):

    _virtual_device_type = VirtualDevice.VIRTUAL_DEV_FILESYSTEM

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
    MOUNT_MODES = [MODE_PASSTHROUGH, MODE_MAPPED, MODE_SQUASH, MODE_DEFAULT]

    WRPOLICY_IMM = "immediate"
    WRPOLICY_DEFAULT = "default"
    WRPOLICIES = [WRPOLICY_IMM, WRPOLICY_DEFAULT]

    DRIVER_PATH = "path"
    DRIVER_HANDLE = "handle"
    DRIVER_PROXY = "proxy"
    DRIVER_DEFAULT = "default"
    DRIVER_TYPES = [DRIVER_PATH, DRIVER_HANDLE, DRIVER_PROXY, DRIVER_DEFAULT]

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

    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        VirtualDevice.__init__(self, conn, parsexml,
                                             parsexmlnode, caps)

        self._type = None
        self._mode = None
        self._driver = None
        self._target = None
        self._source = None
        self._readonly = None
        self._wrpolicy = None

        if self._is_parse():
            return

        self.mode = self.MODE_DEFAULT
        self.type = self.TYPE_DEFAULT
        self.driver = self.DRIVER_DEFAULT
        self.wrpolicy = self.WRPOLICY_DEFAULT

    def _get_type(self):
        return self._type
    def _set_type(self, val):
        if val is not None and not self.TYPES.count(val):
            raise ValueError(_("Unsupported filesystem type '%s'" % val))
        self._type = val
    type = _xml_property(_get_type, _set_type, xpath="./@type")

    def _get_mode(self):
        return self._mode
    def _set_mode(self, val):
        if val is not None and not self.MOUNT_MODES.count(val):
            raise ValueError(_("Unsupported filesystem mode '%s'" % val))
        self._mode = val
    mode = _xml_property(_get_mode, _set_mode, xpath="./@accessmode")

    def _get_wrpolicy(self):
        return self._wrpolicy
    def _set_wrpolicy(self, val):
        if val is not None and not self.WRPOLICIES.count(val):
            raise ValueError(_("Unsupported filesystem write policy '%s'" % val))
        self._wrpolicy = val
    wrpolicy = _xml_property(_get_wrpolicy, _set_wrpolicy, xpath="./driver/@wrpolicy")

    def _get_readonly(self):
        return self._readonly
    def _set_readonly(self, val):
        self._readonly = val
    readonly = _xml_property(_get_readonly, _set_readonly,
                             xpath="./readonly", is_bool=True)

    def _get_driver(self):
        return self._driver
    def _set_driver(self, val):
        if val is not None and not self.DRIVER_TYPES.count(val):
            raise ValueError(_("Unsupported filesystem driver '%s'" % val))
        self._driver = val
    driver = _xml_property(_get_driver, _set_driver, xpath="./driver/@type")

    def _get_source(self):
        return self._source
    def _set_source(self, val):
        if self.type != self.TYPE_TEMPLATE:
            val = os.path.abspath(val)
        self._source = val
    def _xml_get_source_xpath(self):
        xpath = None
        ret = "./source/@dir"
        for prop in self._target_props:
            xpath = "./source/@" + prop
            if self._xml_ctx.xpathEval(xpath):
                ret = xpath

        return ret
    def _xml_set_source_xpath(self):
        ret = "./source/@" + self.type_to_source_prop(self.type)
        return ret
    source = _xml_property(_get_source, _set_source,
                           xml_get_xpath=_xml_get_source_xpath,
                           xml_set_xpath=_xml_set_source_xpath)

    def _get_target(self):
        return self._target
    def _set_target(self, val):
        is_qemu = self.is_qemu()

        # In case of qemu for default fs type (mount) target is not
        # actually a directory, it is merely a arbitrary string tag
        # that is exported to the guest as a hint for where to mount
        if (is_qemu and
            (self.type == self.TYPE_DEFAULT or
             self.type == self.TYPE_MOUNT)):
            pass
        elif not os.path.isabs(val):
            raise ValueError(_("Filesystem target '%s' must be an absolute "
                               "path") % val)
        self._target = val
    target = _xml_property(_get_target, _set_target, xpath="./target/@dir")


    def _get_xml_config(self):
        mode = self.mode
        ftype = self.type
        driver = self.driver
        source = self.source
        target = self.target
        readonly = self.readonly
        wrpolicy = self.wrpolicy

        if mode == self.MODE_DEFAULT:
            mode = None
        if ftype == self.TYPE_DEFAULT:
            ftype = None
        if driver == self.DRIVER_DEFAULT:
            driver = None
            wrpolicy = None
        if wrpolicy == self.WRPOLICY_DEFAULT:
            wrpolicy = None

        if not source or not target:
            raise ValueError(
                _("A filesystem source and target must be specified"))

        fsxml = "    <filesystem"
        if ftype:
            fsxml += " type='%s'" % ftype
        if mode:
            fsxml += " accessmode='%s'" % mode
        fsxml += ">\n"

        if driver:
            if not wrpolicy:
                fsxml += "      <driver type='%s'/>\n" % driver
            else:
                fsxml += "      <driver type='%s' wrpolicy='%s' />\n" % (
                                                                    driver,
                                                                    wrpolicy)

        fsxml += "      <source %s='%s'/>\n" % (
                                            self.type_to_source_prop(ftype),
                                            source)
        fsxml += "      <target dir='%s'/>\n" % target

        if readonly:
            fsxml += "      <readonly/>\n"

        fsxml += "    </filesystem>"

        return fsxml
