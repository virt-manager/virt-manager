#
# Support for parsing libvirt's domcapabilities XML
#
# Copyright 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import re

from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


########################################
# Genering <enum> and <value> handling #
########################################

class _Value(XMLBuilder):
    XML_NAME = "value"
    value = XMLProperty(".")


class _HasValues(XMLBuilder):
    values = XMLChildProperty(_Value)

    def get_values(self):
        return [v.value for v in self.values]


class _Enum(_HasValues):
    XML_NAME = "enum"
    name = XMLProperty("./@name")


class _CapsBlock(_HasValues):
    supported = XMLProperty("./@supported", is_yesno=True)
    enums = XMLChildProperty(_Enum)

    def enum_names(self):
        return [e.name for e in self.enums]

    def get_enum(self, name):
        d = dict((e.name, e) for e in self.enums)
        return d[name]


def _make_capsblock(xml_root_name):
    """
    Build a class object representing a list of <enum> in the XML. For
    example, domcapabilities may have a block like:

    <graphics supported='yes'>
      <enum name='type'>
        <value>sdl</value>
        <value>vnc</value>
        <value>spice</value>
      </enum>
    </graphics>

    To build a class that tracks that whole <graphics> block, call this
    like _make_capsblock("graphics")
    """
    class TmpClass(_CapsBlock):
        pass
    setattr(TmpClass, "XML_NAME", xml_root_name)
    return TmpClass


#############################
# Misc toplevel XML classes #
#############################

class _OS(_CapsBlock):
    XML_NAME = "os"
    loader = XMLChildProperty(_make_capsblock("loader"), is_single=True)


class _Devices(_CapsBlock):
    XML_NAME = "devices"
    hostdev = XMLChildProperty(_make_capsblock("hostdev"), is_single=True)
    disk = XMLChildProperty(_make_capsblock("disk"), is_single=True)


class _Features(_CapsBlock):
    XML_NAME = "features"
    gic = XMLChildProperty(_make_capsblock("gic"), is_single=True)


###############
# CPU classes #
###############

class _CPUModel(XMLBuilder):
    XML_NAME = "model"
    model = XMLProperty(".")
    usable = XMLProperty("./@usable", is_yesno=True)
    fallback = XMLProperty("./@fallback")


class _CPUFeature(XMLBuilder):
    XML_NAME = "feature"
    name = XMLProperty("./@name")
    policy = XMLProperty("./@policy")


class _CPUMode(XMLBuilder):
    XML_NAME = "mode"
    name = XMLProperty("./@name")
    supported = XMLProperty("./@supported", is_yesno=True)
    vendor = XMLProperty("./vendor")

    models = XMLChildProperty(_CPUModel)
    def get_model(self, name):
        for model in self.models:
            if model.model == name:
                return model

    features = XMLChildProperty(_CPUFeature)


class _CPU(XMLBuilder):
    XML_NAME = "cpu"
    modes = XMLChildProperty(_CPUMode)

    def get_mode(self, name):
        for mode in self.modes:
            if mode.name == name:
                return mode


#################################
# DomainCapabilities main class #
#################################

class DomainCapabilities(XMLBuilder):
    @staticmethod
    def build_from_params(conn, emulator, arch, machine, hvtype):
        xml = None
        if conn.check_support(
                conn.SUPPORT_CONN_DOMAIN_CAPABILITIES):
            try:
                xml = conn.getDomainCapabilities(emulator, arch,
                    machine, hvtype)
            except Exception:
                logging.debug("Error fetching domcapabilities XML",
                    exc_info=True)

        if not xml:
            # If not supported, just use a stub object
            return DomainCapabilities(conn)
        return DomainCapabilities(conn, parsexml=xml)

    @staticmethod
    def build_from_guest(guest):
        return DomainCapabilities.build_from_params(guest.conn,
            guest.emulator, guest.os.arch, guest.os.machine, guest.type)

    # Mapping of UEFI binary names to their associated architectures. We
    # only use this info to do things automagically for the user, it shouldn't
    # validate anything the user explicitly enters.
    _uefi_arch_patterns = {
        "i686": [
            r".*ovmf-ia32.*",  # fedora, gerd's firmware repo
        ],
        "x86_64": [
            r".*OVMF_CODE\.fd",  # RHEL
            r".*ovmf-x64/OVMF.*\.fd",  # gerd's firmware repo
            r".*ovmf-x86_64-.*",  # SUSE
            r".*ovmf.*", ".*OVMF.*",  # generic attempt at a catchall
        ],
        "aarch64": [
            r".*AAVMF_CODE\.fd",  # RHEL
            r".*aarch64/QEMU_EFI.*",  # gerd's firmware repo
            r".*aarch64.*",  # generic attempt at a catchall
        ],
        "armv7l": [
            r".*arm/QEMU_EFI.*",  # fedora, gerd's firmware repo
        ],
    }

    def find_uefi_path_for_arch(self):
        """
        Search the loader paths for one that matches the passed arch
        """
        if not self.arch_can_uefi():
            return

        patterns = self._uefi_arch_patterns.get(self.arch)
        for pattern in patterns:
            for path in [v.value for v in self.os.loader.values]:
                if re.match(pattern, path):
                    return path

    def label_for_firmware_path(self, path):
        """
        Return a pretty label for passed path, based on if we know
        about it or not
        """
        if not path:
            if self.arch in ["i686", "x86_64"]:
                return _("BIOS")
            return _("None")

        for arch, patterns in self._uefi_arch_patterns.items():
            for pattern in patterns:
                if re.match(pattern, path):
                    return (_("UEFI %(arch)s: %(path)s") %
                        {"arch": arch, "path": path})

        return _("Custom: %(path)s" % {"path": path})

    def arch_can_uefi(self):
        """
        Return True if we know how to setup UEFI for the passed arch
        """
        return self.arch in list(self._uefi_arch_patterns.keys())

    def supports_uefi_xml(self):
        """
        Return True if libvirt advertises support for proper UEFI setup
        """
        return ("readonly" in self.os.loader.enum_names() and
                "yes" in self.os.loader.get_enum("readonly").get_values())

    def supports_safe_host_model(self):
        """
        Return True if domcaps reports support for cpu mode=host-model.
        host-model infact predates this support, however it wasn't
        general purpose safe prior to domcaps advertisement
        """
        return [(m.name == "host-model" and m.supported)
                for m in self.cpu.modes]


    XML_NAME = "domainCapabilities"
    os = XMLChildProperty(_OS, is_single=True)
    cpu = XMLChildProperty(_CPU, is_single=True)
    devices = XMLChildProperty(_Devices, is_single=True)
    features = XMLChildProperty(_Features, is_single=True)

    arch = XMLProperty("./arch")
    domain = XMLProperty("./domain")
    machine = XMLProperty("./machine")
    path = XMLProperty("./path")
