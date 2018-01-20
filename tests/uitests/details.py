from tests.uitests import utils as uiutils


class Details(uiutils.UITestCase):
    """
    UI tests for virt-manager's VM details window
    """

    def _select_hw(self, win, hwname, tabname):
        c = win.find(hwname, "table cell")
        if not c.onscreen:
            hwlist = win.find("hw-list")
            hwlist.click()
            while not c.onscreen:
                self.pressKey("Down")
        c.click()
        tab = win.find(tabname, None)
        uiutils.check_in_loop(lambda: tab.showing)
        return tab

    def _stop_vm(self, win):
        run = win.find("Run", "push button")
        win.find("Shut Down", "push button").click()
        uiutils.check_in_loop(lambda: run.sensitive)

    def _start_vm(self, win):
        run = win.find("Run", "push button")
        run.click()
        uiutils.check_in_loop(lambda: not run.sensitive)


    ##############
    # Test cases #
    ##############

    def testDetailsHardwareSmokeTest(self):
        """
        Open the VM with all the crazy hardware and just verify that each
        HW panel shows itself without raising any error.
        """
        win = self._open_details_window()
        lst = win.find("hw-list", "table")
        self._walkUIList(win, lst, lambda: False)

    def _testRename(self, origname, newname):
        win = self._open_details_window(origname)

        # Ensure the Overview page is the first selected
        win.find("Hypervisor Details", "label")
        win.find("Overview", "table cell").click()

        oldcell = self.app.root.find_fuzzy(origname, "table cell")
        win.find("Name:", "text").text = newname
        win.find("config-apply", "push button").click()

        # Confirm lists were updated
        self.app.root.find("%s on" % newname, "frame")
        self.app.root.find_fuzzy(newname, "table cell")

        # Make sure the old entry is gone
        uiutils.check_in_loop(lambda: origname not in oldcell.name)

    def testDetailsRenameSimple(self):
        """
        Rename a simple VM
        """
        self._testRename("test-clone-simple", "test-new-name")

    def testDetailsRenameNVRAM(self):
        """
        Rename a VM that will trigger the nvram behavior
        """
        origname = "test-many-devices"
        # Shutdown the VM
        self.app.root.find_fuzzy(origname, "table cell").click()
        b = self.app.root.find("Shut Down", "push button")
        b.click()
        # This insures the VM finished shutting down
        uiutils.check_in_loop(lambda: b.sensitive is False)

        self._testRename(origname, "test-new-name")

    def testDetailsEdits(self):
        win = self._open_details_window(vmname="test-many-devices")
        appl = win.find("config-apply", "push button")
        hwlist = win.find("hw-list")

        # Overview description
        tab = self._select_hw(win, "Overview", "overview-tab")
        tab.find("Description:", "text").text = "hey new description"
        tab.find("Title:", "text").text = "hey new title"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Memory balloon
        tab = self._select_hw(win, "Memory", "memory-tab")
        tab.find("Current allocation:", "spin button").text = "300"
        tab.find("Maximum allocation:", "spin button").text = "800"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # CPU hotplug
        tab = self._select_hw(win, "CPUs", "cpu-tab")
        tab.find("Current allocation:", "spin button").text = "2"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        # Static CPU config
        self._stop_vm(win)
        # more cpu config: host-passthrough, copy, clear CPU, manual
        tab.find("cpu-model").click_combo_entry()
        tab.find_fuzzy("Clear CPU", "menu item").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        tab.find("cpu-model").click_combo_entry()
        tab.find("coreduo", "menu item").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        tab.find("cpu-model").click_combo_entry()
        tab.find("Application Default", "menu item").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        tab.find("cpu-model").click_combo_entry()
        tab.find("Hypervisor Default", "menu item").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        # CPU topology
        tab.find("Topology", "toggle button").click_expander()
        tab.find_fuzzy("Manually set", "check").click()
        tab.find("Sockets:", "spin button").typeText("8")
        tab.find("Cores:", "spin button").typeText("2")
        tab.find("Threads:", "spin button").typeText("2")
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        self.assertTrue(tab.find_fuzzy("Maximum", "spin").text == "32")


        def check_bootorder(c):
            # Click the bootlist checkbox, which is hard to find in the tree
            import dogtail.rawinput
            x = c.position[0] - 30
            y = c.position[1] + c.size[1] / 2
            button = 1
            dogtail.rawinput.click(x, y, button)

        # Boot tweaks
        tab = self._select_hw(win, "Boot Options", "boot-tab")
        self._stop_vm(win)
        tab.find_fuzzy("Start virtual machine on host", "check box").click()
        tab.find("Enable boot menu", "check box").click()
        check_bootorder(tab.find("SCSI Disk 1", "table cell"))
        tab.find("boot-movedown", "push button").click()
        tab.find("Floppy 1", "table cell").click()
        tab.find("boot-moveup", "push button").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        # Kernel boot
        tab.find_fuzzy("Direct kernel boot", "toggle button").click_expander()
        tab.find_fuzzy("Enable direct kernel", "check box").click()
        tab.find("kernel-browse", "push button").click()
        browsewin = self.app.root.find("Choose Storage Volume", "frame")
        browsewin.find("default-pool", "table cell").click()
        browsewin.find("bochs-vol", "table cell").click()
        browsewin.find("Choose Volume", "push button").click()
        uiutils.check_in_loop(lambda: win.active)
        self.assertTrue("bochs" in tab.find("Kernel path:", "text").text)
        tab.find("Initrd path:", "text").text = "/tmp/initrd"
        tab.find("DTB path:", "text").text = "/tmp/dtb"
        tab.find("Kernel args:", "text").text = "console=ttyS0"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Disk options
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        tab.find("Shareable:", "check box").click()
        tab.find("Readonly:", "check box").click()
        tab.find("Advanced options", "toggle button").click_expander()
        tab.find("Storage format:", "text").text = "vmdk"
        tab.find("Serial number:", "text").text = "1234-ABCD"
        tab.find("Disk bus:", "text").text = "usb"
        tab.find("Performance options", "toggle button").click_expander()
        tab.find("IO mode:", "text").text = "threads"
        tab.find("Cache mode:", "text").text = "unsafe"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        # Device is now 'USB Disk 1'
        c = hwlist.find("USB Disk 1", "table cell")
        self.assertTrue(c.state_selected)
        tab.find("Removable:", "check box").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Network values
        tab = self._select_hw(win, "NIC :54:32:10", "network-tab")
        src = tab.find(None, "combo box", "Network source:")
        tab.find("Device model:", "text").text = "rtl8139"
        src.click()
        tab.find_fuzzy("macvtap", "menu item").click()
        mode = tab.find_fuzzy("Source mode:", "combo box")
        mode.click_combo_entry()
        self.assertTrue(mode.find("Bridge", "menu item").selected)
        self.pressKey("Escape")
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        # Manual bridge
        src.click()
        tab.find_fuzzy("Specify shared device", "menu item").click()
        appl.click()
        # Check validation error
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Error changing VM configuration", "label")
        alert.find("Close", "push button").click()
        tab.find("Bridge name:", "text").text = "zbr0"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        # Network with portops
        src.click()
        self.pressKey("Home")
        tab.find_fuzzy("plainbridge-portgroups", "menu item").click()
        c = tab.find_fuzzy("Portgroup:", "combo box")
        c.click_combo_entry()
        self.assertTrue(c.find("engineering", "menu item").selected)
        self.pressKey("Escape")
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        # Network with vport stuff
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
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Graphics
        tab = self._select_hw(win, "Display VNC", "graphics-tab")
        tab.find("Type:", "combo box").click_combo_entry()
        tab.find("Spice server", "menu item").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        tab.find("Type:", "combo box").click_combo_entry()
        tab.find("VNC server", "menu item").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Sound device
        tab = self._select_hw(win, "Sound sb16", "sound-tab")
        tab.find("Model:", "text").text = "ac97"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Host device
        tab = self._select_hw(win, "PCI 0000:00:19.0", "host-tab")
        tab.find("ROM BAR:", "check box").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Video device
        tab = self._select_hw(win, "Video VMVGA", "video-tab")
        tab.find("Model:", "text").text = "virtio"
        tab.find("3D acceleration:", "check box").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Watchdog
        tab = self._select_hw(win, "Watchdog", "watchdog-tab")
        tab.find("Model:", "text").text = "diag288"
        tab.find("Action:", "text").click()
        self.pressKey("Down")
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Controller SCSI
        tab = self._select_hw(
                win, "Controller Virtio SCSI 9", "controller-tab")
        tab.find("controller-model", "combo box").click_combo_entry()
        tab.find("Hypervisor default", "menu item").click()
        tab.find("SCSI Disk 1 on 9:0:0:0", "table cell")
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        # Controller USB
        tab = self._select_hw(win, "Controller USB 0", "controller-tab")
        tab.find("controller-model", "combo box").click_combo_entry()
        tab.find("USB 2", "menu item").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        tab = self._select_hw(win, "Controller USB 0", "controller-tab")
        tab.find("controller-model", "combo box").click_combo_entry()
        tab.find("USB 3", "menu item").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Filesystem tweaks
        tab = self._select_hw(win, "Filesystem /target/", "filesystem-tab")
        tab.find("Driver:", "combo box").click()
        tab.find("Path", "menu item").click()
        tab.find("Write Policy:", "combo box").click()
        tab.find("Immediate", "menu item").click()
        tab.find("Source path:", "text").text = "/frib1"
        tab.find("Target path:", "text").text = "newtarget"
        tab.find_fuzzy("Export filesystem", "check box").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


        # Smartcard tweaks
        tab = self._select_hw(win, "Smartcard", "smartcard-tab")
        tab.find("smartcard-mode", "combo box").click_combo_entry()
        tab.find("Passthrough", "menu item").click()
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)


    def testDetailsMiscEdits(self):
        """
        Test misc editting behavior, like checking for unapplied
        changes
        """
        win = self._open_details_window(vmname="test-many-devices")
        hwlist = win.find("hw-list")

        # Live device removal, see results after shutdown
        disklabel = "SCSI Disk 1"
        tab = self._select_hw(win, disklabel, "disk-tab")
        win.find("config-remove", "push button").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Are you sure you want to remove", "label")
        alert.find_fuzzy("Don't ask", "check").click()
        alert.find("Yes", "push button").click()

        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Device could not be removed", "label")
        alert.find("OK", "push button").click()

        c = hwlist.find(disklabel, "table cell")
        self._stop_vm(win)
        self.assertTrue(c.text != disklabel)

        # Remove a device for offline VM
        tab = self._select_hw(win, "SCSI CDROM 1", "disk-tab")
        win.find("config-remove", "push button").click()
        uiutils.check_in_loop(lambda: win.active)

        # Cancelling changes
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        share = tab.find("Shareable:", "check box")
        self.assertFalse(share.checked)
        share.click()
        win.find("config-cancel").click()
        self.assertFalse(share.checked)

        # Unapplied, clicking no
        share = tab.find("Shareable:", "check box")
        share.click()
        hwlist.find("CPUs", "table cell").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("There are unapplied changes", "label")
        alert.find("No", "push button").click()
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        self.assertFalse(share.checked)

        # Unapplied changes but clicking yes
        share.click()
        hwlist.find("CPUs", "table cell").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("There are unapplied changes", "label")
        alert.find_fuzzy("Don't warn", "check box").click()
        alert.find("Yes", "push button").click()
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        self.assertTrue(share.checked)

        # Make sure no unapplied changes option sticks
        share.click()
        self._select_hw(win, "CPUs", "cpu-tab")
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        self.assertTrue(share.checked)


        # VM State change doesn't refresh UI
        share.click()
        self._start_vm(win)
        self.assertTrue(not share.checked)

        # Now apply changes to running VM, ensure they show up on shutdown
        win.find("config-apply").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("changes will take effect", "label")
        alert.find("OK", "push button").click()
        self.assertTrue(share.checked)
        self._stop_vm(win)
        self.assertTrue(not share.checked)
