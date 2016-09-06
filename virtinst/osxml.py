#
# Copyright 2010, 2013 Red Hat, Inc.
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

from .xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


class _InitArg(XMLBuilder):
    _XML_ROOT_NAME = "initarg"
    val = XMLProperty(".")


class _BootDevice(XMLBuilder):
    _XML_ROOT_NAME = "boot"
    dev = XMLProperty("./@dev")


class OSXML(XMLBuilder):
    """
    Class for generating boot device related XML
    """
    BOOT_DEVICE_HARDDISK = "hd"
    BOOT_DEVICE_CDROM = "cdrom"
    BOOT_DEVICE_FLOPPY = "fd"
    BOOT_DEVICE_NETWORK = "network"
    BOOT_DEVICES = [BOOT_DEVICE_HARDDISK, BOOT_DEVICE_CDROM,
                    BOOT_DEVICE_FLOPPY, BOOT_DEVICE_NETWORK]

    def is_hvm(self):
        return self.os_type == "hvm"
    def is_xenpv(self):
        return self.os_type in ["xen", "linux"]
    def is_container(self):
        return self.os_type == "exe"

    def is_x86(self):
        return self.arch == "x86_64" or self.arch == "i686"
    def is_q35(self):
        return (self.is_x86() and
                self.machine and
                "q35" in self.machine)

    def is_arm32(self):
        return self.arch == "armv7l"
    def is_arm64(self):
        return self.arch == "aarch64"
    def is_arm(self):
        return self.is_arm32() or self.is_arm64()
    def is_arm_vexpress(self):
        return self.is_arm() and str(self.machine).startswith("vexpress-")
    def is_arm_machvirt(self):
        return self.is_arm() and str(self.machine).startswith("virt")

    def is_ppc64(self):
        return self.arch == "ppc64" or self.arch == "ppc64le"
    def is_pseries(self):
        return self.is_ppc64() and str(self.machine).startswith("pseries")

    def is_s390x(self):
        return self.arch == "s390x"

    _XML_ROOT_NAME = "os"
    _XML_PROP_ORDER = ["arch", "os_type", "loader", "loader_ro", "loader_type",
                       "nvram", "nvram_template", "kernel", "initrd",
                       "kernel_args", "dtb", "_bootdevs", "smbios_mode"]

    def _get_bootorder(self):
        return [dev.dev for dev in self._bootdevs]
    def _set_bootorder(self, newdevs):
        for dev in self._bootdevs:
            self.remove_child(dev)

        for d in newdevs:
            dev = _BootDevice(self.conn)
            dev.dev = d
            self.add_child(dev)
    _bootdevs = XMLChildProperty(_BootDevice)
    bootorder = property(_get_bootorder, _set_bootorder)

    initargs = XMLChildProperty(_InitArg)
    def add_initarg(self, val):
        obj = _InitArg(self.conn)
        obj.val = val
        self.add_child(obj)
    def set_initargs_string(self, argstring):
        import shlex
        for obj in self.initargs:
            self.remove_child(obj)
        for val in shlex.split(argstring):
            self.add_initarg(val)

    enable_bootmenu = XMLProperty("./bootmenu/@enable", is_yesno=True)
    useserial = XMLProperty("./bios/@useserial", is_yesno=True)

    kernel = XMLProperty("./kernel", do_abspath=True)
    initrd = XMLProperty("./initrd", do_abspath=True)
    dtb = XMLProperty("./dtb", do_abspath=True)
    kernel_args = XMLProperty("./cmdline")

    init = XMLProperty("./init")
    loader = XMLProperty("./loader")
    loader_ro = XMLProperty("./loader/@readonly", is_yesno=True)
    loader_type = XMLProperty("./loader/@type")
    smbios_mode = XMLProperty("./smbios/@mode")
    nvram = XMLProperty("./nvram")
    nvram_template = XMLProperty("./nvram/@template")
    arch = XMLProperty("./type/@arch",
                       default_cb=lambda s: s.conn.caps.host.cpu.arch)
    machine = XMLProperty("./type/@machine")
    os_type = XMLProperty("./type", default_cb=lambda s: "xen")
