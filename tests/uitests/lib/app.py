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
        self._manager = None
        self.uri = uri


    ####################################
    # Helpers to save testcase imports #
    ####################################

    def check(self, *args, **kwargs):
        return utils.check(*args, **kwargs)

    def sleep(self, *args, **kwargs):
        return time.sleep(*args, **kwargs)

    def find_window(self, name, roleName=None, check_active=True):
        if roleName is None:
            roleName = "(frame|dialog|alert|window)"
        return self.root.find(name=name, roleName=roleName,
                recursive=False, check_active=check_active)

    rawinput = dogtail.rawinput
    tree = dogtail.tree


    #################################
    # virt-manager specific helpers #
    #################################

    def get_manager(self, check_active=True):
        if not self._manager:
            self._manager = self.find_window("Virtual Machine Manager",
                    check_active=check_active)
        return self._manager

    def find_details_window(self, vmname,
            click_details=False, shutdown=False):
        win = self.find_window("%s on" % vmname, "frame")
        if click_details:
            win.find("Details", "radio button").click()
        if shutdown:
            win.find("Shut Down", "push button").click()
            run = win.find("Run", "push button")
            utils.check(lambda: run.sensitive)
        return win

    def click_alert_button(self, label_text, button_text):
        alert = self.find_window("vmm dialog", "alert")
        alert.find_fuzzy(label_text, "label")
        alert.find(button_text, "push button").click()
        utils.check(lambda: not alert.active)

    def select_storagebrowser_volume(self, pool, vol, doubleclick=False):
        browsewin = self.find_window("vmm-storage-browser")
        browsewin.find_fuzzy(pool, "table cell").click()
        volcell = browsewin.find_fuzzy(vol, "table cell")
        if doubleclick:
            volcell.doubleClick()
        else:
            volcell.click()
            browsewin.find_fuzzy("Choose Volume").click()
        utils.check(lambda: not browsewin.active)


    ##########################
    # manager window helpers #
    ##########################

    def manager_open_createconn(self):
        manager = self.get_manager()
        manager.find("File", "menu").click()
        manager.find("Add Connection...", "menu item").click()
        win = self.root.find("Add Connection", "dialog")
        return win

    def manager_createconn(self, uri):
        win = self.manager_open_createconn()
        win.combo_select("Hypervisor", "Custom URI")
        win.find("uri-entry", "text").set_text(uri)
        win.find("Connect", "push button").click()
        utils.check(lambda: win.showing is False)

    def manager_get_conn_cell(self, conn_label):
        return self.get_manager().find(conn_label, "table cell")

    def manager_conn_connect(self, conn_label):
        c = self.manager_get_conn_cell(conn_label)
        c.click(button=3)
        self.root.find("conn-connect", "menu item").click()
        utils.check(lambda: "Not Connected" not in c.text)
        return c

    def manager_conn_disconnect(self, conn_label):
        c = self.manager_get_conn_cell(conn_label)
        c.click()
        utils.check(lambda: c.state_selected)
        c.click(button=3)
        menu = self.root.find("conn-menu", "menu")
        menu.find("conn-disconnect", "menu item").click()
        utils.check(lambda: "Not Connected" in c.text)
        return c

    def manager_conn_delete(self, conn_label):
        c = self.manager_get_conn_cell(conn_label)
        c.click(button=3)
        menu = self.root.find("conn-menu", "menu")
        menu.find("conn-delete", "menu item").click()
        self.click_alert_button("will remove the connection", "Yes")
        utils.check(lambda: c.dead)

    def manager_vm_action(self, vmname, confirm_click_no=False,
            run=False, shutdown=False, destroy=False, reset=False,
            reboot=False, pause=False, resume=False, save=False,
            restore=False, clone=False, migrate=False, delete=False,
            details=False):
        manager = self.get_manager()
        vmcell = manager.find(vmname + "\n", "table cell")

        if run:
            action = "Run"
        if shutdown:
            action = "Shut Down"
        if reboot:
            action = "Reboot"
        if reset:
            action = "Force Reset"
        if destroy:
            action = "Force Off"
        if pause:
            action = "Pause"
        if resume:
            action = "Resume"
        if save:
            action = "Save"
        if restore:
            action = "Restore"
        if clone:
            action = "Clone"
        if migrate:
            action = "Migrate"
        if delete:
            action = "Delete"
        if details:
            action = "Open"

        needs_shutdown = shutdown or destroy or reset or reboot or save
        needs_confirm = needs_shutdown or pause

        def _do_click():
            vmcell.click()
            vmcell.click(button=3)
            menu = self.root.find("vm-action-menu")
            utils.check(lambda: menu.onscreen)
            if needs_shutdown:
                smenu = menu.find("Shut Down", "menu")
                smenu.point()
                utils.check(lambda: smenu.onscreen)
                item = smenu.find(action, "menu item")
            else:
                item = menu.find(action, "menu item")
            utils.check(lambda: item.onscreen)
            item.point()
            utils.check(lambda: item.state_selected)
            item.click()
            return menu

        m = _do_click()
        if needs_confirm:
            if confirm_click_no:
                self.click_alert_button("Are you sure", "No")
                m = _do_click()
            self.click_alert_button("Are you sure", "Yes")
        utils.check(lambda: not m.onscreen)

    def manager_open_clone(self, vmname):
        self.manager_vm_action(vmname, clone=True)
        return self.find_window("Clone Virtual Machine")

    def manager_open_details(self, vmname, shutdown=False):
        self.manager_vm_action(vmname, details=True)
        win = self.find_details_window(vmname,
                shutdown=shutdown, click_details=True)
        return win

    def manager_open_host(self, tab, conn_label="test testdriver.xml"):
        """
        Helper to open host connection window and switch to a tab
        """
        self.root.find_fuzzy(conn_label, "table cell").click()
        self.root.find_fuzzy("Edit", "menu").click()
        self.root.find_fuzzy("Connection Details", "menu item").click()
        win = self.find_window("%s - Connection Details" % conn_label)
        tab = win.find_fuzzy(tab, "page tab")
        tab.point()
        tab.click()
        return win

    def manager_test_conn_window_cleanup(self, conn_label, childwin):
        # Give time for the child window to appear and possibly grab focus
        self.sleep(1)
        self.get_manager(check_active=False)
        dogtail.rawinput.dragWithTrajectory(childwin.title_coordinates(), (1000, 1000))
        self.manager_conn_disconnect(conn_label)
        utils.check(lambda: not childwin.showing)


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

    def has_dbus(self):
        dbus = Gio.DBusProxy.new_sync(
                Gio.bus_get_sync(Gio.BusType.SESSION, None), 0, None,
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", None)
        return "org.virt-manager.virt-manager" in dbus.ListNames()

    def error_if_already_running(self):
        # Ensure virt-manager isn't already running
        if self.has_dbus():
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
            break_setfacl=False, first_run=True,
            will_fail=False, enable_libguestfs=False,
            firstrun_uri=None, show_console=None, allow_debug=True):
        extra_opts = extra_opts or []
        uri = uri or self.uri

        if allow_debug and tests.utils.TESTCONFIG.debug:
            stdout = sys.stdout
            stderr = sys.stderr
            extra_opts.append("--debug")
        else:
            stdout = open(os.devnull)
            stderr = open(os.devnull)

        cmd = [sys.executable]
        cmd += [os.path.join(tests.utils.TOPDIR, "virt-manager")]
        if use_uri:
            cmd += ["--connect", uri]
        if show_console:
            cmd += ["--show-domain-console=%s" % show_console]

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
        if will_fail:
            return

        with utils.dogtail_timeout(10):
            # On Fedora 39 sometimes app launch from the test suite
            # takes a while for reasons I can't quite figure
            self._root = dogtail.tree.root.application("virt-manager")
            self._topwin = self.find_window(window_name)
