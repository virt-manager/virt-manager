# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import tests.utils
from . import lib


#############################################################
# UI tests for manager window, and basic VM lifecycle stuff #
#############################################################

def _testVMLifecycle(app):
    """
    Basic VM lifecycle test, shared between standard and no-events
    testing
    """
    manager = app.topwin
    shutdown = manager.find("Shut Down", "push button")
    pause = manager.find("Pause", "toggle button")
    run = manager.find("Run", "push button")
    force = manager.find("Force Off", "menu item")
    smenu = manager.find("Menu", "toggle button")
    save = manager.find("Save", "menu item")

    c = manager.find("test-many-devices", "table cell")
    c.click()
    smenu.click()
    force.click()
    app.click_alert_button("Are you sure you want", "Yes")
    lib.utils.check(lambda: run.sensitive, timeout=5)

    run.click()
    lib.utils.check(lambda: not run.sensitive, timeout=5)
    pause.click()
    lib.utils.check(lambda: pause.checked, timeout=5)
    pause.click()
    lib.utils.check(lambda: not pause.checked, timeout=5)
    smenu.click()
    save.click()
    lib.utils.check(lambda: run.sensitive, timeout=5)
    lib.utils.check(lambda: "Saved" in c.text)
    run.click()
    lib.utils.check(lambda: shutdown.sensitive, timeout=5)


def testVMLifecycle(app):
    # qemu hits some different domain code paths for setTime
    app.uri = tests.utils.URIs.kvm
    _testVMLifecycle(app)


def testVMNoEventsLifecycle(app):
    app.open(extra_opts=["--test-options=no-events",
                         "--test-options=short-poll"])
    _testVMLifecycle(app)


def testVMLifecycleExtra(app):
    """
    Test vmmenu lifecycle options
    """
    app.open(keyfile="confirm-all.ini")
    manager = app.topwin
    run = manager.find("Run", "push button")
    shutdown = manager.find("Shut Down", "push button")
    pause = manager.find("Pause", "toggle button")

    def confirm_is_running():
        lib.utils.check(lambda: not run.sensitive)

    def confirm_is_shutdown():
        lib.utils.check(lambda: not shutdown.sensitive)

    def confirm_is_paused():
        lib.utils.check(lambda: pause.checked)

    def confirm_not_paused():
        lib.utils.check(lambda: not pause.checked)

    def test_action(**kwargs):
        app.manager_vm_action("test", confirm_click_no=True, **kwargs)

    confirm_is_running()
    test_action(reset=True)
    confirm_is_running()
    test_action(reboot=True)
    confirm_is_running()
    test_action(shutdown=True)
    confirm_is_shutdown()
    test_action(run=True)
    confirm_is_running()
    test_action(destroy=True)
    confirm_is_shutdown()
    test_action(run=True)
    confirm_is_running()
    test_action(pause=True)
    confirm_is_paused()
    test_action(resume=True)
    confirm_not_paused()
    test_action(save=True)
    confirm_is_shutdown()
    test_action(restore=True)
    confirm_is_running()


def testManagerSaveCancelError(app):
    """
    Test managed save special behavior
    """
    app.open(extra_opts=["--test-options=test-managed-save"])

    manager = app.topwin
    run = manager.find("Run", "push button")
    smenu = manager.find("Menu", "toggle button")
    save = manager.find("Save", "menu item")

    c = manager.find("test-many-devices", "table cell")
    c.click()

    # Save it, attempt a cancel operation
    smenu.click()
    save.click()
    progwin = app.find_window("Saving Virtual Machine")
    # Attempt cancel which will fail, then find the error message
    progwin.find("Cancel", "push button").click()
    progwin.find("Error cancelling save job")
    lib.utils.check(lambda: not progwin.showing, timeout=5)
    lib.utils.check(lambda: run.sensitive)

    # Restore will fail and offer to remove managed save
    run.click()
    app.click_alert_button("remove the saved state", "No")
    lib.utils.check(lambda: run.sensitive)
    run.click()
    app.click_alert_button("remove the saved state", "Yes")
    lib.utils.check(lambda: not run.sensitive)


def testManagerQEMUSetTime(app):
    """
    Fake qemu setTime behavior for code coverage
    """
    app.uri = tests.utils.URIs.kvm
    manager = app.topwin
    run = manager.find("Run", "push button")
    smenu = manager.find("Menu", "toggle button")
    save = manager.find("Save", "menu item")

    c = manager.find("test alternate devs title", "table cell")
    c.click()

    # Save -> resume -> save
    smenu.click()
    save.click()
    lib.utils.check(lambda: run.sensitive)
    app.sleep(1)  # give settime thread time to run
    run.click()
    lib.utils.check(lambda: not run.sensitive)
    app.sleep(1)  # give settime thread time to run
    smenu.click()
    save.click()
    lib.utils.check(lambda: run.sensitive)
    app.sleep(1)  # give settime thread time to run


def testManagerVMRunFail(app):
    # Force VM startup to fail so we can test the error path
    app.open(extra_opts=["--test-options=test-vm-run-fail"])

    manager = app.topwin

    c = manager.find("test-clone-simple", "table cell")
    c.click()
    manager.find("Run", "push button").click()
    app.click_alert_button("fake error", "Close")



def testManagerColumns(app):
    # Enable all stat options
    # Need to expand the window size so all columns are onscreen
    app.open(keyfile="winsize.ini")
    app.root.find("Edit", "menu").click()
    app.root.find("Preferences", "menu item").click()
    win = app.find_window("Preferences")
    win.find("Polling", "page tab").click()
    win.find_fuzzy("Poll Disk", "check").click()
    win.find_fuzzy("Poll Network", "check").click()
    win.find_fuzzy("Poll Memory", "check").click()
    win.find("Close", "push button").click()

    manager = app.topwin
    def _test_sort(name):
        col = manager.find(name, "table column header")
        col.check_onscreen()
        # Trigger sorting
        col.click()
        col.click()

    def _click_column_menu(name):
        manager.find("View", "menu").click()
        menu = manager.find("Graph", "menu")
        menu.point()
        menu.find_fuzzy(name, "check menu item").click()

    def _test_column(name):
        _click_column_menu(name)
        _test_sort(name)

    _test_sort("Name")
    _click_column_menu("Guest CPU")
    _click_column_menu("Guest CPU")
    _test_sort("CPU usage")
    _test_column("Host CPU")
    _test_column("Memory")
    _test_column("Disk I/O")
    _test_column("Network I/O")


def testManagerWindowReposition(app):
    """
    Restore previous position when window is reopened
    """
    manager = app.topwin
    host = app.manager_open_host("Storage")
    fmenu = host.find("File", "menu")
    fmenu.click()
    fmenu.find("View Manager", "menu item").click()
    lib.utils.check(lambda: manager.active)

    manager.window_maximize()
    newx = manager.position[0]
    newy = manager.position[1]
    manager.window_close()
    host.click_title()
    host.find("File", "menu").click()
    host.find("View Manager", "menu item").click()
    lib.utils.check(lambda: manager.showing)
    assert manager.position == (newx, newy)



def testManagerWindowCleanup(app):
    """
    Open migrate, clone, delete, newvm, details, host windows, close the
    connection, make sure they all disappear
    """
    manager = app.topwin
    manager.window_maximize()

    # Open delete window hitting a special code path, then close it
    manager.find("test-many-devices", "table cell").click()
    manager.find("Edit", "menu").click()
    manager.find("Delete", "menu item").click()
    delete = app.root.find_fuzzy("Delete", "frame")
    delete.find("storage-list").grab_focus()
    delete.window_close()

    # Open Clone window hitting a special code path, then close it
    manager.find("test-clone", "table cell").click()
    app.rawinput.pressKey("Menu")
    app.root.find("Clone...", "menu item").click()
    clone = app.find_window("Clone Virtual Machine")
    clone.window_close()

    # Open host
    manager.grab_focus()
    c = manager.find_fuzzy("testdriver.xml", "table cell")
    c.doubleClick()
    host = app.find_window("test testdriver.xml - Connection Details")

    # Open details
    manager.grab_focus()
    c = manager.find("test-many-devices", "table cell")
    c.doubleClick()
    details = app.find_details_window("test-many-devices")

    # Close the connection
    manager.grab_focus()
    app.manager_conn_disconnect("test testdriver.xml")

    # Ensure all those windows aren't showing
    lib.utils.check(lambda: not details.showing)

    # Delete the connection, ensure the host dialog disappears
    app.manager_conn_delete("test testdriver.xml")
    lib.utils.check(lambda: not host.showing)


def testManagerDefaultStartup(app):
    app.open(use_uri=False)
    manager = app.topwin
    errlabel = manager.find("error-label")
    lib.utils.check(
            lambda: "Checking for virtualization" in errlabel.text)
    lib.utils.check(
            lambda: "File->Add Connection" in errlabel.text)
    lib.utils.check(
            lambda: "appropriate QEMU/KVM" in errlabel.text)

    manager.find("File", "menu").click()
    manager.find("Quit", "menu item").click()


def testManagerConnOpenFail(app):
    app.open(keyfile="baduri.ini")
    manager = app.topwin
    manager.find_fuzzy("bad uri", "table cell").doubleClick()
    lib.utils.check(lambda: not manager.active)
    app.click_alert_button("Unable to connect", "Close")
    lib.utils.check(lambda: manager.active)
