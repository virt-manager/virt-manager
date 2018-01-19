from tests.uitests import utils as uiutils


class ChooseCD(uiutils.UITestCase):
    """
    UI tests for the choosecd dialog
    """

    ###################
    # Private helpers #
    ###################

    ##############
    # Test cases #
    ##############

    def testChooseCD(self):
        win = self._open_details_window(shutdown=True)
        hw = win.find("hw-list")
        tab = win.find("disk-tab")

        # Floppy + physical
        hw.find("Floppy 1", "table cell").click()
        tab.find("Disconnect", "push button").click()
        tab.find("Connect", "push button").click()
        cm = self.app.root.find("Choose Media", "dialog")
        cm.find("OK", "push button").click()
        self.assertTrue("/dev/fdb" in tab.find("disk-source-path").text)

        # Floppy + image
        hw.find("Floppy 2", "table cell").click()
        tab.find("Disconnect", "push button").click()
        tab.find("Connect", "push button").click()
        cm = self.app.root.find("Choose Media", "dialog")
        cm.find("Image Location", "radio button").click()
        cm.find("Location:", "text").text = "/dev/default-pool/bochs-vol"
        cm.find("OK", "push button").click()
        self.assertTrue("bochs-vol" in tab.find("disk-source-path").text)

        # CDROM + physical
        hw.find("IDE CDROM 1", "table cell").click()
        tab.find("Connect", "push button").click()
        cm = self.app.root.find("Choose Media", "dialog")
        cm.find("Physical Device", "radio button").click()
        cm.find("physical-device-combo").click()
        cm.find_fuzzy("/dev/sr1", "menu item").click()
        cm.find("OK", "push button").click()
        self.assertTrue("/dev/sr1" in tab.find("disk-source-path").text)

        # CDROM + image
        hw.find("SCSI CDROM 1", "table cell").click()
        tab.find("Connect", "push button").click()
        cm = self.app.root.find("Choose Media", "dialog")
        cm.find("Image Location", "radio button").click()
        cm.find("Browse...", "push button").click()
        browsewin = self.app.root.find(
                "Choose Storage Volume", "frame")
        browsewin.find_fuzzy("default-pool", "table cell").click()
        browsewin.find_fuzzy("backingl1.img", "table cell").click()
        browsewin.find("Choose Volume", "push button").click()
        cm.find("OK", "push button").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("already in use by", "label")
        alert.find("Yes", "push button").click()
        self.assertTrue(lambda: not cm.showing)
        self.assertTrue("backing" in tab.find("disk-source-path").text)
        tab.find("Disconnect", "push button").click()
        self.assertTrue("-" in tab.find("disk-source-path").text)

    def testChooseCDHotplug(self):
        """
        Test in the case of a running VM
        """
        win = self._open_details_window()
        hw = win.find("hw-list")
        tab = win.find("disk-tab")

        # CDROM + physical
        hw.find("IDE CDROM 1", "table cell").click()
        tab.find("Connect", "push button").click()
        cm = self.app.root.find("Choose Media", "dialog")
        cm.find("OK", "push button").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("changes will take effect", "label")
        alert.find("OK", "push button").click()
        self.assertTrue("-" in tab.find("disk-source-path").text)

        # Shutdown the VM, verify change shows up
        win.find("Shut Down", "push button").click()
        run = win.find("Run", "push button")
        uiutils.check_in_loop(lambda: run.sensitive)
        self.assertTrue("/dev/sr0" in tab.find("disk-source-path").text)
