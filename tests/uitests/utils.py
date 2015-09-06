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
        self.proc = subprocess.Popen(["python",
            os.path.join(os.getcwd(), "virt-manager"),
            "--test-first-run", "--no-fork", "--connect", uri])
        time.sleep(1)

        self.root = dogtail.tree.root.application("virt-manager")


    @staticmethod
    def find_pattern(root, name, roleName=None):
        """
        Search root for any widget that contains the passed name/role regex
        strings.
        """
        name_pattern = re.compile(name)
        role_pattern = re.compile(roleName or ".*")

        def _walk(node):
            try:
                if not name_pattern.match(node.name):
                    return
                if not role_pattern.match(node.roleName):
                    return
                return node
            except Exception, e:
                print "got walk exception: %s" % e

        ret = root.findChildren(_walk, isLambda=True)
        if not ret:
            raise RuntimeError("Didn't find widget with name='%s' "
                "roleName='%s'" % (name, roleName))
        if len(ret) > 1:
            raise RuntimeError("Found more than 1 widget with name='%s' "
                "rolename='%s':\n%s" % (name, roleName,
                [str(w) for w in ret]))
        return ret[0]

    @staticmethod
    def find_fuzzy(root, name, roleName=None):
        """
        Search root for any widget that contains the passed name/role strings.
        """
        name_pattern = ".*%s.*" % name
        role_pattern = None
        if roleName:
            role_pattern = ".*%s.*" % roleName
        return DogtailApp.find_pattern(root, name_pattern, role_pattern)

    @staticmethod
    def print_nodes(root):
        """
        Helper to print the entire node tree for the passed root. Useful
        if to figure out the roleName for the object you are looking for
        """
        def _walk(node):
            try:
                print "__str__=%s roleName=%s" % (str(node), node.roleName)
            except Exception, e:
                print "got exception: %s" % e

        root.findChildren(_walk, isLambda=True)
