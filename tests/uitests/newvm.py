import time
import unittest

import tests
import tests.uitests



class NewVM(unittest.TestCase):
    """
    UI tests for virt-manager's NewVM wizard
    """
    def setUp(self):
        self.app = tests.uitests.utils.DogtailApp(tests.utils.uri_test)
    def tearDown(self):
        self.app.kill()


    ###################
    # Private helpers #
    ###################

    def _open_create_wizard(self):
        self.app.find_pattern(self.app.root, "New", "push button").click()
        return self.app.find_pattern(self.app.root, "New VM", "frame")


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
        self.app.find_fuzzy(newvm, "PXE", "radio").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Finish", "button").click()

        # Delete it from the VM window
        vmwindow = self.app.find_fuzzy(self.app.root, "generic on", "frame")
        self.app.find_pattern(vmwindow, "Virtual Machine", "menu").click()
        self.app.find_pattern(vmwindow, "Delete", "menu item").click()

        delete = self.app.find_fuzzy(self.app.root, "Delete", "frame")
        self.app.find_fuzzy(delete, "Delete", "button").click()
        alert = self.app.find_pattern(self.app.root, "Warning", "alert")
        self.app.find_fuzzy(alert, "Yes", "push button").click()
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

        self.app.find_fuzzy(newvm, "Local install media", "radio").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()

        # Select a fake iso
        self.app.find_fuzzy(newvm, "Use ISO", "radio").click()
        self.app.find_fuzzy(newvm, "install-iso-browse", "button").click()
        browser = self.app.find_fuzzy(self.app.root, "Choose Storage", "frame")
        self.app.find_fuzzy(browser, "default-pool", "table cell").click()
        self.app.find_fuzzy(browser, "iso-vol", "table cell").click()
        self.app.find_fuzzy(browser, "Choose Volume", "button").click()
        time.sleep(1)

        self.assertFalse(browser.showing)
        self.assertEquals(
            self.app.find_fuzzy(newvm, "os-version-label", "label").text,
            "Unknown")

        # Change distro to win8
        self.app.find_fuzzy(newvm, "Automatically detect", "check").click()
        version = self.app.find_fuzzy(newvm,
            "install-os-version-entry", "text")
        self.assertEquals(version.text, "Generic")

        ostype = self.app.find_fuzzy(newvm, "install-os-type", "combo")
        ostype.click()
        self.app.find_fuzzy(ostype, "Show all", "menu item").click()
        self.app.find_fuzzy(newvm, "install-os-type", "combo").click()
        self.app.find_fuzzy(newvm, "Windows", "menu item").click()
        self.app.find_fuzzy(newvm, "install-os-version-entry",
            "text").typeText("Microsoft Windows 8")
        self.app.find_fuzzy(newvm, "Forward", "button").click()

        # Verify that CPU values are non-default
        time.sleep(1)
        cpus = self.app.find_fuzzy(newvm, None, "spin button", "CPUs:").text
        self.assertTrue(int(cpus) > 1)
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()

        # Select customize wizard
        self.app.find_fuzzy(newvm, "Customize", "check").click()
        self.app.find_fuzzy(newvm, "Finish", "button").click()

        # Change to 'copy host CPU'
        vmwindow = self.app.find_fuzzy(self.app.root, "win8 on", "frame")
        self.app.find_fuzzy(vmwindow, "CPUs", "table cell").click()
        self.app.find_fuzzy(vmwindow, "Copy host", "check").click()
        self.app.find_fuzzy(vmwindow, "config-apply").click()

        # Start the install, close via the VM window
        self.app.find_fuzzy(vmwindow, "Begin Installation", "button").click()
        time.sleep(1)
        vmwindow = self.app.find_fuzzy(self.app.root, "win8 on", "frame")
        self.assertFalse(newvm.showing)
        self.app.find_fuzzy(vmwindow, "File", "menu").click()
        self.app.find_fuzzy(vmwindow, "Quit", "menu item").click()
        time.sleep(.5)


    def testNewVMURL(self):
        """
        New VM with URL and distro detection, plus having fun with
        the storage browser and network selection.
        """
        self.app.uri = tests.utils.uri_kvm
        newvm = self._open_create_wizard()

        self.app.find_fuzzy(newvm, "Network Install", "radio").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()

        self.app.find_pattern(newvm, None, "text", "URL").text = (
            "http://vault.centos.org/5.5/os/x86_64/")

        version = self.app.find_pattern(newvm, "install-os-version-label")
        time.sleep(1)
        while True:
            if "Detecting" not in version.text:
                break
            time.sleep(.5)
        self.assertEquals(version.text, "Red Hat Enterprise Linux 5.5")

        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Finish", "button").click()
        time.sleep(.5)

        progress = self.app.find_fuzzy(self.app.root,
            "Creating Virtual Machine", "frame")
        while True:
            if not progress.showing:
                break
            time.sleep(.5)
        time.sleep(.5)

        self.app.find_fuzzy(self.app.root, "rhel5.5 on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()


    def testNewVMImport(self):
        """
        New VM with a plain x86 import
        """
        newvm = self._open_create_wizard()

        self.app.find_fuzzy(newvm, "Import", "radio").click()
        self.app.find_fuzzy(newvm, None,
            "text", "existing storage").text = "/tmp/foo.img"
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Finish", "button").click()

        time.sleep(1)
        self.app.find_fuzzy(self.app.root, "generic on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()


    def testNewVMArmKernel(self):
        """
        New arm VM that requires kernel/initrd/dtb
        """
        self.app.uri = tests.utils.uri_kvm
        newvm = self._open_create_wizard()

        # Validate some initial defaults
        self.app.find_fuzzy(newvm, "Architecture options", "toggle").click()
        self.app.find_fuzzy(newvm, None, "combo", "Architecture").click()
        self.app.find_fuzzy(newvm, "arm", "menu item").click()
        self.assertFalse(
            self.app.find_fuzzy(newvm, "PXE", "radio").sensitive)
        self.assertFalse(
            self.app.find_fuzzy(newvm, "vexpress-a15", "menu item").showing)
        self.assertFalse(
            self.app.find_pattern(newvm, "virt", "menu item").showing)
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        time.sleep(.5)

        # Set the import media details
        self.app.find_fuzzy(newvm, None,
            "text", "existing storage").text = "/dev/default-pool/default-vol"
        self.app.find_fuzzy(newvm, None,
            "text", "Kernel path").text = "/tmp/kernel"
        self.app.find_fuzzy(newvm, None,
            "text", "Initrd").text = "/tmp/initrd"
        self.app.find_fuzzy(newvm, None,
            "text", "DTB").text = "/tmp/dtb"
        self.app.find_fuzzy(newvm, None,
            "text", "Kernel args").text = "console=ttyS0"
        self.app.find_fuzzy(newvm, "Forward", "button").click()

        # Disk collision box pops up, hit ok
        alert = self.app.find_pattern(self.app.root, "Warning", "alert")
        self.app.find_fuzzy(alert, "Yes", "push button").click()

        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Finish", "button").click()

        time.sleep(1)
        self.app.find_fuzzy(self.app.root, "generic-arm on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()


    def testNewVMContainerApp(self):
        """
        Simple LXC app install
        """
        self.app.uri = tests.utils.uri_lxc

        newvm = self._open_create_wizard()
        self.app.find_fuzzy(newvm, "Application", "radio").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()

        # Set custom init
        self.app.find_fuzzy(newvm, None,
            "text", "application path").text = "/sbin/init"
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Finish", "button").click()

        time.sleep(1)
        self.app.find_fuzzy(self.app.root, "container1 on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()


    def testNewVMContainerTree(self):
        """
        Simple LXC tree install
        """
        self.app.uri = tests.utils.uri_lxc

        newvm = self._open_create_wizard()
        self.app.find_fuzzy(newvm, "Operating system", "radio").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()

        # Set directory path
        self.app.find_fuzzy(newvm, None,
            "text", "root directory").text = "/tmp"
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Forward", "button").click()
        self.app.find_fuzzy(newvm, "Finish", "button").click()

        time.sleep(1)
        self.app.find_fuzzy(self.app.root, "container1 on", "frame")
        self.assertFalse(newvm.showing)
        self.app.quit()
