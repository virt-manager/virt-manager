# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import pytest

from . import lib

try:
    import guestfs  # pylint: disable=import-error
    ignore = guestfs
    HAS_LIBGUESTFS = True
except Exception:
    HAS_LIBGUESTFS = False


#########################################################
# UI tests for the libguestfs inspection infrastructure #
#########################################################

def testInspectionMock(app):
    if not HAS_LIBGUESTFS:
        pytest.skip("libguestfs python not installed")

    # Use the test suite inspection mocking to test parts
    # of the UI that interact with inspection data
    app.open(enable_libguestfs=True)
    manager = app.topwin

    details = app.manager_open_details("test-clone")
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

    details.window_close()

    # Open a VM with no disks which will report an inspection error
    app.root.find_fuzzy("test\n", "table cell").doubleClick()
    details = app.find_window("test on")
    details.find("Details", "radio button").click()
    details.find("OS information", "table cell").click()
    tab = details.find("os-tab")
    tab.find_fuzzy("Fake test error no disks")

    # Closing and reopening a connection triggers some libguest
    # cache reading
    details.window_close()
    manager.click()
    c = manager.find("test testdriver.xml", "table cell")
    app.manager_conn_disconnect("test testdriver.xml")
    lib.utils.check(lambda: "Not Connected" in c.text)
    app.manager_conn_connect("test testdriver.xml")
    lib.utils.check(lambda: "Not Connected" not in c.text)
