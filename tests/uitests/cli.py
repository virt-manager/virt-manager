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
            uiutils.find_fuzzy(self.app.topwin, None, "text", "Name:").text,
            "test testdriver.xml")

    def testShowDetails(self):
        self.app.open(extra_opts=["--show-domain-editor", "test-clone-simple"])

        self.assertTrue("test-clone-simple on" in self.app.topwin.name)
        self.assertFalse(
            uiutils.find_fuzzy(self.app.topwin,
                               "Guest is not running", "label").showing)
        self.assertTrue(
            uiutils.find_fuzzy(self.app.topwin,
                               "add-hardware", "button").showing)

    def testShowPerformance(self):
        self.app.open(extra_opts=["--show-domain-performance",
            "test-clone-simple"])

        self.assertTrue("test-clone-simple on" in self.app.topwin.name)
        self.assertFalse(
            uiutils.find_fuzzy(self.app.topwin,
                               "Guest is not running", "label").showing)
        self.assertTrue(
            uiutils.find_fuzzy(self.app.topwin, "CPU usage", "label").showing)

    def testShowConsole(self):
        self.app.open(extra_opts=["--show-domain-console", "test-clone-simple"])

        self.assertTrue("test-clone-simple on" in self.app.topwin.name)
        self.assertTrue(
            uiutils.find_fuzzy(self.app.topwin,
                               "Guest is not running", "label").showing)
        self.assertFalse(
            uiutils.find_fuzzy(self.app.topwin,
                               "add-hardware", "button").showing)
