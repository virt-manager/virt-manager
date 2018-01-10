from tests.uitests import utils as uiutils



class CloneVM(uiutils.UITestCase):
    """
    UI tests for virt-manager's CloneVM wizard
    """

    ###################
    # Private helpers #
    ###################

    def _open_window(self, vmname):
        # Launch wizard via right click menu
        c = self.app.root.find_fuzzy(vmname, "table cell")
        c.click(button=3)
        self.app.root.find_pattern("Clone...", "menu item").click()
        return self.app.root.find_pattern("Clone Virtual Machine", "frame")


    ##############
    # Test cases #
    ##############

    def testClone(self):
        """
        Clone test-clone, which is meant to hit many clone code paths
        """
        win = self._open_window("test-clone")
        win.find_pattern("Clone", "push button").click()

        # Verify the new VM popped up
        self.app.root.find_pattern("test-clone1", "table cell")

    def testCloneSimple(self):
        """
        Clone test-clone-simple
        """
        win = self._open_window("test-clone-simple")
        win.find_pattern("Clone", "push button").click()

        # Verify the new VM popped up
        self.app.root.find_pattern("test-clone-simple-clone", "table cell")

    def testFullClone(self):
        """
        Clone test-full-clone, which should error due to lack of space
        """
        win = self._open_window("test-clone-full")
        win.find_pattern("Clone", "push button").click()

        # Verify error dialog popped up
        self.app.root.find_pattern(
                ".*There is not enough free space.*", "label")

    def testCloneTweaks(self):
        """
        Clone test-clone-simple, but tweak bits in the clone UI
        """
        win = self._open_window("test-clone-simple")
        win.find_fuzzy(None,
            "text", "Name").text = "test-new-vm"

        win.find_pattern("Details...", "push button").click()
        macwin = self.app.root.find_pattern("Change MAC address", "dialog")
        macwin.find_pattern(None,
                "text", "New MAC:").text = "00:16:3e:cc:cf:05"
        macwin.find_pattern("OK", "push button").click()

        win.find_fuzzy("Clone this disk.*", "combo box").click()
        win.find_fuzzy("Details...", "menu item").click()
        stgwin = self.app.root.find_pattern("Change storage path", "dialog")
        stgwin.find_pattern(None, "text",
                "New Path:").text = "/dev/default-pool/my-new-path"
        stgwin.find_pattern("OK", "push button").click()

        win.find_pattern("Clone", "push button").click()

        # Verify the new VM popped up
        self.app.root.find_pattern("test-new-vm", "table cell")
