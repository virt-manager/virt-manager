# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest.mock

import tests
from tests.uitests import utils as uiutils



class NewVM(uiutils.UITestCase):
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
            uiutils.check(lambda: pagenumlabel.text != oldtext)

    def back(self, newvm, check=True):
        pagenumlabel = newvm.find("pagenum-label")
        oldtext = pagenumlabel.text
        newvm.find_fuzzy("Back", "button").click()
        if check:
            uiutils.check(lambda: pagenumlabel.text != oldtext)


    ##############
    # Test cases #
    ##############

    def testNewVMMultiConnection(self):
        """
        Test the wizard's multiple connection handling
        """
        # Add an extra connection for test:///default
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        win.combo_select("Hypervisor", "Custom URI")
        win.find("uri-entry", "text").text = "test:///default"
        win.find("Connect", "push button").click()

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

        # Back up, select test:///default, verify media-combo is now empty
        self.back(newvm)
        back = newvm.find_fuzzy("Back", "button")
        uiutils.check(lambda: not back.sensitive)
        newvm.combo_select("create-conn", ".*test default.*")
        self.forward(newvm)
        cdrom.click_combo_entry()
        uiutils.check(lambda: "/dev/sr1" not in cdrom.fmt_nodes())

    def testNewVMManualDefault(self):
        """
        Click through the New VM wizard with default values + manual, then
        delete the VM
        """
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Manual", "radio").click()
        self.forward(newvm)
        osentry = newvm.find("oslist-entry")
        uiutils.check(lambda: not osentry.text)

        # Make sure we throw an error if no OS selected
        self.forward(newvm, check=False)
        self._click_alert_button("You must select", "OK")

        # Test activating the osentry to grab the popover selection
        osentry.click()
        osentry.typeText("generic")
        newvm.find("oslist-popover")
        osentry.click()
        self.pressKey("Enter")
        uiutils.check(lambda: osentry.text == "Generic OS")

        # Verify back+forward still keeps Generic selected
        self.sleep(.5)
        self.back(newvm)
        self.sleep(.5)
        self.forward(newvm)
        self.sleep(.5)
        uiutils.check(lambda: "Generic" in osentry.text)
        uiutils.check(lambda: osentry.onscreen)

        # The sleeps shouldn't be required, but this test continues to be
        # flakey, so this is an attempt to fix it.
        self.forward(newvm)
        self.sleep(.5)
        self.forward(newvm)
        self.sleep(.5)
        self.forward(newvm)
        self.sleep(.5)
        newvm.find_fuzzy("Finish", "button").click()

        # Delete it from the VM window
        vmwindow = self.app.root.find_fuzzy("vm1 on", "frame")
        vmwindow.find("Virtual Machine", "menu").click()
        vmwindow.find("Delete", "menu item").click()

        delete = self.app.root.find_fuzzy("Delete", "frame")
        delete.find_fuzzy("Delete", "button").click()
        self._click_alert_button("Are you sure", "Yes")

        # Verify delete dialog and VM dialog are now gone
        uiutils.check(lambda: vmwindow.showing is False)


    def testNewVMCDROM(self):
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
        # test entry activation too
        entry = newvm.find("media-entry")
        entry.click()
        entry.text = "/dev/sr0"
        self.pressKey("Enter")

        # Select a fake iso
        newvm.find_fuzzy("install-iso-browse", "button").click()
        self._select_storagebrowser_volume("default-pool", "iso-vol")

        osentry = newvm.find("oslist-entry")
        uiutils.check(lambda: osentry.text == "None detected")

        # Change distro to win8
        newvm.find_fuzzy("Automatically detect", "check").click()
        osentry.click()
        osentry.text = "windows 8"
        popover = newvm.find("oslist-popover")
        uiutils.check(lambda: popover.onscreen)
        # Verify Escape resets the text entry
        self.pressKey("Escape")
        uiutils.check(lambda: not popover.onscreen)
        uiutils.check(lambda: osentry.text == "")
        # Re-enter text
        osentry.text = "windows 8"
        uiutils.check(lambda: popover.onscreen)
        popover.find_fuzzy("include-eol").click()
        popover.find_fuzzy(r"\(win8\)").click()
        uiutils.check(lambda: not popover.onscreen)
        foundtext = osentry.text
        # Start typing again, and exit, make sure it resets to previous entry
        osentry.click()
        osentry.text = "foo"
        uiutils.check(lambda: popover.onscreen)
        self.pressKey("Escape")
        uiutils.check(lambda: not popover.onscreen)
        uiutils.check(lambda: osentry.text == foundtext)
        self.forward(newvm)

        # Verify that CPU values are non-default
        cpus = newvm.find("cpus", "spin button")
        uiutils.check(lambda: int(cpus.text) > 1, timeout=5)
        self.forward(newvm)
        self.forward(newvm)

        # Select customize wizard
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()

        # Verify CDROM media is inserted
        vmwindow = self.app.root.find_fuzzy("win8 on", "frame")
        vmwindow.find_fuzzy("IDE CDROM", "table cell").click()
        mediaent = vmwindow.find("media-entry")
        uiutils.check(lambda: "iso-vol" in mediaent.text)

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
        uiutils.check(lambda: vmwindow.active)

        # Select the new disk, change the bus to USB
        vmwindow.find_fuzzy("IDE Disk 2", "table cell").click()
        appl = vmwindow.find("config-apply", "push button")
        hwlist = vmwindow.find("hw-list")
        tab = vmwindow.find("disk-tab")
        tab.find("Disk bus:", "text").text = "usb"
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        # Device is now 'USB Disk 1'
        c = hwlist.find("USB Disk 1", "table cell")
        uiutils.check(lambda: c.state_selected)
        tab.find("Removable:", "check box").click()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)

        # Start the install, close via the VM window
        vmwindow.find_fuzzy("Begin Installation", "button").click()
        uiutils.check(lambda: newvm.showing is False)
        vmwindow = self.app.root.find_fuzzy("win8 on", "frame")
        vmwindow.find_fuzzy("File", "menu").click()
        vmwindow.find_fuzzy("Quit", "menu item").click()
        uiutils.check(lambda: self.app.is_running())


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
        uiutils.check(lambda: osentry.text.startswith("Waiting"))

        url = "https://archives.fedoraproject.org/pub/archive/fedora/linux/releases/10/Fedora/x86_64/os/"
        oslabel = "Fedora 10"
        newvm.find("install-url-entry").text = url
        newvm.find("install-urlopts-expander").click_expander()
        newvm.find("install-urlopts-entry").text = "foo=bar"

        uiutils.check(lambda: osentry.text == oslabel, timeout=10)

        # Move forward, then back, ensure OS stays selected
        self.forward(newvm)
        self.back(newvm)
        uiutils.check(lambda: osentry.text == oslabel)

        # Disable autodetect, make sure OS still selected
        newvm.find_fuzzy("Automatically detect", "check").click()
        uiutils.check(lambda: osentry.text == oslabel)
        self.forward(newvm)
        self.back(newvm)

        # Ensure the EOL field was selected
        osentry.click()
        self.pressKey("Down")
        popover = newvm.find("oslist-popover")
        uiutils.check(lambda: popover.showing)
        includeeol = newvm.find("include-eol", "check")
        uiutils.check(lambda: includeeol.isChecked)

        # Re-enable autodetect, check for detecting text
        newvm.find_fuzzy("Automatically detect", "check").click()
        uiutils.check(lambda: not popover.showing)
        uiutils.check(lambda: "Detecting" in osentry.text)
        uiutils.check(lambda: osentry.text == oslabel, timeout=10)

        # Progress the install
        self.forward(newvm)
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        progress = self.app.root.find_fuzzy(
            "Creating Virtual Machine", "frame")
        uiutils.check(lambda: not progress.showing, timeout=120)

        self.app.root.find_fuzzy("fedora10 on", "frame")
        uiutils.check(lambda: not newvm.showing)


    def testNewPPC64(self):
        """
        New PPC64 VM to test architecture selection
        """
        self.app.uri = tests.utils.URIs.kvm
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Architecture options", "toggle").click()
        newvm.combo_select("Architecture", ".*ppc64.*")
        newvm.combo_check_default("Machine Type", ".*pseries.*")

        newvm.find_fuzzy("Import", "radio").click()
        newvm.find_fuzzy(None,
            "text", "existing storage").text = "/dev/default-pool/testvol1.img"
        self.forward(newvm)
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm, check=False)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("vm-ppc64 on", "frame")
        uiutils.check(lambda: not newvm.showing)

    def testNewVMAArch64UEFI(self):
        """
        Test aarch64 UEFI usage
        """
        self.app.uri = tests.utils.URIs.kvm_aarch64
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Local install media", "radio").click()
        self.forward(newvm)

        newvm.find_fuzzy("Automatically detect", "check").click()
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        newvm.find("media-entry").text = "/dev/default-pool/testvol1.img"
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Enable storage", "check box").click()
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("vm1 on", "frame")
        uiutils.check(lambda: not newvm.showing)

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
        uiutils.check(lambda: KVM.focused)
        uiutils.check(lambda: TCG.showing)
        self.pressKey("Esc")

        # Validate some initial defaults
        local = newvm.find_fuzzy("Local", "radio")
        uiutils.check(lambda: not local.sensitive)
        newvm.find_fuzzy("Machine Type", "combo").click()
        self.sleep(.2)
        newvm.find_fuzzy("canon", "menu item").click()
        newvm.find_fuzzy("Machine Type", "combo").click()
        self.sleep(.2)
        newvm.find("virt", "menu item").click()
        self.sleep(.5)
        importradio = newvm.find("Import", "radio")
        importradio.click()
        uiutils.check(lambda: importradio.checked)
        self.forward(newvm)

        # Set the import media details
        importentry = newvm.find_fuzzy(None, "text", "existing storage")
        # For some reason 'Import' doesn't take effect sometimes
        # And we end up in 'Manual' install mode, this will
        # make it explicit when it fails
        uiutils.check(lambda: importentry.onscreen)

        importentry.text = "/dev/default-pool/default-vol"
        # Make sure the info box shows up
        newvm.find("Kernel/initrd settings can be configured")
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm, check=False)

        # Disk collision box pops up, hit ok
        self._click_alert_button("in use", "Yes")

        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        uiutils.check(lambda: not newvm.showing)
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
        apptext.text = ""
        self.forward(newvm, check=False)
        self._click_alert_button("path is required", "OK")
        newvm.find("install-app-browse").click()
        self._select_storagebrowser_volume("default-pool", "aaa-unused.qcow2")
        uiutils.check(lambda: "aaa-unused.qcow2" in apptext.text)

        self.forward(newvm)
        self.forward(newvm)
        # Trigger back, to ensure disk page skipping works
        self.back(newvm)
        self.back(newvm)
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        uiutils.check(lambda: not newvm.showing)
        self.app.root.find_fuzzy("container1 on", "frame")


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
        dirtext.text = ""
        self.forward(newvm, check=False)
        self._click_alert_button("path is required", "OK")

        newvm.find("install-oscontainer-browse").click()
        self._select_storagebrowser_volume("default-pool", "dir-vol")
        uiutils.check(lambda: "dir-vol" in dirtext.text)

        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        uiutils.check(lambda: not newvm.showing)
        self.app.root.find_fuzzy("container1 on", "frame")


    def testNewVMContainerVZ(self):
        """
        Virtuozzo container install
        """
        self.app.uri = tests.utils.URIs.vz

        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Container", "radio").click()
        self.forward(newvm)

        # Set directory path
        newvm.find_fuzzy(None,
            "text", "container template").text = "centos-6-x86_64"
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("container1 on", "frame")
        uiutils.check(lambda: not newvm.showing)


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
        rootdir = newvm.find_fuzzy(None, "text", "root directory")
        uiutils.check(lambda: ".local/share/libvirt" in rootdir.text)
        rootdir.text = tmpdir.name
        newvm.find("install-oscontainer-source-uri").text = "docker://alpine"
        newvm.find("install-oscontainer-root-passwd").text = "foobar"
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()
        prog = self.app.root.find("Creating Virtual Machine", "frame")
        uiutils.check(lambda: not prog.showing, timeout=30)

        uiutils.check(lambda: not newvm.showing)
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
        newvm.find_fuzzy(None,
            "text", "existing storage").text = "/dev/default-pool/testvol1.img"
        self.forward(newvm)
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("vm1 on", "frame")
        uiutils.check(lambda: not newvm.showing)


    def testNewVMInstallFail(self):
        def dofail():
            _newvm = self._open_create_wizard()
            _newvm.find_fuzzy("Manual", "radio").click()
            self.forward(_newvm)
            _newvm.find("oslist-entry").text = "generic"
            _newvm.find("oslist-popover").find_fuzzy("generic").click()
            self.forward(_newvm)
            self.forward(_newvm)
            self.forward(_newvm)

            # '/' in name will trigger libvirt error
            _newvm.find_fuzzy("Name", "text").text = "test/bad"
            _newvm.find_fuzzy("Finish", "button").click()
            self._click_alert_button("Unable to complete install", "Close")
            return _newvm

        newvm = dofail()

        # Closing dialog should trigger storage cleanup path
        newvm.find_fuzzy("Cancel", "button").click()
        uiutils.check(lambda: not newvm.visible)

        # Run again
        newvm = dofail()
        self.back(newvm)
        newvm.find_fuzzy("Select or create", "radio").click()
        newvm.find("storage-entry").text = "/dev/default-pool/somenewvol1"
        self.forward(newvm)
        newvm.find_fuzzy("Name", "text").text = "test-foo"
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("test-foo on", "frame")
        uiutils.check(lambda: not newvm.showing)


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
        newvm.find("media-entry").text = nonexistpath
        uiutils.check(
                lambda: newvm.find("oslist-entry").text == "None detected")
        newvm.find_fuzzy("Automatically detect", "check").click()
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm, check=False)
        self._click_alert_button("Error setting installer", "OK")
        newvm.find("media-entry").text = existpath
        self.forward(newvm)
        self.forward(newvm)
        self.forward(newvm)
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Name", "text").text = vmname
        newvm.find_fuzzy("Finish", "button").click()

        # Change a VM setting and verify it
        win = self.app.root.find_fuzzy("%s on" % vmname, "frame")
        xmleditor = win.find("XML editor")
        finish = win.find("config-apply")
        win.find_fuzzy("Boot", "table cell").click()
        tab = win.find("boot-tab")
        bootmenu = tab.find("Enable boot menu", "check box")
        uiutils.check(lambda: not bootmenu.checked)
        win.find("XML", "page tab").click()
        xmleditor.text = xmleditor.text.replace(
                "<os>", "<os><bootmenu enable='yes'/>")
        finish.click()
        win.find("Details", "page tab").click()
        uiutils.check(lambda: bootmenu.checked)

        # Change a device setting with the XML editor
        win.find_fuzzy("NIC", "table cell").click()
        tab = win.find("network-tab")
        win.find("XML", "page tab").click()
        newbrname = "BRFAKE"
        newx = xmleditor.text.replace("network", "bridge")
        newx = newx.replace('bridge="default"', "bridge='%s'" % newbrname)
        xmleditor.text = newx
        finish.click()

        # Finish install.
        win.find_fuzzy("Begin Installation", "button").click()
        uiutils.check(lambda: win.dead)
        win = self.app.root.find_fuzzy("%s on" % vmname, "frame")
        win.find("Details", "radio button").click()

        # Verify VM change stuck
        win.find_fuzzy("Boot", "table cell").click()
        tab = win.find("boot-tab")
        bootmenu = tab.find("Enable boot menu", "check box")
        uiutils.check(lambda: bootmenu.checked)

        # Verify device change stuck
        win.find_fuzzy("NIC", "table cell").click()
        tab = win.find("network-tab")
        devname = tab.find("Device name:", "text")
        uiutils.check(lambda: devname.text == newbrname)

        # Verify install media is handled correctly after XML customize
        win.find_fuzzy("IDE CDROM 1", "table cell").click()
        tab = win.find("disk-tab")
        mediaent = tab.find("media-entry")
        uiutils.check(lambda: mediaent.text == existpath)
        win.find("Shut Down", "push button").click()
        run = win.find("Run", "push button")
        uiutils.check(lambda: run.sensitive)
        uiutils.check(lambda: mediaent.text == "")

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
        importtext = newvm.find_fuzzy(None, "text", "existing storage")

        # Click forward, hitting missing OS error
        self.forward(newvm, check=False)
        self._click_alert_button("select an OS", "OK")

        # Set OS
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()

        # Click forward, hitting missing Import path error
        self.forward(newvm, check=False)
        self._click_alert_button("import is required", "OK")

        # Click forward, but Import path doesn't exist
        importtext.text = "/dev/default-pool/idontexist"
        self.forward(newvm, check=False)
        self._click_alert_button("import path must point", "OK")

        # Click forward, but Import path is in use, and exit
        importtext.text = "/dev/default-pool/default-vol"
        self.forward(newvm, check=False)
        self._click_alert_button("in use", "No")

        # storagebrowser bits
        newvm.find("install-import-browse").click()
        browsewin = self.app.root.find("vmm-storage-browser")
        # Insensitive for remote connection
        browselocal = browsewin.find("Browse Local")
        uiutils.check(lambda: browselocal.sensitive is False)
        # Close the browser and reopen
        browsewin.find("Cancel").click()
        uiutils.check(lambda: not browsewin.active)
        # Reopen, select storage
        newvm.find("install-import-browse").click()
        self._select_storagebrowser_volume("default-pool", "bochs-vol")
        uiutils.check(
                lambda: importtext.text == "/dev/default-pool/bochs-vol")

        self.forward(newvm)
        self.forward(newvm)

        newvm.find_fuzzy("Finish", "button").click()
        self.app.root.find_fuzzy("vm1 on", "frame")
        uiutils.check(lambda: not newvm.showing)

    def testNewVMSession(self):
        """
        Test with fake qemu session
        """
        self.app.uri = tests.utils.URIs.kvm_session
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        newvm.find_fuzzy(None,
            "text", "existing storage").text = "/dev/default-pool/testvol1.img"
        self.forward(newvm)
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        newvm.combo_check_default("net-source", "Usermode")

        newvm.find_fuzzy("Finish", "button").click()
        self.app.root.find_fuzzy("vm1 on", "frame")
        uiutils.check(lambda: not newvm.showing)

    def testNewVMEmptyConn(self):
        """
        Test with an empty connection
        """
        self.app.uri = tests.utils.URIs.test_empty
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        newvm.find_fuzzy(None,
            "text", "existing storage").text = __file__
        self.forward(newvm)
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        newvm.combo_check_default("net-source", "Bridge")
        warnlabel = newvm.find_fuzzy("suitable default network", "label")
        uiutils.check(lambda: warnlabel.onscreen)
        newvm.find("Device name:", "text").text = "foobr0"

        newvm.find_fuzzy("Finish", "button").click()
        self.app.root.find_fuzzy("vm1 on", "frame")
        uiutils.check(lambda: not newvm.showing)

    def testNewVMInactiveNetwork(self):
        """
        Test with an inactive 'default' network
        """
        self.app.uri = tests.utils.URIs.test_default
        hostwin = self._open_host_window("Virtual Networks",
                conn_label="test default")
        cell = hostwin.find("default", "table cell")
        cell.click()
        hostwin.find("net-stop").click()
        hostwin.keyCombo("<ctrl>w")

        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        newvm.find_fuzzy(None,
            "text", "existing storage").text = __file__
        self.forward(newvm)
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)

        newvm.find_fuzzy("Finish", "button").click()
        self._click_alert_button("start the network", "Yes")
        uiutils.check(lambda: not newvm.showing)

    @unittest.mock.patch.dict('os.environ', {"VIRTINST_TEST_SUITE": "1"})
    def testNewVMDefaultBridge(self):
        """
        We actually set the unittest env variable here, which
        sets a fake bridge in interface.py
        """
        self.app.uri = tests.utils.URIs.test_empty
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Import", "radio").click()
        newvm.find_fuzzy(None,
            "text", "existing storage").text = __file__
        self.forward(newvm)
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        self.forward(newvm)
        self.forward(newvm)
        newvm.find("Network selection", "toggle button").click_expander()
        newvm.combo_check_default("net-source", "Bridge")
        devname = newvm.find("Device name:", "text")
        uiutils.check(lambda: devname.text == "testsuitebr0")

        newvm.find_fuzzy("Finish", "button").click()
        self.app.root.find_fuzzy("vm1 on", "frame")
        uiutils.check(lambda: not newvm.showing)
