import os
import re
import time
import subprocess

import dogtail.tree


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
            (extra_opts or []))
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

    @staticmethod
    def node_string(node):
        msg = "name='%s' roleName='%s'" % (node.name, node.roleName)
        if node.labeller:
            msg += " labeller.text='%s'" % node.labeller.text
        return msg

    @staticmethod
    def find_pattern(root, name, roleName=None, labeller_text=None,
            return_all=False):
        """
        Search root for any widget that contains the passed name/role regex
        strings.
        """
        name_pattern = re.compile(name or ".*")
        role_pattern = re.compile(roleName or ".*")
        labeller_pattern = re.compile(labeller_text or ".*")

        def _walk(node):
            try:
                if not name_pattern.match(node.name):
                    return
                if not role_pattern.match(node.roleName):
                    return
                if labeller_text:
                    if not node.labeller:
                        return
                    if not labeller_pattern.match(node.labeller.text):
                        return
                return node
            except Exception, e:
                print "got walk exception: %s" % e

        ret = root.findChildren(_walk, isLambda=True)
        if not ret:
            raise RuntimeError("Didn't find widget with name='%s' "
                "roleName='%s' labeller_text='%s'" %
                (name, roleName, labeller_text))
        if return_all:
            return ret
        if len(ret) > 1:
            raise RuntimeError("Found more than 1 widget with name='%s' "
                "rolename='%s' labeller_text='%s':\n%s" %
                (name, roleName, labeller_text,
                 "\n".join([DogtailApp.node_string(w) for w in ret])))
        return ret[0]

    @staticmethod
    def find_fuzzy(root, name, roleName=None, labeller_text=None,
            return_all=False):
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

        return DogtailApp.find_pattern(root, name_pattern, role_pattern,
            labeller_pattern, return_all=return_all)

    @staticmethod
    def print_nodes(root):
        """
        Helper to print the entire node tree for the passed root. Useful
        if to figure out the roleName for the object you are looking for
        """
        def _walk(node):
            try:
                print DogtailApp.node_string(node)
            except Exception, e:
                print "got exception: %s" % e

        root.findChildren(_walk, isLambda=True)
