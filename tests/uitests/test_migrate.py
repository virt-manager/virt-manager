# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests import utils
from tests.uitests import utils as uiutils


class VMMMigrate(uiutils.UITestCase):
    """
    UI tests for the migrate dialog
    """

    ##############
    # Test cases #
    ##############

    def _add_conn(self, uri):
        manager = self.app.root
        manager.find("File", "menu").click()
        manager.find("Add Connection...", "menu item").click()
        win = manager.find_fuzzy("Add Connection", "dialog")
        win.combo_select("Hypervisor", "Custom URI")
        win.find("uri-entry", "text").set_text(uri)
        win.find("Connect", "push button").click()
        uiutils.check(lambda: win.showing is False)

    def _open_migrate(self, vmname):
        c = self.app.root.find(vmname, "table cell")
        c.click(button=3)
        self.app.root.find("Migrate...", "menu item").click()
        return self.app.root.find("Migrate the virtual machine", "frame")

    def testMigrateQemu(self):
        # Use fake qemu connections
        self.app.uri = utils.URIs.kvm
        self._add_conn(utils.URIs.test_default +
                ",fakeuri=qemu+tcp://fakehost/system")

        # Run default migrate
        mig = self._open_migrate("test-many-devices")
        mig.find("Migrate", "push button").click()
        self._click_alert_button(
                "the.connection.driver:.virDomainMigrate", "Close")
        mig.find("Cancel", "push button").click()
        uiutils.check(lambda: not mig.showing)

        # Run with deselected URI
        mig = self._open_migrate("test-many-devices")
        mig.find("address-check").click()
        label = mig.find("Let libvirt decide")
        uiutils.check(lambda: label.onscreen)
        mig.find("Migrate", "push button").click()
        self._click_alert_button(
                "the.connection.driver:.virDomainMigrate", "Close")
        mig.find("Cancel", "push button").click()
        uiutils.check(lambda: not mig.showing)

        # Run with tunnelled and other options
        mig = self._open_migrate("test-many-devices")
        mig.combo_select("Mode:", "Tunnelled")
        mig.find("Advanced", "toggle button").click_expander()
        mig.find("Allow unsafe:", "check box").click()
        mig.find("Temporary", "check box").click()

        mig.find("Migrate", "push button").click()
        self._click_alert_button("p2p migration", "Close")
        mig.find("Cancel", "push button").click()
        uiutils.check(lambda: not mig.showing)

    def testMigrateXen(self):
        # Use fake xen connections
        self.app.uri = utils.URIs.test_full + ",fakeuri=xen:///"

        fakeremotexen = (utils.URIs.test_default +
                ",fakeuri=xen+tcp://fakehost/")
        self._add_conn(fakeremotexen)

        # Run default migrate
        mig = self._open_migrate("test-many-devices")
        mig.find("Migrate", "push button").click()
        self._click_alert_button(
                "the.connection.driver:.virDomainMigrate", "Close")
        mig.find("Cancel", "push button").click()
        uiutils.check(lambda: not mig.showing)

    def testMigrateMock(self):
        """
        Trigger the mock migration testing we have to emulate success
        """
        # Add an additional connection
        self._add_conn("test:///default")

        # Run it and check some values
        mig = self._open_migrate("test-many-devices")
        mig.find("address-text").set_text("TESTSUITE-FAKE")

        mig.find("Migrate", "push button").click()
        progwin = self.app.root.find("Migrating VM", "frame")
        # Attempt cancel which will fail, then find the error message
        progwin.find("Cancel", "push button").click()
        progwin.find("Error cancelling migrate job")
        uiutils.check(lambda: not progwin.showing, timeout=5)
        uiutils.check(lambda: not mig.showing)

    def testMigrateConnMismatch(self):
        # Add a possible target but disconnect it
        self.app.uri = utils.URIs.test_default
        c = self.app.root.find("test default", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()

        # Add a mismatched hv connection
        fakexen = utils.URIs.test_empty + ",fakeuri=xen:///"
        self._add_conn(fakexen)

        # Open dialog and confirm no conns are available
        self._add_conn(utils.URIs.test_full)
        mig = self._open_migrate("test-many-devices")
        mig.find("conn-combo").find("No usable", "menu item")
        mig.keyCombo("<alt>F4")
        uiutils.check(lambda: not mig.showing)

    def testMigrateXMLEditor(self):
        self.app.open(xmleditor_enabled=True)
        manager = self.app.topwin

        # Add an additional connection
        self._add_conn("test:///default")

        # Run it and check some values
        vmname = "test-many-devices"
        win = self._open_migrate(vmname)
        win.find("address-text").set_text("TESTSUITE-FAKE")

        # Create a new obj with XML edited name, verify it worked
        newname = "aafroofroo"
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        newtext = xmleditor.text.replace(
                ">%s<" % vmname, ">%s<" % newname)
        xmleditor.set_text(newtext)
        win.find("Migrate", "push button").click()
        uiutils.check(lambda: not win.showing, timeout=10)

        manager.find(newname, "table cell")

        # Do standard xmleditor tests
        win = self._open_migrate(vmname)
        win.find("address-text").set_text("TESTSUITE-FAKE")
        finish = win.find("Migrate", "push button")
        self._test_xmleditor_interactions(win, finish)
        win.find("Cancel", "push button").click()
        uiutils.check(lambda: not win.visible)
