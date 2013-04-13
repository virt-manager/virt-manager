#
# Copyright 2010  Red Hat, Inc.
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

from virtinst import util
from virtinst import XMLBuilderDomain
from virtinst.XMLBuilderDomain import _xml_property


class Boot(XMLBuilderDomain.XMLBuilderDomain):
    """
    Class for generating boot device related XML
    """

    BOOT_DEVICE_HARDDISK = "hd"
    BOOT_DEVICE_CDROM = "cdrom"
    BOOT_DEVICE_FLOPPY = "fd"
    BOOT_DEVICE_NETWORK = "network"
    boot_devices = [BOOT_DEVICE_HARDDISK, BOOT_DEVICE_CDROM,
                    BOOT_DEVICE_FLOPPY, BOOT_DEVICE_NETWORK]

    _dumpxml_xpath = "/domain/os"
    def __init__(self, conn, parsexml=None, parsexmlnode=None, caps=None):
        XMLBuilderDomain.XMLBuilderDomain.__init__(self, conn, parsexml,
                                                   parsexmlnode, caps)

        self._bootorder = []
        self._enable_bootmenu = None
        self._kernel = None
        self._initrd = None
        self._kernel_args = None

    def _get_enable_bootmenu(self):
        return self._enable_bootmenu
    def _set_enable_bootmenu(self, val):
        self._enable_bootmenu = val
    def _get_menu_converter(self, val):
        ignore = self
        if val is None:
            return None
        return bool(val == "yes")
    enable_bootmenu = _xml_property(_get_enable_bootmenu, _set_enable_bootmenu,
                            get_converter=_get_menu_converter,
                            set_converter=lambda s, x: x and "yes" or "no",
                            xpath="./os/bootmenu/@enable")

    def _get_bootorder(self):
        return self._bootorder
    def _set_bootorder(self, val):
        self._bootorder = val
    def _bootorder_xpath_list(self):
        l = []
        for idx in range(len(self._get_bootorder())):
            l.append("./os/boot[%d]/@dev" % (idx + 1))
        return l
    bootorder = _xml_property(_get_bootorder, _set_bootorder,
                              is_multi=True,
                              xml_set_list=_bootorder_xpath_list,
                              xpath="./os/boot/@dev")

    def _get_kernel(self):
        return self._kernel
    def _set_kernel(self, val):
        self._kernel = val
    kernel = _xml_property(_get_kernel, _set_kernel,
                           xpath="./os/kernel")

    def _get_initrd(self):
        return self._initrd
    def _set_initrd(self, val):
        self._initrd = val
    initrd = _xml_property(_get_initrd, _set_initrd,
                           xpath="./os/initrd")

    def _get_kernel_args(self):
        return self._kernel_args
    def _set_kernel_args(self, val):
        self._kernel_args = val
    kernel_args = _xml_property(_get_kernel_args, _set_kernel_args,
                                xpath="./os/cmdline")

    def _get_xml_config(self):
        xml = ""

        if self.kernel:
            xml = util.xml_append(xml, "    <kernel>%s</kernel>" %
                                   util.xml_escape(self.kernel))
            if self.initrd:
                xml = util.xml_append(xml, "    <initrd>%s</initrd>" %
                                       util.xml_escape(self.initrd))
            if self.kernel_args:
                xml = util.xml_append(xml, "    <cmdline>%s</cmdline>" %
                                       util.xml_escape(self.kernel_args))

        else:
            for dev in self.bootorder:
                xml = util.xml_append(xml, "    <boot dev='%s'/>" % dev)

            if self.enable_bootmenu in [True, False]:
                val = self.enable_bootmenu and "yes" or "no"
                xml = util.xml_append(xml,
                                       "    <bootmenu enable='%s'/>" % val)

        return xml
