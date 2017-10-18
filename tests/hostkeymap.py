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
    def testFiles(self):
        def _open(filename):
            return file(os.path.join(os.getcwd(),
                "tests/hostkeymap", filename))

        self.assertEquals(
                hostkeymap._sysconfig_keyboard(_open("sysconfig-comments.txt")),
                "de-latin1-nodeadkeys")

