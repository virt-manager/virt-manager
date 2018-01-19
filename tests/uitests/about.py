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
        self.app.root.find("Help", "menu").click()
        self.app.root.find("About", "menu item").click()
        win = self.app.root.find_fuzzy("About", "dialog")
        l = win.find_fuzzy("Copyright", "label")

        curyear = datetime.datetime.today().strftime("%Y")
        if curyear not in l.text:
            print("Current year=%s not in about.ui dialog!" % curyear)

        win.keyCombo("<ESC>")
        uiutils.check_in_loop(lambda: win.visible is False)
