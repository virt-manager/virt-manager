# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests import utils
from tests.uitests import utils as uiutils


class Manager(uiutils.UITestCase):
    """
    UI tests for manager window, and basic VM lifecycle stuff
    """

    ##############
    # Test cases #
    ##############

    def _testVMLifecycle(self):
        """
        Basic VM lifecycle test, shared between standard and no-events
        testing
        """
        manager = self.app.topwin
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
        self._click_alert_button("Are you sure you want", "Yes")
        uiutils.check(lambda: run.sensitive, timeout=5)

        run.click()
        uiutils.check(lambda: not run.sensitive, timeout=5)
        pause.click()
        uiutils.check(lambda: pause.checked, timeout=5)
        pause.click()
        uiutils.check(lambda: not pause.checked, timeout=5)
        smenu.click()
        save.click()
        uiutils.check(lambda: run.sensitive, timeout=5)
        uiutils.check(lambda: "Saved" in c.text)
        run.click()
        uiutils.check(lambda: shutdown.sensitive, timeout=5)

    def testVMLifecycle(self):
        # qemu hits some different domain code paths for setTime
        self.app.uri = utils.URIs.kvm
        self._testVMLifecycle()

    def testVMNoEventsLifecycle(self):
        self.app.open(extra_opts=["--test-options=no-events"])

        # Change preferences timeout to 1 second
        self.app.root.find("Edit", "menu").click()
        self.app.root.find("Preferences", "menu item").click()
        win = self.app.root.find_fuzzy("Preferences", "frame")
        win.find("Polling", "page tab").click()
        win.find("cpu-poll").set_text("1")
        win.find("Close", "push button").click()

        self._testVMLifecycle()

    def testVMLifecycleExtra(self):
        """
        Test vmmenu lifecycle options
        """
        self.app.open(keyfile="confirm-all.ini")
        manager = self.app.topwin
        run = manager.find("Run", "push button")
        shutdown = manager.find("Shut Down", "push button")
        pause = manager.find("Pause", "toggle button")

        def confirm_is_running():
            uiutils.check(lambda: not run.sensitive)

        def confirm_is_shutdown():
            uiutils.check(lambda: not shutdown.sensitive)

        def confirm_is_paused():
            uiutils.check(lambda: pause.checked)

        def confirm_not_paused():
            uiutils.check(lambda: not pause.checked)

        def test_action(action, shutdown=True, confirm=True):
            def _select():
                cell = manager.find("test\n", "table cell")
                cell.click(button=3)
                menu = self.app.root.find("vm-action-menu")
                uiutils.check(lambda: menu.onscreen)
                if shutdown:
                    smenu = menu.find("Shut Down", "menu")
                    smenu.point()
                    uiutils.check(lambda: smenu.onscreen)
                    item = smenu.find(action, "menu item")
                else:
                    item = menu.find(action, "menu item")
                uiutils.check(lambda: item.onscreen)
                item.point()
                self.sleep(.3)
                item.click()

            _select()
            if confirm:
                self._click_alert_button("Are you sure", "No")
                _select()
                self._click_alert_button("Are you sure", "Yes")


        test_action("Force Reset")
        confirm_is_running()
        test_action("Reboot")
        confirm_is_running()
        test_action("Shut Down")
        confirm_is_shutdown()
        test_action("Run", shutdown=False, confirm=False)
        confirm_is_running()
        test_action("Force Off")
        confirm_is_shutdown()
        test_action("Run", shutdown=False, confirm=False)
        confirm_is_running()
        test_action("Pause", shutdown=False)
        confirm_is_paused()
        test_action("Resume", shutdown=False, confirm=False)
        confirm_not_paused()
        test_action("Save")
        confirm_is_shutdown()
        test_action("Restore", shutdown=False, confirm=False)
        confirm_is_running()

    def testManagerSaveCancelError(self):
        """
        Test managed save special behavior
        """
        self.app.open(extra_opts=["--test-options=test-managed-save"])

        manager = self.app.topwin
        run = manager.find("Run", "push button")
        smenu = manager.find("Menu", "toggle button")
        save = manager.find("Save", "menu item")

        c = manager.find("test-many-devices", "table cell")
        c.click()

        # Save it, attempt a cancel operation
        smenu.click()
        save.click()
        progwin = self.app.root.find("Saving Virtual Machine", "frame")
        # Attempt cancel which will fail, then find the error message
        progwin.find("Cancel", "push button").click()
        progwin.find("Error cancelling save job")
        uiutils.check(lambda: not progwin.showing, timeout=5)
        uiutils.check(lambda: run.sensitive)

        # Restore will fail and offer to remove managed save
        run.click()
        self._click_alert_button("remove the saved state", "No")
        uiutils.check(lambda: run.sensitive)
        run.click()
        self._click_alert_button("remove the saved state", "Yes")
        uiutils.check(lambda: not run.sensitive)

    def testManagerQEMUSetTime(self):
        """
        Fake qemu setTime behavior for code coverage
        """
        self.app.uri = utils.URIs.kvm
        manager = self.app.topwin
        run = manager.find("Run", "push button")
        smenu = manager.find("Menu", "toggle button")
        save = manager.find("Save", "menu item")

        c = manager.find("test alternate devs title", "table cell")
        c.click()

        # Save -> resume -> save
        smenu.click()
        save.click()
        uiutils.check(lambda: run.sensitive)
        self.sleep(1)
        run.click()
        uiutils.check(lambda: not run.sensitive)
        self.sleep(1)
        smenu.click()
        save.click()
        uiutils.check(lambda: run.sensitive)
        self.sleep(1)

    def testManagerVMRunFail(self):
        # Force VM startup to fail so we can test the error path
        self.app.open(extra_opts=["--test-options=test-vm-run-fail"])

        manager = self.app.topwin

        c = manager.find("test-clone-simple", "table cell")
        c.click()
        manager.find("Run", "push button").click()
        self._click_alert_button("fake error", "Close")


    def testManagerColumns(self):
        # Enable all stat options
        # Need to expand the window size so all columns are onscreen
        self.app.open(keyfile="winsize.ini")
        self.app.root.find("Edit", "menu").click()
        self.app.root.find("Preferences", "menu item").click()
        win = self.app.root.find_fuzzy("Preferences", "frame")
        win.find("Polling", "page tab").click()
        win.find_fuzzy("Poll Disk", "check").click()
        win.find_fuzzy("Poll Network", "check").click()
        win.find_fuzzy("Poll Memory", "check").click()
        win.find("Close", "push button").click()

        manager = self.app.topwin
        def _test_sort(name):
            col = manager.find(name, "table column header")
            uiutils.check(lambda: col.onscreen)
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

    def testManagerWindowReposition(self):
        """
        Restore previous position when window is reopened
        """
        manager = self.app.topwin
        host = self._open_host_window("Storage")
        fmenu = host.find("File", "menu")
        fmenu.click()
        fmenu.find("View Manager", "menu item").click()
        uiutils.check(lambda: manager.active)

        # Double click title to maximize
        manager.click_title()
        manager.click_title()
        newx = manager.position[0]
        newy = manager.position[1]
        manager.keyCombo("<alt>F4")
        host.click_title()
        host.find("File", "menu").click()
        host.find("View Manager", "menu item").click()
        uiutils.check(lambda: manager.showing)
        assert manager.position == (newx, newy)


    def testManagerWindowCleanup(self):
        """
        Open migrate, clone, delete, newvm, details, host windows, close the
        connection, make sure they all disappear
        """
        def _drag(win):
            """
            Drag a window so it's not obscuring the manager window
            """
            uiutils.drag(win, 1000, 1000)

        manager = self.app.topwin

        # Open migrate dialog
        c = manager.find("test-many-devices", "table cell")
        c.click(button=3)
        self.app.root.find("Migrate...", "menu item").click()
        migrate = self.app.root.find("Migrate the virtual machine", "frame")
        _drag(migrate)

        # Open clone dialog
        c = manager.find("test-clone", "table cell")
        c.click()
        self.pressKey("Menu")
        self.app.root.find("Clone...", "menu item").click()
        clone = self.app.root.find("Clone Virtual Machine", "frame")
        _drag(clone)

        # Open delete dialog
        c.click()
        manager.find("Edit", "menu").click()
        manager.find("Delete", "menu item").click()
        delete = self.app.root.find_fuzzy("Delete", "frame")
        _drag(delete)

        # Open NewVM
        self.app.root.find("New", "push button").click()
        create = self.app.root.find("New VM", "frame")
        _drag(create)

        # Open host
        c = manager.find_fuzzy("testdriver.xml", "table cell")
        c.doubleClick()
        host = self.app.root.find_fuzzy("Connection Details", "frame")
        _drag(host)

        # Open details
        details = self._open_details_window("test-many-devices")
        _drag(details)

        # Close the connection
        self.sleep(1)
        manager.click()
        c = manager.find_fuzzy("testdriver.xml", "table cell")
        c.click()
        c.click(button=3)
        print("\n\n\nCLICKING DISCONNECT\n\n\n")
        self.app.root.find("conn-disconnect", "menu item").click()

        # Ensure all those windows aren't showing
        uiutils.check(lambda: not migrate.showing)
        uiutils.check(lambda: not clone.showing)
        uiutils.check(lambda: not create.showing)
        uiutils.check(lambda: not details.showing)
        uiutils.check(lambda: not delete.showing)

        # Delete the connection, ensure the host dialog disappears
        c = manager.find_fuzzy("testdriver.xml", "table cell")
        c.click(button=3)
        self.app.root.find("conn-delete", "menu item").click()
        self._click_alert_button("will remove the connection", "Yes")
        uiutils.check(lambda: not host.showing)

    def testManagerDefaultStartup(self):
        self.app.open(use_uri=False)
        manager = self.app.topwin
        errlabel = manager.find("error-label")
        uiutils.check(
                lambda: "Checking for virtualization" in errlabel.text)
        uiutils.check(
                lambda: "File->Add Connection" in errlabel.text)
        uiutils.check(
                lambda: "appropriate QEMU/KVM" in errlabel.text)

        manager.find("File", "menu").click()
        manager.find("Quit", "menu item").click()

    def testManagerConnOpenFail(self):
        self.app.open(keyfile="baduri.ini")
        manager = self.app.topwin
        manager.find_fuzzy("bad uri", "table cell").doubleClick()
        uiutils.check(lambda: not manager.active)
        self._click_alert_button("Unable to connect", "Close")
        uiutils.check(lambda: manager.active)
