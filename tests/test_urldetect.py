# Copyright (C) 2020 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import unittest.mock

import pytest

import virtinst

import tests.utils
import tests.urlfetcher_mock


@unittest.mock.patch.dict(os.environ,
        {"VIRTINST_TEST_SUITE_FORCE_LIBOSINFO": "0"})
def _test(mockurl, distro=None, initrd=None,
          kernel=None, xen=False, iso=False, arch=None):
    # pylint: disable=protected-access

    conn = tests.utils.URIs.open_testdefault_cached()
    guest = virtinst.Guest(conn)
    guest.os.os_type = xen and "xen" or "hvm"
    if arch:
        guest.os.arch = arch

    url = tests.urlfetcher_mock.make_mock_input_url(mockurl)
    installer = virtinst.Installer(guest.conn, location=url)
    treemedia = installer._treemedia
    treemedia._get_fetcher(guest, None)
    if iso:
        treemedia._cached_fetcher._is_iso = True

    detected_distro = installer.detect_distro(guest)
    assert (distro or "") in (detected_distro or "")

    # Fetch regular kernel
    treecache = treemedia._cached_data
    kernels = [p[0] for p in treecache.kernel_pairs]
    initrds = [p[1] for p in treecache.kernel_pairs]
    if initrd:
        assert any([i.endswith(initrd) for i in initrds])
    if kernel:
        assert any([k.endswith(kernel) for k in kernels])


def test_debian():
    _test("debian/buster/main/installer-amd64", distro="debian10",
            kernel="linux")
    _test("debian/buster/main/installer-amd64", distro="debian10",
            xen=True, kernel="netboot/xen/vmlinuz")
    _test("debian/buster/main/installer-s390x", distro="debian10",
            kernel="kernel.debian")
    _test("debian/buster/main/installer-ppc64el", distro="debian10",
            kernel="vmlinux")
    _test("debian/buster/main/installer-arm64", distro="debian10")
    _test("debian/daily-images/amd64", distro="debiantesting")

    _test("debian/debian-8.10.0-amd64-netinst.iso",
            kernel="linux")
    _test("debian/debian-8.10.0-amd64-netinst.iso",
            iso=True, arch="x86_64", kernel="install.amd/vmlinuz")
    _test("debian/debian-8.10.0-s390x-netinst.iso",
            iso=True, arch="s390x", kernel="linux_vm")
    _test("debian/debian-8.10.0-ppc64el-netinst.iso",
            iso=True, arch="ppc64le", kernel="vmlinux")
    _test("debian/debian-8.10.0-i386-netinst.iso",
            iso=True, arch="i686", kernel="install.386/vmlinuz")
    _test("debian/debian-8.10.0-arm64-netinst.iso",
            iso=True, arch="aarch64", kernel="install.a64/vmlinuz")
    # Bad arch triggers a fallback path
    _test("debian/debian-8.10.0-amd64-netinst.iso",
            iso=True, arch="badarch", kernel="install/vmlinuz")
    # Fails to detect treearch, hits certain paths
    _test("debian/debian-8.10.0-s390x-netinst.iso",
            kernel="linux")


def test_ubuntu():
    _test("ubuntu/bionic/main/installer-amd64", "ubuntu18.04")
    _test("ubuntu/focal/main/installer-amd64", "ubuntu20.04")

    _test("ubuntu/ubuntu-17.10-amd64.iso",
            iso=True, kernel="install/vmlinuz")
    _test("ubuntu/ubuntu-17.10-s390x.iso",
            iso=True, arch="s390x", kernel="boot/kernel.ubuntu")


def test_fedora():
    _test("fedora/30", "fedora30")
    _test("fedora/rawhide", "fedora-unknown")
    # Fake fedora version 99 to hit certain code paths
    _test("fedora/99", "fedora-unknown")


def test_rhel():
    _test("rhel/7.6", "rhel7.6")
    # Fake rhel 7.20 to hit certain code paths
    _test("rhel/7.20", "rhel7.")


def test_centos():
    _test("centos/6.10", "centos6.10")
    _test("centos/sl7", "centos7.0")


def test_opensuse():
    _test("opensuse/tumbleweed", "opensusetumbleweed")
    _test("opensuse/10.3", "opensuse10.3")
    _test("opensuse/11.4", "opensuse11.4")
    _test("opensuse/12.3", "opensuse12.3")
    _test("opensuse/13.2", "opensuse13.2",
            xen=True, initrd="initrd-xen")
    # Specifically use trailing slash to hit url scraping code path
    _test("opensuse/42.3/", "opensuse42.3")
    # Fake version to trigger particular path in urldetect.py
    _test("opensuse/15.9", "opensuse15")
    # Has a bad version number which isn't in osinfo-db
    _test("opensuse/badversion/", None)


def test_suse():
    _test("suse/SLES-10-SP4-DVD-x86_64-GM-DVD1.iso", "sles10sp4")
    _test("suse/SLES-11-SP4-DVD-s390x-GM-DVD1.iso", "sles11sp4",
            kernel="vmrdr.ikr")
    _test("suse/SLES-11-SP4-DVD-ppc64-GM-DVD1.iso", "sles11sp4",
            kernel="linux64")


def test_mageia():
    _test("mageia/5", "mageia5", initrd="all.rdz")
    _test("mageia/8", initrd="all.rdz")


def test_misc():
    _test("generic")

    with pytest.raises(ValueError) as e:
        _test("empty")
    assert "installable distribution" in str(e.value)
    assert "mistyped" in str(e.value)
