import dogtail
import pyatspi

from tests.uitests import utils as uiutils


# From dogtail 9.9.0 which isn't widely distributed yet
def _holdKey(keyName):
    code = dogtail.rawinput.keyNameToKeyCode(keyName)
    pyatspi.Registry().generateKeyboardEvent(code, None, pyatspi.KEY_PRESS)


def _releaseKey(keyName):
    code = dogtail.rawinput.keyNameToKeyCode(keyName)
    pyatspi.Registry().generateKeyboardEvent(code, None, pyatspi.KEY_RELEASE)


class VMMPrefs(uiutils.UITestCase):
    """
    UI tests for the preferences dialog
    """

    ##############
    # Test cases #
    ##############

    def testPrefs(self):
        self.app.root.find("Edit", "menu").click()
        self.app.root.find("Preferences", "menu item").click()

        win = self.app.root.find_fuzzy("Preferences", "frame")

        win.find_fuzzy("Enable system tray", "check").click()

        win.find("Polling", "page tab").click()
        win.find_fuzzy(None, "check box",
                           labeller_text="Poll CPU").click()

        win.find("New VM", "page tab").click()
        win.find("prefs-add-spice-usbredir",
                             "combo box").click()
        win.find("No", "menu item").click()

        win.find("Console", "page tab").click()
        win.find("Change...", "push button").click()
        keyframe = self.app.root.find_fuzzy("Configure grab", "dialog")
        _holdKey("Alt_L")
        _holdKey("Z")
        try:
            keyframe.find_fuzzy("OK", "push button").click()
        finally:
            _releaseKey("Z")
            _releaseKey("Alt_L")

        win.find("Feedback", "page tab").click()
        win.find_fuzzy(None, "check box",
                           labeller_text="Force Poweroff").click()

        win.find("General", "page tab").click()
        win.find_fuzzy("Enable system tray", "check").click()

        win.find_fuzzy("Close", "push button").click()
        uiutils.check_in_loop(lambda: win.visible is False)
