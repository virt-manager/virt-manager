import datetime

from tests.uitests import utils as uiutils


class VMMAbout(uiutils.UITestCase):
    """
    UI tests for the 'About' dialog
    """

    ##############
    # Test cases #
    ##############

    def testAbout(self):
        uiutils.find_pattern(self.app.root, "Help", "menu").click()
        uiutils.find_pattern(self.app.root, "About", "menu item").click()
        win = uiutils.find_fuzzy(self.app.root, "About", "dialog")
        l = uiutils.find_fuzzy(win, "Copyright", "label")

        curyear = datetime.datetime.today().strftime("%Y")
        if curyear not in l.text:
            print("Current year=%s not in about.ui dialog!" % curyear)

        win.keyCombo("<ESC>")
        uiutils.check_in_loop(lambda: win.visible is False)
