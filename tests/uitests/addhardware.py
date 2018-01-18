import tests
from tests.uitests import utils as uiutils


class Details(uiutils.UITestCase):
    """
    UI tests for virt-manager's VM details window
    """

    ###################
    # Private helpers #
    ###################

    def _open_details_window(self, vmname="test-clone-simple"):
        self.app.root.find_fuzzy(vmname, "table cell").click(button=3)
        self.app.root.find_pattern("Open", "menu item").click()

        win = self.app.root.find_pattern("%s on" % vmname, "frame")
        win.find_pattern("Details", "radio button").click()
        return win

    def _open_addhw_window(self, details):
        details.find_pattern("add-hardware", "push button").click()
        addhw = self.app.root.find_pattern("Add New Virtual Hardware", "frame")
        return addhw

    def _select_hw(self, addhw, hwname, tabname):
        addhw.find_pattern(hwname, "table cell").click()
        tab = addhw.find_pattern(tabname, None)
        uiutils.check_in_loop(lambda: tab.showing)
        return tab


    ##############
    # Test cases #
    ##############

    def testAddGraphics(self):
        """
        Graphics device testing
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find_pattern("Finish", "push button")

        # VNC example
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.find_pattern(None, "combo box", "Type:").click_combo_entry()
        tab.find_fuzzy("VNC", "menu item").click()
        tab.find_pattern(None, "combo box", "Listen type:").click_combo_entry()
        tab.find_fuzzy("Address", "menu item").click()
        tab.find_pattern(None, "combo box", "Address:").click_combo_entry()
        tab.find_fuzzy("All interfaces", "menu item").click()
        tab.find_pattern("graphics-port-auto", "check").click()
        tab.find_pattern("graphics-port", "spin button").text = "1234"
        tab.find_pattern(None, "check", "Password:").click()
        passwd = tab.find_fuzzy("graphics-password", "text")
        newpass = "foobar"
        passwd.typeText(newpass)
        tab.find_pattern("Show password", "check").click()
        self.assertEqual(passwd.text, newpass)
        tab.find_pattern(None, "combo box", "Keymap:").click()
        self.pressKey("Down")
        self.pressKey("Down")
        self.pressKey("Down")
        finish.click()

        # Catch a port error
        alert = self.app.root.find_pattern("vmm dialog", "alert")
        alert.find_fuzzy("Port must be above 5900", "label")
        alert.find_pattern("OK", "push button").click()
        tab.find_pattern("graphics-port", "spin button").text = "5920"
        uiutils.check_in_loop(lambda: details.active)

        # Spice regular example
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.find_pattern(None, "combo box", "Type:").click_combo_entry()
        tab.find_fuzzy("Spice", "menu item").click()
        tab.find_pattern("graphics-tlsport-auto", "check").click()
        tab.find_pattern("graphics-tlsport", "spin button").text = "5999"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Spice GL example
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.find_pattern(None, "combo box", "Type:").click_combo_entry()
        tab.find_fuzzy("Spice", "menu item").click()
        tab.find_pattern(None, "combo box", "Listen type:").click_combo_entry()
        tab.find_fuzzy("None", "menu item").click()
        tab.find_pattern(None, "check box", "OpenGL:").click()
        render = tab.find_pattern("graphics-rendernode", "combo box")
        m = tab.find_fuzzy("Intel Corp", "menu item")
        render.click_combo_entry()
        self.assertTrue(m.selected)
        self.pressKey("Escape")
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

    def testAddHosts(self):
        """
        Add a few different USB and PCI devices
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find_pattern("Finish", "push button")

        # Add USB device dup1
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("HP Dup USB 1", "table cell").click()
        finish.click()
        alert = self.app.root.find_pattern("vmm dialog", "alert")
        alert.find_fuzzy("device is already in use by", "label")
        alert.find_pattern("Yes", "push button").click()
        uiutils.check_in_loop(lambda: details.active)

        # Add USB device dup2
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("HP Dup USB 2", "table cell").click()
        finish.click()
        alert = self.app.root.find_pattern("vmm dialog", "alert")
        alert.find_fuzzy("device is already in use by", "label")
        alert.find_pattern("Yes", "push button").click()
        uiutils.check_in_loop(lambda: details.active)

        # Add another USB device
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("Cruzer Micro 256", "table cell").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add PCI device
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "PCI Host Device", "host-tab")
        tab.find_fuzzy("(Interface eth0)", "table cell").click()
        finish.click()
        alert = self.app.root.find_pattern("vmm dialog", "alert")
        alert.find_fuzzy("device is already in use by", "label")
        alert.find_pattern("Yes", "push button").click()
        uiutils.check_in_loop(lambda: details.active)


    def testAddChars(self):
        """
        Add a bunch of char devices
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find_pattern("Finish", "push button")

        # Add console device
        tab = self._select_hw(addhw, "Console", "char-tab")
        tab.find(None, "combo box", "Device Type:").click()
        tab.find_fuzzy("Pseudo TTY", "menu item").click()
        tab.find(None, "combo box", "Type:").click()
        tab.find_fuzzy("Hypervisor default", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add serial+file
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Serial", "char-tab")
        tab.find_pattern(None, "combo box", "Device Type:").click()
        tab.find_fuzzy("Output to a file", "menu item").click()
        tab.find_pattern(None, "text", "Path:").text = "/tmp/foo.log"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add udp serial
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Serial", "char-tab")
        tab.find_pattern(None, "combo box", "Device Type:").click()
        tab.find_fuzzy("UDP", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add parallel+device
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Parallel", "char-tab")
        tab.find_pattern(None, "combo box", "Device Type:").click()
        tab.find_fuzzy("Physical host character", "menu item").click()
        tab.find_pattern(None, "text", "Path:").text = "/dev/parallel0"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add spicevmc channel
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Channel", "char-tab")
        # Ensures that this is selected by default
        tab.find_pattern("com.redhat.spice.0", "combo box")
        finish.click()
        uiutils.check_in_loop(lambda: details.active)


    def testAddLXCFilesystem(self):
        """
        Adding LXC specific filesystems
        """
        self.app.uri = tests.utils.uri_lxc

        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find_pattern("Finish", "push button")

        # Add File+nbd share
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find_pattern(None, "combo box", "Type:").click()
        tab.find_pattern("File", "menu item").click()
        tab.find_pattern(None, "combo box", "Driver:").click()
        tab.find_pattern("Nbd", "menu item").click()
        tab.find_pattern(None, "combo box", "Format:").click()
        tab.find_pattern("qcow2", "menu item").click()
        tab.find_pattern("Browse...", "push button").click()

        browsewin = self.app.root.find_pattern(
                "Choose Storage Volume", "frame")
        browsewin.find_pattern("Cancel", "push button").click()
        uiutils.check_in_loop(lambda: addhw.active)

        tab.find_fuzzy(None, "text", "Source path:").text = "/foo/source"
        tab.find_fuzzy(None, "text", "Target path:").text = "/foo/target"
        tab.find_fuzzy("Export filesystem", "check").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add RAM type
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find_pattern(None, "combo box", "Type:").click()
        tab.find_pattern("Ram", "menu item").click()
        tab.find_pattern(None, "spin button", "Usage:").text = "12345"
        tab.find_fuzzy(None, "text", "Target path:").text = "/mem"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)


    def testAddHWMisc(self):
        """
        Add one each of simple devices
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find_pattern("Finish", "push button")

        # Add input
        tab = self._select_hw(addhw, "Input", "input-tab")
        tab.find_pattern(None, "combo box", "Type:").click()
        tab.find_pattern("EvTouch", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add sound
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Sound", "sound-tab")
        tab.find_pattern(None, "combo box", "Model:").click()
        tab.find_pattern("ich6", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add video
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Video", "video-tab")
        tab.find_pattern(None, "combo box", "Model:").click()
        tab.find_pattern("QXL", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add watchdog
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Watchdog", "watchdog-tab")
        tab.find_pattern(None, "combo box", "Model:").click()
        tab.find_pattern("i6300esb", "menu item").click()
        tab.find_pattern(None, "combo box", "Action:").click()
        tab.find_pattern("Pause the guest", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add smartcard
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Smartcard", "smartcard-tab")
        tab.find_pattern(None, "combo box", "Mode:").click()
        tab.find_pattern("Passthrough", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add basic filesystem
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find_fuzzy(None, "text", "Source path:").text = "/foo/source"
        tab.find_fuzzy(None, "text", "Target path:").text = "/foo/target"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add TPM
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "TPM", "tpm-tab")
        tab.find_pattern(None, "text", "Device Path:").text = "/tmp/foo"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add RNG
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "RNG", "rng-tab")
        tab.find_pattern(None, "text", "Device:").text = "/dev/random"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add Panic
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Panic", "panic-tab")
        tab.find_pattern(None, "combo box", "Model:").click()
        tab.find_pattern("Hyper-V", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)
