# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest.mock

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
        uiutils.check(lambda: self.app.topwin.name == "New VM")
        self.app.topwin.keyCombo("<alt>F4")
        uiutils.check(lambda: self.app.is_running() is False)

    def testShowHost(self):
        self.app.open(extra_opts=["--show-host-summary"])

        uiutils.check(lambda: self.app.topwin.name == "test testdriver.xml Connection Details")
        nametext = self.app.topwin.find_fuzzy("Name:", "text")
        uiutils.check(lambda: nametext.text == "test testdriver.xml")
        self.app.topwin.keyCombo("<alt>F4")
        uiutils.check(lambda: self.app.is_running() is False)

    def testShowDetails(self):
        self.app.open(extra_opts=["--show-domain-editor", "test-clone-simple"])

        uiutils.check(lambda: "test-clone-simple on" in self.app.topwin.name)
        rlabel = self.app.topwin.find_fuzzy("Guest is not running", "label")
        uiutils.check(lambda: not rlabel.showing)
        addhw = self.app.topwin.find_fuzzy("add-hardware", "button")
        uiutils.check(lambda: addhw.showing)
        self.app.topwin.keyCombo("<alt>F4")
        uiutils.check(lambda: self.app.is_running() is False)

    def testShowPerformance(self):
        domid = "1"
        self.app.open(extra_opts=["--show-domain-performance", domid])

        uiutils.check(lambda: "test on" in self.app.topwin.name)
        cpulabel = self.app.topwin.find_fuzzy("CPU usage", "label")
        uiutils.check(lambda: cpulabel.showing)

    def testShowConsole(self):
        # UUID of test-clone-simple
        uuid = "12345678-1234-ffff-1234-12345678ffff"
        self.app.open(extra_opts=["--show-domain-console", uuid])

        uiutils.check(lambda: "test-clone-simple on" in self.app.topwin.name)
        rlabel = self.app.topwin.find_fuzzy("Guest is not running", "label")
        uiutils.check(lambda: rlabel.showing)
        addhw = self.app.topwin.find_fuzzy("add-hardware", "button")
        uiutils.check(lambda: not addhw.showing)

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
        uiutils.check(lambda: not self.app.is_running())


    def testShowRemoteDBusConnect(self):
        """
        Test the remote app dbus connection
        """
        self.app.open()
        uiutils.check(lambda: "testdriver" in self.app.topwin.fmt_nodes())
        uiutils.check(lambda: "test default" not in self.app.topwin.fmt_nodes())

        def _run_remote(opts):
            newapp = uiutils.VMMDogtailApp("test:///default")
            newapp.open(check_already_running=False,
                    extra_opts=opts)
            uiutils.check(lambda: not newapp.is_running())
            import dogtail.tree
            vapps = [a for a in dogtail.tree.root.applications() if
                     a.name == "virt-manager"]
            uiutils.check(lambda: len(vapps) == 1)
            # Ensure connection showed up
            self.app.topwin.find("test default", "table cell")

        _run_remote([])
        # Run remote again to trigger engine.py code when a connection
        # is already there and connected
        _run_remote(["--show-domain-console=test"])

    def testShowCLIError(self):
        # Unknown option
        self.app.open(extra_opts=["--idontexist"])
        self._click_alert_button("Unhandled command line", "Close")
        uiutils.check(lambda: not self.app.is_running())

        # Missing VM
        self.app.open(extra_opts=["--show-domain-delete", "IDONTEXIST"])
        self._click_alert_button("does not have VM", "Close")
        uiutils.check(lambda: not self.app.is_running())

        # Bad URI
        baduri = "fribfrobfroo"
        self.app = uiutils.VMMDogtailApp(baduri)
        self._click_alert_button(baduri, "Close")
        uiutils.check(lambda: not self.app.is_running())

    def testCLIFirstRunURIGood(self):
        # Emulate first run with a URI that will succeed
        self.app.open(use_uri=False, firstrun_uri="test:///default")
        self.app.root.find("test default", "table cell")

    def testCLIFirstRunURIBad(self):
        # Emulate first run with a URI that will succeed
        self.app.open(use_uri=False, firstrun_uri="bad:///uri")
        self.app.topwin.find("bad uri", "table cell")
        self._click_alert_button("bad:///uri", "Close")

    def testCLITraceLibvirt(self):
        # Just test this for code coverage
        self.app.open(keyfile="allstats.ini",
                extra_opts=["--trace-libvirt=mainloop"])
        # Give it a little time to work
        self.sleep(2)
        uiutils.check(lambda: self.app.topwin.active)

    def testCLILeakDebug(self):
        # Just test this for code coverage
        self.app.open(keyfile="allstats.ini",
                extra_opts=["--test-options=leak-debug"])
        self.sleep(2)
        # Give it a little time to work
        uiutils.check(lambda: self.app.topwin.active)
        self.app.topwin.keyCombo("<alt>F4")

    def testCLINoFirstRun(self):
        # Test a simple case of loading without any config override
        self.app.open(first_run=False, enable_libguestfs=None, use_uri=False)
        self.sleep(2)
        uiutils.check(lambda: self.app.topwin.showing)

    def testCLINoFork(self):
        # Test app without forking
        self.app.open(first_run=False, enable_libguestfs=None,
                use_uri=False, no_fork=False)
        assert self.app.wait_for_exit() is True
        uiutils.check(lambda: self.app.topwin.showing)
        self.app.topwin.keyCombo("<alt>F4")

    def testCLIGTKArgs(self):
        # Ensure gtk arg passthrough works
        self.app.open(extra_opts=["--gtk-debug=misc"])
        uiutils.check(lambda: self.app.topwin.showing)
        self.app.topwin.keyCombo("<alt>F4")

    @unittest.mock.patch.dict('os.environ', {"DISPLAY": ""})
    def testCLINoDisplay(self):
        # Ensure missing display exits
        self.app.open(will_fail=True)
        self.app.wait_for_exit()
