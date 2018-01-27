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

import logging
import os
import sys
import time
import traceback
import unittest

from tests import utils

from virtinst import Guest
from virtinst import urlfetcher
from virtinst import util
from virtinst.urlfetcher import ALTLinuxDistro
from virtinst.urlfetcher import CentOSDistro
from virtinst.urlfetcher import DebianDistro
from virtinst.urlfetcher import FedoraDistro
from virtinst.urlfetcher import GenericDistro
from virtinst.urlfetcher import MandrivaDistro
from virtinst.urlfetcher import RHELDistro
from virtinst.urlfetcher import SLDistro
from virtinst.urlfetcher import SuseDistro
from virtinst.urlfetcher import UbuntuDistro


class _DistroURL(object):
    def __init__(self, name, url, detectdistro,
            testxen, testbootiso, testshortcircuit):
        self.name = name
        self.url = url
        self.detectdistro = detectdistro
        self.arch = self._find_arch()
        self.distroclass = self._distroclass_for_name(self.name)

        self.testxen = testxen
        self.testbootiso = testbootiso

        # If True, pass in the expected distro value to getDistroStore
        # so it can short circuit the lookup checks. Speeds up the tests
        # and exercises the shortcircuit infrastructure
        self.testshortcircuit = testshortcircuit

    def _distroclass_for_name(self, name):
        # Map the test case name to the expected urlfetcher distro
        # class we should be detecting
        if "fedora" in name:
            return FedoraDistro
        if "centos" in name:
            return CentOSDistro
        if "rhel" in name:
            return RHELDistro
        if "suse" in name:
            return SuseDistro
        if "debian" in name:
            return DebianDistro
        if name.startswith("sl-"):
            return SLDistro
        if "ubuntu" in name:
            return UbuntuDistro
        if "mageia" in name:
            return MandrivaDistro
        if "altlinux" in name:
            return ALTLinuxDistro
        if "generic" in name:
            return GenericDistro
        raise RuntimeError("name=%s didn't map to any distro class. Extend "
            "_distroclass_for_name" % name)

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

testconn = utils.open_testdefault()
hvmguest = Guest(testconn)
hvmguest.os.os_type = "hvm"
xenguest = Guest(testconn)
xenguest.os.os_type = "xen"

meter = util.make_meter(quiet=not utils.get_debug())


def _storeForDistro(fetcher, guest):
    """
    Helper to lookup the Distro store object, basically detecting the
    URL. Handle occasional proxy errors
    """
    for ignore in range(0, 10):
        try:
            return urlfetcher.getDistroStore(guest, fetcher)
        except Exception as e:
            if str(e).count("502"):
                logging.debug("Caught proxy error: %s", str(e))
                time.sleep(.5)
                continue
            raise
    raise  # pylint: disable=misplaced-bare-raise


def _testURL(fetcher, distroobj):
    """
    Test that our URL detection logic works for grabbing kernel, xen
    kernel, and boot.iso
    """
    distname = distroobj.name
    arch = distroobj.arch
    hvmguest.os.arch = arch
    xenguest.os.arch = arch
    if distroobj.testshortcircuit:
        hvmguest.os_variant = distroobj.detectdistro
        xenguest.os_variant = distroobj.detectdistro
    else:
        hvmguest.os_variant = None
        xenguest.os_variant = None

    try:
        hvmstore = _storeForDistro(fetcher, hvmguest)
        xenstore = None
        if distroobj.testxen:
            xenstore = _storeForDistro(fetcher, xenguest)
    except Exception:
        raise AssertionError("\nFailed to detect URLDistro class:\n"
            "name   = %s\n"
            "url    = %s\n\n%s" %
            (distname, fetcher.location, "".join(traceback.format_exc())))

    for s in [hvmstore, xenstore]:
        if (s and distroobj.distroclass and
            not isinstance(s, distroobj.distroclass)):
            raise AssertionError("Unexpected URLDistro class:\n"
                "found  = %s\n"
                "expect = %s\n"
                "name   = %s\n"
                "url    = %s" %
                (s.__class__, distroobj.distroclass, distname,
                 fetcher.location))

        # Make sure the stores are reporting correct distro name/variant
        if (s and distroobj.detectdistro and
            distroobj.detectdistro != s.get_osdict_info()):
            raise AssertionError(
                "Detected OS did not match expected values:\n"
                "found  = %s\n"
                "expect = %s\n"
                "name   = %s\n"
                "url    = %s\n"
                "store  = %s" %
                (s.os_variant, distroobj.detectdistro,
                 distname, fetcher.location, distroobj.distroclass))

    # Do this only after the distro detection, since we actually need
    # to fetch files for that part
    def fakeAcquireFile(filename):
        logging.debug("Fake acquiring %s", filename)
        return fetcher.hasFile(filename)
    fetcher.acquireFile = fakeAcquireFile

    # Fetch boot iso
    if distroobj.testbootiso:
        boot = hvmstore.acquireBootDisk(hvmguest)
        logging.debug("acquireBootDisk: %s", str(boot))

        if boot is not True:
            raise AssertionError("%s-%s: bootiso fetching failed" %
                                 (distname, arch))

    # Fetch regular kernel
    kern = hvmstore.acquireKernel(hvmguest)
    logging.debug("acquireKernel (hvm): %s", str(kern))

    if kern[0] is not True or kern[1] is not True:
        AssertionError("%s-%s: hvm kernel fetching failed" %
                       (distname, arch))

    # Fetch xen kernel
    if xenstore:
        kern = xenstore.acquireKernel(xenguest)
        logging.debug("acquireKernel (xen): %s", str(kern))

        if kern[0] is not True or kern[1] is not True:
            raise AssertionError("%s-%s: xen kernel fetching" %
                                 (distname, arch))


def _testURLWrapper(distroobj):
    os.environ.pop("VIRTINST_TEST_SUITE", None)

    logging.debug("Testing for media arch=%s distroclass=%s",
                  distroobj.arch, distroobj.distroclass)

    sys.stdout.write("\nTesting %-25s " % distroobj.name)
    sys.stdout.flush()

    fetcher = urlfetcher.fetcherForURI(distroobj.url, "/tmp", meter)
    try:
        fetcher.prepareLocation()
        return _testURL(fetcher, distroobj)
    finally:
        fetcher.cleanupLocation()


# Register tests to be picked up by unittest
class URLTests(unittest.TestCase):
    pass


def _make_tests():
    import ConfigParser
    cfg = ConfigParser.ConfigParser()
    cfg.read("tests/test_urls.ini")

    manualpath = "tests/test_urls_manual.ini"
    cfg.read(manualpath)
    if not os.path.exists(manualpath):
        print("NOTE: Pass in manual data with %s" % manualpath)

    urls = {}
    for name in cfg.sections():
        vals = dict(cfg.items(name))
        d = _DistroURL(name, vals["url"],
                       vals.get("distro", None),
                       vals.get("testxen", "0") == "1",
                       vals.get("testbootiso", "0") == "1",
                       vals.get("testshortcircuit", "0") == "1")
        urls[d.name] = d

    keys = urls.keys()
    keys.sort()
    for key in keys:
        distroobj = urls[key]
        def _make_wrapper(d):
            return lambda _self: _testURLWrapper(d)
        setattr(URLTests, "testURL%s" % key.replace("-", "_"),
                _make_wrapper(distroobj))

_make_tests()
