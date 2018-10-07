# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import dogtail.rawinput

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
        Basic VM lifecycle test, shared between standard and --test-no-events
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
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find("Are you sure you want", "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: run.sensitive, timeout=5)

        run.click()
        uiutils.check_in_loop(lambda: not run.sensitive, timeout=5)
        pause.click()
        uiutils.check_in_loop(lambda: pause.checked, timeout=5)
        smenu.click()
        save.click()
        uiutils.check_in_loop(lambda: run.sensitive, timeout=5)
        self.assertTrue("Saved" in c.text)
        run.click()
        uiutils.check_in_loop(lambda: shutdown.sensitive, timeout=5)

    def testVMLifecycle(self):
        self._testVMLifecycle()

    def testVMNoEventsLifecycle(self):
        self.app.open(extra_opts=["--test-no-events"])

        # Change preferences timeout to 1 second
        self.app.root.find("Edit", "menu").click()
        self.app.root.find("Preferences", "menu item").click()
        win = self.app.root.find_fuzzy("Preferences", "frame")
        win.find("Polling", "page tab").click()
        win.find("cpu-poll").text = "1"
        win.find("Close", "push button").click()

        self._testVMLifecycle()

    def testManagerColumns(self):
        # Enable all stat options
        self.app.root.find("Edit", "menu").click()
        self.app.root.find("Preferences", "menu item").click()
        win = self.app.root.find_fuzzy("Preferences", "frame")
        win.find("Polling", "page tab").click()
        win.find_fuzzy("Poll Disk", "check").click()
        win.find_fuzzy("Poll Network", "check").click()
        win.find_fuzzy("Poll Memory", "check").click()
        win.find("Close", "push button").click()

        manager = self.app.topwin
        manager.find("View", "menu").click()
        manager.find("Graph", "menu").point()
        manager.find("Host CPU", "check menu item").click()
        manager.find("View", "menu").click()
        manager.find("Graph", "menu").point()
        manager.find("Memory Usage", "check menu item").click()
        manager.find("View", "menu").click()
        manager.find("Graph", "menu").point()
        manager.find("Disk I/O", "check menu item").click()
        manager.find("View", "menu").click()
        manager.find("Graph", "menu").point()
        manager.find("Network I/O", "check menu item").click()

        # Verify columns showed up
        manager.find("Name", "table column header")
        manager.find("CPU usage", "table column header")
        manager.find("Host CPU usage", "table column header")
        manager.find("Memory usage", "table column header")
        manager.find("Disk I/O", "table column header")
        manager.find("Network I/O", "table column header")

    def testManagerWindowCleanup(self):
        """
        Open migrate, clone, delete, newvm, details, host windows, close the
        connection, make sure they all disappear
        """
        def _drag(win):
            """
            Drag a window so it's not obscuring the manager window
            """
            win.click()
            clickX = win.position[0] + win.size[0] / 2
            clickY = win.position[1] + 10
            dogtail.rawinput.drag((clickX, clickY), (1000, 1000))

        manager = self.app.topwin

        # Open migrate dialog
        c = manager.find("test-many-devices", "table cell")
        c.click(button=3)
        self.app.root.find("Migrate...", "menu item").click()
        migrate = self.app.root.find("Migrate the virtual machine", "frame")
        _drag(migrate)

        # Open clone dialog
        c = manager.find("test-clone", "table cell")
        c.click(button=3)
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
        host = self._open_host_window("Virtual Networks")
        _drag(host)

        # Open details
        details = self._open_details_window("test-many-devices")
        _drag(details)

        # Close the connection
        c = manager.find_fuzzy("testdriver.xml", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()

        # Ensure all those windows aren't showing
        uiutils.check_in_loop(lambda: not migrate.showing)
        uiutils.check_in_loop(lambda: not clone.showing)
        uiutils.check_in_loop(lambda: not create.showing)
        uiutils.check_in_loop(lambda: not details.showing)
        uiutils.check_in_loop(lambda: not delete.showing)

        # Delete the connection, ensure the host dialog disappears
        c = manager.find_fuzzy("testdriver.xml", "table cell")
        c.click(button=3)
        self.app.root.find("conn-delete", "menu item").click()
        err = self.app.root.find("vmm dialog", "alert")
        err.find_fuzzy("will remove the connection", "label")
        err.find_fuzzy("Yes", "push button").click()
        uiutils.check_in_loop(lambda: not host.showing)

    def testManagerDefaultStartup(self):
        self.app.open(use_uri=False)
        manager = self.app.topwin
        errlabel = manager.find("error-label")
        uiutils.check_in_loop(
                lambda: "Checking for virtualization" in errlabel.text)
        uiutils.check_in_loop(
                lambda: "File->Add Connection" in errlabel.text)
        uiutils.check_in_loop(
                lambda: "appropriate qemu/kvm" in errlabel.text)
