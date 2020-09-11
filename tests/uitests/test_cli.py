# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest.mock

from . import lib


class VMMCLI(lib.testcase.UITestCase):
    """
    UI tests for virt-manager's command line --show options
    """

    ##############
    # Test cases #
    ##############

    def testShowNewVM(self):
        self.app.open(extra_opts=["--show-domain-creator"])
        lib.utils.check(lambda: self.app.topwin.name == "New VM")
        self.app.topwin.keyCombo("<alt>F4")
        lib.utils.check(lambda: self.app.is_running() is False)

    def testShowHost(self):
        self.app.open(extra_opts=["--show-host-summary"])

        lib.utils.check(lambda: self.app.topwin.name == "test testdriver.xml Connection Details")
        nametext = self.app.topwin.find_fuzzy("Name:", "text")
        lib.utils.check(lambda: nametext.text == "test testdriver.xml")
        self.app.topwin.keyCombo("<alt>F4")
        lib.utils.check(lambda: self.app.is_running() is False)

    def testShowDetails(self):
        self.app.open(extra_opts=["--show-domain-editor", "test-clone-simple"])

        lib.utils.check(lambda: "test-clone-simple on" in self.app.topwin.name)
        rlabel = self.app.topwin.find_fuzzy("Guest is not running", "label")
        lib.utils.check(lambda: not rlabel.showing)
        addhw = self.app.topwin.find_fuzzy("add-hardware", "button")
        lib.utils.check(lambda: addhw.showing)
        self.app.topwin.keyCombo("<alt>F4")
        lib.utils.check(lambda: self.app.is_running() is False)

    def testShowPerformance(self):
        domid = "1"
        self.app.open(extra_opts=["--show-domain-performance", domid])

        lib.utils.check(lambda: "test on" in self.app.topwin.name)
        cpulabel = self.app.topwin.find_fuzzy("CPU usage", "label")
        lib.utils.check(lambda: cpulabel.showing)

    def testShowConsole(self):
        # UUID of test-clone-simple
        uuid = "12345678-1234-ffff-1234-12345678ffff"
        self.app.open(extra_opts=["--show-domain-console", uuid])

        lib.utils.check(lambda: "test-clone-simple on" in self.app.topwin.name)
        rlabel = self.app.topwin.find_fuzzy("Guest is not running", "label")
        lib.utils.check(lambda: rlabel.showing)
        addhw = self.app.topwin.find_fuzzy("add-hardware", "button")
        lib.utils.check(lambda: not addhw.showing)

    def testShowDelete(self):
        self.app.open(
                extra_opts=["--show-domain-delete", "test-clone"],
                window_name="Delete")
        # Ensure details opened too
        self.app.root.find("test-clone on", "frame",
                check_active=False)

        delete = self.app.topwin
        delete.find_fuzzy("Delete", "button").click()
        self.app.click_alert_button("Are you sure", "Yes")

        # Ensure app exits
        lib.utils.check(lambda: not self.app.is_running())


    def testShowRemoteDBusConnect(self):
        """
        Test the remote app dbus connection
        """
        self.app.open()
        lib.utils.check(lambda: "testdriver" in self.app.topwin.fmt_nodes())
        lib.utils.check(lambda: "test default" not in self.app.topwin.fmt_nodes())

        def _run_remote(opts):
            newapp = lib.app.VMMDogtailApp("test:///default")
            newapp.open(check_already_running=False,
                    extra_opts=opts)
            lib.utils.check(lambda: not newapp.is_running())
            vapps = [a for a in newapp.tree.root.applications() if
                     a.name == "virt-manager"]
            lib.utils.check(lambda: len(vapps) == 1)
            # Ensure connection showed up
            self.app.topwin.find("test default", "table cell")

        _run_remote([])
        # Run remote again to trigger engine.py code when a connection
        # is already there and connected
        _run_remote(["--show-domain-console=test"])

    def testShowCLIError(self):
        # Unknown option
        self.app.open(extra_opts=["--idontexist"])
        self.app.click_alert_button("Unhandled command line", "Close")
        lib.utils.check(lambda: not self.app.is_running())

        # Missing VM
        self.app.open(extra_opts=["--show-domain-delete", "IDONTEXIST"])
        self.app.click_alert_button("does not have VM", "Close")
        lib.utils.check(lambda: not self.app.is_running())

        # Bad URI
        baduri = "fribfrobfroo"
        self.app = lib.app.VMMDogtailApp(baduri)
        self.app.click_alert_button(baduri, "Close")
        lib.utils.check(lambda: not self.app.is_running())

    def testCLIFirstRunURIGood(self):
        # Emulate first run with a URI that will succeed
        self.app.open(use_uri=False, firstrun_uri="test:///default")
        self.app.root.find("test default", "table cell")

    def testCLIFirstRunURIBad(self):
        # Emulate first run with a URI that will succeed
        self.app.open(use_uri=False, firstrun_uri="bad:///uri")
        self.app.topwin.find("bad uri", "table cell")
        self.app.click_alert_button("bad:///uri", "Close")

    def testCLITraceLibvirt(self):
        # Just test this for code coverage
        self.app.open(keyfile="allstats.ini",
                extra_opts=["--trace-libvirt=mainloop"])
        # Give it a little time to work
        self.app.sleep(2)
        lib.utils.check(lambda: self.app.topwin.active)

    def testCLILeakDebug(self):
        # Just test this for code coverage
        self.app.open(keyfile="allstats.ini",
                extra_opts=["--test-options=leak-debug"])
        self.app.sleep(2)
        # Give it a little time to work
        lib.utils.check(lambda: self.app.topwin.active)
        self.app.topwin.keyCombo("<alt>F4")

    def testCLINoFirstRun(self):
        # Test a simple case of loading without any config override
        self.app.open(first_run=False, enable_libguestfs=None, use_uri=False)
        self.app.sleep(2)
        lib.utils.check(lambda: self.app.topwin.showing)

    def testCLINoFork(self):
        # Test app without forking
        self.app.open(first_run=False, enable_libguestfs=None,
                use_uri=False, no_fork=False)
        assert self.app.wait_for_exit() is True
        lib.utils.check(lambda: self.app.topwin.showing)
        self.app.topwin.keyCombo("<alt>F4")

    def testCLIGTKArgs(self):
        # Ensure gtk arg passthrough works
        self.app.open(extra_opts=["--gtk-debug=misc"])
        lib.utils.check(lambda: self.app.topwin.showing)
        self.app.topwin.keyCombo("<alt>F4")

    @unittest.mock.patch.dict('os.environ', {"DISPLAY": ""})
    def testCLINoDisplay(self):
        # Ensure missing display exits
        self.app.open(will_fail=True)
        self.app.wait_for_exit()
