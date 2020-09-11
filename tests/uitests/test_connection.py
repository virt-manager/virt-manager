# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


class UITestConnection(lib.testcase.UITestCase):
    """
    UI tests for various connection.py related bits
    """

    ##############
    # Test cases #
    ##############

    def testConnectionBlacklist(self):
        self.app.open(
            extra_opts=["--test-options=object-blacklist=test-many-devices"])
        manager = self.app.topwin

        def _delete_vm(vmname):
            cell = manager.find(vmname, "table cell")
            cell.click()
            cell.click(button=3)
            menu = self.app.root.find("vm-action-menu")
            menu.find("Delete", "menu item").click()
            delete = self.app.root.find_fuzzy("Delete", "frame")
            delete.find("Delete associated", "check box").click()
            delete.find("Delete", "push button").click()
            lib.utils.check(lambda: cell.dead)
            lib.utils.check(lambda: manager.active)

        lib.utils.check(
                lambda: "test-many-devices" not in self.app.topwin.fmt_nodes())
        _delete_vm("test-arm-kernel")
        _delete_vm("test alternate")
        _delete_vm("test-clone-simple")
        self.app.sleep(.5)
        lib.utils.check(
                lambda: "test-many-devices" not in self.app.topwin.fmt_nodes())

    def testConnectionConnCrash(self):
        self.app.open(
            extra_opts=["--test-options=conn-crash"])
        manager = self.app.topwin

        self.app.sleep(1)
        manager.find(r"^test testdriver.xml - Not Connected", "table cell")
        lib.utils.check(lambda: manager.active)

    def testConnectionFakeEvents(self):
        self.app.open(
            extra_opts=["--test-options=fake-nodedev-event=computer",
                        "--test-options=fake-agent-event=test-many-devices"])
        manager = self.app.topwin
        self.app.sleep(2.5)
        lib.utils.check(lambda: manager.active)

    def testConnectionOpenauth(self):
        self.app.open(
            extra_opts=["--test-options=fake-openauth"],
            window_name="Authentication required")

        dialog = self.app.root.find("Authentication required")
        def _run():
            username = dialog.find("Username:.*entry")
            password = dialog.find("Password:.*entry")
            username.click()
            username.text = "foo"
            self.app.rawinput.pressKey("Enter")
            lib.utils.check(lambda: password.focused)
            password.typeText("bar")


        _run()
        dialog.find("OK", "push button").click()
        lib.utils.check(lambda: not dialog.showing)
        manager = self.app.root.find("Virtual Machine Manager", "frame")
        manager.find("^test testdriver.xml$", "table cell")

        # Disconnect and reconnect to trigger it again
        def _retrigger_connection():
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

        _retrigger_connection()
        dialog = self.app.root.find("Authentication required")
        _run()
        self.app.rawinput.pressKey("Enter")
        lib.utils.check(lambda: not dialog.showing)
        manager = self.app.root.find("Virtual Machine Manager", "frame")
        manager.find("^test testdriver.xml$", "table cell")

        _retrigger_connection()
        dialog = self.app.root.find("Authentication required")
        dialog.find("Cancel", "push button").click()
        lib.utils.check(lambda: not dialog.showing)
        self.app.click_alert_button("Unable to connect", "Close")
        manager.find("test testdriver.xml - Not Connected", "table cell")

    def testConnectionSessionError(self):
        self.app.open(
            extra_opts=["--test-options=fake-session-error"])
        self.app.click_alert_button("Could not detect a local session", "Close")
