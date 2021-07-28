#
# Copyright 2010, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


class _InitArg(XMLBuilder):
    XML_NAME = "initarg"
    val = XMLProperty(".")


class _BootDevice(XMLBuilder):
    XML_NAME = "boot"
    dev = XMLProperty("./@dev")


class _FirmwareFeature(XMLBuilder):
    XML_NAME = "feature"
    _XML_PROP_ORDER = ["enabled", "name"]

    enabled = XMLProperty("./@enabled", is_yesno=True)
    name = XMLProperty("./@name")


class DomainOs(XMLBuilder):
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
    def is_arm_machvirt(self):
        return self.is_arm() and str(self.machine).startswith("virt")

    def is_ppc64(self):
        return self.arch == "ppc64" or self.arch == "ppc64le"
    def is_pseries(self):
        return self.is_ppc64() and str(self.machine).startswith("pseries")

    def is_s390x(self):
        return self.arch == "s390x"

    def is_riscv(self):
        return self.arch == "riscv64" or self.arch == "riscv32"
    def is_riscv_virt(self):
        return self.is_riscv() and str(self.machine).startswith("virt")

    XML_NAME = "os"
    _XML_PROP_ORDER = ["arch", "os_type", "loader", "loader_ro", "loader_type",
                       "nvram", "nvram_template", "kernel", "initrd",
                       "initdir", "inituser", "initgroup",
                       "kernel_args", "dtb", "bootdevs", "smbios_mode"]

    # BIOS bootloader
    def _get_bootorder(self):
        return [dev.dev for dev in self.bootdevs]
    def _set_bootorder(self, newdevs):
        for dev in self.bootdevs:
            self.remove_child(dev)

        for d in newdevs:
            dev = self.bootdevs.add_new()
            dev.dev = d
    bootorder = property(_get_bootorder, _set_bootorder)
    bootdevs = XMLChildProperty(_BootDevice)
    smbios_mode = XMLProperty("./smbios/@mode")
    bootmenu_enable = XMLProperty("./bootmenu/@enable", is_yesno=True)
    bootmenu_timeout = XMLProperty("./bootmenu/@timeout", is_int=True)
    bios_rebootTimeout = XMLProperty("./bios/@rebootTimeout", is_int=True)
    bios_useserial = XMLProperty("./bios/@useserial", is_yesno=True)

    # Host bootloader
    # Since the elements for a host bootloader are actually directly under
    # <domain> rather than <domain><os>, they are handled via callbacks in
    # the CLI. This is just a placeholder to remind of that fact.

    initargs = XMLChildProperty(_InitArg)
    def set_initargs_string(self, argstring):
        import shlex
        for obj in self.initargs:
            self.remove_child(obj)
        for val in shlex.split(argstring):
            obj = self.initargs.add_new()
            obj.val = val

    kernel = XMLProperty("./kernel", do_abspath=True)
    initrd = XMLProperty("./initrd", do_abspath=True)
    dtb = XMLProperty("./dtb", do_abspath=True)
    kernel_args = XMLProperty("./cmdline")

    init = XMLProperty("./init")
    initdir = XMLProperty("./initdir")
    inituser = XMLProperty("./inituser")
    initgroup = XMLProperty("./initgroup")
    loader = XMLProperty("./loader")
    loader_ro = XMLProperty("./loader/@readonly", is_yesno=True)
    loader_type = XMLProperty("./loader/@type")
    loader_secure = XMLProperty("./loader/@secure", is_yesno=True)
    nvram = XMLProperty("./nvram", do_abspath=True)
    nvram_template = XMLProperty("./nvram/@template")
    arch = XMLProperty("./type/@arch")
    machine = XMLProperty("./type/@machine")
    os_type = XMLProperty("./type")
    firmware = XMLProperty("./@firmware")
    firmware_features = XMLChildProperty(_FirmwareFeature, relative_xpath="./firmware")


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if self.is_container() and not self.init:
            if guest.is_full_os_container():
                self.init = "/sbin/init"
            else:
                self.init = "/bin/sh"
