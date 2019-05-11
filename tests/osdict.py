# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest

from virtinst import Guest
from virtinst import OSDB
from virtinst import urldetect

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

    def test_recommended_resources(self):
        conn = utils.URIs.open_testdefault_cached()
        guest = Guest(conn)
        assert not OSDB.lookup_os("generic").get_recommended_resources(guest)

        res = OSDB.lookup_os("fedora21").get_recommended_resources(guest)
        assert res["n-cpus"] == 2

    def test_urldetct_matching_distros(self):
        allstores = urldetect.ALLSTORES

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
        winxp = OSDB.lookup_os("winxp")

        # Valid tree URL
        assert "fedoraproject.org" in f26.get_location("x86_64")

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

    def test_get_script(self):
        dos = OSDB.lookup_os("msdos6.22")
        winxp = OSDB.lookup_os("winxp")

        # No install scripts at all
        try:
            dos.get_install_script("desktop")
            raise AssertionError("Expected failure")
        except RuntimeError as e:
            assert "does not support unattended installation." in str(e)

        # No profile foobar
        try:
            winxp.get_install_script("foobar")
            raise AssertionError("Expected failure")
        except RuntimeError as e:
            assert "foobar" in str(e)

        script = winxp.get_install_script("desktop")
        self.assertTrue(bool(script))

    def test_prepare_install_script(self):
        from virtinst import unattended

        conn = utils.URIs.open_testdriver_cached()
        g = Guest(conn)
        g.set_os_name("fedora26")
        g.set_capabilities_defaults()
        g.name = "foo-vm"

        u = unattended.UnattendedData()
        u.profile = "desktop"
        u.admin_password = "fooadmin"
        u.user_password = "foouser"

        try:
            script = unattended.prepare_install_script(g, u)
            dummy = script
        except RuntimeError as e:
            if "libosinfo is too old" not in str(e):
                raise
            self.skipTest(str(e))
