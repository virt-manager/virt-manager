# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests.uitests import utils as uiutils


class MediaChange(uiutils.UITestCase):
    """
    UI tests for details storage media change
    """

    ##############
    # Test cases #
    ##############

    def testMediaChange(self):
        win = self._open_details_window(shutdown=True)
        hw = win.find("hw-list")
        tab = win.find("disk-tab")
        combo = win.find("media-combo")
        entry = win.find("media-entry")
        appl = win.find("config-apply")

        # Floppy + physical
        hw.find("Floppy 1", "table cell").click()
        combo.click_combo_entry()
        combo.find(r"Floppy_install_label \(/dev/fdb\)")
        self.assertTrue(entry.text == "No media detected (/dev/fda)")
        entry.click()
        entry.click_secondary_icon()
        self.assertTrue(not entry.text)
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        self.assertTrue(not entry.text)
        appl.click()

        # Enter /dev/fdb, after apply it should change to pretty label
        entry.text = "/dev/fdb"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        self.assertTrue(entry.text == "Floppy_install_label (/dev/fdb)")

        # Specify manual path
        path = "/tmp/aaaaaaaaaaaaaaaaaaaaaaa.img"
        entry.text = path
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        self.assertTrue(entry.text == path)

        # Go to Floppy 2, make sure previous path is in recent list
        hw.find("Floppy 2", "table cell").click()
        combo.click_combo_entry()
        combo.find(path)
        entry.click()

        # Browse for image
        hw.find("IDE CDROM 1", "table cell").click()
        combo.click_combo_entry()
        combo.find(r"Fedora12_media \(/dev/sr0\)")
        entry.click()
        tab.find("Browse", "push button").click()
        browsewin = self.app.root.find(
                "Choose Storage Volume", "frame")
        browsewin.find_fuzzy("default-pool", "table cell").click()
        browsewin.find_fuzzy("backingl1.img", "table cell").click()
        browsewin.find("Choose Volume", "push button").click()
        appl.click()
        # Check 'already in use' dialog
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("already in use by", "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        self.assertTrue("backing" in entry.text)
        entry.text = ""
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        self.assertTrue(not entry.text)


    def testMediaHotplug(self):
        """
        Test in the case of a running VM
        """
        win = self._open_details_window()
        hw = win.find("hw-list")
        entry = win.find("media-entry")
        appl = win.find("config-apply")

        # CDROM + physical
        hw.find("IDE CDROM 1", "table cell").click()
        self.assertTrue(not entry.text)
        entry.text = "/dev/sr0"
        appl.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("changes will take effect", "label")
        alert.find("OK", "push button").click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        self.assertTrue(not entry.text)

        # Shutdown the VM, verify change shows up
        win.find("Shut Down", "push button").click()
        run = win.find("Run", "push button")
        uiutils.check_in_loop(lambda: run.sensitive)
        self.assertTrue(entry.text == "Fedora12_media (/dev/sr0)")
