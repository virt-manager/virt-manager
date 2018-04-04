# Copyright (C) 2017 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import unittest

from virtinst import hostkeymap


class TestHostkeymap(unittest.TestCase):
    """
    Tests for hostkeymap.py file parsing
    """
    # pylint: disable=protected-access

    def testFiles(self):
        def _open(filename):
            return open(os.path.join(os.getcwd(),
                "tests/hostkeymap", filename))

        self.assertEqual(
                hostkeymap._sysconfig_keyboard(
                    _open("sysconfig-comments.txt")),
                "")
        self.assertEqual(
                hostkeymap._sysconfig_keyboard(
                    _open("sysconfig-rhel5.txt")),
                "us")
        self.assertEqual(
                hostkeymap._find_xkblayout(
                    _open("default-keyboard-debian9.txt")),
                "us")
        self.assertEqual(
                hostkeymap._find_xkblayout(
                    _open("console-setup-debian9.txt")),
                None)
        self.assertEqual(
                hostkeymap._xorg_keymap(
                    _open("xorg-rhel5.txt")),
                "us")
