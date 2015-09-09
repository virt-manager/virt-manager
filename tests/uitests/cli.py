import time
import unittest

import tests
import tests.uitests



class VMMCLI(unittest.TestCase):
    """
    UI tests for virt-manager's command line --show options
    """
    def setUp(self):
        self.app = tests.uitests.utils.DogtailApp(tests.utils.uri_test)
    def tearDown(self):
        self.app.kill()


    ##############
    # Test cases #
    ##############

    def testShowNewVM(self):
        self.app.open(extra_opts=["--show-domain-creator"])
        time.sleep(.5)

        self.app.find_pattern(self.app.root,
            "Virtual Machine Manager", "frame")
        self.app.find_pattern(self.app.root, "New VM", "frame")
        self.app.quit()

    def testShowHost(self):
        self.app.open(extra_opts=["--show-host-summary"])
        time.sleep(.5)

        win = self.app.find_pattern(self.app.root,
            "test testdriver.xml Connection Details", "frame")
        self.assertEquals(
            self.app.find_fuzzy(win, None, "text", "Name:").text,
            "test testdriver.xml")
        self.app.quit()

    def testShowDetails(self):
        self.app.open(extra_opts=["--show-domain-editor", "test-for-clone"])
        time.sleep(.5)

        win = self.app.find_fuzzy(self.app.root, "test-for-clone on", "frame")
        self.assertFalse(
            self.app.find_fuzzy(win, "Graphical console not", "label").showing)
        self.assertTrue(
            self.app.find_fuzzy(win, "add-hardware", "button").showing)
        self.app.quit()

    def testShowPerformance(self):
        self.app.open(extra_opts=["--show-domain-performance",
            "test-for-clone"])
        time.sleep(.5)

        win = self.app.find_fuzzy(self.app.root, "test-for-clone on", "frame")
        self.assertFalse(
            self.app.find_fuzzy(win, "Graphical console not", "label").showing)
        self.assertTrue(
            self.app.find_fuzzy(win, "CPU usage", "label").showing)
        self.app.quit()

    def testShowConsole(self):
        self.app.open(extra_opts=["--show-domain-console", "test-for-clone"])
        time.sleep(.5)

        win = self.app.find_fuzzy(self.app.root, "test-for-clone on", "frame")
        self.assertTrue(
            self.app.find_fuzzy(win, "Graphical console not", "label").showing)
        self.assertFalse(
            self.app.find_fuzzy(win, "add-hardware", "button").showing)
        self.app.quit()
