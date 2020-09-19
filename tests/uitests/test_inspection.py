# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import pytest

from . import lib

try:
    import guestfs
    ignore = guestfs
    HAS_LIBGUESTFS = True
except Exception:
    HAS_LIBGUESTFS = False


class VMMInspection(lib.testcase.UITestCase):
    """
    UI tests for the libguestfs inspection infrastructure
    """

    ##############
    # Test cases #
    ##############

    def testInspectionMock(self):
        if not HAS_LIBGUESTFS:
            pytest.skip("libguestfs python not installed")

        # Use the test suite inspection mocking to test parts
        # of the UI that interact with inspection data
        self.app.open(enable_libguestfs=True)
        manager = self.app.topwin

        details = self.app.open_details_window("test-clone")
        details.find("OS information", "table cell").click()
        tab = details.find("os-tab")

        tab.find("Application", "toggle").click_expander()
        apps = tab.find("inspection-apps")
        apps.check_onscreen()
        apps.click_expander()

        nodestr1 = apps.fmt_nodes()
        assert "test_app1_summary" in nodestr1
        tab.find("Refresh", "push button").click()
        lib.utils.check(lambda: apps.fmt_nodes() != nodestr1)

        details.keyCombo("<alt>F4")
        lib.utils.check(lambda: not details.showing)

        # Open a VM with no disks which will report an inspection error
        self.app.root.find_fuzzy("test\n", "table cell").doubleClick()
        details = self.app.root.find("test on", "frame")
        details.find("Details", "radio button").click()
        details.find("OS information", "table cell").click()
        tab = details.find("os-tab")
        tab.find_fuzzy("Fake test error no disks")

        # Closing and reopening a connection triggers some libguest
        # cache reading
        details.keyCombo("<alt>F4")
        manager.click()
        c = manager.find_fuzzy("testdriver.xml", "table cell")
        c.click()
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()
        manager.click()
        c = manager.find_fuzzy("testdriver.xml", "table cell")
        c.click()
        c.click(button=3)
        self.app.root.find("conn-connect", "menu item").click()
        self.app.sleep(2)
