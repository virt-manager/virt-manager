from tests.uitests import utils as uiutils


class VMMMigrate(uiutils.UITestCase):
    """
    UI tests for the migrate dialog
    """

    ##############
    # Test cases #
    ##############

    def testMigrate(self):
        # Add an additional connection
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        win.find_fuzzy("Hypervisor", "combo box").click()
        win.find_fuzzy("Custom URI", "menu item").click()
        win.find("uri-entry", "text").text = "test:///default"
        win.find("Connect", "push button").click()

        uiutils.check_in_loop(lambda: win.showing is False)
        c = self.app.root.find("test-many-devices", "table cell")
        c.click(button=3)
        self.app.root.find("Migrate...", "menu item").click()

        mig = self.app.root.find("Migrate the virtual machine", "frame")
        mig.find("Advanced", "toggle button").click_expander()
        mig.find("Migrate", "push button").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("the connection driver: virDomainMigrate")
        alert.find("Close", "push button").click()
        mig.find("Cancel", "push button").click()
        uiutils.check_in_loop(lambda: not mig.showing)
