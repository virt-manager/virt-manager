import time
import unittest

import dogtail.rawinput
import pyatspi

import tests
from tests.uitests import utils as uiutils


class Details(unittest.TestCase):
    """
    UI tests for virt-manager's VM details window
    """
    def setUp(self):
        self.app = uiutils.DogtailApp(tests.utils.uri_test)
    def tearDown(self):
        self.app.kill()


    ###################
    # Private helpers #
    ###################

    def _open_details_window(self, vmname="test-many-devices"):
        uiutils.find_fuzzy(
            self.app.root, vmname, "table cell").doubleClick()
        win = uiutils.find_pattern(self.app.root, "%s on" % vmname, "frame")
        uiutils.find_pattern(win, "Details", "radio button").click()
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
        uiutils.find_pattern(win, "Hypervisor Details", "label")
        uiutils.find_pattern(win, "Overview", "table cell").click()

        # After we hit this number of down presses, start checking for
        # widget focus to determine if we hit the end of the list. We
        # don't check for widget focus unconditionally because it's slow.
        # The seemingly arbitrary number here is because it matches the
        # number of devices in test-many-devices at the time of this writing.
        check_after = 88

        focused = None
        old_focused = None
        count = 0
        while True:
            count += 1
            dogtail.rawinput.pressKey("Down")

            if not win.getState().contains(pyatspi.STATE_ACTIVE):
                # Should mean an error dialog popped up
                uiutils.find_pattern(self.app.root, "Error", "alert")
                raise AssertionError(
                    "One of the hardware pages raised an error")

            if count < check_after:
                time.sleep(.1)
                continue

            # pylint: disable=not-an-iterable
            old_focused = focused
            focused = uiutils.focused_nodes(win)
            if old_focused is None:
                continue

            overlap = [w for w in old_focused if w in focused]
            if len(overlap) == len(old_focused):
                # Focus didn't change, meaning we hit the end of the HW list,
                # so our testing is done
                break

        self.app.quit()
        return

    def _testRename(self, origname, newname):
        win = self._open_details_window(origname)

        # Ensure the Overview page is the first selected
        uiutils.find_pattern(win, "Hypervisor Details", "label")
        uiutils.find_pattern(win, "Overview", "table cell").click()

        uiutils.find_pattern(win, None, "text", "Name:").text = newname
        uiutils.find_pattern(win, "config-apply", "push button").click()

        # Confirm lists were updated
        uiutils.find_pattern(self.app.root, "%s on" % newname, "frame")
        uiutils.find_fuzzy(self.app.root, newname, "table cell")

        # Ensure old VM entry is gone
        try:
            uiutils.find_fuzzy(self.app.root, origname, "table cell",
                               retry=False)
            raise AssertionError("Still found manager row for %s" % origname)
        except dogtail.tree.SearchError:
            # We want this
            pass

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
        uiutils.find_fuzzy(self.app.root, origname, "table cell").click()
        uiutils.find_pattern(self.app.root, "Shut Down", "push button").click()

        self._testRename(origname, "test-new-name")
