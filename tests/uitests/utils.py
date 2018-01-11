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
            self.assertTrue(cell.state_selected)
            dogtail.rawinput.pressKey("Down")

            if not win.active:
                # Should mean an error dialog popped up
                self.app.root.find_pattern("Error", "alert")
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
        self._name_pattern = re.compile(name or ".*")
        self._role_pattern = re.compile(roleName or ".*")
        self._labeller_text = bool(labeller_text)
        self._labeller_pattern = re.compile(labeller_text or ".*")

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
            if not self._name_pattern.match(node.name):
                return
            if not self._role_pattern.match(node.roleName):
                return
            if self._labeller_text:
                if not node.labeller:
                    return
                if not self._labeller_pattern.match(node.labeller.text):
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


    #########################
    # Widget search helpers #
    #########################

    def find_pattern(self, name, roleName=None, labeller_text=None):
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

        return self.find_pattern(name_pattern, role_pattern, labeller_pattern)


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
        self._topwin = self._root.find_pattern(None, "(frame|dialog|alert)")

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
            return

        # Wait for shutdown for 1 second, with 20 checks
        for ignore in range(20):
            time.sleep(.05)
            if self._proc.poll() is not None:
                return

        logging.warning("App didn't exit gracefully from SIGINT. Killing...")
        try:
            self._proc.kill()
        finally:
            time.sleep(1)
