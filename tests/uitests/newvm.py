import time
import unittest

import tests
from tests.uitests import utils as uiutils



class NewVM(unittest.TestCase):
    """
    UI tests for virt-manager's NewVM wizard
    """
    def setUp(self):
        self.app = uiutils.DogtailApp(tests.utils.uri_test)
    def tearDown(self):
        self.app.kill()


    ###################
    # Private helpers #
    ###################

    def _open_create_wizard(self):
        uiutils.find_pattern(self.app.root, "New", "push button").click()
        return uiutils.find_pattern(self.app.root, "New VM", "frame")

    def _do_simple_import(self, newvm):
        # Create default PXE VM
        uiutils.find_fuzzy(newvm, "Import", "radio").click()
        uiutils.find_fuzzy(newvm, None,
            "text", "existing storage").text = "/dev/default-pool/testvol1.img"
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Finish", "button").click()
        time.sleep(1)


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
        uiutils.find_fuzzy(newvm, "PXE", "radio").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Finish", "button").click()

        # Delete it from the VM window
        vmwindow = uiutils.find_fuzzy(self.app.root, "generic on", "frame")
        uiutils.find_pattern(vmwindow, "Virtual Machine", "menu").click()
        uiutils.find_pattern(vmwindow, "Delete", "menu item").click()

        delete = uiutils.find_fuzzy(self.app.root, "Delete", "frame")
        uiutils.find_fuzzy(delete, "Delete", "button").click()
        alert = uiutils.find_pattern(self.app.root, "Warning", "alert")
        uiutils.find_fuzzy(alert, "Yes", "push button").click()
        time.sleep(1)

        # Verify delete dialog and VM dialog are now gone
        self.assertFalse(vmwindow.showing)

        self.app.quit()


    def testNewVMCDROM(self):
        """
        Create a new CDROM VM, choosing distro win8, and do some basic
        'Customize before install' before exiting
        """
        newvm = self._open_create_wizard()

        uiutils.find_fuzzy(newvm, "Local install media", "radio").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()

        # Select a fake iso
        uiutils.find_fuzzy(newvm, "Use ISO", "radio").click()
        uiutils.find_fuzzy(newvm, "install-iso-browse", "button").click()
        browser = uiutils.find_fuzzy(self.app.root, "Choose Storage", "frame")
        uiutils.find_fuzzy(browser, "default-pool", "table cell").click()
        uiutils.find_fuzzy(browser, "iso-vol", "table cell").click()
        uiutils.find_fuzzy(browser, "Choose Volume", "button").click()
        time.sleep(1)

        self.assertFalse(browser.showing)
        self.assertEquals(
            uiutils.find_fuzzy(newvm, "os-version-label", "label").text,
            "Unknown")

        # Change distro to win8
        uiutils.find_fuzzy(newvm, "Automatically detect", "check").click()
        version = uiutils.find_fuzzy(newvm,
            "install-os-version-entry", "text")
        self.assertEquals(version.text, "Generic")

        ostype = uiutils.find_fuzzy(newvm, "install-os-type", "combo")
        ostype.click()
        uiutils.find_fuzzy(ostype, "Show all", "menu item").click()
        uiutils.find_fuzzy(newvm, "install-os-type", "combo").click()
        uiutils.find_fuzzy(newvm, "Windows", "menu item").click()
        uiutils.find_fuzzy(newvm, "install-os-version-entry",
            "text").typeText("Microsoft Windows 8")
        uiutils.find_fuzzy(newvm, "install-os-version-entry", "text").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()

        # Verify that CPU values are non-default
        cpus = uiutils.find_fuzzy(newvm, None, "spin button", "CPUs:")
        uiutils.check_in_loop(lambda: int(cpus.text) > 1, timeout=5)
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()

        # Select customize wizard
        uiutils.find_fuzzy(newvm, "Customize", "check").click()
        uiutils.find_fuzzy(newvm, "Finish", "button").click()

        # Change to 'copy host CPU'
        vmwindow = uiutils.find_fuzzy(self.app.root, "win8 on", "frame")
        uiutils.find_fuzzy(vmwindow, "CPUs", "table cell").click()
        uiutils.find_fuzzy(vmwindow, "Copy host", "check").click()
        uiutils.find_fuzzy(vmwindow, "config-apply").click()

        # Start the install, close via the VM window
        uiutils.find_fuzzy(vmwindow, "Begin Installation", "button").click()
        time.sleep(1)
        vmwindow = uiutils.find_fuzzy(self.app.root, "win8 on", "frame")
        self.assertFalse(newvm.showing)
        uiutils.find_fuzzy(vmwindow, "File", "menu").click()
        uiutils.find_fuzzy(vmwindow, "Quit", "menu item").click()
        time.sleep(.5)


    def testNewVMURL(self):
        """
        New VM with URL and distro detection, plus having fun with
        the storage browser and network selection.
        """
        self.app.uri = tests.utils.uri_kvm
        newvm = self._open_create_wizard()

        uiutils.find_fuzzy(newvm, "Network Install", "radio").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()

        uiutils.find_pattern(newvm, None, "text", "URL").text = (
            "http://vault.centos.org/5.5/os/x86_64/")

        version = uiutils.find_pattern(newvm, "install-os-version-label")
        time.sleep(1)
        uiutils.check_in_loop(lambda: "Detecting" not in version.text)
        self.assertEquals(version.text, "Red Hat Enterprise Linux 5.5")

        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Finish", "button").click()
        time.sleep(.5)

        progress = uiutils.find_fuzzy(self.app.root,
            "Creating Virtual Machine", "frame")
        uiutils.check_in_loop(lambda: not progress.showing)
        time.sleep(.5)

        uiutils.find_fuzzy(self.app.root, "rhel5.5 on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()

    def testNewPPC64(self):
        """
        New PPC64 VM to test architecture selection
        """
        self.app.uri = tests.utils.uri_kvm
        newvm = self._open_create_wizard()

        uiutils.find_fuzzy(newvm, "Architecture options", "toggle").click()
        uiutils.find_fuzzy(newvm, None, "combo", "Architecture").click()
        uiutils.find_fuzzy(newvm, "ppc64", "menu item").click()
        uiutils.find_fuzzy(newvm, "pseries", "menu item")

        self._do_simple_import(newvm)

        time.sleep(1)
        uiutils.find_fuzzy(self.app.root, "generic-ppc64 on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()


    def testNewArmKernel(self):
        """
        New arm VM that requires kernel/initrd/dtb
        """
        self.app.uri = tests.utils.uri_kvm_armv7l
        newvm = self._open_create_wizard()

        uiutils.find_fuzzy(newvm, "Architecture options", "toggle").click()
        uiutils.find_fuzzy(newvm, None, "combo", "Virt Type").click()
        KVM = uiutils.find_fuzzy(newvm, "KVM", "menu item")
        TCG = uiutils.find_fuzzy(newvm, "TCG", "menu item")
        self.assertTrue(KVM.focused)
        self.assertTrue(TCG.showing)
        uiutils.find_fuzzy(newvm, None, "combo", "Virt Type").click()

        # Validate some initial defaults
        self.assertFalse(
            uiutils.find_fuzzy(newvm, "PXE", "radio").sensitive)
        uiutils.find_fuzzy(newvm, "vexpress-a15", "menu item")
        uiutils.find_pattern(newvm, "virt", "menu item")
        uiutils.find_fuzzy(newvm, "Forward", "button").click()

        # Set the import media details
        uiutils.find_fuzzy(newvm, None,
            "text", "existing storage").text = "/dev/default-pool/default-vol"
        uiutils.find_fuzzy(newvm, None,
            "text", "Kernel path").text = "/tmp/kernel"
        uiutils.find_fuzzy(newvm, None,
            "text", "Initrd").text = "/tmp/initrd"
        uiutils.find_fuzzy(newvm, None,
            "text", "DTB").text = "/tmp/dtb"
        uiutils.find_fuzzy(newvm, None,
            "text", "Kernel args").text = "console=ttyS0"
        uiutils.find_fuzzy(newvm, "Forward", "button").click()

        # Disk collision box pops up, hit ok
        alert = uiutils.find_pattern(self.app.root, "Warning", "alert")
        uiutils.find_fuzzy(alert, "Yes", "push button").click()

        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Finish", "button").click()

        time.sleep(1)
        uiutils.find_fuzzy(self.app.root, "generic on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()


    def testNewVMContainerApp(self):
        """
        Simple LXC app install
        """
        self.app.uri = tests.utils.uri_lxc

        newvm = self._open_create_wizard()
        uiutils.find_fuzzy(newvm, "Application", "radio").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()

        # Set custom init
        uiutils.find_fuzzy(newvm, None,
            "text", "application path").text = "/sbin/init"
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Finish", "button").click()

        time.sleep(1)
        uiutils.find_fuzzy(self.app.root, "container1 on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()


    def testNewVMContainerTree(self):
        """
        Simple LXC tree install
        """
        self.app.uri = tests.utils.uri_lxc

        newvm = self._open_create_wizard()
        uiutils.find_fuzzy(newvm, "Operating system", "radio").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()

        # Set directory path
        uiutils.find_fuzzy(newvm, None,
            "text", "root directory").text = "/tmp"
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Forward", "button").click()
        uiutils.find_fuzzy(newvm, "Finish", "button").click()

        time.sleep(1)
        uiutils.find_fuzzy(self.app.root, "container1 on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()

    def testNewXenPV(self):
        """
        Test the create wizard with a fake xen PV install
        """
        self.app.uri = tests.utils.uri_xen
        newvm = self._open_create_wizard()

        uiutils.find_fuzzy(newvm, "Architecture options", "toggle").click()
        uiutils.find_fuzzy(newvm, None, "combo", "Xen Type").click()
        uiutils.find_fuzzy(newvm, "paravirt", "menu item").click()

        self._do_simple_import(newvm)

        self.app.quit()
