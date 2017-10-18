# Copyright (C) 2017 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

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
            return file(os.path.join(os.getcwd(),
                "tests/hostkeymap", filename))

        self.assertEquals(
                hostkeymap._sysconfig_keyboard(
                    _open("sysconfig-comments.txt")),
                "")
        self.assertEquals(
                hostkeymap._sysconfig_keyboard(
                    _open("sysconfig-rhel5.txt")),
                "us")
        self.assertEquals(
                hostkeymap._find_xkblayout(
                    _open("default-keyboard-debian9.txt")),
                "us")
        self.assertEquals(
                hostkeymap._find_xkblayout(
                    _open("console-setup-debian9.txt")),
                None)
        self.assertEquals(
                hostkeymap._xorg_keymap(
                    _open("xorg-rhel5.txt")),
                "us")
