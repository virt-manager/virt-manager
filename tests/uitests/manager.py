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
