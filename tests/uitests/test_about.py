# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import datetime

from . import lib


class VMMAbout(lib.testcase.UITestCase):
    """
    UI tests for the 'About' dialog
    """

    ##############
    # Test cases #
    ##############

    def testAbout(self):
        self.app.root.find("Help", "menu").click()
        self.app.root.find("About", "menu item").click()
        win = self.app.root.find_fuzzy("About", "dialog")
        l = win.find_fuzzy("Copyright", "label")

        curyear = datetime.datetime.today().strftime("%Y")
        if curyear not in l.text:
            print("Current year=%s not in about.ui dialog!" % curyear)

        win.keyCombo("<ESC>")
        lib.utils.check(lambda: win.visible is False)
