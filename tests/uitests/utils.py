from __future__ import print_function

import logging
import os
import re
import time
import signal
import subprocess
import sys
import unittest

import pyatspi
import dogtail.tree

import tests


class UITestCase(unittest.TestCase):
    """
    Common testcase bits shared for ui tests
    """
    def setUp(self):
        self.app = VMMDogtailApp(tests.utils.uri_test)
    def tearDown(self):
        self.app.stop()

    _default_vmname = "test-many-devices"

    # Helpers to save testfile imports
    @staticmethod
    def sleep(*args, **kwargs):
        return time.sleep(*args, **kwargs)
    @staticmethod
    def pressKey(*args, **kwargs):
        return dogtail.rawinput.pressKey(*args, **kwargs)

    def holdKey(self, keyName):
        # From dogtail 9.9.0 which isn't widely distributed yet
        code = dogtail.rawinput.keyNameToKeyCode(keyName)
        pyatspi.Registry().generateKeyboardEvent(
                code, None, pyatspi.KEY_PRESS)

    def releaseKey(self, keyName):
        # From dogtail 9.9.0 which isn't widely distributed yet
        code = dogtail.rawinput.keyNameToKeyCode(keyName)
        pyatspi.Registry().generateKeyboardEvent(
                code, None, pyatspi.KEY_RELEASE)

    def point(self, x, y):
        # From dogtail 9.9.0 which isn't widely distributed yet
        pyatspi.Registry().generateMouseEvent(x, y, 'abs')


    #################################
    # virt-manager specific helpers #
    #################################

    def _open_host_window(self, tab, conn_label="test testdriver.xml"):
        """
        Helper to open host connection window and switch to a tab
        """
        self.app.root.find_fuzzy(conn_label, "table cell").click()
        self.app.root.find_fuzzy("Edit", "menu").click()
        self.app.root.find_fuzzy("Connection Details", "menu item").click()
        win = self.app.root.find_fuzzy(
                "%s Connection Details" % conn_label, "frame")
        win.find_fuzzy(tab, "page tab").click()
        return win

    def _open_details_window(self, vmname=None, shutdown=False):
        if vmname is None:
            vmname = self._default_vmname
        self.app.root.find_fuzzy(vmname, "table cell").click(button=3)
        self.app.root.find("Open", "menu item").click()

        win = self.app.root.find("%s on" % vmname, "frame")
        win.find("Details", "radio button").click()
        if shutdown:
            win.find("Shut Down", "push button").click()
            run = win.find("Run", "push button")
            check_in_loop(lambda: run.sensitive)
        return win

    def _walkUIList(self, win, lst, error_cb):
        """
        Toggle down through a UI list like addhardware, net/storage/iface
        lists, and ensure an error isn't raised.
        """
        # Walk the lst UI and find all labelled table cells, these are
        # the actual list entries
        all_cells = lst.findChildren(lambda w: w.roleName == "table cell")
        all_cells[0].click()
        cells_per_selection = len([c for c in all_cells if c.focused])

        idx = 0
        while idx < len(all_cells):
            cell = all_cells[idx]
            if not cell.state_selected:
                # Could be a separator table cell. Try to figure it out
                if not any([c.name for c in
                            all_cells[idx:(idx + cells_per_selection)]]):
                    idx += cells_per_selection
                    continue

            self.assertTrue(cell.state_selected)
            dogtail.rawinput.pressKey("Down")

            if not win.active:
                # Should mean an error dialog popped up
                self.app.root.find("Error", "alert")
                raise AssertionError("Error dialog raised?")
            if error_cb():
                raise AssertionError("Error found on a page")

            idx += cells_per_selection
            if idx >= len(all_cells):
                # Last cell, selection shouldn't have changed
                self.assertTrue(cell.state_selected)
            else:
                self.assertTrue(not cell.state_selected)


class _FuzzyPredicate(dogtail.predicate.Predicate):
    """
    Object dogtail/pyatspi want for node searching.
    """
    def __init__(self, name=None, roleName=None, labeller_text=None):
        """
        :param name: Match node.name or node.labeller.text if
            labeller_text not specified
        :param roleName: Match node.roleName
        :param labeller_text: Match node.labeller.text
        """
        self._name = name
        self._roleName = roleName
        self._labeller_text = labeller_text

        self._name_pattern = None
        self._role_pattern = None
        self._labeller_pattern = None
        if self._name:
            self._name_pattern = re.compile(self._name)
        if self._roleName:
            self._role_pattern = re.compile(self._roleName)
        if self._labeller_text:
            self._labeller_pattern = re.compile(self._labeller_text)

    def makeScriptMethodCall(self, isRecursive):
        ignore = isRecursive
        return
    def makeScriptVariableName(self):
        return
    def describeSearchResult(self, node=None):
        if not node:
            return ""
        return node.node_string()

    def satisfiedByNode(self, node):
        """
        The actual search routine
        """
        try:
            if self._roleName and not self._role_pattern.match(node.roleName):
                return

            labeller = ""
            if node.labeller:
                labeller = node.labeller.text

            if (self._name and
                    not self._name_pattern.match(node.name) and
                    not self._name_pattern.match(labeller)):
                return
            if (self._labeller_text and
                    not self._labeller_pattern.match(labeller)):
                return
            return True
        except Exception as e:
            print("got predicate exception: %s" % e)


def check_in_loop(func, timeout=2):
    """
    Run the passed func in a loop every .1 seconds until timeout is hit or
    the func returns True.
    """
    start_time = time.time()
    interval = 0.1
    while True:
        if func() is True:
            return
        if (time.time() - start_time) > timeout:
            raise RuntimeError("Loop condition wasn't met")
        time.sleep(interval)


class VMMDogtailNode(dogtail.tree.Node):
    """
    Our extensions to the dogtail node wrapper class.
    """
    # The class hackery means pylint can't figure this class out
    # pylint: disable=no-member

    @property
    def active(self):
        """
        If the window is the raised and active window or not
        """
        return self.getState().contains(pyatspi.STATE_ACTIVE)

    @property
    def state_selected(self):
        return self.getState().contains(pyatspi.STATE_SELECTED)

    @property
    def onscreen(self):
        return self.position[0] > 0 and self.position[1] > 0

    def click_combo_entry(self):
        """
        Helper for clicking the arrow of a combo entry, to expose the menu.
        Clicks middle of Y axis, but 1 pixel in from the right side
        """
        button = 1
        clickX = self.position[0] + self.size[0] - 1
        clickY = self.position[1] + self.size[1] / 2
        dogtail.rawinput.click(clickX, clickY, button)

    def click_expander(self):
        """
        Helper for clicking expander, hitting the text part to actually
        open it. Basically clicks top left corner with some indent
        """
        button = 1
        clickX = self.position[0] + 10
        clickY = self.position[1] + 5
        dogtail.rawinput.click(clickX, clickY, button)


    #########################
    # Widget search helpers #
    #########################

    def find(self, name, roleName=None, labeller_text=None):
        """
        Search root for any widget that contains the passed name/role regex
        strings.
        """
        pred = _FuzzyPredicate(name, roleName, labeller_text)

        try:
            ret = self.findChild(pred)
        except dogtail.tree.SearchError:
            raise dogtail.tree.SearchError("Didn't find widget with name='%s' "
                "roleName='%s' labeller_text='%s'" %
                (name, roleName, labeller_text))

        # Wait for independent windows to become active in the window manager
        # before we return them. This ensures the window is actually onscreen
        # so it sidesteps a lot of race conditions
        if ret.roleName in ["frame", "dialog", "alert"]:
            check_in_loop(lambda: ret.active)
        return ret

    def find_fuzzy(self, name, roleName=None, labeller_text=None):
        """
        Search root for any widget that contains the passed name/role strings.
        """
        name_pattern = None
        role_pattern = None
        labeller_pattern = None
        if name:
            name_pattern = ".*%s.*" % name
        if roleName:
            role_pattern = ".*%s.*" % roleName
        if labeller_text:
            labeller_pattern = ".*%s.*" % labeller_text

        return self.find(name_pattern, role_pattern, labeller_pattern)


    #####################
    # Debugging helpers #
    #####################

    def node_string(self):
        msg = "name='%s' roleName='%s'" % (self.name, self.roleName)
        if self.labeller:
            msg += " labeller.text='%s'" % self.labeller.text
        return msg

    def print_nodes(self):
        """
        Helper to print the entire node tree for the passed root. Useful
        if to figure out the roleName for the object you are looking for
        """
        def _walk(node):
            try:
                print(node.node_string())
            except Exception as e:
                print("got exception: %s" % e)

        self.findChildren(_walk, isLambda=True)


# This is the same hack dogtail uses to extend the Accessible class.
_bases = list(pyatspi.Accessibility.Accessible.__bases__)
_bases.insert(_bases.index(dogtail.tree.Node), VMMDogtailNode)
_bases.remove(dogtail.tree.Node)
pyatspi.Accessibility.Accessible.__bases__ = tuple(_bases)


class VMMDogtailApp(object):
    """
    Wrapper class to simplify dogtail app handling
    """
    def __init__(self, uri):
        self._proc = None
        self._root = None
        self._topwin = None
        self.uri = uri


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

    def is_running(self):
        return bool(self._proc and self._proc.poll() is None)

    def open(self, extra_opts=None):
        extra_opts = extra_opts or []

        if tests.utils.get_debug():
            stdout = sys.stdout
            stderr = sys.stderr
            extra_opts.append("--debug")
        else:
            stdout = open(os.devnull)
            stderr = open(os.devnull)

        cmd = [sys.executable]
        if tests.utils.clistate.use_coverage:
            cmd += ["-m", "coverage", "run", "--append"]
        cmd += [os.path.join(os.getcwd(), "virt-manager"),
                "--test-first-run", "--no-fork", "--connect", self.uri]
        cmd += extra_opts

        self._proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr)
        self._root = dogtail.tree.root.application("virt-manager")
        self._topwin = self._root.find(None, "(frame|dialog|alert)")

    def stop(self):
        """
        Try graceful process shutdown, then kill it
        """
        if not self._proc:
            return

        try:
            self._proc.send_signal(signal.SIGINT)
        except Exception:
            logging.debug("Error terminating process", exc_info=True)
            self._proc = None
            return

        # Wait for shutdown for 1 second, with 20 checks
        for ignore in range(20):
            time.sleep(.05)
            if self._proc.poll() is not None:
                self._proc = None
                return

        logging.warning("App didn't exit gracefully from SIGINT. Killing...")
        try:
            self._proc.kill()
        finally:
            time.sleep(1)
        self._proc = None
