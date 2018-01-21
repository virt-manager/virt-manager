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

    def testShowHost(self):
        self.app.open(extra_opts=["--show-host-summary"])

        self.assertEqual(self.app.topwin.name,
            "test testdriver.xml Connection Details")
        self.assertEqual(
            self.app.topwin.find_fuzzy("Name:", "text").text,
            "test testdriver.xml")

    def testShowDetails(self):
        self.app.open(extra_opts=["--show-domain-editor", "test-clone-simple"])

        self.assertTrue("test-clone-simple on" in self.app.topwin.name)
        self.assertFalse(
            self.app.topwin.find_fuzzy(
                               "Guest is not running", "label").showing)
        self.assertTrue(
            self.app.topwin.find_fuzzy(
                               "add-hardware", "button").showing)

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

    def testShowRemoteConnect(self):
        """
        Test the remote app dbus connection
        """
        self.app.open()
        newapp = uiutils.VMMDogtailApp("test:///default")
        newapp.open()
        uiutils.check_in_loop(lambda: not newapp.is_running())
        import dogtail.tree
        vapps = [a for a in dogtail.tree.root.applications() if
                 a.name == "virt-manager"]
        self.assertEqual(len(vapps), 1)

        self.app.topwin.find("test default", "table cell")

    def testShowError(self):
        self.app.open(extra_opts=["--idontexist"])
        alert = self.app.root.find("vmm dialog")
        alert.find_fuzzy("Unhandled command line")
