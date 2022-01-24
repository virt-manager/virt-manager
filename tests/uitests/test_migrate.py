# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import tests.utils
from . import lib


###################################
# UI tests for the migrate dialog #
###################################

def _open_migrate(app, vmname):
    app.manager_vm_action(vmname, migrate=True)
    return app.find_window("Migrate the virtual machine")


def testMigrateQemu(app):
    # Use fake qemu connections
    app.uri = tests.utils.URIs.kvm_x86
    newuri = (tests.utils.URIs.test_default +
            ",fakeuri=qemu+tcp://fakehost/system")
    app.manager_createconn(newuri)

    # Run default migrate
    mig = _open_migrate(app, "test-many-devices")
    mig.find("Migrate", "push button").click()
    app.click_alert_button(
            "the.connection.driver:.virDomainMigrate", "Close")
    mig.find("Cancel", "push button").click()
    lib.utils.check(lambda: not mig.showing)

    # Run with deselected URI
    mig = _open_migrate(app, "test-many-devices")
    mig.find("address-check").click()
    label = mig.find("Let libvirt decide")
    label.check_onscreen()
    mig.find("Migrate", "push button").click()
    app.click_alert_button(
            "the.connection.driver:.virDomainMigrate", "Close")
    mig.find("Cancel", "push button").click()
    lib.utils.check(lambda: not mig.showing)

    # Run with tunnelled and other options
    mig = _open_migrate(app, "test-many-devices")
    mig.combo_select("Mode:", "Tunnelled")
    mig.find("Advanced", "toggle button").click_expander()
    mig.find("Allow unsafe:", "check box").click()
    mig.find("Temporary", "check box").click()

    mig.find("Migrate", "push button").click()
    app.click_alert_button("p2p migration", "Close")
    mig.find("Cancel", "push button").click()
    lib.utils.check(lambda: not mig.showing)


def testMigrateXen(app):
    # Use fake xen connections
    app.uri = tests.utils.URIs.test_full + ",fakeuri=xen:///"

    fakeremotexen = (tests.utils.URIs.test_default +
            ",fakeuri=xen+tcp://fakehost/")
    app.manager_createconn(fakeremotexen)

    # Run default migrate
    mig = _open_migrate(app, "test-many-devices")
    mig.find("Migrate", "push button").click()
    app.click_alert_button(
            "the.connection.driver:.virDomainMigrate", "Close")
    mig.find("Cancel", "push button").click()
    lib.utils.check(lambda: not mig.showing)


def testMigrateMock(app):
    """
    Trigger the mock migration testing we have to emulate success
    """
    # Add an additional connection
    app.manager_createconn("test:///default")

    # Run it and check some values
    mig = _open_migrate(app, "test-many-devices")
    mig.find("address-text").set_text("TESTSUITE-FAKE")

    mig.find("Migrate", "push button").click()
    progwin = app.find_window("Migrating VM")
    # Attempt cancel which will fail, then find the error message
    progwin.find("Cancel", "push button").click()
    progwin.find("Error cancelling migrate job")
    lib.utils.check(lambda: not progwin.showing, timeout=5)
    lib.utils.check(lambda: not mig.showing)


def testMigrateConnMismatch(app):
    # Add a possible target but disconnect it
    app.uri = tests.utils.URIs.test_default
    manager = app.topwin
    manager.window_maximize()
    manager.click()
    app.manager_conn_disconnect("test default")

    # Add a mismatched hv connection
    fakexen = tests.utils.URIs.test_empty + ",fakeuri=xen:///"
    app.manager_createconn(fakexen)

    # Open dialog and confirm no conns are available
    app.manager_createconn(tests.utils.URIs.test_full)
    mig = _open_migrate(app, "test-many-devices")
    mig.find("conn-combo").find("No usable", "menu item")

    # Test explicit dialog 'delete'
    mig.window_close()

    # Ensure disconnecting will close the dialog
    manager.click_title()
    mig = _open_migrate(app, "test-many-devices")
    app.manager_conn_disconnect("test testdriver.xml")
    lib.utils.check(lambda: not mig.showing)


def testMigrateXMLEditor(app):
    app.open(xmleditor_enabled=True)
    manager = app.topwin

    # Add an additional connection
    app.manager_createconn("test:///default")

    # Run it and check some values
    vmname = "test-many-devices"
    win = _open_migrate(app, vmname)
    win.find("address-text").set_text("TESTSUITE-FAKE")

    # Create a new obj with XML edited name, verify it worked
    newname = "aafroofroo"
    win.find("XML", "page tab").click()
    xmleditor = win.find("XML editor")
    newtext = xmleditor.text.replace(
            ">%s<" % vmname, ">%s<" % newname)
    xmleditor.set_text(newtext)
    win.find("Migrate", "push button").click()
    lib.utils.check(lambda: not win.showing, timeout=10)

    manager.find(newname, "table cell")

    # Do standard xmleditor tests
    win = _open_migrate(app, vmname)
    win.find("address-text").set_text("TESTSUITE-FAKE")
    finish = win.find("Migrate", "push button")
    lib.utils.test_xmleditor_interactions(app, win, finish)
    win.find("Cancel", "push button").click()
    lib.utils.check(lambda: not win.visible)
