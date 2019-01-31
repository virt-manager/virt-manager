# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import os
import re
import sys
import traceback
import unittest

from tests import utils

from virtinst import Installer
from virtinst import Guest
from virtinst import util


class _URLTestData(object):
    """
    Class that tracks all data needed for a single URL test case.
    Data is stored in test_urls.ini
    """
    def __init__(self, name, url, detectdistro,
            testxen, testshortcircuit, kernelarg, kernelregex):
        self.name = name
        self.url = url
        self.detectdistro = detectdistro
        self.arch = self._find_arch()
        self.kernelarg = kernelarg
        self.kernelregex = kernelregex

        self.testxen = testxen

        # If True, pass in the expected distro value to getDistroStore
        # so it can short circuit the lookup checks. Speeds up the tests
        # and exercises the shortcircuit infrastructure
        self.testshortcircuit = testshortcircuit

    def _find_arch(self):
        if ("i686" in self.url or
            "i386" in self.url or
            "i586" in self.url):
            return "i686"
        if ("arm64" in self.url or
            "aarch64" in self.url):
            return "aarch64"
        if ("ppc64el" in self.url or
            "ppc64le" in self.url):
            return "ppc64le"
        if "s390" in self.url:
            return "s390x"
        if ("x86_64" in self.url or
            "amd64" in self.url):
            return "x86_64"
        return "x86_64"

testconn = utils.URIs.open_testdefault_cached()
hvmguest = Guest(testconn)
hvmguest.os.os_type = "hvm"
xenguest = Guest(testconn)
xenguest.os.os_type = "xen"

meter = util.make_meter(quiet=not utils.clistate.debug)


def _sanitize_osdict_name(detectdistro):
    if detectdistro in ["none", "None", None]:
        return None
    return detectdistro


def _testGuest(testdata, guest):
    distname = testdata.name
    arch = testdata.arch
    url = testdata.url
    checkdistro = testdata.detectdistro

    guest.os.arch = arch
    if testdata.testshortcircuit:
        guest.set_os_name(checkdistro)

    installer = Installer(guest.conn, location=url)
    try:
        detected_distro = installer.detect_distro(guest)
    except Exception:
        raise AssertionError("\nFailed in installer detect_distro():\n"
            "name   = %s\n"
            "url    = %s\n\n%s" %
            (distname, url, "".join(traceback.format_exc())))

    # Make sure the stores are reporting correct distro name/variant
    if checkdistro != detected_distro:
        raise AssertionError(
            "Detected OS did not match expected values:\n"
            "found   = %s\n"
            "expect  = %s\n\n"
            "testname = %s\n"
            "url      = %s\n" %
            (detected_distro, checkdistro, distname, url))

    if guest is xenguest:
        return

    # Fetch regular kernel
    store = installer._treemedia._cached_store
    kernel, initrd = store.check_kernel_paths()
    dummy = initrd
    if testdata.kernelregex and not re.match(testdata.kernelregex, kernel):
        raise AssertionError("kernel=%s but testdata.kernelregex='%s'" %
                (kernel, testdata.kernelregex))

    kernelargs = store.get_kernel_url_arg()
    if testdata.kernelarg == "None":
        if bool(kernelargs):
            raise AssertionError("kernelargs='%s' but testdata.kernelarg='%s'"
                    % (kernelargs, testdata.kernelarg))
    elif testdata.kernelarg:
        if not kernelargs == testdata.kernelarg:
            raise AssertionError("kernelargs='%s' but testdata.kernelarg='%s'"
                    % (kernelargs, testdata.kernelarg))


def _testURL(testdata):
    """
    Test that our URL detection logic works for grabbing kernels
    """
    testdata.detectdistro = _sanitize_osdict_name(testdata.detectdistro)
    _testGuest(testdata, hvmguest)
    if testdata.testxen:
        _testGuest(testdata, xenguest)


def _testURLWrapper(testdata):
    os.environ.pop("VIRTINST_TEST_SUITE", None)

    sys.stdout.write("\nTesting %-25s " % testdata.name)
    sys.stdout.flush()

    return _testURL(testdata)


# Register tests to be picked up by unittest
class URLTests(unittest.TestCase):
    def test001BadURL(self):
        badurl = "http://aksdkakskdfa-idontexist.com/foo/tree"

        try:
            installer = Installer(hvmguest.conn, location=badurl)
            installer.detect_distro(hvmguest)
            raise AssertionError("Expected URL failure")
        except ValueError as e:
            self.assertTrue("maybe you mistyped" in str(e))

        # Non-existent cdrom fails
        try:
            installer = Installer(hvmguest.conn, cdrom="/i/dont/exist/foobar")
            self.assertEqual(None, installer.detect_distro(hvmguest))
            raise AssertionError("Expected cdrom failure")
        except ValueError as e:
            self.assertTrue("non-existent path" in str(e))

        # Ensure existing but non-distro file doesn't error
        installer = Installer(hvmguest.conn, cdrom="/dev/null")
        self.assertEqual(None, installer.detect_distro(hvmguest))


def _make_tests():
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read("tests/test_urls.ini")

    manualpath = "~/.config/virt-manager/test_urls_manual.ini"
    cfg.read(os.path.expanduser(manualpath))
    if not os.path.exists(os.path.expanduser(manualpath)):
        print("NOTE: Pass in manual data with %s" % manualpath)

    urls = {}
    for name in cfg.sections():
        vals = dict(cfg.items(name))
        d = _URLTestData(name, vals["url"],
                vals.get("distro", None),
                vals.get("testxen", "0") == "1",
                vals.get("testshortcircuit", "0") == "1",
                vals.get("kernelarg", None),
                vals.get("kernelregex", None))
        urls[d.name] = d

    for key, testdata in sorted(urls.items()):
        def _make_wrapper(d):
            return lambda _self: _testURLWrapper(d)
        setattr(URLTests, "testURL%s" % key.replace("-", "_"),
                _make_wrapper(testdata))

_make_tests()
