#
# Copyright 2010, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty


class _InitArg(XMLBuilder):
    XML_NAME = "initarg"
    val = XMLProperty(".")


class _InitEnv(XMLBuilder):
    XML_NAME = "initenv"
    name = XMLProperty("./@name")
    value = XMLProperty(".")


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

    ##################
    # XML properties #
    ##################

    XML_NAME = "os"
    _XML_PROP_ORDER = [
            "firmware", "os_type", "arch", "machine", "firmware_features",
            "loader", "loader_ro", "loader_secure", "loader_type",
            "nvram", "nvram_template",
            "init", "initargs", "initenvs", "initdir", "inituser", "initgroup",
            "kernel", "initrd", "kernel_args", "dtb", "acpi_tb", "acpi_tb_type",
            "bootdevs", "bootmenu_enable", "bootmenu_timeout",
            "bios_useserial", "bios_rebootTimeout", "smbios_mode"]

    # Shared/Generic boot options
    os_type = XMLProperty("./type")
    arch = XMLProperty("./type/@arch")
    machine = XMLProperty("./type/@machine")
    loader = XMLProperty("./loader")
    loader_ro = XMLProperty("./loader/@readonly", is_yesno=True)
    loader_type = XMLProperty("./loader/@type")
    loader_secure = XMLProperty("./loader/@secure", is_yesno=True)

    # BIOS bootloader options
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
    firmware = XMLProperty("./@firmware")
    firmware_features = XMLChildProperty(_FirmwareFeature, relative_xpath="./firmware")
    nvram = XMLProperty("./nvram", do_abspath=True)
    nvram_template = XMLProperty("./nvram/@template")
    bootmenu_enable = XMLProperty("./bootmenu/@enable", is_yesno=True)
    bootmenu_timeout = XMLProperty("./bootmenu/@timeout", is_int=True)
    bios_useserial = XMLProperty("./bios/@useserial", is_yesno=True)
    bios_rebootTimeout = XMLProperty("./bios/@rebootTimeout", is_int=True)
    smbios_mode = XMLProperty("./smbios/@mode")

    # Host bootloader options
    # Since the elements for a host bootloader are actually directly under
    # <domain> rather than <domain><os>, they are handled via callbacks in
    # the CLI. This is just a placeholder to remind of that fact.

    # Direct kernel boot options
    kernel = XMLProperty("./kernel", do_abspath=True)
    initrd = XMLProperty("./initrd", do_abspath=True)
    kernel_args = XMLProperty("./cmdline")
    dtb = XMLProperty("./dtb", do_abspath=True)
    acpi_tb = XMLProperty("./acpi/table", do_abspath=True)
    acpi_tb_type = XMLProperty("./acpi/table/@type")

    # Container boot options
    init = XMLProperty("./init")
    initargs = XMLChildProperty(_InitArg)
    initenvs = XMLChildProperty(_InitEnv)
    initdir = XMLProperty("./initdir")
    inituser = XMLProperty("./inituser")
    initgroup = XMLProperty("./initgroup")
    def set_initargs_string(self, argstring):
        import shlex
        for obj in self.initargs:
            self.remove_child(obj)
        for val in shlex.split(argstring):
            obj = self.initargs.add_new()
            obj.val = val


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if self.is_container() and not self.init:
            if guest.is_full_os_container():
                self.init = "/sbin/init"
            else:
                self.init = "/bin/sh"
