# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests.uitests import utils as uiutils


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

        # On certain environments pressing "Alt_L" and clicking a window starts
        # window drag operation. Work around by pushing both Control and Alt.
        self.holdKey("Control_L")
        self.holdKey("Alt_L")
        self.holdKey("Z")
        try:
            keyframe.find_fuzzy("OK", "push button").click()
        finally:
            self.releaseKey("Z")
            self.releaseKey("Alt_L")
            self.releaseKey("Control_L")

        win.find("Feedback", "page tab").click()
        win.find_fuzzy(None, "check box",
                           labeller_text="Force Poweroff").click()

        win.find("General", "page tab").click()
        win.find_fuzzy("Enable system tray", "check").click()

        win.find_fuzzy("Close", "push button").click()
        uiutils.check_in_loop(lambda: win.visible is False)


    def testPrefsXMLEditor(self):
        managerwin = self.app.topwin
        uiutils.drag(managerwin, 0, 200)
        detailswin = self._open_details_window(vmname="test-clone-simple")
        finish = detailswin.find("config-apply")
        xmleditor = detailswin.find("XML editor")

        detailswin.find("XML", "page tab").click()
        uiutils.drag(detailswin, 400, 400)
        warnlabel = detailswin.find_fuzzy("XML editing is disabled")
        self.assertTrue(warnlabel.visible)
        origtext = xmleditor.text
        xmleditor.typeText("1234abcd")
        self.assertEqual(xmleditor.text, origtext)

        managerwin.grabFocus()
        managerwin.click()
        managerwin.find("Edit", "menu").click()
        managerwin.find("Preferences", "menu item").click()
        prefswin = self.app.root.find_fuzzy("Preferences", "frame")
        prefswin.find_fuzzy("Enable XML").click()
        prefswin.find_fuzzy("Close", "push button").click()
        uiutils.check_in_loop(lambda: prefswin.visible is False)

        managerwin.keyCombo("<alt>F4")
        detailswin.click()
        xmleditor.text = xmleditor.text.replace(">",
            "><title>FOOTITLE</title>", 1)
        finish.click()
        detailswin.find("Details", "page tab").click()
        uiutils.check_in_loop(lambda:
                detailswin.find("Title:", "text").text == "FOOTITLE")
