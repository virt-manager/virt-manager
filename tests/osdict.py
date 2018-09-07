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

        guest.type = "qemu"
        res = OSDB.lookup_os("fedora21").get_recommended_resources(guest)
        assert res["n-cpus"] == 1

    def test_urldetct_matching_distros(self):
        allstores = urldetect._allstores  # pylint: disable=protected-access

        seen_distro = []
        for store in allstores:
            for distro in store.matching_distros:
                if distro in seen_distro:
                    raise RuntimeError("programming error: "
                            "store=%s has conflicting matching_distro=%s " %
                            (store.PRETTY_NAME, distro))
                seen_distro.append(distro)
