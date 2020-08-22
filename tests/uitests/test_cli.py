# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests.uitests import utils as uiutils


class VMMCLI(uiutils.UITestCase):
    """
    UI tests for virt-manager's command line --show options
    """

    ##############
    # Test cases #
    ##############

    def testShowNewVM(self):
        self.app.open(extra_opts=["--show-domain-creator"])
        self.assertEqual(self.app.topwin.name, "New VM")
        self.app.topwin.keyCombo("<alt>F4")
        uiutils.check_in_loop(lambda: self.app.is_running() is False)

    def testShowHost(self):
        self.app.open(extra_opts=["--show-host-summary"])

        self.assertEqual(self.app.topwin.name,
            "test testdriver.xml Connection Details")
        self.assertEqual(
            self.app.topwin.find_fuzzy("Name:", "text").text,
            "test testdriver.xml")
        self.app.topwin.keyCombo("<alt>F4")
        uiutils.check_in_loop(lambda: self.app.is_running() is False)

    def testShowDetails(self):
        self.app.open(extra_opts=["--show-domain-editor", "test-clone-simple"])

        self.assertTrue("test-clone-simple on" in self.app.topwin.name)
        self.assertFalse(
            self.app.topwin.find_fuzzy(
                               "Guest is not running", "label").showing)
        self.assertTrue(
            self.app.topwin.find_fuzzy(
                               "add-hardware", "button").showing)
        self.app.topwin.keyCombo("<alt>F4")
        uiutils.check_in_loop(lambda: self.app.is_running() is False)

    def testShowPerformance(self):
        self.app.open(extra_opts=["--show-domain-performance",
            "test-clone-simple"])

        self.assertTrue("test-clone-simple on" in self.app.topwin.name)
        self.assertFalse(
            self.app.topwin.find_fuzzy(
                               "Guest is not running", "label").showing)
        self.assertTrue(
            self.app.topwin.find_fuzzy("CPU usage", "label").showing)

    def testShowConsole(self):
        self.app.open(extra_opts=["--show-domain-console", "test-clone-simple"])

        self.assertTrue("test-clone-simple on" in self.app.topwin.name)
        self.assertTrue(
            self.app.topwin.find_fuzzy(
                               "Guest is not running", "label").showing)
        self.assertFalse(
            self.app.topwin.find_fuzzy(
                               "add-hardware", "button").showing)

    def testShowDelete(self):
        self.app.open(
                extra_opts=["--show-domain-delete", "test-clone"],
                window_name="Delete")
        # Ensure details opened too
        self.app.root.find("test-clone on", "frame",
                check_active=False)

        delete = self.app.topwin
        delete.find_fuzzy("Delete", "button").click()
        self._click_alert_button("Are you sure", "Yes")

        # Ensure app exits
        uiutils.check_in_loop(lambda: not self.app.is_running())


    def testShowRemoteDBusConnect(self):
        """
        Test the remote app dbus connection
        """
        self.app.open()
        newapp = uiutils.VMMDogtailApp("test:///default")
        newapp.open(check_already_running=False)
        uiutils.check_in_loop(lambda: not newapp.is_running())
        import dogtail.tree
        vapps = [a for a in dogtail.tree.root.applications() if
                 a.name == "virt-manager"]
        self.assertEqual(len(vapps), 1)

        self.app.topwin.find("test default", "table cell")

    def testShowCLIError(self):
        # Unknown option
        self.app.open(extra_opts=["--idontexist"])
        self._click_alert_button("Unhandled command line", "Close")
        uiutils.check_in_loop(lambda: not self.app.is_running())

        # Missing VM
        self.app.open(extra_opts=["--show-domain-delete", "IDONTEXIST"])
        self._click_alert_button("does not have VM", "Close")
        uiutils.check_in_loop(lambda: not self.app.is_running())

        # Bad URI
        baduri = "fribfrobfroo"
        self.app = uiutils.VMMDogtailApp(baduri)
        self._click_alert_button(baduri, "Close")
        uiutils.check_in_loop(lambda: not self.app.is_running())

    def testCLITraceLibvirt(self):
        self.app.open(extra_opts=["--trace-libvirt=mainloop"])
        self.sleep(5)
