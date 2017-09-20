#
# Support for parsing libvirt's domcapabilities XML
#
# Copyright 2014 Red Hat, Inc.
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

import logging
import re

from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _Value(XMLBuilder):
    _XML_ROOT_NAME = "value"
    value = XMLProperty(".")


class _HasValues(XMLBuilder):
    values = XMLChildProperty(_Value)

    def get_values(self):
        return [v.value for v in self.values]


class _Enum(_HasValues):
    _XML_ROOT_NAME = "enum"
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
    class TmpClass(_CapsBlock):
        pass
    setattr(TmpClass, "_XML_ROOT_NAME", xml_root_name)
    return TmpClass


class _OS(_CapsBlock):
    _XML_ROOT_NAME = "os"
    loader = XMLChildProperty(_make_capsblock("loader"), is_single=True)


class _Devices(_CapsBlock):
    _XML_ROOT_NAME = "devices"
    hostdev = XMLChildProperty(_make_capsblock("hostdev"), is_single=True)
    disk = XMLChildProperty(_make_capsblock("disk"), is_single=True)


class _Features(_CapsBlock):
    _XML_ROOT_NAME = "features"
    gic = XMLChildProperty(_make_capsblock("gic"), is_single=True)


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
        "x86_64": [
            ".*OVMF_CODE\.fd",  # RHEL
            ".*ovmf-x64/OVMF.*\.fd",  # gerd's firmware repo
            ".*ovmf-x86_64-.*",  # SUSE
            ".*ovmf.*", ".*OVMF.*",  # generic attempt at a catchall
        ],
        "aarch64": [
            ".*AAVMF_CODE\.fd",  # RHEL
            ".*aarch64/QEMU_EFI.*",  # gerd's firmware repo
            ".*aarch64.*",  # generic attempt at a catchall
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
        return self.arch in self._uefi_arch_patterns.keys()

    def supports_uefi_xml(self):
        """
        Return True if libvirt advertises support for proper UEFI setup
        """
        return ("readonly" in self.os.loader.enum_names() and
                "yes" in self.os.loader.get_enum("readonly").get_values())


    _XML_ROOT_NAME = "domainCapabilities"
    os = XMLChildProperty(_OS, is_single=True)
    devices = XMLChildProperty(_Devices, is_single=True)

    arch = XMLProperty("./arch")
    features = XMLChildProperty(_Features, is_single=True)
