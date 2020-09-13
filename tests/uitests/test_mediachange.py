# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


class MediaChange(lib.testcase.UITestCase):
    """
    UI tests for details storage media change
    """

    ##############
    # Test cases #
    ##############

    def testMediaChange(self):
        win = self.app.open_details_window("test-many-devices", shutdown=True)
        hw = win.find("hw-list")
        tab = win.find("disk-tab")
        combo = win.find("media-combo")
        entry = win.find("media-entry")
        appl = win.find("config-apply")

        # Floppy + physical
        hw.find("Floppy 1", "table cell").click()
        combo.click_combo_entry()
        combo.find(r"Floppy_install_label \(/dev/fdb\)")
        lib.utils.check(lambda: entry.text == "No media detected (/dev/fda)")
        entry.click()
        entry.click_secondary_icon()
        lib.utils.check(lambda: not entry.text)
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        lib.utils.check(lambda: not entry.text)

        # Enter /dev/fdb, after apply it should change to pretty label
        entry.set_text("/dev/fdb")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        lib.utils.check(lambda:
            entry.text == "Floppy_install_label (/dev/fdb)")

        # Specify manual path
        path = "/tmp/aaaaaaaaaaaaaaaaaaaaaaa.img"
        entry.set_text(path)
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        lib.utils.check(lambda: entry.text == path)

        # Go to Floppy 2, make sure previous path is in recent list
        hw.find("Floppy 2", "table cell").click()
        combo.click_combo_entry()
        combo.find(path)
        entry.click()
        # Use the storage browser to select new floppy storage
        tab.find("Browse", "push button").click()
        self.app.select_storagebrowser_volume("default-pool", "iso-vol")
        appl.click()

        # Browse for image
        hw.find("IDE CDROM 1", "table cell").click()
        combo.click_combo_entry()
        combo.find(r"Fedora12_media \(/dev/sr0\)")
        entry.click()
        tab.find("Browse", "push button").click()
        self.app.select_storagebrowser_volume("default-pool", "backingl1.img")
        # Check 'already in use' dialog
        appl.click()
        self.app.click_alert_button("already in use by", "No")
        lib.utils.check(lambda: appl.sensitive)
        appl.click()
        self.app.click_alert_button("already in use by", "Yes")
        lib.utils.check(lambda: not appl.sensitive)
        lib.utils.check(lambda: "backing" in entry.text)
        entry.set_text("")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        lib.utils.check(lambda: not entry.text)


    def testMediaHotplug(self):
        """
        Test in the case of a running VM
        """
        win = self.app.open_details_window("test-many-devices")
        hw = win.find("hw-list")
        entry = win.find("media-entry")
        appl = win.find("config-apply")

        # CDROM + physical
        hw.find("IDE CDROM 1", "table cell").click()
        lib.utils.check(lambda: not entry.text)
        entry.set_text("/dev/sr0")
        appl.click()
        self.app.click_alert_button("changes will take effect", "OK")
        lib.utils.check(lambda: not appl.sensitive)
        lib.utils.check(lambda: not entry.text)

        # Shutdown the VM, verify change shows up
        win.find("Shut Down", "push button").click()
        run = win.find("Run", "push button")
        lib.utils.check(lambda: run.sensitive)
        lib.utils.check(lambda: entry.text == "Fedora12_media (/dev/sr0)")
