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

    def _check_alert(self):
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("changes will take effect", "label")
        alert.find("OK", "push button").click()

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

        """
        # Overview description
        tab = self._select_hw(win, "Overview", "overview-tab")
        tab.find("Description:", "text").text = "hey new description"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        # CPU hotplug
        tab = self._select_hw(win, "CPUs", "cpu-tab")
        tab.find("Current allocation:", "spin button").text = "2"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)

        # Memory balloon
        tab = self._select_hw(win, "Memory", "memory-tab")
        tab.find("Current allocation:", "spin button").text = "300"
        tab.find("Maximum allocation:", "spin button").text = "800"
        appl.click()
        uiutils.check_in_loop(lambda: not appl.sensitive)
        """
        self._stop_vm(win)
        """

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
        """


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
        #appl.click()
        #uiutils.check_in_loop(lambda: not appl.sensitive)
        tab.print_nodes()
        self.sleep(5)

        """
        sound model
        usb2->usb3
        change network source
        vnc to spice
        video 3d

        """


    """
        # Live device removal
        self._start_vm(win)
        tab = self._select_hw(win, "SCSI Disk 1", "disk-tab")
        tab.find("Remove", "push button")
        self._check_alert()
        c = hwlist.find("SCSI Disk 1", "table cell")
        self.assertTrue(lambda: c.showing)
        self._stop_vm()
        uiutils.check_in_loop(lambda: c.dead)

        misc stuff:
            make changes, VM change state, changes stay in place
            unapplied changes
            cancel to reset changes
            removing devices
            - offline and online
    """
