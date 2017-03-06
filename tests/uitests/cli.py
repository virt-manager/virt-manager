import time
import unittest

import tests
from tests.uitests import utils as uiutils


class VMMCLI(unittest.TestCase):
    """
    UI tests for virt-manager's command line --show options
    """
    def setUp(self):
        self.app = uiutils.DogtailApp(tests.utils.uri_test)
    def tearDown(self):
        self.app.kill()


    ##############
    # Test cases #
    ##############

    def testShowNewVM(self):
        self.app.open(extra_opts=["--show-domain-creator"])
        time.sleep(.5)

        uiutils.find_pattern(self.app.root, "New VM", "frame")
        self.app.quit()

    def testShowHost(self):
        self.app.open(extra_opts=["--show-host-summary"])
        time.sleep(.5)

        win = uiutils.find_pattern(self.app.root,
            "test testdriver.xml Connection Details", "frame")
        self.assertEquals(
            uiutils.find_fuzzy(win, None, "text", "Name:").text,
            "test testdriver.xml")
        self.app.quit()

    def testShowDetails(self):
        self.app.open(extra_opts=["--show-domain-editor", "test-clone-simple"])
        time.sleep(.5)

        win = uiutils.find_fuzzy(self.app.root, "test-clone-simple on", "frame")
        self.assertFalse(
            uiutils.find_fuzzy(win, "Guest is not running", "label").showing)
        self.assertTrue(
            uiutils.find_fuzzy(win, "add-hardware", "button").showing)
        self.app.quit()

    def testShowPerformance(self):
        self.app.open(extra_opts=["--show-domain-performance",
            "test-clone-simple"])
        time.sleep(.5)

        win = uiutils.find_fuzzy(self.app.root, "test-clone-simple on", "frame")
        self.assertFalse(
            uiutils.find_fuzzy(win, "Guest is not running", "label").showing)
        self.assertTrue(
            uiutils.find_fuzzy(win, "CPU usage", "label").showing)
        self.app.quit()

    def testShowConsole(self):
        self.app.open(extra_opts=["--show-domain-console", "test-clone-simple"])
        time.sleep(.5)

        win = uiutils.find_fuzzy(self.app.root, "test-clone-simple on", "frame")
        self.assertTrue(
            uiutils.find_fuzzy(win, "Guest is not running", "label").showing)
        self.assertFalse(
            uiutils.find_fuzzy(win, "add-hardware", "button").showing)
        self.app.quit()
