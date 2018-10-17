# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import time

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

    def _do_simple_import(self, newvm):
        # Create default PXE VM
        newvm.find_fuzzy("Import", "radio").click()
        newvm.find_fuzzy(None,
            "text", "existing storage").text = "/dev/default-pool/testvol1.img"
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Finish", "button").click()


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
        win.find_fuzzy("Hypervisor", "combo box").click()
        win.find_fuzzy("Custom URI", "menu item").click()
        win.find("uri-entry", "text").text = "test:///default"
        win.find("Connect", "push button").click()

        # Open the new VM wizard, select a connection
        newvm = self._open_create_wizard()
        combo = newvm.find("create-conn")
        combo.click()
        combo.find_fuzzy("testdriver.xml").click()
        newvm.find_fuzzy("Forward", "button").click()

        # Verify media-combo contents for testdriver.xml
        cdrom = newvm.find("media-combo")
        entry = newvm.find("media-entry")
        cdrom.click_combo_entry()
        cdrom.find_fuzzy(r"\(/dev/sr1\)")
        entry.click()

        # Back up, select test:///default, verify media-combo is now empty
        back = newvm.find_fuzzy("Back", "button")
        back.click()
        uiutils.check_in_loop(lambda: not back.sensitive)
        combo.click()
        combo.find_fuzzy("test default").click()
        newvm.find_fuzzy("Forward", "button").click()
        cdrom.click_combo_entry()
        self.assertTrue("/dev/sr1" not in cdrom.fmt_nodes())

    def testNewVMPXEDefault(self):
        """
        Click through the New VM wizard with default values + PXE, then
        delete the VM
        """
        newvm = self._open_create_wizard()

        # Create default PXE VM
        newvm.find_fuzzy("PXE", "radio").click()
        newvm.find_fuzzy("Forward", "button").click()
        osentry = newvm.find("oslist-entry")
        uiutils.check_in_loop(lambda: not osentry.text)

        # Make sure we throw an error if no OS selected
        newvm.find_fuzzy("Forward", "button").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find("You must select", "label")
        alert.find("OK", "push button").click()

        # Test activating the osentry to grab the popover selection
        osentry.click()
        osentry.typeText("generic")
        newvm.find("oslist-popover")
        osentry.click()
        self.pressKey("Enter")
        uiutils.check_in_loop(lambda: osentry.text == "Generic default")

        # Verify back+forward still keeps Generic selected
        newvm.find_fuzzy("Back", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        uiutils.check_in_loop(lambda: "Generic" in osentry.text)

        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Finish", "button").click()

        # Delete it from the VM window
        vmwindow = self.app.root.find_fuzzy("generic on", "frame")
        vmwindow.find("Virtual Machine", "menu").click()
        vmwindow.find("Delete", "menu item").click()

        delete = self.app.root.find_fuzzy("Delete", "frame")
        delete.find_fuzzy("Delete", "button").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Yes", "push button").click()

        # Verify delete dialog and VM dialog are now gone
        uiutils.check_in_loop(lambda: vmwindow.showing is False)


    def testNewVMCDROM(self):
        """
        Create a new CDROM VM, choosing distro win8, and do some basic
        'Customize before install' before exiting
        """
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Local install media", "radio").click()
        newvm.find_fuzzy("Forward", "button").click()

        # check prepopulated cdrom media
        combo = newvm.find("media-combo")
        combo.click_combo_entry()
        combo.find(r"No media detected \(/dev/sr1\)")
        combo.find(r"Fedora12_media \(/dev/sr0\)").click()

        # Select a fake iso
        newvm.find_fuzzy("install-iso-browse", "button").click()
        browser = self.app.root.find_fuzzy("Choose Storage", "frame")
        browser.find_fuzzy("default-pool", "table cell").click()
        browser.find_fuzzy("iso-vol", "table cell").click()
        browser.find_fuzzy("Choose Volume", "button").click()

        osentry = newvm.find("oslist-entry")
        uiutils.check_in_loop(lambda: browser.showing is False)
        uiutils.check_in_loop(lambda: osentry.text == "None detected")

        # Change distro to win8
        newvm.find_fuzzy("Automatically detect", "check").click()
        osentry.text = "windows 8"
        popover = newvm.find("oslist-popover")
        popover.find_fuzzy("include-eol").click()
        popover.find_fuzzy(r"\(win8\)").click()
        newvm.find_fuzzy("Forward", "button").click()

        # Verify that CPU values are non-default
        cpus = newvm.find("cpus", "spin button")
        uiutils.check_in_loop(lambda: int(cpus.text) > 1, timeout=5)
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()

        # Select customize wizard
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()

        # Verify CDROM media is inserted
        vmwindow = self.app.root.find_fuzzy("win8 on", "frame")
        vmwindow.find_fuzzy("IDE CDROM", "table cell").click()
        self.assertTrue("iso-vol" in vmwindow.find("media-entry").text)

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
        uiutils.check_in_loop(lambda: vmwindow.active)

        # Start the install, close via the VM window
        vmwindow.find_fuzzy("Begin Installation", "button").click()
        uiutils.check_in_loop(lambda: newvm.showing is False)
        vmwindow = self.app.root.find_fuzzy("win8 on", "frame")
        vmwindow.find_fuzzy("File", "menu").click()
        vmwindow.find_fuzzy("Quit", "menu item").click()
        uiutils.check_in_loop(lambda: self.app.is_running())


    def testNewVMURL(self):
        """
        New VM with URL and distro detection, plus having fun with
        the storage browser and network selection.
        """
        self.app.uri = tests.utils.URIs.kvm
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Network Install", "radio").click()
        newvm.find_fuzzy("Forward", "button").click()
        osentry = newvm.find("oslist-entry")
        uiutils.check_in_loop(lambda: osentry.text.startswith("Waiting"))

        url = "https://archives.fedoraproject.org/pub/archive/fedora/linux/releases/10/Fedora/x86_64/os/"
        oslabel = "Fedora 10"
        newvm.find("install-url-entry").text = url

        uiutils.check_in_loop(lambda: osentry.text == oslabel, timeout=10)

        # Move forward, then back, ensure OS stays selected
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Back", "button").click()
        uiutils.check_in_loop(lambda: osentry.text == oslabel)

        # Disable autodetect, make sure OS still selected
        newvm.find_fuzzy("Automatically detect", "check").click()
        uiutils.check_in_loop(lambda: osentry.text == oslabel)
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Back", "button").click()

        # Ensure the EOL field was selected
        osentry.click()
        self.pressKey("Down")
        popover = newvm.find("oslist-popover")
        uiutils.check_in_loop(lambda: popover.showing)
        self.assertTrue(newvm.find("include-eol", "check").isChecked)

        # Re-enable autodetect, check for detecting text
        newvm.find_fuzzy("Automatically detect", "check").click()
        uiutils.check_in_loop(lambda: not popover.showing)
        uiutils.check_in_loop(lambda: "Detecting" in osentry.text)
        uiutils.check_in_loop(lambda: osentry.text == oslabel, timeout=10)

        # Progress the install
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Finish", "button").click()

        progress = self.app.root.find_fuzzy(
            "Creating Virtual Machine", "frame")
        uiutils.check_in_loop(lambda: not progress.showing, timeout=120)

        self.app.root.find_fuzzy("fedora10 on", "frame")
        self.assertFalse(newvm.showing)


    def testNewPPC64(self):
        """
        New PPC64 VM to test architecture selection
        """
        self.app.uri = tests.utils.URIs.kvm
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Architecture options", "toggle").click()
        newvm.find_fuzzy("Architecture", "combo").click()
        newvm.find_fuzzy("ppc64", "menu item").click()
        newvm.find_fuzzy("pseries", "menu item")

        self._do_simple_import(newvm)

        self.app.root.find_fuzzy("generic-ppc64 on", "frame")
        self.assertFalse(newvm.showing)


    def testNewArmKernel(self):
        """
        New arm VM that requires kernel/initrd/dtb
        """
        self.app.uri = tests.utils.URIs.kvm_armv7l_nodomcaps
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Architecture options", "toggle").click_expander()
        newvm.find_fuzzy("Virt Type", "combo").click()
        KVM = newvm.find_fuzzy("KVM", "menu item")
        TCG = newvm.find_fuzzy("TCG", "menu item")
        self.assertTrue(KVM.focused)
        self.assertTrue(TCG.showing)

        # Validate some initial defaults
        newvm.find_fuzzy("Virt Type", "combo").click()
        self.assertFalse(newvm.find_fuzzy("PXE", "radio").sensitive)
        newvm.find_fuzzy("vexpress-a15", "menu item")
        newvm.find("virt", "menu item")
        newvm.find_fuzzy("Forward", "button").click()

        # Set the import media details
        newvm.find_fuzzy(None,
            "text", "existing storage").text = "/dev/default-pool/default-vol"
        newvm.find_fuzzy(None,
            "text", "Kernel path").text = "/tmp/kernel"
        newvm.find_fuzzy(None,
            "text", "Initrd").text = "/tmp/initrd"
        newvm.find_fuzzy(None,
            "text", "DTB").text = "/tmp/dtb"
        newvm.find_fuzzy(None,
            "text", "Kernel args").text = "console=ttyS0"
        newvm.find("oslist-entry").text = "generic"
        newvm.find("oslist-popover").find_fuzzy("generic").click()
        newvm.find_fuzzy("Forward", "button").click()

        # Disk collision box pops up, hit ok
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Yes", "push button").click()

        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Finish", "button").click()

        time.sleep(1)
        self.app.root.find_fuzzy("generic on", "frame")
        self.assertFalse(newvm.showing)


    def testNewVMContainerApp(self):
        """
        Simple LXC app install
        """
        self.app.uri = tests.utils.URIs.lxc

        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Application", "radio").click()
        newvm.find_fuzzy("Forward", "button").click()

        # Set custom init
        newvm.find_fuzzy(None,
            "text", "application path").text = "/sbin/init"
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Finish", "button").click()

        time.sleep(1)
        self.app.root.find_fuzzy("container1 on", "frame")
        self.assertFalse(newvm.showing)


    def testNewVMContainerTree(self):
        """
        Simple LXC tree install
        """
        self.app.uri = tests.utils.URIs.lxc

        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Operating system", "radio").click()
        newvm.find_fuzzy("Forward", "button").click()

        # Set directory path
        newvm.find_fuzzy(None,
            "text", "root directory").text = "/tmp"
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Finish", "button").click()

        time.sleep(1)
        self.app.root.find_fuzzy("container1 on", "frame")
        self.assertFalse(newvm.showing)


    def testNewVMContainerVZ(self):
        """
        Virtuozzo container install
        """
        self.app.uri = tests.utils.URIs.vz

        newvm = self._open_create_wizard()
        newvm.find_fuzzy("Container", "radio").click()
        newvm.find_fuzzy("Forward", "button").click()

        # Set directory path
        newvm.find_fuzzy(None,
            "text", "container template").text = "centos-6-x86_64"
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Finish", "button").click()

        self.app.root.find_fuzzy("container1 on", "frame")
        self.assertFalse(newvm.showing)


    def testNewXenPV(self):
        """
        Test the create wizard with a fake xen PV install
        """
        self.app.uri = tests.utils.URIs.xen
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Architecture options", "toggle").click()
        newvm.find_fuzzy("Xen Type", "combo").click()
        newvm.find_fuzzy("paravirt", "menu item").click()

        self._do_simple_import(newvm)
