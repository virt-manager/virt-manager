# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import pytest

from tests.uitests import utils as uiutils

try:
    import guestfs
    ignore = guestfs
    HAS_LIBGUESTFS = True
except Exception:
    HAS_LIBGUESTFS = False


class VMMInspection(uiutils.UITestCase):
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
        self.app.open(extra_opts=["--test-options=config-libguestfs"])
        details = self._open_details_window("test-clone")
        details.find("OS information", "table cell").click()
        tab = details.find("os-tab")

        tab.find("Application", "toggle").click_expander()
        apps = tab.find("inspection-apps")
        uiutils.check(lambda: apps.onscreen)
        apps.click_expander()

        nodestr1 = apps.fmt_nodes()
        assert "test_app1_summary" in nodestr1
        tab.find("Refresh", "push button").click()
        uiutils.check(lambda: apps.fmt_nodes() != nodestr1)
