# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest.mock

import tests
from . import lib



class NewVM(lib.testcase.UITestCase):
    """
    UI tests for virt-manager's NewVM wizard
    """


    ###################
    # Private helpers #
    ###################

    def _open_create_wizard(self):
        self.app.root.find("New", "push button").click()
        return self.app.root.find("New VM", "frame")

    def forward(self, newvm, check=True):
        pagenumlabel = newvm.find("pagenum-label")
        oldtext = pagenumlabel.text
        newvm.find_fuzzy("Forward", "button").click()
        if check:
            lib.utils.check(lambda: pagenumlabel.text != oldtext)

    def back(self, newvm, check=True):
        pagenumlabel = newvm.find("pagenum-label")
        oldtext = pagenumlabel.text
        newvm.find_fuzzy("Back", "button").click()
        if check:
            lib.utils.check(lambda: pagenumlabel.text != oldtext)


    ##############
    # Test cases #
    ##############

    def testNewVMMultiConnection(self):
        """
        Test the wizard's multiple connection handling
        """
        manager = self.app.topwin

        def _add_conn(uri):
            manager.find("File", "menu").click()
            manager.find("Add Connection...", "menu item").click()
            win = self.app.root.find_fuzzy("Add Connection", "dialog")
            win.combo_select("Hypervisor", "Custom URI")
            win.find("uri-entry", "text").set_text(uri)
            win.find("Connect", "push button").click()

        def _stop_conn(txt):
            c = manager.find(txt, "table cell")
            c.click()
            c.click(button=3)
            self.app.root.find("conn-disconnect", "menu item").click()
            lib.utils.check(lambda: "Not Connected" in c.text)

        # Check the dialog shows 'no connection' error
        _stop_conn("test testdriver.xml")
        newvm = self._open_create_wizard()
        newvm.find_fuzzy("No active connection to install on")
        newvm.keyCombo("<alt>F4")
        lib.utils.check(lambda: manager.active)

        # Check the xen PV only startup warning
        def _capsopt(fname):
            capsdir = tests.utils.DATADIR + "/capabilities/"
            return ",caps=" + capsdir + fname

        # Test empty qemu connection
        _add_conn(tests.utils.URIs.kvm + _capsopt("test-empty.xml"))
        newvm = self._open_create_wizard()
        newvm.find(".*No hypervisor options were found.*KVM kernel modules.*")
        newvm.click_title()
        newvm.keyCombo("<alt>F4")
        _stop_conn("QEMU/KVM")

        _add_conn(tests.utils.URIs.kvm_session +
                _capsopt("test-qemu-no-kvm.xml"))
        newvm = self._open_create_wizard()
        newvm.find(".*KVM is not available.*")
        newvm.click_title()
        newvm.keyCombo("<alt>F4")

        _add_conn(tests.utils.URIs.lxc)
        _add_conn(tests.utils.URIs.test_full)
        _add_conn(tests.utils.URIs.test_default)

        # Open the new VM wizard, select a connection
        newvm = self._open_create_wizard()
        newvm.combo_select("create-conn", ".*testdriver.xml.*")
        self.forward(newvm)

        # Verify media-combo contents for testdriver.xml
        cdrom = newvm.find("media-combo")
        entry = newvm.find("media-entry")
        cdrom.click_combo_entry()
        cdrom.find_fuzzy(r"\(/dev/sr1\)")
        entry.click()
        # Launch this so we can verify storage browser is reset too
        newvm.find_fuzzy("install-iso-browse", "button").click()
        self.app.select_storagebrowser_volume("default-pool", "iso-vol")
        newvm.find_fuzzy("Automatically detect", "check").click()
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)

        # Back up, select test:///default, verify media-combo is now empty
        newvm.click_title()
        newvm.keyCombo("<alt>F4")
        newvm = self._open_create_wizard()
        newvm.combo_select("create-conn", ".*test default.*")
        self.forward(newvm)
        cdrom.click_combo_entry()
        lib.utils.check(lambda: "/dev/sr1" not in cdrom.fmt_nodes())
        newvm.find_fuzzy("install-iso-browse", "button").click()
        browsewin = self.app.root.find("vmm-storage-browser")
        lib.utils.check(lambda: "disk-pool" not in browsewin.fmt_nodes())

    def testNewVMManualDefault(self):
        """
        Click through the New VM wizard with default values + manual, then
        delete the VM
        """
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Manual", "radio").click()
        self.forward(newvm)
        osentry = newvm.find("oslist-entry")
        lib.utils.check(lambda: not osentry.text)

        # Make sure we throw an error if no OS selected
        self.forward(newvm, check=False)
        self.app.click_alert_button("You must select", "OK")

        # Test activating the osentry to grab the popover selection
        osentry.click()
        osentry.typeText("generic")
        newvm.find("oslist-popover")
        osentry.click()
        self.app.rawinput.pressKey("Enter")
        lib.utils.check(lambda: osentry.text == "Generic OS")

        # Verify back+forward still keeps Generic selected
        self.app.sleep(.5)
        self.back(newvm)
        self.app.sleep(.5)
        self.forward(newvm)
        self.app.sleep(.5)
        lib.utils.check(lambda: "Generic" in osentry.text)
        osentry.check_onscreen()

        # The sleeps shouldn't be required, but this test continues to be
        # flakey, so this is an attempt to fix it.
        self.forward(newvm)
        self.app.sleep(.5)
        self.forward(newvm)
        self.app.sleep(.5)
        self.forward(newvm)
        self.app.sleep(.5)


        # Empty triggers a specific codepath
        newvm.find_fuzzy("Name", "text").set_text("")
        # Name collision failure
        newvm.find_fuzzy("Name", "text").set_text("test-many-devices")
        newvm.find_fuzzy("Finish", "button").click()
        self.app.click_alert_button("in use", "OK")
        newvm.find_fuzzy("Name", "text").set_text("vm1")
        newvm.find_fuzzy("Finish", "button").click()

        # Delete it from the VM window
        vmwindow = self.app.root.find_fuzzy("vm1 on", "frame")
        vmwindow.find("Virtual Machine", "menu").click()
        vmwindow.find("Delete", "menu item").click()

        delete = self.app.root.find_fuzzy("Delete", "frame")
        delete.find_fuzzy("Delete", "button").click()
        self.app.click_alert_button("Are you sure", "Yes")

        # Verify delete dialog and VM dialog are now gone
        lib.utils.check(lambda: vmwindow.showing is False)

    def testNewVMStorage(self):
        """
        Test some storage specific paths
        """
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Manual", "radio").click()
        self.forward(newvm)
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)

        # Trigger size validation failure
        sizetext = newvm.find(None, "spin button", "GiB")
        sizetext.set_text("10000000")
        self.forward(newvm, check=False)
        self.app.click_alert_button("Storage parameter error", "OK")
        sizetext.set_text("1")

        # Use the storage browser to select a local file
        storagetext = newvm.find("storage-entry")
        newvm.find_fuzzy("Select or create", "radio").click()
        newvm.find("storage-browse").click()
        browse = self.app.root.find("vmm-storage-browser")
        browse.find("Browse Local", "push button").click()
        chooser = self.app.root.find(
                "Locate existing storage", "file chooser")
        fname = "COPYING"
        chooser.find(fname, "table cell").click()
        chooser.find("Open", "push button").click()
        lib.utils.check(lambda: newvm.active)
        lib.utils.check(lambda: "COPYING" in storagetext.text)

        # Start the install
        self.forward(newvm)
        newvm.find("Finish", "push button").click()
        self.app.root.find_fuzzy("vm1 on", "frame")
        lib.utils.check(lambda: not newvm.showing)


    def testNewVMCDROMRegular(self):
        """
        Create a new CDROM VM, choosing distro win8, and do some basic
        'Customize before install' before exiting
        """
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Local install media", "radio").click()
        self.forward(newvm)

        # check prepopulated cdrom media
        combo = newvm.find("media-combo")
        combo.click_combo_entry()
        combo.find(r"No media detected \(/dev/sr1\)")
        combo.find(r"Fedora12_media \(/dev/sr0\)").click()

        # Catch validation error
        entry = newvm.find("media-entry")
        entry.click()
        entry.set_text("")
        self.forward(newvm, check=False)
        self.app.click_alert_button("media selection is required", "OK")

        # test entry activation too
        entry.click()
        entry.set_text("/dev/sr0")
        self.app.rawinput.pressKey("Enter")

        # Select a fake iso
        newvm.find_fuzzy("install-iso-browse", "button").click()
        self.app.select_storagebrowser_volume("default-pool", "iso-vol")

        osentry = newvm.find("oslist-entry")
        lib.utils.check(lambda: osentry.text == "None detected")

        # Change distro to win8
        newvm.find_fuzzy("Automatically detect", "check").click()
        osentry.click()
        osentry.set_text("windows 8")
        popover = newvm.find("oslist-popover")
        popover.check_onscreen()
        # Verify Escape resets the text entry
        self.app.rawinput.pressKey("Escape")
        popover.check_not_onscreen()
        lib.utils.check(lambda: osentry.text == "")
        # Re-enter text
        osentry.set_text("windows 8")
        popover.check_onscreen()
        popover.find_fuzzy("include-eol").click()
        popover.find_fuzzy(r"\(win8\)").click()
        popover.check_not_onscreen()
        foundtext = osentry.text
        # Start typing again, and exit, make sure it resets to previous entry
        osentry.click()
        osentry.set_text("foo")
        popover.check_onscreen()
        self.app.rawinput.pressKey("Escape")
        popover.check_not_onscreen()
        lib.utils.check(lambda: osentry.text == foundtext)
        self.forward(newvm)

        # Verify that CPU values are non-default
        cpus = newvm.find("cpus", "spin button")
        lib.utils.check(lambda: int(cpus.text) > 1, timeout=5)
        self.forward(newvm)
        self.forward(newvm)

        # Select customize wizard
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()

        # Verify CDROM media is inserted
        vmwindow = self.app.root.find_fuzzy("win8 on", "frame")
        vmwindow.find_fuzzy("IDE CDROM", "table cell").click()
        mediaent = vmwindow.find("media-entry")
        lib.utils.check(lambda: "iso-vol" in mediaent.text)

        # Change boot autostart
        vmwindow.find_fuzzy("Boot", "table cell").click()
        vmwindow.find_fuzzy("Start virtual machine", "check").click()
        vmwindow.find_fuzzy("config-apply").click()

        # Change to 'copy host CPU'
        vmwindow.find_fuzzy("CPUs", "table cell").click()
        vmwindow.find_fuzzy("Copy host", "check").click()
        vmwindow.find_fuzzy("config-apply").click()

        # Add a default disk
        vmwindow.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        addhw.find("Finish", "push button").click()
        lib.utils.check(lambda: vmwindow.active)

        # Select the new disk, change the bus to USB
        vmwindow.find_fuzzy("IDE Disk 2", "table cell").click()
        appl = vmwindow.find("config-apply", "push button")
        hwlist = vmwindow.find("hw-list")
        tab = vmwindow.find("disk-tab")
        tab.find("Disk bus:", "text").set_text("usb")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        # Device is now 'USB Disk 1'
        c = hwlist.find("USB Disk 1", "table cell")
        lib.utils.check(lambda: c.state_selected)
        tab.find("Advanced options", "toggle button").click_expander()
        tab.find("Removable:", "check box").click()
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)

        # Change NIC mac
        vmwindow.find_fuzzy("NIC", "table cell").click()
        tab = vmwindow.find("network-tab")
        tab.find("mac-entry", "text").set_text("00:11:00:11:00:11")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)

        # Start the install, close via the VM window
        vmwindow.find_fuzzy("Begin Installation", "button").click()
        lib.utils.check(lambda: newvm.showing is False)
        vmwindow = self.app.root.find_fuzzy("win8 on", "frame")
        vmwindow.find_fuzzy("File", "menu").click()
        vmwindow.find_fuzzy("Quit", "menu item").click()
        lib.utils.check(lambda: self.app.is_running())

    def testNewVMCDROMDetect(self):
        """
        CDROM with detection
        """
        cdrom = tests.utils.DATADIR + "/fakemedia/fake-win7.iso"
        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Local install media", "radio").click()
        self.forward(newvm)
        newvm.find("media-entry").click()
        newvm.find("media-entry").set_text(cdrom)
        # Use forward to trigger detection
        self.forward(newvm)
        self.forward(newvm)
        self.forward(newvm)
        newvm.find("Finish", "push button").click()
        self.app.root.find_fuzzy("win7 on", "frame")
        lib.utils.check(lambda: not newvm.showing)


    def testNewVMURL(self):
        """
        New VM with URL and distro detection, plus having fun with
        the storage browser and network selection.
        """
        self.app.uri = tests.utils.URIs.kvm
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Network Install", "radio").click()
        self.forward(newvm)
        osentry = newvm.find("oslist-entry")
        lib.utils.check(lambda: osentry.text.startswith("Waiting"))

        newvm.find("install-url-entry").set_text("")
        self.forward(newvm, check=False)
        self.app.click_alert_button("tree is required", "OK")

        url = "https://archives.fedoraproject.org/pub/archive/fedora/linux/releases/10/Fedora/x86_64/os/"
        oslabel = "Fedora 10"
        newvm.find("install-url-entry").set_text(url)
        newvm.find("install-url-entry").click()
        self.app.rawinput.pressKey("Enter")
        newvm.find("install-urlopts-expander").click_expander()
        newvm.find("install-urlopts-entry").set_text("foo=bar")

        lib.utils.check(lambda: osentry.text == oslabel, timeout=10)

        # Move forward, then back, ensure OS stays selected
        self.forward(newvm)
        self.back(newvm)
        lib.utils.check(lambda: osentry.text == oslabel)

        # Disable autodetect, make sure OS still selected
        newvm.find_fuzzy("Automatically detect", "check").click()
        lib.utils.check(lambda: osentry.text == oslabel)
        self.forward(newvm)
        self.back(newvm)

        # Ensure the EOL field was selected
        osentry.click()
        self.app.rawinput.pressKey("Down")
        popover = newvm.find("oslist-popover")
        lib.utils.check(lambda: popover.showing)
        includeeol = newvm.find("include-eol", "check")
        lib.utils.check(lambda: includeeol.isChecked)

        # Re-enable autodetect, check for detecting text
        newvm.find_fuzzy("Automatically detect", "check").click()
        lib.utils.check(lambda: not popover.showing)
        lib.utils.check(lambda: "Detecting" in osentry.text)
        lib.utils.check(lambda: osentry.text == oslabel, timeout=10)

        # Progress the install
        self.forward(newvm)
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        progress = self.app.root.find_fuzzy(
            "Creating Virtual Machine", "frame")
        lib.utils.check(lambda: not progress.showing, timeout=120)

        details = self.app.root.find_fuzzy("fedora10 on", "frame")
        lib.utils.check(lambda: not newvm.showing)

        # Re-run the newvm wizard, check that URL was remembered
        details.keyCombo("<alt>F4")
        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Network Install", "radio").click()
        self.forward(newvm)
        urlcombo = newvm.find("install-url-combo")
        lib.utils.check(lambda: urlcombo.showing)
        lib.utils.check(lambda: url in urlcombo.fmt_nodes())

    def testNewKVMQ35Tweaks(self):
        """
        New VM that should default to Q35, but tweak things a bunch
        """
        self.app.uri = tests.utils.URIs.kvm
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        self.forward(newvm)
        newvm.find("import-entry").set_text("/dev/default-pool/testvol1.img")
        newvm.find("oslist-entry").set_text("fedora30")
        popover = newvm.find("oslist-popover")
        popover.find("include-eol").click()
        popover.find_fuzzy("Fedora 30").click()
        self.forward(newvm)
        self.forward(newvm)

        # Select customize wizard, we will use this VM to
        # hit some code paths elsewhere
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()
        vmname = "fedora30"
        details = self.app.root.find_fuzzy("%s on" % vmname, "frame")
        appl = details.find("config-apply")

        # Tweak some Overview settings
        details.combo_check_default("Chipset:", "Q35")
        details.combo_check_default("Firmware:", "BIOS")

        # Switch i440FX and back
        details.combo_select("Chipset:", "i440FX")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        details.combo_select("Chipset:", "Q35")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        # Switch to UEFI, back to BIOS, back to UEFI
        details.combo_select("Firmware:", ".*x86_64.*")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        # Switch back to BIOS
        details.combo_select("Firmware:", "BIOS")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        # Switch back to UEFI
        details.combo_select("Firmware:", ".*x86_64.*")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)

        # Add another network device
        details.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        addhw.find("Network", "table cell").click()
        tab = addhw.find("network-tab", None)
        lib.utils.check(lambda: tab.showing)
        addhw.find("Finish", "push button").click()
        lib.utils.check(lambda: not addhw.active)
        lib.utils.check(lambda: details.active)

        # Finish
        details.find_fuzzy("Begin Installation", "button").click()
        lib.utils.check(lambda: details.dead)
        self.app.root.find_fuzzy("%s on" % vmname, "frame")

    def testNewKVMQ35UEFI(self):
        """
        New VM that should default to Q35, and set UEFI
        """
        self.app.uri = tests.utils.URIs.kvm
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        self.forward(newvm)
        newvm.find("import-entry").set_text("/dev/default-pool/testvol1.img")
        newvm.find("oslist-entry").set_text("fedora30")
        popover = newvm.find("oslist-popover")
        popover.find("include-eol").click()
        popover.find_fuzzy("Fedora 30").click()
        self.forward(newvm)
        self.forward(newvm)

        # Select customize wizard, we will use this VM to
        # hit some PPC64 code paths elsewhere
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()
        vmname = "fedora30"
        details = self.app.root.find_fuzzy("%s on" % vmname, "frame")

        # Change to UEFI
        details.combo_check_default("Chipset:", "Q35")
        details.combo_check_default("Firmware:", "BIOS")
        details.combo_select("Firmware:", ".*x86_64.*")
        details.find("config-apply").click()

        # Finish
        details.find_fuzzy("Begin Installation", "button").click()
        lib.utils.check(lambda: details.dead)
        self.app.root.find_fuzzy("%s on" % vmname, "frame")

    def testNewPPC64(self):
        """
        New PPC64 VM to test architecture selection
        """
        self.app.uri = tests.utils.URIs.kvm
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Architecture options", "toggle").click()
        newvm.combo_select("Architecture", ".*ppc64.*")
        newvm.combo_check_default("Machine Type", ".*pseries.*")

        newvm.find_fuzzy("Manual", "radio").click()
        self.forward(newvm)
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        # Disable storage, we add some via customize
        newvm.find_fuzzy("Enable storage", "check box").click()
        self.forward(newvm)

        # Select customize wizard, we will use this VM to
        # hit some PPC64 code paths elsewhere
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()
        details = self.app.root.find_fuzzy("vm-ppc64 on", "frame")

        tab = details.find("overview-tab")
        tab.combo_check_default("machine-combo", "pseries")
        tab.combo_select("machine-combo", "pseries-2.1")
        appl = details.find("config-apply")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)

        # Add a TPM SPAPR device
        details.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        addhw.find("TPM", "table cell").click()
        tab = addhw.find("tpm-tab", None)
        lib.utils.check(lambda: tab.showing)
        addhw.find("Finish", "push button").click()
        lib.utils.check(lambda: not addhw.active)
        lib.utils.check(lambda: details.active)

        # Add a SCSI disk which also adds virtio-scsi controller
        details.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        addhw.find("Storage", "table cell").click()
        tab = addhw.find("storage-tab", None)
        lib.utils.check(lambda: tab.showing)
        tab.combo_select("Bus type:", "SCSI")
        addhw.find("Finish", "push button").click()
        lib.utils.check(lambda: not addhw.active)
        lib.utils.check(lambda: details.active)

        # Finish
        details.find_fuzzy("Begin Installation", "button").click()
        lib.utils.check(lambda: details.dead)
        self.app.root.find_fuzzy("vm-ppc64 on", "frame")

    def testNewVMAArch64UEFI(self):
        """
        Test aarch64 UEFI usage
        """
        self.app.uri = tests.utils.URIs.kvm_aarch64
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Local install media", "radio").click()
        self.forward(newvm)

        newvm.find_fuzzy("Automatically detect", "check").click()
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        newvm.find("media-entry").set_text("/dev/default-pool/testvol1.img")
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Enable storage", "check box").click()
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("vm1 on", "frame")
        lib.utils.check(lambda: not newvm.showing)

    def testNewVMArmKernel(self):
        """
        New arm VM that requires kernel/initrd/dtb
        """
        self.app.uri = tests.utils.URIs.kvm_armv7l_nodomcaps
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Architecture options", "toggle").click_expander()
        newvm.find_fuzzy("Virt Type", "combo").click()
        KVM = newvm.find_fuzzy("KVM", "menu item")
        TCG = newvm.find_fuzzy("TCG", "menu item")
        lib.utils.check(lambda: KVM.focused)
        lib.utils.check(lambda: TCG.showing)
        self.app.rawinput.pressKey("Esc")

        # Validate some initial defaults
        local = newvm.find_fuzzy("Local", "radio")
        lib.utils.check(lambda: not local.sensitive)
        newvm.find_fuzzy("Machine Type", "combo").click()
        self.app.sleep(.2)
        newvm.find_fuzzy("canon", "menu item").click()
        newvm.find_fuzzy("Machine Type", "combo").click()
        self.app.sleep(.2)
        newvm.find("virt", "menu item").click()
        self.app.sleep(.5)
        importradio = newvm.find("Import", "radio")
        importradio.click()
        lib.utils.check(lambda: importradio.checked)
        self.forward(newvm)

        newvm.find("import-entry").set_text("/dev/default-pool/default-vol")
        # Make sure the info box shows up
        newvm.find("Kernel/initrd settings can be configured")
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm, check=False)

        # Disk collision box pops up, hit ok
        self.app.click_alert_button("in use", "Yes")

        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        lib.utils.check(lambda: not newvm.showing)
        self.app.root.find_fuzzy("vm1 on", "frame")


    def testNewVMContainerApp(self):
        """
        Simple LXC app install
        """
        self.app.uri = tests.utils.URIs.lxc

        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Application", "radio").click()
        self.forward(newvm)

        # Set custom init
        apptext = newvm.find_fuzzy(None, "text", "application path")
        apptext.set_text("")
        self.forward(newvm, check=False)
        self.app.click_alert_button("path is required", "OK")
        newvm.find("install-app-browse").click()
        self.app.select_storagebrowser_volume("default-pool", "aaa-unused.qcow2")
        lib.utils.check(lambda: "aaa-unused.qcow2" in apptext.text)

        self.forward(newvm)
        self.forward(newvm)
        # Trigger back, to ensure disk page skipping works
        self.back(newvm)
        self.back(newvm)
        self.forward(newvm)
        self.forward(newvm)

        # Select customize wizard, we will use this VM to hit specific
        # code paths
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()
        vmname = "container1"
        details = self.app.root.find_fuzzy("%s on" % vmname, "frame")

        # Tweak init values
        details.find("Boot Options", "table cell").click()
        tab = details.find("boot-tab")
        tab.find("Init path:", "text").set_text("")
        tab.find("Init args:", "text").set_text("some args")
        appl = details.find("config-apply")
        appl.click()
        self.app.click_alert_button("init path must be specified", "OK")
        lib.utils.check(lambda: appl.sensitive)
        tab.find("Init path:", "text").set_text("/some/path")
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)

        # Check that addhw container options are disabled
        details.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        addhw.find("PCI Host Device", "table cell").click()
        # Ensure the error label is showing
        label = addhw.find("Not supported for containers")
        label.check_onscreen()
        addhw.find("Cancel", "push button").click()
        lib.utils.check(lambda: not addhw.active)
        lib.utils.check(lambda: details.active)

        # Finish
        details.find_fuzzy("Begin Installation", "button").click()
        lib.utils.check(lambda: not newvm.showing)
        self.app.root.find_fuzzy("%s on" % vmname, "frame")

    def testNewVMCustomizeCancel(self):
        """
        Test cancelling out of the customize wizard
        """
        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Manual", "radio").click()
        self.forward(newvm)
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        self.forward(newvm)

        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()
        vmname = "vm1"
        details = self.app.root.find_fuzzy("%s on" % vmname, "frame")

        details.find("Cancel Installation", "push button").click()
        self.app.click_alert_button("abort the installation", "No")
        lib.utils.check(lambda: details.active)
        details.find("Cancel Installation", "push button").click()
        self.app.click_alert_button("abort the installation", "Yes")
        lib.utils.check(lambda: not details.active)
        lib.utils.check(lambda: not newvm.active)

    def testNewVMCustomizeMisc(self):
        """
        Some specific customize logic paths
        """
        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Manual", "radio").click()
        self.forward(newvm)
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        self.forward(newvm)

        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()
        vmname = "vm1"
        details = self.app.root.find_fuzzy("%s on" % vmname, "frame")

        # Test name change
        tab = details.find("overview-tab")
        nametext = tab.find("Name:", "text")
        nametext.set_text("foonewname")
        details.find("config-apply").click()
        self.app.root.find_fuzzy("foonewname", "frame")

        # Trigger XML failure to hit some codepaths
        nametext.set_text("")
        details.find("Begin Installation").click()
        self.app.click_alert_button("unapplied changes", "Yes")
        self.app.click_alert_button("name must be specified", "Close")
        lib.utils.check(lambda: details.showing)

        # Discard XML change and continue with install
        details.find("Begin Installation").click()
        self.app.click_alert_button("unapplied changes", "No")
        lib.utils.check(lambda: not details.showing)
        lib.utils.check(lambda: not newvm.showing)
        self.app.root.find_fuzzy("foonewname on", "frame")


    def testNewVMContainerTree(self):
        """
        Simple LXC tree install
        """
        self.app.uri = tests.utils.URIs.lxc

        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Operating system", "radio").click()
        self.forward(newvm)

        # Set directory path
        dirtext = newvm.find_fuzzy(None, "text", "root directory")
        dirtext.set_text("")
        self.forward(newvm, check=False)
        self.app.click_alert_button("path is required", "OK")

        newvm.find("install-oscontainer-browse").click()
        self.app.select_storagebrowser_volume("default-pool", "dir-vol")
        lib.utils.check(lambda: "dir-vol" in dirtext.text)

        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        lib.utils.check(lambda: not newvm.showing)
        self.app.root.find_fuzzy("container1 on", "frame")


    def testNewVMContainerVZ(self):
        """
        Virtuozzo container install
        """
        self.app.uri = tests.utils.URIs.vz

        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Container", "radio").click()
        newvm.find_fuzzy("Virtual machine", "radio").click()
        newvm.find_fuzzy("Container", "radio").click()
        self.forward(newvm)

        # Set directory path
        templatetext = newvm.find_fuzzy(None, "text", "container template")
        templatetext.set_text("")
        self.forward(newvm, check=False)
        self.app.click_alert_button("template name is required", "OK")
        templatetext.set_text("centos-6-x86_64")
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("container1 on", "frame")
        lib.utils.check(lambda: not newvm.showing)


    def testNewVMContainerBootstrap(self):
        self.app.uri = tests.utils.URIs.lxc
        try:
            import virtBootstrap  # pylint: disable=unused-import
        except ImportError:
            self.skipTest("virtBootstrap not installed")

        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Operating system", "radio").click()
        self.forward(newvm)

        # Set directory path
        import tempfile
        tmpdir = tempfile.TemporaryDirectory()
        newvm.find_fuzzy("Create OS directory", "check box").click()

        uritext = newvm.find("install-oscontainer-source-uri")
        uritext.text = ""
        self.forward(newvm, check=False)
        self.app.click_alert_button("Source URL is required", "OK")
        uritext.text = "docker://alpine"

        rootdir = newvm.find_fuzzy(None, "text", "root directory")
        lib.utils.check(lambda: ".local/share/libvirt" in rootdir.text)
        rootdir.set_text("/dev/null")
        self.forward(newvm, check=False)
        self.app.click_alert_button("not directory", "OK")
        rootdir.set_text("/root")
        self.forward(newvm, check=False)
        self.app.click_alert_button("No write permissions", "OK")
        rootdir.set_text("/tmp")
        self.forward(newvm, check=False)
        self.app.click_alert_button("directory is not empty", "No")
        rootdir.set_text(tmpdir.name)
        newvm.find("install-oscontainer-root-passwd").set_text("foobar")
        # Invalid credentials to trigger failure
        newvm.find("Credentials", "toggle button").click_expander()
        newvm.find("bootstrap-registry-user").set_text("foo")
        self.forward(newvm, check=None)
        self.app.click_alert_button("Please specify password", "OK")
        newvm.find("bootstrap-registry-password").set_text("bar")

        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()
        self.app.click_alert_button("virt-bootstrap did not complete", "Close")
        self.back(newvm)
        self.back(newvm)
        newvm.find("bootstrap-registry-user").set_text("")
        newvm.find("bootstrap-registry-password").set_text("")

        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()
        prog = self.app.root.find("Creating Virtual Machine", "frame")
        lib.utils.check(lambda: not prog.showing, timeout=30)

        lib.utils.check(lambda: not newvm.showing)
        self.app.root.find_fuzzy("container1 on", "frame")


    def testNewVMXenPV(self):
        """
        Test the create wizard with a fake xen PV install
        """
        self.app.uri = tests.utils.URIs.xen
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Architecture options", "toggle").click()
        newvm.combo_select("Xen Type", ".*paravirt.*")

        newvm.find_fuzzy("Import", "radio").click()
        self.forward(newvm)
        newvm.find("import-entry").set_text("/dev/default-pool/testvol1.img")
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("vm1 on", "frame")
        lib.utils.check(lambda: not newvm.showing)


    def testNewVMInstallFail(self):
        def dofail():
            _newvm = self._open_create_wizard()
            _newvm.find_fuzzy("Manual", "radio").click()
            self.forward(_newvm)
            _newvm.find("oslist-entry").set_text("generic")
            _newvm.find("oslist-popover").find_fuzzy("generic").click()
            self.forward(_newvm)
            self.forward(_newvm)
            self.forward(_newvm)

            # '/' in name will trigger libvirt error
            _newvm.find_fuzzy("Name", "text").set_text("test/bad")
            _newvm.find_fuzzy("Finish", "button").click()
            self.app.click_alert_button("Unable to complete install", "Close")
            return _newvm

        newvm = dofail()
        pathlabel = newvm.find(".*test/bad.qcow2")
        generatedpath = pathlabel.text
        # Changing VM name should not generate a new path
        newvm.find_fuzzy("Name", "text").set_text("test/badfoo")
        lib.utils.check(lambda: pathlabel.text == generatedpath)
        newvm.find_fuzzy("Finish", "button").click()
        self.app.click_alert_button("Unable to complete install", "Close")
        # Closing dialog should trigger storage cleanup path
        newvm.find_fuzzy("Cancel", "button").click()
        lib.utils.check(lambda: not newvm.visible)

        # Run again
        newvm = dofail()
        self.back(newvm)
        newvm.find_fuzzy("Select or create", "radio").click()

        newvm.find("storage-entry").set_text("/dev/default-pool/somenewvol1")
        self.forward(newvm)
        newvm.find_fuzzy("Name", "text").set_text("test-foo")
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("test-foo on", "frame")
        lib.utils.check(lambda: not newvm.showing)


    def testNewVMCustomizeXMLEdit(self):
        """
        Test new VM with raw XML editing via customize wizard
        """
        self.app.open(xmleditor_enabled=True)
        newvm = self._open_create_wizard()

        # Create a custom named VM, using CDROM media, and default storage
        vmname = "fooxmleditvm"
        newvm.find_fuzzy("Local install media", "radio").click()
        newvm.find_fuzzy("Forward", "button").click()
        nonexistpath = "/dev/foovmm-idontexist"
        existpath = "/dev/default-pool/testvol1.img"
        newvm.find("media-entry").set_text(nonexistpath)
        lib.utils.check(
                lambda: newvm.find("oslist-entry").text == "None detected")
        newvm.find_fuzzy("Automatically detect", "check").click()
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm, check=False)
        self.app.click_alert_button("Error setting installer", "OK")
        newvm.find("media-entry").set_text(existpath)
        self.forward(newvm)
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Name", "text").set_text(vmname)
        newvm.find_fuzzy("Finish", "button").click()
        win = self.app.root.find_fuzzy("%s on" % vmname, "frame")
        xmleditor = win.find("XML editor")
        finish = win.find("config-apply")

        # Change a device setting with the XML editor
        win.find_fuzzy("IDE Disk 1", "table cell").click()
        tab = win.find("disk-tab")
        win.find("XML", "page tab").click()
        # Change the disk path via the XML editor
        fname = vmname + ".qcow2"
        lib.utils.check(lambda: fname in xmleditor.text)
        newx = xmleditor.text.replace(fname, "default-vol")
        xmleditor.set_text(newx)
        appl = win.find("config-apply")
        # This is kindof a bug, changing path in XML editor in Customize
        # doesn't take effect for storage with creation parameters, but
        # it's a pain to fix.
        appl.click()
        lib.utils.check(lambda: not appl.sensitive)
        lib.utils.check(lambda: vmname in xmleditor.text)

        # Change a VM setting and verify it
        win.find_fuzzy("Boot", "table cell").click()
        tab = win.find("boot-tab")
        bootmenu = tab.find("Enable boot menu", "check box")
        lib.utils.check(lambda: not bootmenu.checked)
        win.find("XML", "page tab").click()
        newtext = xmleditor.text.replace(
                "<os>", "<os><bootmenu enable='yes'/>")
        xmleditor.set_text(newtext)
        finish.click()
        win.find("Details", "page tab").click()
        lib.utils.check(lambda: bootmenu.checked)

        # Change a device setting with the XML editor
        win.find_fuzzy("NIC", "table cell").click()
        tab = win.find("network-tab")
        win.find("XML", "page tab").click()
        newbrname = "BRFAKE"
        newx = xmleditor.text.replace("network", "bridge")
        newx = newx.replace('bridge="default"', "bridge='%s'" % newbrname)
        xmleditor.set_text(newx)
        finish.click()

        # Finish install.
        win.find_fuzzy("Begin Installation", "button").click()
        lib.utils.check(lambda: win.dead)
        win = self.app.root.find_fuzzy("%s on" % vmname, "frame")
        win.find("Details", "radio button").click()

        # Verify VM change stuck
        win.find_fuzzy("Boot", "table cell").click()
        tab = win.find("boot-tab")
        bootmenu = tab.find("Enable boot menu", "check box")
        lib.utils.check(lambda: bootmenu.checked)

        # Verify device change stuck
        win.find_fuzzy("NIC", "table cell").click()
        tab = win.find("network-tab")
        devname = tab.find("Device name:", "text")
        lib.utils.check(lambda: devname.text == newbrname)

        # Verify install media is handled correctly after XML customize
        win.find_fuzzy("IDE CDROM 1", "table cell").click()
        tab = win.find("disk-tab")
        mediaent = tab.find("media-entry")
        lib.utils.check(lambda: mediaent.text == existpath)
        win.find("Shut Down", "push button").click()
        run = win.find("Run", "push button")
        lib.utils.check(lambda: run.sensitive)
        lib.utils.check(lambda: mediaent.text == "")

        # Verify default disk storage was actually created. This has some
        # special handling in domain.py
        tab.find("Browse", "push button").click()
        browser = self.app.root.find("vmm-storage-browser")
        browser.find("%s.qcow2" % vmname, "table cell")

    def testNewVMRemote(self):
        """
        Hit some is_remote code paths
        """
        self.app.uri = tests.utils.URIs.test_remote
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        self.forward(newvm)
        importtext = newvm.find("import-entry")

        # Click forward, hitting missing Import path error
        self.forward(newvm, check=False)
        self.app.click_alert_button("import is required", "OK")

        # Click forward, but Import path doesn't exist
        importtext.set_text("/dev/default-pool/idontexist")
        self.forward(newvm, check=False)
        self.app.click_alert_button("import path must point", "OK")
        importtext.set_text("/dev/default-pool/default-vol")

        # Click forward, hitting missing OS error
        self.forward(newvm, check=False)
        self.app.click_alert_button("select an OS", "OK")

        # Set OS
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()

        # Click forward, but Import path is in use, and exit
        self.forward(newvm, check=False)
        self.app.click_alert_button("in use", "No")

        # storagebrowser bits
        newvm.find("install-import-browse").click()
        browsewin = self.app.root.find("vmm-storage-browser")
        # Insensitive for remote connection
        browselocal = browsewin.find("Browse Local")
        lib.utils.check(lambda: browselocal.sensitive is False)
        # Close the browser and reopen
        browsewin.find("Cancel").click()
        lib.utils.check(lambda: not browsewin.active)
        # Reopen, select storage
        newvm.find("install-import-browse").click()
        self.app.select_storagebrowser_volume("default-pool", "bochs-vol")
        lib.utils.check(
                lambda: importtext.text == "/dev/default-pool/bochs-vol")

        self.forward(newvm)
        self.forward(newvm)

        newvm.find_fuzzy("Finish", "button").click()
        self.app.root.find_fuzzy("vm1 on", "frame")
        lib.utils.check(lambda: not newvm.showing)

    def testNewVMSession(self):
        """
        Test with fake qemu session
        """
        self.app.uri = tests.utils.URIs.kvm_session
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        self.forward(newvm)
        newvm.find("import-entry").set_text("/dev/default-pool/testvol1.img")
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        newvm.combo_check_default("net-source", "Usermode")

        newvm.find_fuzzy("Finish", "button").click()
        self.app.root.find_fuzzy("vm1 on", "frame")
        lib.utils.check(lambda: not newvm.showing)

    def testNewVMEmptyConn(self):
        """
        Test with an empty connection
        """
        self.app.uri = tests.utils.URIs.test_empty
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        self.forward(newvm)
        newvm.find("import-entry").set_text(__file__)
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        newvm.combo_check_default("net-source", "Bridge")
        warnlabel = newvm.find_fuzzy("suitable default network", "label")
        warnlabel.check_onscreen()
        newvm.find("Device name:", "text").set_text("foobr0")

        # Select customize wizard, we will use this VM to hit specific
        # code paths
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()
        vmname = "vm1"
        details = self.app.root.find_fuzzy("%s on" % vmname, "frame")

        # Check that addhw hostdev drop down is empty
        details.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        addhw.find("USB Host Device", "table cell").click()
        tab = addhw.find("host-tab", None)
        lib.utils.check(lambda: tab.showing)
        cell = tab.find("No Devices", "table cell")
        lib.utils.check(lambda: cell.selected)
        addhw.find("Cancel", "push button").click()
        lib.utils.check(lambda: not addhw.active)
        lib.utils.check(lambda: details.active)

        # Finish
        details.find_fuzzy("Begin Installation", "button").click()
        lib.utils.check(lambda: details.dead)
        self.app.root.find_fuzzy("%s on" % vmname, "frame")

    def testNewVMInactiveNetwork(self):
        """
        Test with an inactive 'default' network
        """
        self.app.uri = tests.utils.URIs.test_default
        hostwin = self.app.open_host_window("Virtual Networks",
                conn_label="test default")
        cell = hostwin.find("default", "table cell")
        cell.click()
        hostwin.find("net-stop").click()
        hostwin.keyCombo("<ctrl>w")

        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        self.forward(newvm)
        newvm.find("import-entry").set_text(__file__)
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)

        newvm.find_fuzzy("Finish", "button").click()
        self.app.click_alert_button("start the network", "Yes")
        lib.utils.check(lambda: not newvm.showing)

    @unittest.mock.patch.dict('os.environ', {"VIRTINST_TEST_SUITE": "1"})
    def testNewVMDefaultBridge(self):
        """
        We actually set the unittest env variable here, which
        sets a fake bridge in interface.py
        """
        self.app.uri = tests.utils.URIs.test_empty
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        self.forward(newvm)
        newvm.find("import-entry").set_text(__file__)
        newvm.find("oslist-entry").set_text("generic")
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        newvm.find("Network selection", "toggle button").click_expander()
        newvm.combo_check_default("net-source", "Bridge")
        devname = newvm.find("Device name:", "text")
        lib.utils.check(lambda: devname.text == "testsuitebr0")

        newvm.find_fuzzy("Finish", "button").click()
        self.app.root.find_fuzzy("vm1 on", "frame")
        lib.utils.check(lambda: not newvm.showing)
