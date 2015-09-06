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
        self.app.proc.kill()

    ###################
    # Private helpers #
    ###################

    def _open_create_wizard(self):
        self.app.find_pattern(self.app.root, "New", "push button").click()
        return self.app.find_pattern(self.app.root, "New VM", "frame")


    ##############
    # Test cases #
    ##############

    def testNewVMDefault(self):
        """
        Click through the New VM wizard with default values + PXE, then
        delete the VM
        """
        # Create default PXE VM
        newvm = self._open_create_wizard()
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
        self.assertFalse(delete.showing)
        self.assertFalse(vmwindow.showing)

        # Close the app from the main window
        self.app.find_pattern(self.app.root, "File", "menu").click()
        self.app.find_pattern(self.app.root, "Quit", "menu item").click()
        time.sleep(.5)
