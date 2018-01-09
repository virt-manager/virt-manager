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

        uiutils.find_pattern(self.app.root, "New VM", "frame")

    def testShowHost(self):
        self.app.open(extra_opts=["--show-host-summary"])

        win = uiutils.find_pattern(self.app.root,
            "test testdriver.xml Connection Details", "frame")
        self.assertEqual(
            uiutils.find_fuzzy(win, None, "text", "Name:").text,
            "test testdriver.xml")

    def testShowDetails(self):
        self.app.open(extra_opts=["--show-domain-editor", "test-clone-simple"])

        win = uiutils.find_fuzzy(self.app.root, "test-clone-simple on", "frame")
        self.assertFalse(
            uiutils.find_fuzzy(win, "Guest is not running", "label").showing)
        self.assertTrue(
            uiutils.find_fuzzy(win, "add-hardware", "button").showing)

    def testShowPerformance(self):
        self.app.open(extra_opts=["--show-domain-performance",
            "test-clone-simple"])

        win = uiutils.find_fuzzy(self.app.root, "test-clone-simple on", "frame")
        self.assertFalse(
            uiutils.find_fuzzy(win, "Guest is not running", "label").showing)
        self.assertTrue(
            uiutils.find_fuzzy(win, "CPU usage", "label").showing)

    def testShowConsole(self):
        self.app.open(extra_opts=["--show-domain-console", "test-clone-simple"])

        win = uiutils.find_fuzzy(self.app.root, "test-clone-simple on", "frame")
        self.assertTrue(
            uiutils.find_fuzzy(win, "Guest is not running", "label").showing)
        self.assertFalse(
            uiutils.find_fuzzy(win, "add-hardware", "button").showing)
