# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


###################################################
# UI tests for various connection.py related bits #
###################################################

def testConnectionBlacklist(app):
    app.open(
        extra_opts=["--test-options=object-denylist=test-many-devices"])
    manager = app.topwin

    def _delete_vm(vmname):
        app.manager_vm_action(vmname, delete=True)
        delete = app.find_window("Delete")
        delete.find("Delete associated", "check box").click()
        delete.find("Delete", "push button").click()
        lib.utils.check(lambda: manager.active)

    lib.utils.check(
            lambda: "test-many-devices" not in app.topwin.fmt_nodes())
    _delete_vm("test-arm-kernel")
    _delete_vm("test-clone-full")
    _delete_vm("test-clone-simple")
    app.sleep(.5)  # Give events time to register to hit full denylist path
    lib.utils.check(
            lambda: "test-many-devices" not in app.topwin.fmt_nodes())


def testConnectionConnCrash(app):
    app.open(
        extra_opts=["--test-options=conn-crash",
                    "--test-options=short-poll"])
    manager = app.topwin

    manager.find(r"^test testdriver.xml - Not Connected", "table cell")
    lib.utils.check(lambda: manager.active)


def testConnectionFakeEvents(app):
    app.open(
        extra_opts=["--test-options=fake-nodedev-event=computer",
                    "--test-options=fake-agent-event=test-many-devices",
                    "--test-options=short-poll"])
    manager = app.topwin
    app.sleep(1.2)  # needs a second to hit both nodedev/agent event paths
    lib.utils.check(lambda: manager.active)


def testConnectionOpenauth(app):
    app.open(
        extra_opts=["--test-options=fake-openauth"],
        window_name="Authentication required")

    dialog = app.root.find("Authentication required")
    def _run():
        username = dialog.find("Username:.*entry")
        password = dialog.find("Password:.*entry")
        username.click()
        username.text = "foo"
        app.rawinput.pressKey("Enter")
        lib.utils.check(lambda: password.focused)
        password.typeText("bar")


    _run()
    dialog.find("OK", "push button").click()
    lib.utils.check(lambda: not dialog.showing)
    manager = app.find_window("Virtual Machine Manager")
    manager.find("^test testdriver.xml$", "table cell")

    # Disconnect and reconnect to trigger it again
    def _retrigger_connection():
        manager.click()
        app.manager_conn_disconnect("test testdriver.xml")
        manager.click()
        app.manager_conn_connect("test testdriver.xml")

    _retrigger_connection()
    dialog = app.root.find("Authentication required")
    _run()
    app.rawinput.pressKey("Enter")
    lib.utils.check(lambda: not dialog.showing)
    manager = app.find_window("Virtual Machine Manager")
    manager.find("^test testdriver.xml$", "table cell")

    _retrigger_connection()
    dialog = app.root.find("Authentication required")
    dialog.find("Cancel", "push button").click()
    lib.utils.check(lambda: not dialog.showing)
    app.click_alert_button("Unable to connect", "Close")
    manager.find("test testdriver.xml - Not Connected", "table cell")


def testConnectionSessionError(app):
    app.open(
        extra_opts=["--test-options=fake-session-error"])
    app.click_alert_button("Could not detect a local session", "Close")
