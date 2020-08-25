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

    def testPrefsAll(self):
        self.app.root.find("Edit", "menu").click()
        self.app.root.find("Preferences", "menu item").click()

        win = self.app.root.find_fuzzy("Preferences", "frame")
        generaltab = win.find("general-tab")
        pollingtab = win.find("polling-tab")
        newvmtab = win.find("newvm-tab")
        consoletab = win.find("console-tab")
        feedbacktab = win.find("feedback-tab")

        uiutils.check(lambda: not feedbacktab.onscreen)
        tab = generaltab
        uiutils.check(lambda: tab.onscreen)
        tab.find_fuzzy("Enable system tray", "check").click()
        tab.find_fuzzy("Enable XML").click()
        tab.find_fuzzy("libguestfs VM").click()

        win.find("Polling", "page tab").click()
        tab = pollingtab
        uiutils.check(lambda: tab.onscreen)
        tab.find_fuzzy(None, "check box", "Poll CPU").click()
        tab.find_fuzzy(None, "check box", "Poll Disk").click()
        tab.find_fuzzy(None, "check box", "Poll Memory").click()
        tab.find_fuzzy(None, "check box", "Poll Network").click()
        period = tab.find_fuzzy("cpu-poll", "spin button")
        period.click()
        period.text = "5"

        win.find("New VM", "page tab").click()
        tab = newvmtab
        newvmtab.print_nodes()
        uiutils.check(lambda: tab.onscreen)
        tab.find_fuzzy(None, "check box", "sound device").click()
        tab.find(None, "combo box", "CPU default:").click()
        tab.find_fuzzy("Copy host", "menu item").click()
        tab.find(None, "combo box", "Storage format:").click()
        tab.find("Raw", "menu item").click()
        tab.find("prefs-add-spice-usbredir", "combo box").click()
        tab.find("No", "menu item").click()
        tab.find_fuzzy("Graphics type", "combo box").click()
        tab.find("VNC", "menu item").click()

        win.find("Console", "page tab").click()
        tab = consoletab
        uiutils.check(lambda: tab.onscreen)
        tab.find(None, "combo box", "SPICE USB").click()
        tab.find_fuzzy("Manual redirect", "menu item").click()
        tab.find_fuzzy(None, "combo box", "Resize guest").click()
        tab.find("On", "menu item").click()
        tab.find_fuzzy(None, "combo box", "console scaling").click()
        tab.find_fuzzy("Always", "menu item").click()
        tab.find_fuzzy(None, "check box", "Force console").click()

        tab.find("Change...", "push button").click()
        keyframe = self.app.root.find_fuzzy("Configure grab", "dialog")

        # On certain environments pressing "Alt_L" and
        # clicking a window starts window drag operation.
        # Work around by pushing both Control and Alt.
        self.holdKey("Control_L")
        self.holdKey("Alt_L")
        self.holdKey("Z")

        # Test releasekey handler
        self.releaseKey("Z")
        self.holdKey("Z")
        try:
            keyframe.find_fuzzy("OK", "push button").click()
        finally:
            self.releaseKey("Z")
            self.releaseKey("Alt_L")
            self.releaseKey("Control_L")

        win.find("Feedback", "page tab").click()
        tab = feedbacktab
        uiutils.check(lambda: tab.onscreen)
        tab.find_fuzzy(None, "check box", "Force Poweroff").click()
        tab.find_fuzzy(None, "check box", "Poweroff/Reboot").click()
        tab.find_fuzzy(None, "check box", "Pause").click()
        tab.find_fuzzy(None, "check box", "Device removal").click()
        tab.find_fuzzy(None, "check box", "Unapplied changes").click()
        tab.find_fuzzy(None, "check box", "Deleting storage").click()

        win.find("General", "page tab").click()
        win.find_fuzzy("Enable system tray", "check").click()

        win.find_fuzzy("Close", "push button").click()
        uiutils.check(lambda: win.visible is False)


    def testPrefsXMLEditor(self):
        managerwin = self.app.topwin
        uiutils.drag(managerwin, 0, 200)
        detailswin = self._open_details_window(vmname="test-clone-simple")
        finish = detailswin.find("config-apply")
        xmleditor = detailswin.find("XML editor")

        detailswin.find("XML", "page tab").click()
        uiutils.drag(detailswin, 400, 400)
        warnlabel = detailswin.find_fuzzy("XML editing is disabled")
        uiutils.check(lambda: warnlabel.visible)
        origtext = xmleditor.text
        xmleditor.typeText("1234abcd")
        uiutils.check(lambda: xmleditor.text == origtext)

        managerwin.grabFocus()
        managerwin.click()
        managerwin.find("Edit", "menu").click()
        managerwin.find("Preferences", "menu item").click()
        prefswin = self.app.root.find_fuzzy("Preferences", "frame")
        prefswin.find_fuzzy("Enable XML").click()
        prefswin.find_fuzzy("Close", "push button").click()
        uiutils.check(lambda: prefswin.visible is False)

        managerwin.keyCombo("<alt>F4")
        detailswin.click()
        xmleditor.text = xmleditor.text.replace(">",
            "><title>FOOTITLE</title>", 1)
        finish.click()
        detailswin.find("Details", "page tab").click()
        uiutils.check(lambda:
                detailswin.find("Title:", "text").text == "FOOTITLE")

    def testPrefsKeyfile(self):
        """
        Preload some keyfile settings and verify they work as expected
        """
        self.app.open(use_uri=False, keyfile="defaultconn.ini")
        managerwin = self.app.topwin

        # test:///default should be connected
        managerwin.find("test default", "table cell")
        managerwin.find("foo - Not Connected", "table cell")
