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

from virtinst import URISplit

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
                    "tag for gtk+, it should say 3.8")

            if (int(required_version.split(".")[0]) != 3 or
                int(required_version.split(".")[1]) != 8):
                failures.append((filename, required_version))

        if failures:
            raise AssertionError("The following files should require gtk "
                "version of gtk-3.8, which is what we target:\n" +
                "\n".join([("%s version=%s" % tup) for tup in failures]))

    def test_libosinfo_aliases_ro(self):
        from virtinst import osdict
        aliases = getattr(osdict, "_aliases")

        if len(aliases) != 40:
            raise AssertionError(_("osdict._aliases changed size. It "
                "should never be extended, since it is only for back "
                "compat with pre-libosinfo osdict."))


class TestURI(unittest.TestCase):
    """
    Test virtinst URISplit module
    """
    def _compare(self, uri, scheme='',
                 transport='', port='', username='', path='',
                 hostname='', query='', fragment='',
                 is_ipv6=False, host_is_ipv4_string=False):
        uriinfo = URISplit(uri)
        self.assertEquals(scheme, uriinfo.scheme)
        self.assertEquals(transport, uriinfo.transport)
        self.assertEquals(port, uriinfo.port)
        self.assertEquals(username, uriinfo.username)
        self.assertEquals(path, uriinfo.path)
        self.assertEquals(hostname, uriinfo.hostname)
        self.assertEquals(query, uriinfo.query)
        self.assertEquals(fragment, uriinfo.fragment)
        self.assertEquals(is_ipv6, uriinfo.is_ipv6)
        self.assertEquals(host_is_ipv4_string, uriinfo.host_is_ipv4_string)
        self.assertEquals(uri, uriinfo.rebuild_uri())

    def testURIs(self):
        self._compare("lxc://", scheme="lxc")
        self._compare("qemu:///session", scheme="qemu", path="/session")
        self._compare("http://foobar.com:5901/my/example.path#my-frag",
            scheme="http", hostname="foobar.com",
            port="5901", path='/my/example.path',
            fragment="my-frag")
        self._compare(
            "gluster+tcp://[1:2:3:4:5:6:7:8]:24007/testvol/dir/a.img",
            scheme="gluster", transport="tcp",
            hostname="1:2:3:4:5:6:7:8", port="24007",
            path="/testvol/dir/a.img", is_ipv6=True)
        self._compare(
            "qemu+ssh://root@192.168.2.3/system?no_verify=1",
            scheme="qemu", transport="ssh", username="root",
            hostname="192.168.2.3", path="/system",
            query="no_verify=1", host_is_ipv4_string=True)
