#
# Support for parsing libvirt's domcapabilities XML
#
# Copyright 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import re
import xml.etree.ElementTree as ET

import libvirt

from .domain import DomainCpu
from .logger import log
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
        for enum in self.enums:
            if enum.name == name:
                return enum
        # Didn't find a match. Could be talking to older libvirt, or
        # driver with incomplete info. Return a stub enum
        return _Enum(self.conn)


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


################################
# SEV launch security handling #
################################

class _SEV(XMLBuilder):
    XML_NAME = "sev"
    supported = XMLProperty("./@supported", is_yesno=True)
    cbitpos = XMLProperty("./cbitpos", is_int=True)
    reducedPhysBits = XMLProperty("./reducedPhysBits", is_int=True)


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
    video = XMLChildProperty(_make_capsblock("video"), is_single=True)


class _Features(_CapsBlock):
    XML_NAME = "features"
    gic = XMLChildProperty(_make_capsblock("gic"), is_single=True)
    sev = XMLChildProperty(_SEV, is_single=True)


###############
# CPU classes #
###############

class _CPUModel(XMLBuilder):
    XML_NAME = "model"
    model = XMLProperty(".")
    usable = XMLProperty("./@usable")
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
        if conn.support.conn_domain_capabilities():
            try:
                xml = conn.getDomainCapabilities(emulator, arch,
                    machine, hvtype)
            except Exception:  # pragma: no cover
                log.debug("Error fetching domcapabilities XML",
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
            r".*edk2-i386-.*\.fd",  # upstream qemu
            r".*ovmf-ia32.*",  # fedora, gerd's firmware repo
        ],
        "x86_64": [
            r".*edk2-x86_64-.*\.fd",  # upstream qemu
            r".*OVMF_CODE\.fd",  # RHEL
            r".*ovmf-x64/OVMF.*\.fd",  # gerd's firmware repo
            r".*ovmf-x86_64-.*",  # SUSE
            r".*ovmf.*", ".*OVMF.*",  # generic attempt at a catchall
        ],
        "aarch64": [
            r".*AAVMF_CODE\.fd",  # RHEL
            r".*aarch64/QEMU_EFI.*",  # gerd's firmware repo
            r".*aarch64.*",  # generic attempt at a catchall
            r".*edk2-aarch64-code\.fd",  # upstream qemu
        ],
        "armv7l": [
            r".*AAVMF32_CODE\.fd",  # Debian qemu-efi-arm package
            r".*arm/QEMU_EFI.*",  # fedora, gerd's firmware repo
            r".*edk2-arm-code\.fd"  # upstream qemu
        ],
    }

    def find_uefi_path_for_arch(self):
        """
        Search the loader paths for one that matches the passed arch
        """
        if not self.arch_can_uefi():
            return  # pragma: no cover

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
        host-model in fact predates this support, however it wasn't
        general purpose safe prior to domcaps advertisement.
        """
        for m in self.cpu.modes:
            if (m.name == "host-model" and m.supported and
                    m.models[0].fallback == "forbid"):
                return True
        return False

    def get_cpu_models(self):
        models = []

        for m in self.cpu.modes:
            if m.name == "custom" and m.supported:
                for model in m.models:
                    if model.usable != "no":
                        models.append(model.model)

        return models

    def _convert_mode_to_cpu(self, xml):
        root = ET.fromstring(xml)
        root.tag = "cpu"
        root.attrib = {}
        arch = ET.SubElement(root, "arch")
        arch.text = self.arch
        return ET.tostring(root, encoding="unicode")

    def _get_expanded_cpu(self, mode):
        cpuXML = self._convert_mode_to_cpu(mode.get_xml())
        log.debug("Generated CPU XML for security flag baseline:\n%s", cpuXML)

        try:
            expandedXML = self.conn.baselineHypervisorCPU(
                    self.path, self.arch, self.machine, self.domain, [cpuXML],
                    libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES)
        except (libvirt.libvirtError, AttributeError):
            expandedXML = self.conn.baselineCPU([cpuXML],
                    libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES)

        return DomainCpu(self.conn, expandedXML)

    def _lookup_cpu_security_features(self):
        ret = []
        sec_features = [
                'spec-ctrl',
                'ssbd',
                'ibpb',
                'virt-ssbd',
                'md-clear']

        for m in self.cpu.modes:
            if m.name != "host-model" or not m.supported:
                continue  # pragma: no cover

            try:
                cpu = self._get_expanded_cpu(m)
            except libvirt.libvirtError as e:  # pragma: no cover
                log.warning(_("Failed to get expanded CPU XML: %s"), e)
                break

            for feature in cpu.features:
                if feature.name in sec_features:
                    ret.append(feature.name)

        log.debug("Found host-model security features: %s", ret)
        return ret

    _features = None
    def get_cpu_security_features(self):
        if self._features is None:
            self._features = self._lookup_cpu_security_features() or []
        return self._features


    def supports_sev_launch_security(self):
        """
        Returns False if either libvirt doesn't advertise support for SEV at
        all (< libvirt-4.5.0) or if it explicitly advertises it as unsupported
        on the platform
        """
        return bool(self.features.sev.supported)

    def supports_video_bochs(self):
        """
        Returns False if either libvirt or qemu do not have support to bochs
        video type.
        """
        models = self.devices.video.get_enum("modelType").get_values()
        return bool("bochs" in models)

    XML_NAME = "domainCapabilities"
    os = XMLChildProperty(_OS, is_single=True)
    cpu = XMLChildProperty(_CPU, is_single=True)
    devices = XMLChildProperty(_Devices, is_single=True)
    features = XMLChildProperty(_Features, is_single=True)

    arch = XMLProperty("./arch")
    domain = XMLProperty("./domain")
    machine = XMLProperty("./machine")
    path = XMLProperty("./path")
