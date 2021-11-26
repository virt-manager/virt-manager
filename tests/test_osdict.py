# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import pytest

from virtinst import Guest
from virtinst import OSDB
from virtinst import xmlutil
from virtinst.install import urldetect

from tests import utils


##################
# Test osdict.py #
##################


def test_list_os():
    OSDB.list_os()


def test_recommended_resources():
    conn = utils.URIs.open_testdefault_cached()
    guest = Guest(conn)
    res = OSDB.lookup_os("generic").get_recommended_resources()
    assert res.get_recommended_ram(guest.os.arch) is None

    res = OSDB.lookup_os("fedora21").get_recommended_resources()
    assert res.get_recommended_ncpus(guest.os.arch) == 2


def test_urldetct_matching_distros():
    # pylint: disable=protected-access
    allstores = urldetect._build_distro_list(OSDB.lookup_os("generic"))

    seen_distro = []
    for store in allstores:
        for distro in store.matching_distros:
            if distro in seen_distro:
                raise xmlutil.DevError(
                        "store=%s has conflicting matching_distro=%s " %
                        (store.PRETTY_NAME, distro))
            seen_distro.append(distro)


def test_tree_url():
    f26 = OSDB.lookup_os("fedora26")
    f29 = OSDB.lookup_os("fedora29")
    winxp = OSDB.lookup_os("winxp")

    # Valid tree URL
    assert "fedoraproject.org" in f26.get_location("x86_64")

    # Most generic tree URL
    assert "Everything" in f29.get_location("x86_64")

    # Specific tree
    assert "Server" in f29.get_location("x86_64", "jeos")
    assert "Workstation" in f29.get_location("x86_64", "desktop")

    # Has tree URLs, but none for arch
    try:
        f26.get_location("ia64")
        raise AssertionError("Expected failure")
    except RuntimeError as e:
        assert "ia64" in str(e)

    # Has no tree URLs
    try:
        winxp.get_location("x86_64")
        raise AssertionError("Expected failure")
    except RuntimeError as e:
        assert str(e).endswith("URL location")

    # Trigger an error path for code coverage
    assert OSDB.guess_os_by_tree(utils.TESTDIR) is None


def test_kernel_url():
    def _c(name):
        osobj = OSDB.lookup_os(name)
        if not osobj:
            pytest.skip("osinfo-db doesn't have '%s'" % name)
        return osobj.get_kernel_url_arg()

    assert _c("rhel7-unknown") == "inst.repo"
    assert _c("rhel6-unknown") == "method"
    assert _c("fedora-rawhide") == "inst.repo"
    assert _c("fedora20") == "inst.repo"
    assert _c("generic") is None
    assert _c("win10") is None
    assert _c("sle15") == "install"


def test_related_to():
    # pylint: disable=protected-access
    win10 = OSDB.lookup_os("win10")
    assert win10._is_related_to("winxp") is True
    assert win10._is_related_to("win10") is True
    assert win10._is_related_to("fedora26") is False


def test_drivers():
    win7 = OSDB.lookup_os("win7")
    generic = OSDB.lookup_os("generic")
    assert generic.supports_unattended_drivers("x86_64") is False
    assert win7.supports_unattended_drivers("x86_64") is True
    assert win7.supports_unattended_drivers("fakearch") is False
    assert win7.get_pre_installable_drivers_location("x86_64")
