from __future__ import print_function

import os
import re
import time
import subprocess

import dogtail.tree


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
        return node_string(node)

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



class DogtailApp(object):
    """
    Wrapper class to simplify dogtail app handling
    """
    def __init__(self, uri):
        self._proc = None
        self._root = None
        self.uri = uri


    @property
    def root(self):
        if self._root is None:
            self.open()
        return self._root

    def open(self, extra_opts=None):
        self._proc = subprocess.Popen(["python",
            os.path.join(os.getcwd(), "virt-manager"),
            "--test-first-run", "--no-fork", "--connect", self.uri] +
            (extra_opts or []),
            stdout=open(os.devnull), stderr=open(os.devnull))
        time.sleep(1)

        self._root = dogtail.tree.root.application("virt-manager")

    def kill(self):
        """
        Force kill the process
        """
        if self._proc:
            self._proc.kill()

    def quit(self):
        """
        Quit the app via Ctrl+q
        """
        self.root.keyCombo("<ctrl>q")
        time.sleep(.5)


#########################
# Widget search helpers #
#########################

def find_pattern(root, name, roleName=None, labeller_text=None, retry=True):
    """
    Search root for any widget that contains the passed name/role regex
    strings.
    """
    pred = _FuzzyPredicate(name, roleName, labeller_text)

    try:
        return root.findChild(pred, retry=retry)
    except dogtail.tree.SearchError:
        raise dogtail.tree.SearchError("Didn't find widget with name='%s' "
            "roleName='%s' labeller_text='%s'" %
            (name, roleName, labeller_text))


def find_fuzzy(root, name, roleName=None, labeller_text=None, retry=True):
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

    return find_pattern(root, name_pattern, role_pattern,
        labeller_pattern, retry=retry)


def check_in_loop(func, timeout=-1):
    """
    Run the passed func in a loop every .5 seconds until timeout is hit or
    the func returns True.
    If timeout=-1, check indefinitely.
    """
    total_time = 0.0
    while True:
        time.sleep(.5)
        total_time += .5
        if func() is True:
            return
        if timeout > 0 and total_time >= timeout:
            raise RuntimeError("Loop condition wasn't met")


#####################
# Debugging helpers #
#####################

def node_string(node):
    msg = "name='%s' roleName='%s'" % (node.name, node.roleName)
    if node.labeller:
        msg += " labeller.text='%s'" % node.labeller.text
    return msg


def print_nodes(root):
    """
    Helper to print the entire node tree for the passed root. Useful
    if to figure out the roleName for the object you are looking for
    """
    def _walk(node):
        try:
            print(node_string(node))
        except Exception as e:
            print("got exception: %s" % e)

    root.findChildren(_walk, isLambda=True)


def focused_nodes(root):
    """
    Return a list of all focused nodes. Useful for debugging
    """
    def _walk(node):
        try:
            if node.focused:
                return node
        except Exception as e:
            print("got exception: %s" % e)

    return root.findChildren(_walk, isLambda=True)
