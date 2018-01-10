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
        uiutils.find_pattern(self.app.root, "Edit", "menu").click()
        uiutils.find_pattern(self.app.root, "Preferences", "menu item").click()

        win = uiutils.find_fuzzy(self.app.root, "Preferences", "frame")

        uiutils.find_fuzzy(win, "Enable system tray", "check").click()

        uiutils.find_pattern(win, "Polling", "page tab").click()
        uiutils.find_fuzzy(win, None, "check box",
                           labeller_text="Poll CPU").click()

        uiutils.find_pattern(win, "New VM", "page tab").click()
        uiutils.find_pattern(win, "prefs-add-spice-usbredir",
                             "combo box").click()
        uiutils.find_pattern(win, "No", "menu item").click()

        uiutils.find_pattern(win, "Console", "page tab").click()
        uiutils.find_pattern(win, "Change...", "push button").click()
        keyframe = uiutils.find_fuzzy(self.app.root,
                                      "Configure grab", "dialog")
        _holdKey("Alt_L")
        _holdKey("Z")
        try:
            uiutils.find_fuzzy(keyframe, "OK", "push button").click()
        finally:
            _releaseKey("Z")
            _releaseKey("Alt_L")

        uiutils.find_pattern(win, "Feedback", "page tab").click()
        uiutils.find_fuzzy(win, None, "check box",
                           labeller_text="Force Poweroff").click()

        uiutils.find_pattern(win, "General", "page tab").click()
        uiutils.find_fuzzy(win, "Enable system tray", "check").click()

        uiutils.find_fuzzy(win, "Close", "push button").click()
        uiutils.check_in_loop(lambda: win.visible is False)
