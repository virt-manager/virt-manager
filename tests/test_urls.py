# Copyright (C) 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import re
import sys

import pytest

from tests import utils

import virtinst.progress
from virtinst import Installer
from virtinst import Guest
from virtinst import log

# These are all functional tests
os.environ.pop("VIRTINST_TEST_SUITE", None)


class _URLTestData(object):
    """
    Class that tracks all data needed for a single URL test case.
    Data is stored in data/test_urls.ini
    """
    def __init__(self, name, url, detectdistro,
            testxen, testshortcircuit, kernelarg, kernelregex,
            skip_libosinfo):
        self.name = name
        self.url = url
        self.detectdistro = detectdistro
        self.arch = self._find_arch()
        self.kernelarg = kernelarg
        self.kernelregex = kernelregex
        self.skip_libosinfo = skip_libosinfo

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

meter = virtinst.progress.make_meter(quiet=not utils.TESTCONFIG.debug)

if utils.TESTCONFIG.url_skip_libosinfo:
    os.environ["VIRTINST_TEST_SUITE_FORCE_LIBOSINFO"] = "0"
elif utils.TESTCONFIG.url_force_libosinfo:
    os.environ["VIRTINST_TEST_SUITE_FORCE_LIBOSINFO"] = "1"


def _sanitize_osdict_name(detectdistro):
    if detectdistro in ["none", "None", None]:
        return None
    return detectdistro


def _skipmsg(testdata):
    is_iso = testdata.url.lower().endswith(".iso")
    distname = testdata.name

    if utils.TESTCONFIG.url_iso_only and not is_iso:
        return "skipping non-iso test"
    elif utils.TESTCONFIG.url_only and is_iso:
        return "skipping non-url test"

    if not utils.TESTCONFIG.url_force_libosinfo:
        return
    if testdata.skip_libosinfo:
        return "force-libosinfo requested but test has skip_libosinfo set"
    if is_iso:
        return

    # If --force-libosinfo used, don't run tests that we know libosinfo
    # can't detect, non-treeinfo URLs basically
    if ("ubuntu" in distname or
        "debian" in distname or
        "mageia" in distname or
        "opensuse10" in distname or
        "opensuse11" in distname or
        "opensuse12" in distname or
        "opensuse13" in distname or
        "opensuseleap-42" in distname or
        "generic" in distname or
        testdata.url.startswith("ftp:/")):
        return "skipping known busted libosinfo URL tests"


def _testGuest(testdata, guest):
    distname = testdata.name
    arch = testdata.arch
    url = testdata.url
    checkdistro = testdata.detectdistro

    guest.os.arch = arch
    guest.set_os_name("generic")
    if testdata.testshortcircuit:
        guest.set_os_name(checkdistro)

    msg = _skipmsg(testdata)
    if msg:
        raise pytest.skip(msg)

    installer = Installer(guest.conn, location=url)
    try:
        detected_distro = installer.detect_distro(guest)
    except Exception as e:
        msg = ("\nFailed in installer detect_distro():\n"
            "name   = %s\n"
            "url    = %s\n\n%s" % (distname, url, str(e)))
        raise type(e)(msg).with_traceback(sys.exc_info()[2]) from None

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


    # Do this only after the distro detection, since we actually need
    # to fetch files for that part
    treemedia = installer._treemedia  # pylint: disable=protected-access
    fetcher = treemedia._cached_fetcher  # pylint: disable=protected-access
    def fakeAcquireFile(filename, fullurl=None):
        log.debug("Fake acquiring filename=%s fullurl=%s", filename, fullurl)
        return filename
    fetcher.acquireFile = fakeAcquireFile

    # Fetch regular kernel
    kernel, initrd, kernelargs = treemedia.prepare(guest, meter, None)
    dummy = initrd
    if testdata.kernelregex and not re.match(testdata.kernelregex, kernel):
        raise AssertionError("kernel=%s but testdata.kernelregex='%s'" %
                (kernel, testdata.kernelregex))

    if testdata.kernelarg == "None":
        if bool(kernelargs):
            raise AssertionError("kernelargs='%s' but testdata.kernelarg='%s'"
                    % (kernelargs, testdata.kernelarg))
    elif testdata.kernelarg:
        if testdata.kernelarg != str(kernelargs).split("=")[0]:
            raise AssertionError("kernelargs='%s' but testdata.kernelarg='%s'"
                    % (kernelargs, testdata.kernelarg))


def _testURL(testdata):
    """
    Test that our URL detection logic works for grabbing kernels
    """
    sys.stdout.write("\nTesting %-25s " % testdata.name)
    sys.stdout.flush()

    testdata.detectdistro = _sanitize_osdict_name(testdata.detectdistro)
    _testGuest(testdata, hvmguest)
    if testdata.testxen:
        _testGuest(testdata, xenguest)


def test001BadURL():
    badurl = "http://aksdkakskdfa-idontexist.com/foo/tree"

    with pytest.raises(ValueError, match=".*maybe you mistyped.*"):
        installer = Installer(hvmguest.conn, location=badurl)
        installer.detect_distro(hvmguest)

    # Non-existent cdrom fails
    with pytest.raises(ValueError, match=".*non-existent path.*"):
        installer = Installer(hvmguest.conn, cdrom="/not/exist/foobar")
        assert installer.detect_distro(hvmguest) is None

    # Ensure existing but non-distro file doesn't error
    installer = Installer(hvmguest.conn, cdrom="/dev/null")
    assert installer.detect_distro(hvmguest) is None


def _make_tests():
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read("tests/data/test_urls.ini")

    manualpath = "~/.config/virt-manager/test_urls_manual.ini"
    cfg.read(os.path.expanduser(manualpath))
    if not os.path.exists(os.path.expanduser(manualpath)):
        print("NOTE: Pass in manual data with %s" % manualpath)

    urls = {}
    for name in cfg.sections():
        vals = dict(cfg.items(name))
        url = vals["url"]

        if "distro" not in vals:
            print("url needs an explicit distro= value: %s" % url)
            sys.exit(1)
        d = _URLTestData(name, url, vals["distro"],
                vals.get("testxen", "0") == "1",
                vals.get("testshortcircuit", "0") == "1",
                vals.get("kernelarg", None),
                vals.get("kernelregex", None),
                vals.get("skiplibosinfo", "0") == "1")
        urls[d.name] = d

    for key, testdata in sorted(urls.items()):
        def _make_wrapper(d):
            return lambda: _testURL(d)
        methodname = "test_URL%s" % key.replace("-", "_")
        globals()[methodname] = _make_wrapper(testdata)

_make_tests()
