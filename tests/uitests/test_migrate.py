# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

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
        win.combo_select("Hypervisor", "Custom URI")
        win.find("uri-entry", "text").text = "test:///default"
        win.find("Connect", "push button").click()

        uiutils.check(lambda: win.showing is False)
        c = self.app.root.find("test-many-devices", "table cell")
        c.click(button=3)
        self.app.root.find("Migrate...", "menu item").click()

        mig = self.app.root.find("Migrate the virtual machine", "frame")
        mig.find("Advanced", "toggle button").click_expander()
        mig.find("Migrate", "push button").click()
        self._click_alert_button(
                "the.connection.driver:.virDomainMigrate", "Close")
        mig.find("Cancel", "push button").click()
        uiutils.check(lambda: not mig.showing)
