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

from virtinst.xmlbuilder import XMLBuilder, XMLProperty


class OSXML(XMLBuilder):
    """
    Class for generating boot device related XML
    """

    BOOT_DEVICE_HARDDISK = "hd"
    BOOT_DEVICE_CDROM = "cdrom"
    BOOT_DEVICE_FLOPPY = "fd"
    BOOT_DEVICE_NETWORK = "network"
    boot_devices = [BOOT_DEVICE_HARDDISK, BOOT_DEVICE_CDROM,
                    BOOT_DEVICE_FLOPPY, BOOT_DEVICE_NETWORK]

    def is_hvm(self):
        return self.os_type == "hvm"
    def is_xenpv(self):
        return self.os_type in ["xen", "linux"]
    def is_container(self):
        return self.os_type == "exe"

    _dumpxml_xpath = "/domain/os"
    _XML_ROOT_NAME = "os"
    _XML_INDENT = 2
    _XML_XPATH_RELATIVE = True
    _XML_PROP_ORDER = ["arch", "os_type", "loader",
                       "kernel", "initrd", "kernel_args",
                       "bootorder"]

    type = property(lambda s: s.snarf)

    enable_bootmenu = XMLProperty(xpath="./os/bootmenu/@enable", is_yesno=True)
    bootorder = XMLProperty(xpath="./os/boot/@dev", is_multi=True)

    kernel = XMLProperty(xpath="./os/kernel")
    initrd = XMLProperty(xpath="./os/initrd")
    kernel_args = XMLProperty(xpath="./os/cmdline")

    init = XMLProperty(xpath="./os/init")
    loader = XMLProperty(xpath="./os/loader")
    arch = XMLProperty(xpath="./os/type/@arch",
                       default_cb=lambda s: s.conn.caps.host.arch)
    machine = XMLProperty(xpath="./os/type/@machine")
    os_type = XMLProperty(xpath="./os/type", default_cb=lambda s: "xen")
