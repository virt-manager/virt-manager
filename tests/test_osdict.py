# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import unittest

from virtinst import Guest
from virtinst import OSDB
from virtinst.install import urldetect

from tests import utils


class TestOSDB(unittest.TestCase):
    """
    Test osdict/OSDB
    """
    def test_osdict_aliases_ro(self):
        aliases = getattr(OSDB, "_aliases")

        if len(aliases) != 42:
            raise AssertionError(_("OSDB._aliases changed size. It "
                "should never be extended, since it is only for back "
                "compat with pre-libosinfo osdict.py"))

    def test_list_os(self):
        OSDB.list_os()

    def test_recommended_resources(self):
        conn = utils.URIs.open_testdefault_cached()
        guest = Guest(conn)
        res = OSDB.lookup_os("generic").get_recommended_resources()
        self.assertEqual(res.get_recommended_ram(guest.os.arch), None)

        res = OSDB.lookup_os("fedora21").get_recommended_resources()
        self.assertEqual(res.get_recommended_ncpus(guest.os.arch), 2)

    def test_urldetct_matching_distros(self):
        # pylint: disable=protected-access
        allstores = urldetect._build_distro_list(OSDB.lookup_os("generic"))

        seen_distro = []
        for store in allstores:
            for distro in store.matching_distros:
                if distro in seen_distro:
                    raise RuntimeError("programming error: "
                            "store=%s has conflicting matching_distro=%s " %
                            (store.PRETTY_NAME, distro))
                seen_distro.append(distro)

    def test_tree_url(self):
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
        self.assertEqual(OSDB.guess_os_by_tree(os.getcwd()), None)

    def test_kernel_url(self):
        def _c(name):
            osobj = OSDB.lookup_os(name)
            if not osobj:
                self.skipTest("osinfo-db doesn't have '%s'" % name)
            return osobj.get_kernel_url_arg()

        self.assertEqual(_c("rhel7-unknown"), "inst.repo")
        self.assertEqual(_c("rhel6-unknown"), "method")
        self.assertEqual(_c("fedora-rawhide"), "inst.repo")
        self.assertEqual(_c("fedora20"), "inst.repo")
        self.assertEqual(_c("generic"), None)
        self.assertEqual(_c("win10"), None)
        self.assertEqual(_c("sle15"), "install")

    def test_related_to(self):
        # pylint: disable=protected-access
        win10 = OSDB.lookup_os("win10")
        self.assertTrue(win10._is_related_to("winxp"))
        self.assertTrue(win10._is_related_to("win10"))
        self.assertTrue(win10._is_related_to("fedora26") is False)

    def test_drivers(self):
        win7 = OSDB.lookup_os("win7")
        generic = OSDB.lookup_os("generic")
        self.assertFalse(generic.supports_unattended_drivers("x86_64"))
        self.assertTrue(win7.supports_unattended_drivers("x86_64"))
        self.assertFalse(win7.supports_unattended_drivers("fakearch"))
        self.assertTrue(win7.get_pre_installable_drivers_location("x86_64"))

        # Just call this for code coverage. Values differ by osinfo-db version
        win7.get_post_installable_drivers_location("x86_64")

        win10 = OSDB.lookup_os("win10")
        win10.get_post_installable_drivers_location("x86_64")
        win10.supports_unattended_agents("x86_64")
