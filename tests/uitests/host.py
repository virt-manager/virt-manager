import time
import unittest

import dogtail.rawinput
import pyatspi

import tests
from tests.uitests import utils as uiutils


class Host(unittest.TestCase):
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

    def _open_host_window(self, tab):
        conn_label = "test testdriver.xml"
        uiutils.find_fuzzy(self.app.root, conn_label,
                           "table cell").click()
        uiutils.find_fuzzy(self.app.root, "Edit", "menu").click()
        uiutils.find_fuzzy(self.app.root, "Connection Details",
                           "menu item").click()
        win = uiutils.find_fuzzy(self.app.root,
                                 "%s Connection Details" % conn_label,
                                 "frame")
        uiutils.find_fuzzy(win, tab, "page tab").click()
        return win

    def _checkListEntrys(self, win, check_after):
        # After we hit this number of down presses, start checking for
        # widget focus to determine if we hit the end of the list. We
        # don't check for widget focus unconditionally because it's slow.
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
                    "One of the pages raised an error")

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


    ##############
    # Test cases #
    ##############

    def testHostNetworkSmokeTest(self):
        """
        Verify that each virtual network displays, without error.
        """
        win = self._open_host_window("Virtual Networks")

        # Make sure the first item is selected
        cell = uiutils.find_pattern(win, "default", "table cell")
        self.assertTrue(cell.getState().contains(pyatspi.STATE_SELECTED))

        self._checkListEntrys(win, 13)
        self.app.quit()

    def testHostStorageSmokeTest(self):
        """
        Verify that each storage pool displays, without error.
        """
        win = self._open_host_window("Storage")

        # Make sure the first item is selected
        cell = uiutils.find_pattern(win, "cross-pool", "table cell")
        self.assertTrue(cell.getState().contains(pyatspi.STATE_SELECTED))

        self._checkListEntrys(win, 13)
        self.app.quit()

    def testHostInterfaceSmokeTest(self):
        """
        Verify that each storage pool displays, without error.
        """
        win = self._open_host_window("Network Interfaces")

        # Make sure the first item is selected
        cell = uiutils.find_pattern(win, "bond0", "table cell")
        self.assertTrue(cell.getState().contains(pyatspi.STATE_SELECTED))

        self._checkListEntrys(win, 18)
        self.app.quit()
