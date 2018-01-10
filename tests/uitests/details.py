import dogtail.rawinput
import pyatspi

from tests.uitests import utils as uiutils


class Details(uiutils.UITestCase):
    """
    UI tests for virt-manager's VM details window
    """

    ###################
    # Private helpers #
    ###################

    def _open_details_window(self, vmname="test-many-devices"):
        self.app.root.find_fuzzy(vmname, "table cell").click(button=3)
        self.app.root.find_pattern("Open", "menu item").click()

        win = self.app.root.find_pattern("%s on" % vmname, "frame")
        win.find_pattern("Details", "radio button").click()
        return win


    ##############
    # Test cases #
    ##############

    def testDetailsHardwareSmokeTest(self):
        """
        Open the VM with all the crazy hardware and just verify that each
        HW panel shows itself without raising any error.
        """
        win = self._open_details_window()

        # Ensure the Overview page is the first selected
        win.find_pattern("Hypervisor Details", "label")
        win.find_pattern("Overview", "table cell").click()

        # After we hit this number of down presses, start checking for
        # widget focus to determine if we hit the end of the list. We
        # don't check for widget focus unconditionally because it's slow.
        # The seemingly arbitrary number here is because it matches the
        # number of devices in test-many-devices at the time of this writing.
        check_after = 93

        focused = None
        old_focused = None
        count = 0
        while True:
            count += 1
            dogtail.rawinput.pressKey("Down")

            if not win.getState().contains(pyatspi.STATE_ACTIVE):
                # Should mean an error dialog popped up
                self.app.root.find_pattern("Error", "alert")
                raise AssertionError(
                    "One of the hardware pages raised an error")

            if count < check_after:
                #time.sleep(.05)
                continue

            # pylint: disable=not-an-iterable
            old_focused = focused
            focused = win.focused_nodes()
            if old_focused is None:
                continue

            overlap = [w for w in old_focused if w in focused]
            if len(overlap) == len(old_focused):
                # Focus didn't change, meaning we hit the end of the HW list,
                # so our testing is done
                break

        return

    def _testRename(self, origname, newname):
        win = self._open_details_window(origname)

        # Ensure the Overview page is the first selected
        win.find_pattern("Hypervisor Details", "label")
        win.find_pattern("Overview", "table cell").click()

        oldcell = self.app.root.find_fuzzy(origname, "table cell")
        win.find_pattern(None, "text", "Name:").text = newname
        win.find_pattern("config-apply", "push button").click()

        # Confirm lists were updated
        self.app.root.find_pattern("%s on" % newname, "frame")
        self.app.root.find_fuzzy(newname, "table cell")

        # Make sure the old entry is gone
        uiutils.check_in_loop(lambda: origname not in oldcell.name)

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
        b = self.app.root.find_pattern("Shut Down", "push button")
        b.click()
        # This insures the VM finished shutting down
        uiutils.check_in_loop(lambda: b.sensitive is False)

        self._testRename(origname, "test-new-name")
