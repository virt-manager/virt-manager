# Copyright (C) 2013 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

import fileinput
import fnmatch
import glob
import imp
import importlib
import os
import sys
import unittest
import xml.etree.ElementTree as ET

_badmodules = ["gi.repository.Gtk", "gi.repository.Gdk"]


def _restore_modules(fn):
    def wrap(*args, **kwargs):
        origimport = __builtins__["__import__"]
        def my_import(name, *iargs, **ikwargs):
            if name in _badmodules:
                raise AssertionError("Tried to import '%s'" % name)
            return origimport(name, *iargs, **ikwargs)

        try:
            __builtins__["__import__"] = my_import
            return fn(*args, **kwargs)
        finally:
            __builtins__["__import__"] = origimport
    return wrap


def _find_py(dirname):
    ret = []
    for root, ignore, filenames in os.walk(dirname):
        for filename in fnmatch.filter(filenames, "*.py"):
            ret.append(os.path.join(root, filename))
    ret.sort(key=lambda s: s.lower())
    return ret


class TestMisc(unittest.TestCase):
    """
    Miscellaneous tests
    """
    def _check_modules(self, files):
        for f in files:
            regular_import = f.endswith(".py")
            if f.endswith("/__init__.py"):
                f = f.rsplit("/", 1)[0]
            name = f.rsplit(".", 1)[0].replace("/", ".")
            if name in sys.modules:
                continue

            if regular_import:
                importlib.import_module(name)
            else:
                imp.load_source(name, f)

        found = []
        for f in _badmodules:
            if f in sys.modules:
                found.append(f)

        if found:
            raise AssertionError("%s found in sys.modules" % found)


    @_restore_modules
    def test_no_gtk_virtinst(self):
        """
        Make sure virtinst doesn't pull in any gnome modules
        """
        files = ["virt-install", "virt-clone", "virt-convert"]
        files += _find_py("virtinst")
        files += _find_py("virtconv")
        files += _find_py("virtcli")

        self._check_modules(files)


    def test_ui_minimum_version(self):
        failures = []
        for filename in glob.glob("ui/*.ui"):
            required_version = None
            for line in fileinput.input(filename):
                # This is much faster than XML parsing the whole file
                if not line.strip().startswith('<requires '):
                    continue

                req = ET.fromstring(line)
                if (req.tag != "requires" or
                    req.attrib.get("lib") != "gtk+"):
                    continue
                required_version = req.attrib["version"]

            if required_version is None:
                raise AssertionError("ui file=%s doesn't have a <requires> "
                    "tag for gtk+, it should say 3.10")

            if (int(required_version.split(".")[0]) != 3 or
                int(required_version.split(".")[1]) != 14):
                failures.append((filename, required_version))

        if failures:
            raise AssertionError("The following files should require gtk "
                "version of gtk-3.10, which is what we target:\n" +
                "\n".join([("%s version=%s" % tup) for tup in failures]))
