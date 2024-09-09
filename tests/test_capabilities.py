# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

import pytest

from tests import utils

from virtinst import Capabilities
from virtinst import DomainCapabilities


DATADIR = utils.DATADIR + "/capabilities"


def _buildCaps(filename):
    path = os.path.join(DATADIR, filename)
    conn = utils.URIs.open_testdefault_cached()
    return Capabilities(conn, open(path).read())


def testCapsCPUFeaturesNewSyntax():
    filename = "test-qemu-with-kvm.xml"
    caps = _buildCaps(filename)

    assert caps.host.cpu.arch == "x86_64"
    assert caps.host.cpu.model == "core2duo"


def testCapsUtilFuncs():
    caps_with_kvm = _buildCaps("test-qemu-with-kvm.xml")
    caps_no_kvm = _buildCaps("test-qemu-no-kvm.xml")
    caps_empty = _buildCaps("test-empty.xml")

    def test_utils(caps, has_guests, is_kvm):
        assert caps.has_install_options() == has_guests
        if caps.guests:
            assert caps.guests[0].is_kvm_available() == is_kvm

    test_utils(caps_empty, False, False)
    test_utils(caps_with_kvm, True, True)
    test_utils(caps_no_kvm, True, False)

    # Small test for extra coverage
    with pytest.raises(ValueError, match=r".*virtualization type 'xen'.*"):
        caps_empty.guest_lookup(os_type="linux")
    with pytest.raises(ValueError, match=r".*not support any.*"):
        caps_empty.guest_lookup()


def testGuestCapabilities():
    filename = "kvm-x86_64.xml"
    caps = _buildCaps(filename)

    assert caps.guests[0].supports_externalSnapshot() is True


##############################
# domcapabilities.py testing #
##############################

def testDomainCapabilities():
    xml = open(DATADIR + "/test-domcaps.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

    assert caps.machine == "my-machine-type"
    assert caps.arch == "x86_64"
    assert caps.domain == "kvm"
    assert caps.path == "/bin/emulatorbin"

    assert caps.os.loader.supported is True
    assert caps.os.loader.get_values() == ["/foo/bar", "/tmp/my_path"]
    assert caps.os.loader.enum_names() == ["type", "readonly"]
    assert caps.os.loader.get_enum("type").get_values() == [
            "rom", "pflash"]
    assert caps.os.loader.get_enum("idontexist").get_values() == []


def testDomainCapabilitiesx86():
    xml = open(DATADIR + "/kvm-x86_64-domcaps-latest.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

    custom_mode = caps.cpu.get_mode("custom")
    assert bool(custom_mode)
    cpu_model = custom_mode.get_model("Opteron_G4")
    assert bool(cpu_model)
    assert cpu_model.usable

    models = caps.get_cpu_models()
    assert len(models) > 10
    assert "SandyBridge" in models

    assert caps.label_for_firmware_path(None) == "BIOS"
    assert "Custom:" in caps.label_for_firmware_path("/foobar")
    assert "UEFI" in caps.label_for_firmware_path("OVMF")

    assert caps.supports_filesystem_virtiofs()
    assert caps.supports_memorybacking_memfd()
    assert caps.supports_redirdev_usb()
    assert caps.supports_channel_spicevmc()

    xml = open(DATADIR + "/kvm-x86_64-domcaps-amd-sev.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)
    assert caps.supports_sev_launch_security()


def testDomainCapabilitiesAArch64():
    xml = open(DATADIR + "/kvm-aarch64-domcaps.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

    assert "Default" in caps.label_for_firmware_path(None)
    assert "Custom:" in caps.label_for_firmware_path("/foobar")
    assert "UEFI" in caps.label_for_firmware_path("aarch64/QEMU_EFI")

    assert caps.supports_filesystem_virtiofs()
    assert caps.supports_memorybacking_memfd()
    assert caps.supports_redirdev_usb()
    assert caps.supports_channel_spicevmc()


def testDomainCapabilitiesPPC64le():
    xml = open(DATADIR + "/kvm-ppc64le-domcaps.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

    custom_mode = caps.cpu.get_mode("custom")
    assert bool(custom_mode)

    models = caps.get_cpu_models()
    assert "POWER9" in models

    assert "Default" in caps.label_for_firmware_path(None)

    assert caps.supports_filesystem_virtiofs()
    assert caps.supports_memorybacking_memfd()
    assert caps.supports_redirdev_usb()
    assert not caps.supports_channel_spicevmc()


def testDomainCapabilitiesRISCV64():
    xml = open(DATADIR + "/qemu-riscv64-domcaps.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

    host_mode = caps.cpu.get_mode("host-passthrough")
    assert bool(host_mode)
    assert not host_mode.supported
    max_mode = caps.cpu.get_mode("maximum")
    assert bool(max_mode)
    assert max_mode.supported
    custom_mode = caps.cpu.get_mode("custom")
    assert bool(custom_mode)
    cpu_model = custom_mode.get_model("rv64")
    assert bool(cpu_model)
    assert cpu_model.usable

    models = caps.get_cpu_models()
    assert len(models) > 5
    assert "veyron-v1" in models

    assert "Default" in caps.label_for_firmware_path(None)
    assert "Custom:" in caps.label_for_firmware_path("/foobar")
    assert "UEFI" in caps.label_for_firmware_path("RISCV_VIRT_CODE.fd")

    assert caps.supports_filesystem_virtiofs()
    assert caps.supports_memorybacking_memfd()
    assert caps.supports_redirdev_usb()
    assert caps.supports_channel_spicevmc()


def testDomainCapabilitiesLoongArch64():
    xml = open(DATADIR + "/kvm-loongarch64-domcaps.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

    host_mode = caps.cpu.get_mode("host-passthrough")
    assert bool(host_mode)
    assert host_mode.supported
    max_mode = caps.cpu.get_mode("maximum")
    assert bool(max_mode)
    assert max_mode.supported
    custom_mode = caps.cpu.get_mode("custom")
    assert bool(custom_mode)
    cpu_model = custom_mode.get_model("la132")
    assert bool(cpu_model)
    assert cpu_model.usable

    models = caps.get_cpu_models()
    assert len(models) > 2
    assert "la464" in models

    assert "Default" in caps.label_for_firmware_path(None)
    assert "Custom:" in caps.label_for_firmware_path("/foobar")
    assert "UEFI" in caps.label_for_firmware_path("loongarch64/QEMU_CODE.fd")

    assert caps.supports_filesystem_virtiofs()
    assert caps.supports_memorybacking_memfd()
    assert caps.supports_redirdev_usb()
    assert caps.supports_channel_spicevmc()
