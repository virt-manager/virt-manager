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


class BootDevice(XMLBuilder):
    _XML_ROOT_XPATH = "/domain/os/boot"

    def __init__(self, conn, dev, parsexml=None, parsexmlnode=None):
        XMLBuilder.__init__(self, conn, parsexml, parsexmlnode)
        self._dev = dev
        self._xmldev = dev

    def _get_dev(self):
        return self._xmldev
    dev = property(_get_dev)

    def _dev_xpath(self):
        return "./os/boot[@dev='%s']/@dev" % self._dev
    _xmldev = XMLProperty(name="boot dev type",
                make_getter_xpath_cb=_dev_xpath,
                make_setter_xpath_cb=_dev_xpath)


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

    def __init__(self, *args, **kwargs):
        self._bootdevs = []
        XMLBuilder.__init__(self, *args, **kwargs)

    def _parsexml(self, xml, node):
        XMLBuilder._parsexml(self, xml, node)

        for node in self._xml_node.children or []:
            if node.name != "boot" or not node.prop("dev"):
                continue
            bootdev = BootDevice(self.conn, node.prop("dev"),
                                 parsexmlnode=self._xml_node)
            self._bootdevs.append(bootdev)

    def clear(self):
        XMLBuilder.clear(self)
        self.bootorder = []

    def is_hvm(self):
        return self.os_type == "hvm"
    def is_xenpv(self):
        return self.os_type in ["xen", "linux"]
    def is_container(self):
        return self.os_type == "exe"

    _XML_ROOT_XPATH = "/domain/os"
    _XML_PROP_ORDER = ["arch", "os_type", "loader",
                       "kernel", "initrd", "kernel_args", "dtb",
                       "_bootdevs"]

    def _get_bootorder(self):
        return [dev.dev for dev in self._bootdevs]
    def _set_bootorder(self, newdevs):
        for dev in self._bootdevs:
            dev.clear()
        self._bootdevs = [BootDevice(self.conn, d,
                                     parsexmlnode=self._xml_node)
                          for d in newdevs]
    bootorder = property(_get_bootorder, _set_bootorder)

    enable_bootmenu = XMLProperty(xpath="./os/bootmenu/@enable", is_yesno=True)

    kernel = XMLProperty(xpath="./os/kernel")
    initrd = XMLProperty(xpath="./os/initrd")
    kernel_args = XMLProperty(xpath="./os/cmdline")
    dtb = XMLProperty(xpath="./os/dtb")

    init = XMLProperty(xpath="./os/init")
    loader = XMLProperty(xpath="./os/loader")
    arch = XMLProperty(xpath="./os/type/@arch",
                       default_cb=lambda s: s.conn.caps.host.arch)
    machine = XMLProperty(xpath="./os/type/@machine")
    os_type = XMLProperty(xpath="./os/type", default_cb=lambda s: "xen")
