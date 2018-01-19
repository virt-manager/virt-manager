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
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Finish", "button").click()


    ##############
    # Test cases #
    ##############

    def testNewVMPXEDefault(self):
        """
        Click through the New VM wizard with default values + PXE, then
        delete the VM
        """
        newvm = self._open_create_wizard()

        # Create default PXE VM
        newvm.find_fuzzy("PXE", "radio").click()
        newvm.find_fuzzy("Forward", "button").click()
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

        # Select a fake iso
        newvm.find_fuzzy("Use ISO", "radio").click()
        newvm.find_fuzzy("install-iso-browse", "button").click()
        browser = self.app.root.find_fuzzy("Choose Storage", "frame")
        browser.find_fuzzy("default-pool", "table cell").click()
        browser.find_fuzzy("iso-vol", "table cell").click()
        browser.find_fuzzy("Choose Volume", "button").click()

        label = newvm.find_fuzzy("os-version-label", "label")
        uiutils.check_in_loop(lambda: browser.showing is False)
        uiutils.check_in_loop(lambda: label.text == "Unknown")

        # Change distro to win8
        newvm.find_fuzzy("Automatically detect", "check").click()
        version = newvm.find_fuzzy("install-os-version-entry", "text")
        self.assertEqual(version.text, "Generic")

        ostype = newvm.find_fuzzy("install-os-type", "combo")
        ostype.click()
        ostype.find_fuzzy("Show all", "menu item").click()
        newvm.find_fuzzy("install-os-type", "combo").click()
        newvm.find_fuzzy("Windows", "menu item").click()
        newvm.find_fuzzy("install-os-version-entry",
            "text").typeText("Microsoft Windows 8")
        newvm.find_fuzzy("install-os-version-entry", "text").click()
        newvm.find_fuzzy("Forward", "button").click()

        # Verify that CPU values are non-default
        cpus = newvm.find("cpus", "spin button")
        uiutils.check_in_loop(lambda: int(cpus.text) > 1, timeout=5)
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()

        # Select customize wizard
        newvm.find_fuzzy("Customize", "check").click()
        newvm.find_fuzzy("Finish", "button").click()

        # Change to 'copy host CPU'
        vmwindow = self.app.root.find_fuzzy("win8 on", "frame")
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
        self.app.uri = tests.utils.uri_kvm
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Network Install", "radio").click()
        newvm.find_fuzzy("Forward", "button").click()

        newvm.find("URL", "text").text = (
            "http://vault.centos.org/5.5/os/x86_64/")

        version = newvm.find("install-os-version-label")
        uiutils.check_in_loop(lambda: "Detecting" in version.text)
        uiutils.check_in_loop(
            lambda: version.text == "Red Hat Enterprise Linux 5.5",
            timeout=10)

        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Forward", "button").click()
        newvm.find_fuzzy("Finish", "button").click()

        progress = self.app.root.find_fuzzy(
            "Creating Virtual Machine", "frame")
        uiutils.check_in_loop(lambda: not progress.showing, timeout=120)

        self.app.root.find_fuzzy("rhel5.5 on", "frame")
        self.assertFalse(newvm.showing)


    def testNewPPC64(self):
        """
        New PPC64 VM to test architecture selection
        """
        self.app.uri = tests.utils.uri_kvm
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
        self.app.uri = tests.utils.uri_kvm_armv7l
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Architecture options", "toggle").click()
        newvm.find_fuzzy("Virt Type", "combo").click()
        KVM = newvm.find_fuzzy("KVM", "menu item")
        TCG = newvm.find_fuzzy("TCG", "menu item")
        self.assertTrue(KVM.focused)
        self.assertTrue(TCG.showing)
        newvm.find_fuzzy("Virt Type", "combo").click()

        # Validate some initial defaults
        self.assertFalse(
            newvm.find_fuzzy("PXE", "radio").sensitive)
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
        self.app.uri = tests.utils.uri_lxc

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
        self.app.uri = tests.utils.uri_lxc

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
        self.app.uri = tests.utils.uri_vz

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
        self.app.uri = tests.utils.uri_xen
        newvm = self._open_create_wizard()

        newvm.find_fuzzy("Architecture options", "toggle").click()
        newvm.find_fuzzy("Xen Type", "combo").click()
        newvm.find_fuzzy("paravirt", "menu item").click()

        self._do_simple_import(newvm)
