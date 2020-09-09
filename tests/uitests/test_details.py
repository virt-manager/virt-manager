# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests.uitests import utils as uiutils
import tests.utils


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
        uiutils.check(lambda: tab.showing)
        return tab

    def _stop_vm(self, win):
        run = win.find("Run", "push button")
        win.find("Shut Down", "push button").click()
        uiutils.check(lambda: run.sensitive)

    def _start_vm(self, win):
        run = win.find("Run", "push button")
        run.click()
        uiutils.check(lambda: not run.sensitive)


    ##############
    # Test cases #
    ##############

    def _testSmokeTest(self, vmname):
        """
        Open the VM with all the crazy hardware and just verify that each
        HW panel shows itself without raising any error.
        """
        win = self._open_details_window(vmname=vmname, double=True)
        lst = win.find("hw-list", "table")
        self._walkUIList(win, lst, lambda: False)

        # Select XML editor, and reverse walk the list
        win.find("XML", "page tab").click()
        self._walkUIList(win, lst, lambda: False, reverse=True)
        return win

    def testDetailsHardwareSmokeTest(self):
        self._testSmokeTest(None)

    def testDetailsHardwareSmokeTestAlternate(self):
        self.app.open(keyfile="allstats.ini")
        win = self._testSmokeTest("test alternate devs title")
        win.find("Details", "page tab").click()
        self._select_hw(win, "Performance", "performance-tab")
        # Wait for perf signals to trigger, to cover more code
        self.sleep(2)

    def _testRename(self, origname, newname):
        # Enable all stats prefs to hit some extra code
        win = self._open_details_window(origname)

        # Ensure the Overview page is the first selected
        win.find("Hypervisor Details", "label")
        win.find("Overview", "table cell").click()

        oldcell = self.app.root.find_fuzzy(origname, "table cell")
        badname = "foo/bar"
        win.find("Name:", "text").set_text(badname)
        appl = win.find("config-apply")
        appl.click()
        self._click_alert_button(badname, "Close")

        # Actual name change
        win.find("Name:", "text").set_text(newname)
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Confirm lists were updated
        self.app.root.find("%s on" % newname, "frame")
        self.app.root.find_fuzzy(newname, "table cell")

        # Make sure the old entry is gone
        uiutils.check(lambda: origname not in oldcell.name)

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
        uiutils.check(lambda: b.sensitive is False)

        self._testRename(origname, "test-new-name")

    def testDetailsStateMisc(self):
        """
        Test state changes and unapplied changes warnings
        """
        self.app.uri = tests.utils.URIs.kvm
        win = self._open_details_window(vmname="test", shutdown=True)
        fmenu = win.find("File", "menu")
        fmenu.click()
        fmenu.find("View Manager").click()
        # Double run to hit a show() codepath
        win = self._open_details_window(vmname="test")
        uiutils.check(lambda: win.active)
        appl = win.find("config-apply", "push button")

        # View Manager option
        win.find("File", "menu").click()
        win.find("View Manager", "menu item").click()
        uiutils.check(lambda: self.app.topwin.active)
        self.app.topwin.keyCombo("<alt>F4")
        uiutils.check(lambda: win.active)

        # Make a change and then trigger unapplied change warning
        tab = self._select_hw(win, "Overview", "overview-tab")
        tab.find("Name:", "text").set_text("")
        uiutils.check(lambda: appl.sensitive)
        run = win.find("Run", "push button")
        run.click()
        # Trigger apply error to hit some code paths
        self._click_alert_button("unapplied changes", "Yes")
        self._click_alert_button("name must be specified", "Close")
        uiutils.check(lambda: run.sensitive)
        consolebtn = win.find("Console", "radio button")
        consolebtn.click()
        self._click_alert_button("unapplied changes", "Yes")
        self._click_alert_button("name must be specified", "Close")
        uiutils.check(lambda: not consolebtn.checked)

        # Test the pause toggle
        win.find("config-cancel").click()
        run.click()
        uiutils.check(lambda: not run.sensitive)
        pause = win.find("Pause", "toggle button")
        pause.click()
        uiutils.check(lambda: pause.checked)
        pause.click()
        uiutils.check(lambda: not pause.checked)
        uiutils.check(lambda: win.active)

    def testDetailsEditDomain1(self):
        """
        Test overview, memory, cpu pages
        """
        self.app.uri = tests.utils.URIs.kvm_cpu_insecure
        win = self._open_details_window(vmname="test")
        appl = win.find("config-apply", "push button")

        # Overview description
        tab = self._select_hw(win, "Overview", "overview-tab")
        tab.find("Description:", "text").set_text("hey new description")
        tab.find("Title:", "text").set_text("hey new title")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # There's no hotplug operations after this point
        self._stop_vm(win)

        # Memory
        tab = self._select_hw(win, "Memory", "memory-tab")
        tab.find("Memory allocation:", "spin button").set_text("300")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Static CPU config
        # more cpu config: host-passthrough, copy, clear CPU, manual
        tab = self._select_hw(win, "CPUs", "cpu-tab")
        tab.find("cpu-model").click_combo_entry()
        tab.find_fuzzy("Clear CPU", "menu item").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        tab.find("cpu-model").click_combo_entry()
        tab.find("coreduo", "menu item").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        tab.find_fuzzy("CPU security", "check box").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        tab.find("cpu-model").click_combo_entry()
        tab.find("Application Default", "menu item").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        copyhost = tab.find("Copy host", "check box")
        uiutils.check(lambda: copyhost.checked)
        copyhost.click()
        tab.find("cpu-model").click_combo_entry()
        tab.find("Hypervisor Default", "menu item").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        tab.find("cpu-model").find(None, "text").text = "host-passthrough"
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # vCPUs
        tab.find("vCPU allocation:", "spin button").set_text("50")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # CPU topology
        tab.find_fuzzy("Topology", "toggle button").click_expander()
        tab.find_fuzzy("Manually set", "check").click()
        sockets = tab.find("Sockets:", "spin button")
        sockets.typeText("8")
        tab.find("Cores:", "spin button").typeText("2")
        tab.find("Threads:", "spin button").typeText("2")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        # Confirm VCPUs were adjusted
        vcpualloc = tab.find_fuzzy("vCPU allocation", "spin")
        uiutils.check(lambda: vcpualloc.text == "32")

        # Unset topology
        tab.find_fuzzy("Manually set", "check").click()
        uiutils.check(lambda: not sockets.sensitive)
        appl.click()
        uiutils.check(lambda: not appl.sensitive)


    def testDetailsEditDomain2(self):
        """
        Test boot and OS pages
        """
        win = self._open_details_window(vmname="test-many-devices")
        appl = win.find("config-apply", "push button")
        self._stop_vm(win)


        # OS edits
        tab = self._select_hw(win, "OS information", "os-tab")
        entry = tab.find("oslist-entry")
        uiutils.check(lambda: entry.text == "Fedora")
        entry.click()
        self.pressKey("Down")
        popover = win.find("oslist-popover")
        popover.find("include-eol").click()
        entry.set_text("fedora12")
        popover.find_fuzzy("fedora12").bring_on_screen().click()
        uiutils.check(lambda: not popover.visible)
        uiutils.check(lambda: entry.text == "Fedora 12")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        uiutils.check(lambda: entry.text == "Fedora 12")


        # Boot tweaks
        def check_bootorder(c):
            # Click the bootlist checkbox, which is hard to find in the tree
            import dogtail.rawinput
            x = c.position[0] - 30
            y = c.position[1] + c.size[1] / 2
            button = 1
            dogtail.rawinput.click(x, y, button)

        tab = self._select_hw(win, "Boot Options", "boot-tab")
        tab.find_fuzzy("Start virtual machine on host", "check box").click()
        tab.find("Enable boot menu", "check box").click()
        tab.find("SCSI Disk 1", "table cell").click()
        tab.find("boot-movedown", "push button").click()
        tab.find("Floppy 1", "table cell").click()
        tab.find("boot-moveup", "push button").click()
        check_bootorder(tab.find("NIC :33:44", "table cell"))
        check_bootorder(tab.find("PCI 0003:", "table cell"))
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Kernel boot
        tab.find_fuzzy("Direct kernel boot", "toggle button").click_expander()
        tab.find_fuzzy("Enable direct kernel", "check box").click()

        tab.find("Kernel args:", "text").set_text("console=ttyS0")
        appl.click()
        self._click_alert_button("arguments without specifying", "OK")
        uiutils.check(lambda: win.active)

        initrd = tab.find("Initrd path:", "text")
        tab.find("initrd-browse", "push button").click()
        self._select_storagebrowser_volume("default-pool", "backingl1.img")
        uiutils.check(lambda: win.active)
        uiutils.check(lambda: "backing" in initrd.text)
        appl.click()
        self._click_alert_button("initrd without specifying", "OK")
        uiutils.check(lambda: win.active)

        tab.find("kernel-browse", "push button").click()
        self._select_storagebrowser_volume("default-pool", "bochs-vol")
        uiutils.check(lambda: win.active)
        kernelpath = tab.find("Kernel path:", "text")
        uiutils.check(lambda: "bochs" in kernelpath.text)

        dtb = tab.find("DTB path:", "text")
        tab.find("dtb-browse", "push button").click()
        self._select_storagebrowser_volume("default-pool", "iso-vol")
        uiutils.check(lambda: win.active)
        uiutils.check(lambda: "iso-vol" in dtb.text)

        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Now disable kernel, but verify that we keep the values in the UI
        tab.find_fuzzy("Enable direct kernel", "check box").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        tab = self._select_hw(win, "OS information", "os-tab")
        tab = self._select_hw(win, "Boot Options", "boot-tab")
        uiutils.check(lambda: "backing" in initrd.text)

    def testDetailsAlternateEdits(self):
        """
        Some specific handling via test-alternate-devs
        """
        win = self._open_details_window(vmname="test alternate devs title")

        # tests the console dup removal
        self._select_hw(win, "Serial 1", "char-tab")
        win.find("config-remove").click()
        self._click_alert_button("Are you sure", "Yes")
        self._click_alert_button("take effect after", "OK")
        self._stop_vm(win)

    def testDetailsEmptyBoot(self):
        """
        Check boot handling when VM has no devices
        """
        win = self._open_details_window(vmname="test-state-crashed")
        self._select_hw(win, "Boot Options", "boot-tab")
        win.find("No bootable devices")

        # Add in switching back to the console view to hit a vmwindow path
        win.find("Console", "radio button").click()

    def testDetailsEditDiskNet(self):
        """
        Test disk and network devices
        """
        win = self._open_details_window(vmname="test-many-devices")
        appl = win.find("config-apply", "push button")

        # Quick test to hit some serialcon.py paths
        viewmenu = win.find("^View$", "menu")
        viewmenu.click()
        textmenu = viewmenu.find("Consoles", "menu")
        textmenu.point()
        conitem = textmenu.find("Serial 1")
        uiutils.check(lambda: not conitem.sensitive)
        viewmenu.click()

        self._stop_vm(win)

        # Disk options
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        tab.find("Advanced options", "toggle button").click_expander()
        tab.find("Shareable:", "check box").click()
        tab.find("Readonly:", "check box").click()
        tab.find("Serial:", "text").set_text("1234-ABCD")
        tab.combo_select("Cache mode:", "unsafe")
        tab.combo_select("Discard mode:", "unmap")
        tab.combo_select("Detect zeroes:", "unmap")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Network values w/ macvtap manual
        tab = self._select_hw(win, "NIC :54:32:10", "network-tab")
        tab.find("IP address", "push button").click()
        src = tab.find("net-source")
        src.click()
        self.pressKey("Home")
        tab.find_fuzzy("Macvtap device...",
                       "menu item").bring_on_screen().click()
        tab.find("Device name:", "text").set_text("fakedev12")
        tab.combo_select("Device model:", "rtl8139")
        tab.find("Link state:", "check box").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Manual bridge
        src.click()
        tab.find_fuzzy("Bridge device...",
                       "menu item").bring_on_screen().click()
        tab.find("Device name:", "text").set_text("")
        appl.click()
        # Check validation error
        self._click_alert_button("Error changing VM configuration", "Close")
        tab.find("Device name:", "text").set_text("zbr0")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

    def testDetailsNetIPAddress(self):
        """
        Test all the IP code paths with a few mock cases
        """
        win = self._open_details_window(vmname="test-many-devices")
        def check_ip(*args):
            for ip in args:
                tab.find_fuzzy(ip, "label")

        # First case has a virtual network, so hits the leases path
        tab = self._select_hw(win, "NIC :54:32:10", "network-tab")
        check_ip("10.0.0.2", "fd00:beef::2")
        tab.find("IP address:", "push button").click()
        check_ip("10.0.0.2", "fd00:beef::2")

        # Next case has a missing virtual network, so hits the arp path
        tab = self._select_hw(win, "NIC :11:11:11", "network-tab")
        check_ip("Unknown")
        tab.find("IP address:", "push button").click()
        check_ip("10.0.0.3")

        win.keyCombo("<alt>F4")
        uiutils.check(lambda: not win.showing)
        self.app.topwin.click_title()

        # Tests the fake qemu guest agent path
        win = self._open_details_window(vmname="test alternate devs title")
        tab = self._select_hw(win, "NIC :11:72:72", "network-tab")
        check_ip("10.0.0.1", "fd00:beef::1/128")


    def testDetailsEditDevices1(self):
        """
        Test all other devices
        """
        win = self._open_details_window(vmname="test-many-devices")
        appl = win.find("config-apply", "push button")

        # Fail to hotremove
        tab = self._select_hw(win, "Floppy 1", "disk-tab")
        tab.find("Advanced options", "toggle button").click_expander()
        share = tab.find("Shareable", "check box")
        share.click()
        uiutils.check(lambda: appl.sensitive)
        win.find("config-remove").click()
        delete = self.app.root.find_fuzzy("Remove Disk", "frame")
        delete.find_fuzzy("Delete", "button").click()
        self._click_alert_button("change will take effect", "OK")
        uiutils.check(lambda: not delete.showing)
        uiutils.check(lambda: appl.sensitive)
        uiutils.check(lambda: share.checked)
        win.find("config-cancel").click()

        self._stop_vm(win)

        # Graphics simple VNC -> SPICE
        tab = self._select_hw(win, "Display VNC", "graphics-tab")
        tab.combo_select("Type:", "Spice")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Spice GL example
        tab.combo_select("Listen type:", "None")
        tab.find("OpenGL:", "check box").click()
        tab.combo_check_default("graphics-rendernode", "0000")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Switch to VNC with options
        tab.combo_select("Type:", "VNC")
        tab.combo_select("Listen type:", "Address")
        tab.find("graphics-port-auto", "check").click()
        tab.find("graphics-port-auto", "check").click()
        tab.find("graphics-port", "spin button").set_text("6001")
        tab.find("Password:", "check").click()
        passwd = tab.find_fuzzy("graphics-password", "text")
        newpass = "foobar"
        passwd.typeText(newpass)
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Sound device
        tab = self._select_hw(win, "Sound sb16", "sound-tab")
        tab.find("Model:", "text").set_text("ac97")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        # Test non-disk removal
        win.find("config-remove").click()
        cell = win.find("Sound ac97", "table cell")
        oldtext = cell.text
        self._click_alert_button("Are you sure", "No")
        uiutils.check(lambda: cell.state_selected)
        cell.click(button=3)
        self.app.root.find("Remove Hardware", "menu item").click()
        self._click_alert_button("Are you sure", "Yes")
        uiutils.check(lambda: cell.text != oldtext)


        # Host device
        tab = self._select_hw(win, "PCI 0000:00:19.0", "host-tab")
        tab.find("ROM BAR:", "check box").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)


        # Video device
        tab = self._select_hw(win, "Video VMVGA", "video-tab")
        tab.find("Model:", "text").set_text("virtio")
        tab.find("3D acceleration:", "check box").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)


        # Watchdog
        tab = self._select_hw(win, "Watchdog", "watchdog-tab")
        tab.find("Model:", "text").set_text("diag288")
        tab.find("Action:", "text").click()
        self.pressKey("Down")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)


    def testDetailsEditDevices2(self):
        win = self._open_details_window(vmname="test-many-devices",
                shutdown=True)
        appl = win.find("config-apply", "push button")

        # Controller SCSI
        tab = self._select_hw(
                win, "Controller VirtIO SCSI 9", "controller-tab")
        tab.combo_select("controller-model", "Hypervisor")
        tab.find("SCSI Disk 1 on 9:0:0:0", "table cell")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Controller USB
        tab = self._select_hw(win, "Controller USB 0", "controller-tab")
        tab.combo_select("controller-model", "USB 2")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        tab = self._select_hw(win, "Controller USB 0", "controller-tab")
        tab.combo_select("controller-model", "USB 3")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        tab = self._select_hw(win, "Controller USB 0", "controller-tab")
        tab.find("controller-model").find(None, "text").text = "piix3-uhci"
        appl.click()
        uiutils.check(lambda: not appl.sensitive)


        # Filesystem tweaks
        tab = self._select_hw(win, "Filesystem /target/", "filesystem-tab")
        tab.combo_select("Driver:", "Path")
        tab.combo_select("Write Policy:", "Immediate")
        tab.find("Source path:", "text").set_text("/frib1")
        tab.find("Target path:", "text").set_text("newtarget")
        tab.find_fuzzy("Export filesystem", "check box").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)


        # Smartcard tweaks
        tab = self._select_hw(win, "Smartcard", "smartcard-tab")
        tab.combo_select("smartcard-mode", "Passthrough")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # TPM tweaks
        tab = self._select_hw(win, "TPM", "tpm-tab")
        tab.combo_select("tpm-model", "CRB")
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # vsock tweaks
        tab = self._select_hw(win, "VirtIO VSOCK", "vsock-tab")
        addr = tab.find("vsock-cid")
        auto = tab.find("vsock-auto")
        uiutils.check(lambda: addr.text == "5")
        addr.set_text("7")
        appl.click()
        uiutils.check(lambda: addr.text == "7")
        uiutils.check(lambda: not appl.sensitive)
        auto.click()
        uiutils.check(lambda: not addr.visible)
        appl.click()
        uiutils.check(lambda: not appl.sensitive)


    def testDetailsMiscEdits(self):
        """
        Test misc editing behavior, like checking for unapplied
        changes
        """
        win = self._open_details_window(vmname="test-many-devices",
                double=True)
        hwlist = win.find("hw-list")

        # Live device removal, see results after shutdown
        disklabel = "SCSI Disk 1"
        tab = self._select_hw(win, disklabel, "disk-tab")
        win.find("config-remove", "push button").click()
        delete = self.app.root.find_fuzzy("Remove Disk", "frame")
        delete.find_fuzzy("Delete", "button").click()

        # Will be fixed eventually
        self._click_alert_button("Device could not be removed", "OK")

        c = hwlist.find(disklabel, "table cell")
        self._stop_vm(win)
        uiutils.check(lambda: c.text != disklabel)

        # Remove a device for offline VM
        tab = self._select_hw(win, "SCSI CDROM 1", "disk-tab")
        win.find("config-remove", "push button").click()
        delete = self.app.root.find_fuzzy("Remove Disk", "frame")
        delete.find_fuzzy("Delete", "button").click()
        uiutils.check(lambda: win.active)

        # Attempt to apply changes when skipping away, but they fail
        tab.find("Advanced options", "toggle button").click_expander()
        tab.find("Cache mode:", "combo").find(None, "text").set_text("badcachemode")
        hwlist.find("CPUs", "table cell").click()
        self._click_alert_button("There are unapplied changes", "Yes")
        self._click_alert_button("badcachemode", "Close")

        # Cancelling changes
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        share = tab.find("Shareable:", "check box")
        uiutils.check(lambda: not share.checked)
        share.click()
        win.find("config-cancel").click()
        uiutils.check(lambda: not share.checked)

        # Unapplied, clicking no
        share = tab.find("Shareable:", "check box")
        share.click()
        hwlist.find("CPUs", "table cell").click()
        self._click_alert_button("There are unapplied changes", "No")
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        uiutils.check(lambda: not share.checked)

        # Unapplied changes but clicking yes
        share.click()
        hwlist.find("CPUs", "table cell").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("There are unapplied changes", "label")
        alert.find_fuzzy("Don't warn", "check box").click()
        alert.find("Yes", "push button").click()
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        uiutils.check(lambda: share.checked)

        # Make sure no unapplied changes option sticks
        share.click()
        self._select_hw(win, "CPUs", "cpu-tab")
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        uiutils.check(lambda: share.checked)

        # VM State change doesn't refresh UI
        share.click()
        self._start_vm(win)
        uiutils.check(lambda: not share.checked)

        # Now apply changes to running VM, ensure they show up on shutdown
        win.find("config-apply").click()
        self._click_alert_button("changes will take effect", "OK")
        uiutils.check(lambda: share.checked)
        self._stop_vm(win)
        uiutils.check(lambda: not share.checked)

        # Unapplied changes should warn when switching to XML tab
        tab = self._select_hw(win, "Overview", "overview-tab")
        tab.find("Description:", "text").set_text("hey new description")
        win.find("XML", "page tab").click()
        # Select 'No', meaning don't abandon changes
        self._click_alert_button("changes will be lost", "No")
        uiutils.check(lambda: tab.showing)

        # Try unapplied changes again, this time abandon our changes
        win.find("XML", "page tab").click()
        self._click_alert_button("changes will be lost", "Yes")
        uiutils.check(lambda: not tab.showing)

        # Verify addhardware right click works
        win.find("Overview", "table cell").click(button=3)
        self.app.root.find("Add Hardware", "menu item").click()
        self.app.root.find("Add New Virtual Hardware", "frame")

    def testDetailsXMLEdit(self):
        """
        Test XML editing interaction
        """
        self.app.open(xmleditor_enabled=True)
        win = self._open_details_window(vmname="test-clone-simple")
        finish = win.find("config-apply")
        xmleditor = win.find("XML editor")

        # Edit vcpu count and verify it's reflected in CPU page
        tab = self._select_hw(win, "CPUs", "cpu-tab")
        win.find("XML", "page tab").click()
        xmleditor.set_text(xmleditor.text.replace(">5</vcpu", ">8</vcpu"))
        finish.click()
        win.find("Details", "page tab").click()
        vcpualloc = tab.find("vCPU allocation:", "spin button")
        uiutils.check(lambda: vcpualloc.text == "8")

        # Make some disk edits
        tab = self._select_hw(win, "IDE Disk 1", "disk-tab")
        win.find("XML", "page tab").click()
        origpath = "/dev/default-pool/test-clone-simple.img"
        newpath = "/path/FOOBAR"
        xmleditor.set_text(xmleditor.text.replace(origpath, newpath))
        finish.click()
        win.find("Details", "page tab").click()
        disksrc = win.find("disk-source-path")
        uiutils.check(lambda: disksrc.text == newpath)

        # Do standard xmleditor tests
        self._test_xmleditor_interactions(win, finish)

    def testDetailsConsoleChecksSSH(self):
        """
        Trigger a bunch of console connection failures to hit
        various details/* code paths
        """
        fakeuri = "qemu+ssh://foouser@256.256.256.256:1234/system"
        uri = tests.utils.URIs.test_full + ",fakeuri=%s" % fakeuri
        self.app.uri = uri
        self.app.open(xmleditor_enabled=True)

        self.app.topwin.find("test\n", "table cell").doubleClick()
        win = self.app.root.find("test on", "frame")
        conpages = win.find("console-pages")
        run = win.find("Run", "push button")
        shutdown = win.find("Shut Down", "push button")
        conbtn = win.find("Console", "radio button")
        detailsbtn = win.find("Details", "radio button")

        def _run():
            win.click_title()
            run.click()
            uiutils.check(lambda: not run.sensitive)
        def _stop():
            shutdown.click()
            uiutils.check(lambda: not shutdown.sensitive)
        def _checkcon(msg):
            conbtn.click()
            uiutils.check(lambda: conpages.showing)
            conpages.find(msg)
        def _check_textconsole_menu(msg):
            vmenu = win.find("^View$", "menu")
            vmenu.click()
            tmenu = win.find("Consoles", "menu")
            tmenu.point()
            tmenu.find(msg, ".*menu item.*")
            vmenu.click()

        # Check initial state
        _checkcon("Graphical console not configured")
        _stop()
        _check_textconsole_menu("No graphical console available")

        # Add a SDL graphics device which can't be displayed
        detailsbtn.click()
        win.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        addhw.find("Graphics", "table cell").click()
        addhw.find("XML", "page tab").click()
        dev = '<graphics type="sdl" display=":3.4" xauth="/tmp/.Xauthority"/>'
        addhw.find("XML editor").text = dev
        addhw.find("Finish", "push button").click()
        uiutils.check(lambda: not addhw.active)
        uiutils.check(lambda: win.active)
        _run()
        _checkcon("Cannot display graphical console type")

        def _change_gfx_xml(_xml):
            detailsbtn.click()
            win.find("Display ", "table cell").click()
            win.find("XML", "page tab").click()
            win.find("XML editor").set_text(_xml)
            win.find("config-apply").click()

        # Listening from some other address
        _stop()
        xml = '<graphics type="spice" listen="0.0.0.0" port="6000" tlsPort="6001"/>'
        _change_gfx_xml(xml)
        _run()
        _checkcon(".*resolving.*256.256.256.256.*")

        # Listening from some other address
        _stop()
        xml = '<graphics type="spice" listen="257.0.0.1" port="6000"/>'
        _change_gfx_xml(xml)
        _run()
        _checkcon(".*resolving.*257.0.0.1.*")

        # Hit a specific error about tls only and ssh
        _stop()
        xml = '<graphics type="spice" tlsPort="60001" autoport="no"/>'
        _change_gfx_xml(xml)
        _run()
        _checkcon(".*configured for TLS only.*")

        # Fake a socket connection
        _stop()
        xml = '<graphics type="vnc" socket="/tmp/foobar.sock"/>'
        _change_gfx_xml(xml)
        _run()
        _checkcon(".*SSH tunnel error output.*")

        # Add a listen type='none' check
        _stop()
        xml = '<graphics type="spice"><listen type="none"/></graphics>'
        _change_gfx_xml(xml)
        _run()
        _checkcon(".*local file descriptor.*")

        # Add a local list + port check
        _stop()
        xml = '<graphics type="spice" listen="127.0.0.1" port="6000" tlsPort="60001"/>'
        _change_gfx_xml(xml)
        _run()
        _checkcon(".*SSH tunnel error output.*")

    def testDetailsConsoleChecksTCP(self):
        """
        Hit a specific warning when the connection has
        non-SSH transport but the guest config is only listening locally
        """
        fakeuri = "qemu+tcp://foouser@256.256.256.256:1234/system"
        uri = tests.utils.URIs.test_full + ",fakeuri=%s" % fakeuri
        self.app.uri = uri
        self.app.open(xmleditor_enabled=True)

        self.app.topwin.find("test\n", "table cell").doubleClick()
        win = self.app.root.find("test on", "frame")
        conpages = win.find("console-pages")
        run = win.find("Run", "push button")
        shutdown = win.find("Shut Down", "push button")
        conbtn = win.find("Console", "radio button")
        detailsbtn = win.find("Details", "radio button")

        def _run():
            win.click_title()
            run.click()
            uiutils.check(lambda: not run.sensitive)
        def _stop():
            shutdown.click()
            uiutils.check(lambda: not shutdown.sensitive)
        def _checkcon(msg):
            conbtn.click()
            uiutils.check(lambda: conpages.showing)
            conpages.find(msg)

        # Check initial state
        _checkcon("Graphical console not configured")
        _stop()

        # Add a SDL graphics device which can't be displayed
        detailsbtn.click()
        win.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        addhw.find("Graphics", "table cell").click()
        addhw.find("XML", "page tab").click()
        dev = '<graphics type="vnc" port="6000" address="127.0.0.1"/>'
        addhw.find("XML editor").text = dev
        addhw.find("Finish", "push button").click()
        uiutils.check(lambda: not addhw.active)
        uiutils.check(lambda: win.active)
        _run()
        _checkcon(".*configured to listen locally.*")
