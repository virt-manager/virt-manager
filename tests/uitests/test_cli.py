# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest.mock

from . import lib


# UI tests for virt-manager's command line --show options


def testShowNewVM(app):
    app.open(
            uri="test:///default",
            extra_opts=["--show-domain-creator"])
    lib.utils.check(lambda: app.topwin.name == "New VM")
    app.topwin.window_close()
    app.wait_for_exit()


def testShowHost(app):
    app.open(
            uri="test:///default",
            extra_opts=["--show-host-summary"])

    lib.utils.check(lambda: app.topwin.name == "test default - Connection Details")
    nametext = app.topwin.find_fuzzy("Name:", "text")
    lib.utils.check(lambda: nametext.text == "test default")
    app.topwin.window_close()
    app.wait_for_exit()


def testShowDetails(app):
    app.open(
            extra_opts=["--show-domain-editor", "test-clone-simple"])

    lib.utils.check(lambda: "test-clone-simple on" in app.topwin.name)
    rlabel = app.topwin.find_fuzzy("Guest is not running", "label")
    lib.utils.check(lambda: not rlabel.showing)
    addhw = app.topwin.find_fuzzy("add-hardware", "button")
    lib.utils.check(lambda: addhw.showing)
    app.topwin.window_close()
    app.wait_for_exit()


def testShowPerformance(app):
    domid = "1"
    app.open(
            uri="test:///default",
            extra_opts=["--show-domain-performance", domid])

    lib.utils.check(lambda: "test on" in app.topwin.name)
    cpulabel = app.topwin.find_fuzzy("CPU usage", "label")
    lib.utils.check(lambda: cpulabel.showing)


def testShowConsole(app):
    # UUID of test-clone-simple
    uuid = "12345678-1234-ffff-1234-12345678ffff"
    app.open(
            extra_opts=["--show-domain-console", uuid])

    lib.utils.check(lambda: "test-clone-simple on" in app.topwin.name)
    rlabel = app.topwin.find_fuzzy("Guest is not running", "label")
    lib.utils.check(lambda: rlabel.showing)
    addhw = app.topwin.find_fuzzy("add-hardware", "button")
    lib.utils.check(lambda: not addhw.showing)


def testShowDelete(app):
    app.open(
            uri="test:///default",
            extra_opts=["--show-domain-delete", "test"],
            window_name="Delete")
    # Ensure details opened too
    app.root.find("test on", "frame", check_active=False)

    delete = app.topwin
    delete.find_fuzzy("Delete", "button").click()
    app.wait_for_exit()


def testShowSystray(app):
    opts = ["--test-options=fake-systray", "--show-systray"]
    app.open(use_uri=False,
             extra_opts=opts,
             window_name="vmm-fake-systray")
    app.sleep(1)
    app.stop()

    app.open(uri="test:///default",
             extra_opts=opts,
             window_name="vmm-fake-systray")


def testShowRemoteDBusConnect(app):
    """
    Test the remote app dbus connection
    """
    app.open()
    lib.utils.check(lambda: "testdriver" in app.topwin.fmt_nodes())
    lib.utils.check(lambda: "test default" not in app.topwin.fmt_nodes())

    def _run_remote(opts):
        newapp = lib.app.VMMDogtailApp("test:///default")
        newapp.open(check_already_running=False,
                extra_opts=opts)
        timeout = 10
        lib.utils.check(lambda: not newapp.is_running(), timeout)
        vapps = [a for a in newapp.tree.root.applications() if
                 a.name == "virt-manager"]
        lib.utils.check(lambda: len(vapps) == 1, timeout=timeout)
        # Ensure connection showed up
        app.topwin.find("test default", "table cell")

    _run_remote([])
    # Run remote again to trigger engine.py code when a connection
    # is already there and connected
    _run_remote(["--show-domain-console=test"])


def testShowCLIError(app):
    # Unknown option
    app.open(
            extra_opts=["--idontexist"])
    app.click_alert_button("Unhandled command line", "Close")
    lib.utils.check(lambda: not app.is_running())

    # Missing VM
    app.open(
            uri="test:///default",
            extra_opts=["--show-domain-delete", "IDONTEXIST"])
    app.click_alert_button("does not have VM", "Close")
    lib.utils.check(lambda: not app.is_running())

    # Bad URI
    baduri = "fribfrobfroo"
    app = lib.app.VMMDogtailApp(baduri)
    app.click_alert_button(baduri, "Close")
    lib.utils.check(lambda: not app.is_running())


def testCLIFirstRunURIGood(app):
    # Emulate first run with a URI that will succeed
    app.open(use_uri=False, firstrun_uri="test:///default")
    app.root.find("test default", "table cell")


def testCLIFirstRunURIBad(app):
    # Emulate first run with a URI that will not succeed
    app.open(use_uri=False, firstrun_uri="bad:///uri")
    app.topwin.find("bad uri", "table cell")
    app.click_alert_button("bad:///uri", "Close")


def testCLIFirstRunNoURI(app):
    # Emulate first run with no libvirtd detected
    app.open(use_uri=False, firstrun_uri="")
    errlabel = app.topwin.find("error-label")
    lib.utils.check(
            lambda: "Checking for virtualization" in errlabel.text)
    lib.utils.check(
            lambda: "detect a default hypervisor" in errlabel.text)


def testCLITraceLibvirt(app):
    # Just test this for code coverage
    app.open(keyfile="allstats.ini",
             extra_opts=["--trace-libvirt=mainloop",
                         "--test-options=short-poll"])
    app.sleep(.5)  # Give time for polling to trigger
    lib.utils.check(lambda: app.topwin.active)


def testCLILeakDebug(app):
    # Just test this for code coverage
    app.open(keyfile="allstats.ini",
             extra_opts=["--test-options=leak-debug",
                         "--test-options=short-poll"])
    app.sleep(.5)  # Give time for polling to trigger
    app.topwin.window_close()
    app.wait_for_exit()


def testCLINoFirstRun(app):
    # Test a simple case of loading without any config override
    app.open(first_run=False, enable_libguestfs=None, use_uri=False)
    lib.utils.check(lambda: app.topwin.showing)


def _testCLIFork(app, opts):
    app.open(first_run=False, enable_libguestfs=None,
            use_uri=False, allow_debug=False,
            extra_opts=opts)
    app.wait_for_exit()
    lib.utils.check(lambda: app.has_dbus())
    app.topwin.window_close()
    lib.utils.check(lambda: not app.has_dbus())


def testCLIFork(app):
    # Test app with --fork
    _testCLIFork(app, ["--fork"])


@unittest.mock.patch.dict('os.environ', {"VIRT_MANAGER_DEFAULT_FORK": "yes"})
def testCLIForkEnv(app):
    # Test with fork via env
    _testCLIFork(app, [])


def testCLIGTKArgs(app):
    # Ensure gtk arg passthrough works
    # Also test --no-fork is a no-op
    app.open(extra_opts=["--gtk-debug=misc", "--no-fork"])
    lib.utils.check(lambda: app.topwin.showing)


@unittest.mock.patch.dict('os.environ', {"DISPLAY": ""})
def testCLINoDisplay(app):
    # Ensure missing display exits
    app.open(will_fail=True)
    app.wait_for_exit()
