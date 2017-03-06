import time
import unittest

import tests
from tests.uitests import utils as uiutils



class CloneVM(unittest.TestCase):
    """
    UI tests for virt-manager's CloneVM wizard
    """
    def setUp(self):
        self.app = uiutils.DogtailApp(tests.utils.uri_test)
    def tearDown(self):
        self.app.kill()


    ###################
    # Private helpers #
    ###################

    def _open_window(self, vmname):
        # Launch wizard via right click menu
        uiutils.find_fuzzy(
                self.app.root, vmname, "table cell").click(button=3)
        uiutils.find_pattern(self.app.root, "Clone...", "menu item").click()
        return uiutils.find_pattern(
                self.app.root, "Clone Virtual Machine", "frame")


    ##############
    # Test cases #
    ##############

    def testClone(self):
        """
        Clone test-clone, which is meant to hit many clone code paths
        """
        win = self._open_window("test-clone")
        uiutils.find_pattern(win, "Clone", "push button").click()
        time.sleep(1)

        # Verify the new VM popped up
        uiutils.find_pattern(
                self.app.root, "test-clone1", "table cell")

    def testCloneSimple(self):
        """
        Clone test-clone-simple
        """
        win = self._open_window("test-clone-simple")
        uiutils.find_pattern(win, "Clone", "push button").click()
        time.sleep(1)

        # Verify the new VM popped up
        uiutils.find_pattern(
                self.app.root, "test-clone-simple-clone", "table cell")

    def testFullClone(self):
        """
        Clone test-full-clone, which should error due to lack of space
        """
        win = self._open_window("test-clone-full")
        uiutils.find_pattern(win, "Clone", "push button").click()
        time.sleep(1)

        # Verify error dialog popped up
        uiutils.find_pattern(
                self.app.root, ".*There is not enough free space.*", "label")

    def testCloneTweaks(self):
        """
        Clone test-clone-simple, but tweak bits in the clone UI
        """
        win = self._open_window("test-clone-simple")
        uiutils.find_fuzzy(win, None,
            "text", "Name").text = "test-new-vm"

        uiutils.find_pattern(win, "Details...", "push button").click()
        macwin = uiutils.find_pattern(
                self.app.root, "Change MAC address", "dialog")
        uiutils.find_pattern(macwin, None,
                "text", "New MAC:").text = "00:16:3e:cc:cf:05"
        uiutils.find_pattern(macwin, "OK", "push button").click()

        uiutils.find_fuzzy(win, "Clone this disk.*", "combo box").click()
        uiutils.find_fuzzy(win, "Details...", "menu item").click()
        stgwin = uiutils.find_pattern(
                self.app.root, "Change storage path", "dialog")
        uiutils.find_pattern(stgwin, None, "text",
                "New Path:").text = "/dev/default-pool/my-new-path"
        uiutils.find_pattern(stgwin, "OK", "push button").click()

        uiutils.find_pattern(win, "Clone", "push button").click()
        time.sleep(1)

        # Verify the new VM popped up
        uiutils.find_pattern(
                self.app.root, "test-new-vm", "table cell")
