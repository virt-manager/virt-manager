# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import signal
import subprocess
import sys
import time

from gi.repository import Gio
import dogtail.rawinput
import dogtail.tree

from virtinst import log
import tests.utils
from . import utils


class VMMDogtailApp(object):
    """
    Wrapper class to simplify dogtail app handling
    """
    def __init__(self, uri=tests.utils.URIs.test_full):
        self._proc = None
        self._root = None
        self._topwin = None
        self.uri = uri


    ####################################
    # Helpers to save testcase imports #
    ####################################

    def check(self, *args, **kwargs):
        return utils.check(*args, **kwargs)

    def sleep(self, *args, **kwargs):
        return time.sleep(*args, **kwargs)

    rawinput = dogtail.rawinput
    tree = dogtail.tree


    #################################
    # virt-manager specific helpers #
    #################################

    def open_host_window(self, tab, conn_label="test testdriver.xml"):
        """
        Helper to open host connection window and switch to a tab
        """
        self.root.find_fuzzy(conn_label, "table cell").click()
        self.root.find_fuzzy("Edit", "menu").click()
        self.root.find_fuzzy("Connection Details", "menu item").click()
        win = self.root.find_fuzzy(
                "%s - Connection Details" % conn_label, "frame")
        win.find_fuzzy(tab, "page tab").click()
        return win

    def open_details_window(self, vmname, shutdown=False, double=False):
        if double:
            self.root.find_fuzzy(vmname, "table cell").doubleClick()
        else:
            self.root.find_fuzzy(vmname, "table cell").click(button=3)
            self.root.find("Open", "menu item").click()

        win = self.root.find("%s on" % vmname, "frame")
        win.find("Details", "radio button").click()
        if shutdown:
            win.find("Shut Down", "push button").click()
            run = win.find("Run", "push button")
            utils.check(lambda: run.sensitive)
        return win

    def click_alert_button(self, label_text, button_text):
        alert = self.root.find("vmm dialog", "alert")
        alert.find_fuzzy(label_text, "label")
        alert.find(button_text, "push button").click()
        utils.check(lambda: not alert.active)

    def select_storagebrowser_volume(self, pool, vol, doubleclick=False):
        browsewin = self.root.find("vmm-storage-browser")
        browsewin.find_fuzzy(pool, "table cell").click()
        volcell = browsewin.find_fuzzy(vol, "table cell")
        if doubleclick:
            volcell.doubleClick()
        else:
            volcell.click()
            browsewin.find_fuzzy("Choose Volume").click()
        utils.check(lambda: not browsewin.active)


    ###########################
    # Process management APIs #
    ###########################

    @property
    def root(self):
        if self._root is None:
            self.open()
        return self._root

    @property
    def topwin(self):
        if self._topwin is None:
            self.open()
        return self._topwin

    def error_if_already_running(self):
        # Ensure virt-manager isn't already running
        dbus = Gio.DBusProxy.new_sync(
                Gio.bus_get_sync(Gio.BusType.SESSION, None), 0, None,
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", None)
        if "org.virt-manager.virt-manager" in dbus.ListNames():
            raise RuntimeError("virt-manager is already running. "
                    "Close it before running this test suite.")

    def is_running(self):
        return bool(self._proc and self._proc.poll() is None)

    def wait_for_exit(self):
        # Wait for shutdown for 2 sec
        waittime = 5
        self._proc.wait(timeout=waittime)

    def stop(self):
        """
        Try graceful process shutdown, then kill it
        """
        if not self._proc:
            return

        try:
            self._proc.send_signal(signal.SIGINT)
        except Exception:
            log.debug("Error terminating process", exc_info=True)
            self._proc = None
            return

        try:
            self.wait_for_exit()
        except subprocess.TimeoutExpired:
            log.warning("App didn't exit gracefully from SIGINT. Killing...")
            self._proc.kill()
            self.wait_for_exit()
            raise


    #####################################
    # virt-manager launching entrypoint #
    #####################################

    def open(self, uri=None,
            extra_opts=None, check_already_running=True, use_uri=True,
            window_name=None, xmleditor_enabled=False, keyfile=None,
            break_setfacl=False, first_run=True, no_fork=True,
            will_fail=False, enable_libguestfs=False,
            firstrun_uri=None):
        extra_opts = extra_opts or []
        uri = uri or self.uri

        if tests.utils.TESTCONFIG.debug and no_fork:
            stdout = sys.stdout
            stderr = sys.stderr
            extra_opts.append("--debug")
        else:
            stdout = open(os.devnull)
            stderr = open(os.devnull)

        cmd = [sys.executable]
        cmd += [os.path.join(tests.utils.TOPDIR, "virt-manager")]
        if no_fork:
            cmd += ["--no-fork"]
        if use_uri:
            cmd += ["--connect", uri]

        if first_run:
            cmd.append("--test-options=first-run")
            if not firstrun_uri:
                firstrun_uri = ""
        if firstrun_uri is not None:
            cmd.append("--test-options=firstrun-uri=%s" % firstrun_uri)
        if xmleditor_enabled:
            cmd.append("--test-options=xmleditor-enabled")
        if break_setfacl:
            cmd.append("--test-options=break-setfacl")
        if enable_libguestfs is True:
            cmd.append("--test-options=enable-libguestfs")
        if enable_libguestfs is False:
            cmd.append("--test-options=disable-libguestfs")
        if keyfile:
            import atexit
            import tempfile
            keyfile = tests.utils.UITESTDATADIR + "/keyfile/" + keyfile
            tempname = tempfile.mktemp(prefix="virtmanager-uitests-keyfile")
            open(tempname, "w").write(open(keyfile).read())
            atexit.register(lambda: os.unlink(tempname))
            cmd.append("--test-options=gsettings-keyfile=%s" % tempname)

        cmd += extra_opts

        if check_already_running:
            self.error_if_already_running()
        self._proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
        if not will_fail:
            self._root = dogtail.tree.root.application("virt-manager")
            self._topwin = self._root.find(window_name, "(frame|dialog|alert)")
