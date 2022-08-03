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

    def has_value(self, val):
        return val in self.get_values()


class _Enum(_HasValues):
    XML_NAME = "enum"
    name = XMLProperty("./@name")


class _CapsBlock(_HasValues):
    supported = XMLProperty("./@supported", is_yesno=True)
    _supported_present = XMLProperty("./@supported")
    enums = XMLChildProperty(_Enum)

    @property
    def present(self):
        return self._supported_present is not None

    def enum_names(self):
        return [e.name for e in self.enums]

    def has_enum(self, name):
        return name in self.enum_names()

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
    maxESGuests = XMLProperty("./maxESGuests")


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
    graphics = XMLChildProperty(_make_capsblock("graphics"), is_single=True)
    tpm = XMLChildProperty(_make_capsblock("tpm"), is_single=True)
    filesystem = XMLChildProperty(_make_capsblock("filesystem"), is_single=True)


class _Features(_CapsBlock):
    XML_NAME = "features"
    gic = XMLChildProperty(_make_capsblock("gic"), is_single=True)
    sev = XMLChildProperty(_SEV, is_single=True)


class _MemoryBacking(_CapsBlock):
    XML_NAME = "memoryBacking"


###############
# CPU classes #
###############

class _CPUModel(XMLBuilder):
    XML_NAME = "model"
    model = XMLProperty(".")
    usable = XMLProperty("./@usable")
    fallback = XMLProperty("./@fallback")


class _CPUMode(_CapsBlock):
    XML_NAME = "mode"
    name = XMLProperty("./@name")

    models = XMLChildProperty(_CPUModel)
    def get_model(self, name):
        for model in self.models:
            if model.model == name:
                return model


class _CPU(XMLBuilder):
    XML_NAME = "cpu"
    modes = XMLChildProperty(_CPUMode)

    def get_mode(self, name):
        for mode in self.modes:
            if mode.name == name:
                return mode


#############################
# CPU flags/baseline helpers#
#############################

def _convert_mode_to_cpu(xml, arch):
    root = ET.fromstring(xml)
    root.tag = "cpu"
    root.attrib = {}
    aelement = ET.SubElement(root, "arch")
    aelement.text = arch
    return ET.tostring(root, encoding="unicode")


def _get_expanded_cpu(domcaps, mode):
    cpuXML = _convert_mode_to_cpu(mode.get_xml(), domcaps.arch)
    log.debug("Generated CPU XML for security flag baseline:\n%s", cpuXML)

    try:
        expandedXML = domcaps.conn.baselineHypervisorCPU(
                domcaps.path, domcaps.arch,
                domcaps.machine, domcaps.domain, [cpuXML],
                libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES)
    except (libvirt.libvirtError, AttributeError):
        expandedXML = domcaps.conn.baselineCPU([cpuXML],
                libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES)

    return DomainCpu(domcaps.conn, expandedXML)


def _lookup_cpu_security_features(domcaps):
    ret = []
    sec_features = [
            'spec-ctrl',
            'ssbd',
            'ibpb',
            'virt-ssbd',
            'md-clear']

    for m in domcaps.cpu.modes:
        if m.name != "host-model" or not m.supported:
            continue  # pragma: no cover

        try:
            cpu = _get_expanded_cpu(domcaps, m)
        except libvirt.libvirtError as e:  # pragma: no cover
            log.warning(_("Failed to get expanded CPU XML: %s"), e)
            break

        for feature in cpu.features:
            if feature.name in sec_features:
                ret.append(feature.name)

    log.debug("Found host-model security features: %s", ret)
    return ret


#################################
# DomainCapabilities main class #
#################################

class DomainCapabilities(XMLBuilder):
    XML_NAME = "domainCapabilities"
    os = XMLChildProperty(_OS, is_single=True)
    cpu = XMLChildProperty(_CPU, is_single=True)
    devices = XMLChildProperty(_Devices, is_single=True)
    features = XMLChildProperty(_Features, is_single=True)
    memorybacking = XMLChildProperty(_MemoryBacking, is_single=True)

    arch = XMLProperty("./arch")
    domain = XMLProperty("./domain")
    machine = XMLProperty("./machine")
    path = XMLProperty("./path")


    ################
    # Init helpers #
    ################

    @staticmethod
    def build_from_params(conn, emulator, arch, machine, hvtype):
        xml = None
        if conn.support.conn_domain_capabilities():
            try:
                xml = conn.getDomainCapabilities(emulator, arch,
                    machine, hvtype)
                log.debug("Fetched domain capabilities for (%s,%s,%s,%s): %s",
                          emulator, arch, machine, hvtype, xml)
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


    #########################
    # UEFI/firmware methods #
    #########################

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

        firmware_files = [f.value for f in self.os.loader.values]
        if self.conn.is_bhyve():
            for firmware_file in firmware_files:
                if 'BHYVE_UEFI.fd' in firmware_file:
                    return firmware_file
            return (firmware_files and
                    firmware_files[0] or None)  # pragma: no cover

        patterns = self._uefi_arch_patterns.get(self.arch)
        for pattern in patterns:
            for path in firmware_files:
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
            return _("Default")

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

    def supports_uefi_loader(self):
        """
        Return True if libvirt advertises support for UEFI loader
        """
        return self.os.loader.get_enum("readonly").has_value("yes")

    def supports_firmware_efi(self):
        return self.os.get_enum("firmware").has_value("efi")


    #######################
    # CPU support methods #
    #######################

    def supports_safe_host_model(self):
        """
        Return True if domcaps reports support for cpu mode=host-model.
        host-model in fact predates this support, however it wasn't
        general purpose safe prior to domcaps advertisement.
        """
        m = self.cpu.get_mode("host-model")
        return (m and m.supported and
                m.models[0].fallback == "forbid")

    def supports_safe_host_passthrough(self):
        """
        Return True if host-passthrough is safe enough to use by default.
        We limit this to domcaps new enough to report whether host-passthrough
        is migratable or not, which also means libvirt is about new enough
        to not taint the VM for using host-passthrough
        """
        m = self.cpu.get_mode("host-passthrough")
        return (m and m.supported and
                "on" in m.get_enum("hostPassthroughMigratable").get_values())

    def get_cpu_models(self):
        models = []

        for m in self.cpu.modes:
            if m.name == "custom" and m.supported:
                for model in m.models:
                    if model.usable != "no":
                        models.append(model.model)

        return models

    _features = None
    def get_cpu_security_features(self):
        if self._features is None:
            self._features = _lookup_cpu_security_features(self) or []
        return self._features


    ########################
    # Misc support methods #
    ########################

    def supports_sev_launch_security(self, check_es=False):
        """
        Returns False if either libvirt doesn't advertise support for SEV at
        all (< libvirt-4.5.0) or if it explicitly advertises it as unsupported
        on the platform
        """
        if check_es:
            return bool(self.features.sev.supported and
                        self.features.sev.maxESGuests)
        return bool(self.features.sev.supported)

    def supports_video_bochs(self):
        """
        Returns False if either libvirt or qemu do not have support to bochs
        video type.
        """
        return self.devices.video.get_enum("modelType").has_value("bochs")

    def supports_video_qxl(self):
        if not self.devices.video.has_enum("modelType"):
            # qxl long predates modelType in domcaps, so if it is missing,
            # use spice support as a rough value
            return self.supports_graphics_spice()
        return self.devices.video.get_enum("modelType").has_value("qxl")

    def supports_video_virtio(self):
        return self.devices.video.get_enum("modelType").has_value("virtio")

    def supports_tpm_emulator(self):
        """
        Returns False if either libvirt or qemu do not have support for
        emulating a TPM.
        """
        models = self.devices.tpm.get_enum("model").get_values()
        backends = self.devices.tpm.get_enum("backendModel").get_values()

        if self.arch == "armv7l" and models == ["tpm-tis"]:
            # libvirt as of 8.4.0 can advertise armv7l tpm-tis support,
            # but then explicitly rejects that config. If we see it,
            # assume TPM is not supported
            # https://gitlab.com/libvirt/libvirt/-/issues/329
            return False

        return len(models) > 0 and bool("emulator" in backends)

    def supports_graphics_spice(self):
        if not self.devices.graphics.supported:
            # domcaps is too old, or the driver doesn't advertise graphics
            # support. Use our pre-existing logic
            if not self.conn.is_qemu() and not self.conn.is_test():
                return False
            return self.conn.caps.host.cpu.arch in ["i686", "x86_64"]

        return self.devices.graphics.get_enum("type").has_value("spice")

    def supports_filesystem_virtiofs(self):
        """
        Return True if libvirt advertises support for virtiofs
        """
        return self.devices.filesystem.get_enum(
                "driverType").has_value("virtiofs")

    def supports_memorybacking_memfd(self):
        """
        Return True if libvirt advertises support for memfd memory backend
        """
        return self.memorybacking.get_enum("sourceType").has_value("memfd")
