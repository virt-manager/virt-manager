import tests
from tests.uitests import utils as uiutils


class AddHardware(uiutils.UITestCase):
    """
    UI tests for virt-manager's VM addhardware window
    """

    ###################
    # Private helpers #
    ###################

    _default_vmname = "test-clone-simple"

    def _open_addhw_window(self, details):
        details.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        return addhw

    def _select_hw(self, addhw, hwname, tabname):
        addhw.find(hwname, "table cell").click()
        tab = addhw.find(tabname, None)
        uiutils.check_in_loop(lambda: tab.showing)
        return tab


    ##############
    # Test cases #
    ##############

    def testAddControllers(self):
        """
        Add various controller configs
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Default SCSI
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        typ = tab.find("Type:", "combo box")
        typ.click()
        tab.find("SCSI", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Virtio SCSI
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        typ.click()
        tab.find("SCSI", "menu item").click()
        tab.find("Model:", "combo box").click_combo_entry()
        tab.find("VirtIO SCSI", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # USB 2
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        typ.click()
        tab.find("USB", "menu item").click()
        tab.find("Model:", "combo box").click_combo_entry()
        tab.find("USB 2", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # USB 3
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        typ.click()
        tab.find("USB", "menu item").click()
        tab.find("Model:", "combo box").click_combo_entry()
        tab.find("USB 3", "menu item").click()
        # Can't add more than 1 USB controller, so finish isn't sensitive
        self.assertFalse(finish.sensitive)

    def testAddDisks(self):
        """
        Add various disk configs and test storage browser
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Default disk
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Disk with some tweaks
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find("GiB", "spin button").text = "1.5"
        tab.find("Bus type:", "combo box").click()
        tab.find("VirtIO", "menu item").click()
        tab.find("Advanced options", "toggle button").click_expander()
        tab.find("Cache mode:", "combo box").click()
        tab.find("none", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Managed storage tests
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        tab.find("storage-browse", "push button").click()
        browse = self.app.root.find("Choose Storage Volume", "frame")

        # Create a vol, refresh, then delete it
        browse.find_fuzzy("default-pool", "table cell").click()
        browse.find("vol-new", "push button").click()
        newvol = self.app.root.find("Add a Storage Volume", "frame")
        newname = "a-newvol"
        newvol.find("Name:", "text").text = newname
        newvol.find("Finish", "push button").click()
        uiutils.check_in_loop(lambda: not newvol.showing)
        volcell = browse.find(newname, "table cell")
        self.assertTrue(volcell.selected)
        browse.find("vol-refresh", "push button").click()
        volcell = browse.find(newname, "table cell")
        self.assertTrue(volcell.selected)
        browse.find("vol-delete", "push button").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("permanently delete the volume", "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: volcell.dead)

        # Test browse local
        browse.find("Browse Local", "push button").click()
        chooser = self.app.root.find(
                "Locate existing storage", "file chooser")
        fname = "virt-manager.spec.in"
        chooser.find(fname, "table cell").click()
        chooser.find("Open", "push button").click()
        uiutils.check_in_loop(lambda: not chooser.showing)
        uiutils.check_in_loop(lambda: addhw.active)
        self.assertTrue(("/" + fname) in tab.find("storage-entry").text)

        # Reopen dialog, select a volume, etic
        tab.find("storage-browse", "push button").click()
        browse = self.app.root.find("Choose Storage Volume", "frame")

        browse.find_fuzzy("disk-pool", "table cell").click()
        browse.find("diskvol1", "table cell").click()
        browse.find("Choose Volume", "push button").click()
        self.assertTrue("/diskvol1" in tab.find("storage-entry").text)
        finish.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("already in use by", "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: details.active)


        # choose file for floppy
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find("Device type:", "combo box").click()
        tab.find("Floppy device", "menu item").click()
        self.assertFalse(
                tab.find_fuzzy("Create a disk image", "radio").sensitive)
        tab.find("storage-entry").text = "/dev/default-pool/bochs-vol"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # empty cdrom
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find("Device type:", "combo box").click()
        tab.find("CDROM device", "menu item").click()
        tab.find("Bus type:", "combo box").click()
        tab.find("SCSI", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)


    def testAddNetworks(self):
        """
        Test various network configs
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Basic network + opts
        tab = self._select_hw(addhw, "Network", "network-tab")
        src = tab.find(None, "combo box", "Network source:")
        src.click()
        tab.find_fuzzy("Virtual network 'default' : NAT", "menu item").click()
        tab.find("MAC Address Field", "text").text = "00:11:00:11:00:11"
        tab.find("Device model:", "combo box").click_combo_entry()
        tab.find("virtio", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # macvtap
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Network", "network-tab")
        src.click()
        tab.find_fuzzy("macvtap", "menu item").click()
        mode = tab.find_fuzzy("Source mode:", "combo box")
        mode.click_combo_entry()
        self.assertTrue(mode.find("Bridge", "menu item").selected)
        self.pressKey("Escape")
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Manual bridge
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Network", "network-tab")
        tab.find("mac-address-enable", "check box").click()
        src.click()
        self.pressKey("End")
        tab.find_fuzzy("Specify shared device", "menu item").click()
        finish.click()

        # Check validation error
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Error adding device", "label")
        alert.find("Close", "push button").click()

        # Enter bridge name
        tab.find("Bridge name:", "text").text = "zbr0"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Network with portops
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Network", "network-tab")
        tab.find("mac-address-enable", "check box").click()
        src.click()
        self.pressKey("Home")
        tab.find_fuzzy("plainbridge-portgroups", "menu item").click()
        c = tab.find_fuzzy("Portgroup:", "combo box")
        c.click_combo_entry()
        self.assertTrue(c.find("engineering", "menu item").selected)
        self.pressKey("Escape")
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Network with vport stuff
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Network", "network-tab")
        tab.find("mac-address-enable", "check box").click()
        src.click()
        tab.find_fuzzy("OpenVSwitch", "menu item").click()
        t = tab.find("Virtual port", "toggle button")
        t.click()
        t.find("Type:", "text").text = "802.1Qbg"
        t.find("Managerid:", "text").text = "12"
        t.find("Typeid:", "text").text = "1193046"
        t.find("Typeid version:", "text").text = "1"
        t.find("Instance id:", "text").text = (
                "09b11c53-8b5c-4eeb-8f00-d84eaa0aaa3b")
        finish.click()
        uiutils.check_in_loop(lambda: details.active)


    def testAddGraphics(self):
        """
        Graphics device testing
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # VNC example
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.find("Type:", "combo box").click_combo_entry()
        tab.find_fuzzy("VNC", "menu item").click()
        tab.find("Listen type:", "combo box").click_combo_entry()
        tab.find_fuzzy("Address", "menu item").click()
        tab.find("Address:", "combo box").click_combo_entry()
        tab.find_fuzzy("All interfaces", "menu item").click()
        tab.find("graphics-port-auto", "check").click()
        tab.find("graphics-port", "spin button").text = "1234"
        tab.find("Password:", "check").click()
        passwd = tab.find_fuzzy("graphics-password", "text")
        newpass = "foobar"
        passwd.typeText(newpass)
        tab.find("Show password", "check").click()
        self.assertEqual(passwd.text, newpass)
        tab.find("Keymap:", "combo box").click()
        self.pressKey("Down")
        self.pressKey("Down")
        self.pressKey("Down")
        finish.click()

        # Catch a port error
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Port must be above 5900", "label")
        alert.find("OK", "push button").click()
        tab.find("graphics-port", "spin button").text = "5920"
        uiutils.check_in_loop(lambda: details.active)

        # Spice regular example
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.find("Type:", "combo box").click_combo_entry()
        tab.find_fuzzy("Spice", "menu item").click()
        tab.find("graphics-tlsport-auto", "check").click()
        tab.find("graphics-tlsport", "spin button").text = "5999"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Spice GL example
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.find("Type:", "combo box").click_combo_entry()
        tab.find_fuzzy("Spice", "menu item").click()
        tab.find("Listen type:", "combo box").click_combo_entry()
        tab.find_fuzzy("None", "menu item").click()
        tab.find("OpenGL:", "check box").click()
        render = tab.find("graphics-rendernode", "combo box")
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
        finish = addhw.find("Finish", "push button")

        # Add USB device dup1
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("HP Dup USB 1", "table cell").click()
        finish.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("device is already in use by", "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: details.active)

        # Add USB device dup2
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("HP Dup USB 2", "table cell").click()
        finish.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("device is already in use by", "label")
        alert.find("Yes", "push button").click()
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
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("device is already in use by", "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: details.active)


    def testAddChars(self):
        """
        Add a bunch of char devices
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Add console device
        tab = self._select_hw(addhw, "Console", "char-tab")
        tab.find("Device Type:", "combo box").click()
        tab.find_fuzzy("Pseudo TTY", "menu item").click()
        tab.find("Type:", "combo box").click()
        tab.find_fuzzy("Hypervisor default", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add serial+file
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Serial", "char-tab")
        tab.find("Device Type:", "combo box").click()
        tab.find_fuzzy("Output to a file", "menu item").click()
        tab.find("Path:", "text").text = "/tmp/foo.log"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add udp serial
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Serial", "char-tab")
        tab.find("Device Type:", "combo box").click()
        tab.find_fuzzy("UDP", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add parallel+device
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Parallel", "char-tab")
        tab.find("Device Type:", "combo box").click()
        tab.find_fuzzy("Physical host character", "menu item").click()
        tab.find("Path:", "text").text = "/dev/parallel0"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add spicevmc channel
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Channel", "char-tab")
        # Ensures that this is selected by default
        tab.find("com.redhat.spice.0", "combo box")
        finish.click()
        uiutils.check_in_loop(lambda: details.active)


    def testAddLXCFilesystem(self):
        """
        Adding LXC specific filesystems
        """
        self.app.uri = tests.utils.uri_lxc

        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Add File+nbd share
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find("Type:", "combo box").click()
        tab.find("File", "menu item").click()
        tab.find("Driver:", "combo box").click()
        tab.find("Nbd", "menu item").click()
        tab.find("Format:", "combo box").click()
        tab.find("qcow2", "menu item").click()
        tab.find("Browse...", "push button").click()

        browsewin = self.app.root.find(
                "Choose Storage Volume", "frame")
        browsewin.find("Cancel", "push button").click()
        uiutils.check_in_loop(lambda: addhw.active)

        tab.find("Source path:", "text").text = "/foo/source"
        tab.find("Target path:", "text").text = "/foo/target"
        tab.find_fuzzy("Export filesystem", "check").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add RAM type
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find("Type:", "combo box").click()
        tab.find("Ram", "menu item").click()
        tab.find("Usage:", "spin button").text = "12345"
        tab.find("Target path:", "text").text = "/mem"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)


    def testAddHWMisc(self):
        """
        Add one each of simple devices
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Add input
        tab = self._select_hw(addhw, "Input", "input-tab")
        tab.find("Type:", "combo box").click()
        tab.find("EvTouch", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add sound
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Sound", "sound-tab")
        tab.find("Model:", "combo box").click()
        tab.find("ich6", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add video
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Video", "video-tab")
        tab.find("Model:", "combo box").click()
        tab.find("QXL", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add watchdog
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Watchdog", "watchdog-tab")
        tab.find("Model:", "combo box").click()
        tab.find("i6300esb", "menu item").click()
        tab.find("Action:", "combo box").click()
        tab.find("Pause the guest", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add smartcard
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Smartcard", "smartcard-tab")
        tab.find("Mode:", "combo box").click()
        tab.find("Passthrough", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add basic filesystem
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find("Source path:", "text").text = "/foo/source"
        tab.find("Target path:", "text").text = "/foo/target"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add TPM
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "TPM", "tpm-tab")
        tab.find("Device Path:", "text").text = "/tmp/foo"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add RNG
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "RNG", "rng-tab")
        tab.find("Device:", "text").text = "/dev/random"
        finish.click()
        uiutils.check_in_loop(lambda: details.active)

        # Add Panic
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Panic", "panic-tab")
        tab.find("Model:", "combo box").click()
        tab.find("Hyper-V", "menu item").click()
        finish.click()
        uiutils.check_in_loop(lambda: details.active)


    def testAddCornerCases(self):
        """
        Could random addhardware related tests
        """
        details = self._open_details_window("test-many-devices")
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Test cancel
        addhw.find("Cancel", "push button").click()

        # Test live adding, error dialog, click no
        self._open_addhw_window(details)
        finish.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find(
                "This device could not be attached to the running machine",
                "label")
        alert.find("Details", "toggle button").click_expander()
        alert.find("No", "push button").click()
        uiutils.check_in_loop(lambda: details.active)

        self._open_addhw_window(details)
        finish.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find(
                "This device could not be attached to the running machine",
                "label")
        alert.find("Details", "toggle button").click_expander()
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: alert.dead)
