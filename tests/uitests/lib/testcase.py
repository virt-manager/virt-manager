# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest

from .app import VMMDogtailApp


class UITestCase(unittest.TestCase):
    """
    Common testcase bits shared for ui tests
    """
    def setUp(self):
        self.app = VMMDogtailApp()
    def tearDown(self):
        self.app.stop()
