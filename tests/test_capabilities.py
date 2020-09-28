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
    host_feature_list = ['lahf_lm', 'xtpr', 'cx16', 'tm2', 'est', 'vmx',
        'ds_cpl', 'pbe', 'tm', 'ht', 'ss', 'acpi', 'ds']

    caps = _buildCaps(filename)
    for f in host_feature_list:
        assert f in [feat.name for feat in caps.host.cpu.features]

    assert caps.host.cpu.model == "core2duo"
    assert caps.host.cpu.vendor == "Intel"
    assert caps.host.cpu.topology.threads == 3
    assert caps.host.cpu.topology.cores == 5
    assert caps.host.cpu.topology.sockets == 7


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


def testCapsNuma():
    cells = _buildCaps("lxc.xml").host.topology.cells
    assert len(cells) == 1
    assert len(cells[0].cpus) == 8
    assert cells[0].cpus[3].id == '3'


##############################
# domcapabilities.py testing #
##############################


def testDomainCapabilities():
    xml = open(DATADIR + "/test-domcaps.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

    assert caps.os.loader.supported is True
    assert caps.os.loader.get_values() == ["/foo/bar", "/tmp/my_path"]
    assert caps.os.loader.enum_names() == ["type", "readonly"]
    assert caps.os.loader.get_enum("type").get_values() == [
            "rom", "pflash"]
    assert caps.os.loader.get_enum("idontexist").get_values() == []


def testDomainCapabilitiesx86():
    xml = open(DATADIR + "/kvm-x86_64-domcaps.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

    assert caps.machine == "pc-i440fx-2.1"
    assert caps.arch == "x86_64"
    assert caps.domain == "kvm"
    assert caps.path == "/bin/qemu-system-x86_64"

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


def testDomainCapabilitiesAArch64():
    xml = open(DATADIR + "/kvm-aarch64-domcaps.xml").read()
    caps = DomainCapabilities(utils.URIs.open_testdriver_cached(), xml)

    assert "None" in caps.label_for_firmware_path(None)
