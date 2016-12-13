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

import unittest
import time
import logging
import platform
import traceback

from tests import URLTEST_LOCAL_MEDIA
from tests import utils

from virtinst import Guest
from virtinst import urlfetcher
from virtinst import util
from virtinst.urlfetcher import FedoraDistro
from virtinst.urlfetcher import SuseDistro
from virtinst.urlfetcher import DebianDistro
from virtinst.urlfetcher import CentOSDistro
from virtinst.urlfetcher import SLDistro
from virtinst.urlfetcher import UbuntuDistro
from virtinst.urlfetcher import MandrivaDistro


# pylint: disable=protected-access
# Access to protected member, needed to unittest stuff

ARCHIVE_FEDORA_URL = "https://archives.fedoraproject.org/pub/archive/fedora/linux/releases/%s/Fedora/%s/os/"
DEVFEDORA_URL = "http://dl.fedoraproject.org/pub/fedora/linux/development/%s/Server/%s/os/"
FEDORA_URL = "http://dl.fedoraproject.org/pub/fedora/linux/releases/%s/Server/%s/os/"

OLD_CENTOS_URL = "http://vault.centos.org/%s/os/%s"
CENTOS_URL = "http://mirrors.mit.edu/centos/%s/os/%s/"
OLD_SCIENTIFIC_URL = "http://ftp.scientificlinux.org/linux/scientific/%s/%s/"
SCIENTIFIC_URL = "http://ftp.scientificlinux.org/linux/scientific/%s/%s/os"

OPENSUSE10 = "http://ftp.hosteurope.de/mirror/ftp.opensuse.org/discontinued/10.0"
OLD_OPENSUSE_URL = "http://ftp5.gwdg.de/pub/opensuse/discontinued/distribution/%s/repo/oss"
OPENSUSE_URL = "http://download.opensuse.org/distribution/%s/repo/oss/"
OPENSUSE_TUMBLEWEED = "http://download.opensuse.org/tumbleweed/repo/oss/"

OLD_UBUNTU_URL = "http://old-releases.ubuntu.com/ubuntu/dists/%s/main/installer-%s"
UBUNTU_URL = "http://us.archive.ubuntu.com:80/ubuntu/dists/%s/main/installer-%s"

OLD_DEBIAN_URL = "http://archive.debian.org/debian/dists/%s/main/installer-%s/"
DAILY_DEBIAN_URL = "http://d-i.debian.org/daily-images/%s/"
DEBIAN_URL = "ftp://ftp.us.debian.org/debian/dists/%s/main/installer-%s/"

MAGEIA_URL = "http://distro.ibiblio.org/mageia/distrib/%s/%s"


urls = {}
_distro = None


class _DistroURL(object):
    def __init__(self, x86_64, detectdistro=None, i686=None,
                 hasxen=True, hasbootiso=True, name=None,
                 testshortcircuit=False):
        self.x86_64 = x86_64
        self.i686 = i686
        self.detectdistro = detectdistro
        self.hasxen = hasxen
        self.hasbootiso = hasbootiso
        self.name = name or self.detectdistro
        self.distroclass = _distro

        # If True, pass in the expected distro value to getDistroStore
        # so it can short circuit the lookup checks
        self.testshortcircuit = testshortcircuit


def _set_distro(_d):
    # Saves us from having to pass distro class to ever _add invocation
    global _distro
    _distro = _d


def _add(*args, **kwargs):
    _d = _DistroURL(*args, **kwargs)
    if _d.name in urls:
        raise RuntimeError("distro=%s url=%s collides with entry in urls, "
                           "set a unique name" % (_d.name, _d.x86_64))
    urls[_d.name] = _d


# Goal here is generally to cover all tree variants for each distro,
# where feasible. Don't exhaustively test i686 trees since most people
# aren't using it and it slows down the test, only use it in a couple
# places. Follow the comments for what trees to keep around

_set_distro(FedoraDistro)
# One old Fedora
_add(ARCHIVE_FEDORA_URL % ("14", "x86_64"), "fedora14",
     i686=ARCHIVE_FEDORA_URL % ("14", "i386"))
# 2 Latest releases
_add(FEDORA_URL % ("23", "x86_64"), "fedora23", name="fedora23")
_add(FEDORA_URL % ("24", "x86_64"), "fedora24", name="fedora24")
# Any Dev release
# _add(DEVFEDORA_URL % ("25", "x86_64"), "fedora23", name="fedora25")
_add(DEVFEDORA_URL % ("rawhide", "x86_64"), "fedora24", name="fedora-rawhide")


_set_distro(CentOSDistro)
# One old and new centos 4. No distro detection since there's no treeinfo
_add(OLD_CENTOS_URL % ("4.0", "x86_64"), hasxen=False, name="centos-4.0")
_add(OLD_CENTOS_URL % ("4.9", "x86_64"), name="centos-4.9")
# One old centos 5
_add(OLD_CENTOS_URL % ("5.0", "x86_64"), name="centos-5.0")
# Latest centos 5 w/ i686
_add(CENTOS_URL % ("5", "x86_64"), "rhel5.11", name="centos-5-latest",
     i686=CENTOS_URL % ("5", "i386"))
# Latest centos 6 w/ i686
_add(CENTOS_URL % ("6", "x86_64"), "centos6.7", name="centos-6-latest",
     i686=CENTOS_URL % ("6", "i386"))
# Latest centos 7, but no i686 as of 2014-09-06
_add(CENTOS_URL % ("7", "x86_64"), "centos7.0", name="centos-7-latest")
# Centos 7 ppc64le
_add("http://mirror.centos.org/altarch/7/os/ppc64le/",
     "centos7.0", name="centos-7-ppc64", hasbootiso=False, hasxen=False)


_set_distro(SLDistro)
# scientific 5
_add(OLD_SCIENTIFIC_URL % ("55", "x86_64"), "rhel5.5", name="sl-5.5")
# Latest scientific 6
_add(SCIENTIFIC_URL % ("6", "x86_64"), "rhel6.8", name="sl-6latest")


_set_distro(SuseDistro)
# Latest 10 series
_add(OLD_OPENSUSE_URL % ("10.3"), "opensuse10.3", hasbootiso=False)
# Latest 11 series
_add(OLD_OPENSUSE_URL % ("11.4"), "opensuse11.4", hasbootiso=False)
# Latest 12 series
# Only keep i686 for the latest opensuse
_add(OPENSUSE_URL % ("12.3"), "opensuse12.3",
     i686=OPENSUSE_URL % ("12.3"), hasbootiso=False, testshortcircuit=True)
# Latest 13.x releases
_add(OPENSUSE_URL % ("13.1"), "opensuse13.1", hasbootiso=False)
_add(OPENSUSE_URL % ("13.2"), "opensuse13.2", hasbootiso=False)
# tumbleweed (rolling distro)
_add(OPENSUSE_TUMBLEWEED, "opensusetumbleweed", hasbootiso=False)


_set_distro(DebianDistro)
# Debian releases rarely enough that we can just do every release since lenny
_add(OLD_DEBIAN_URL % ("lenny", "amd64"), "debian5", hasxen=False,
     testshortcircuit=True)
_add(DEBIAN_URL % ("wheezy", "amd64"), "debian7")
# And daily builds, since we specially handle that URL
_add(DAILY_DEBIAN_URL % ("amd64"), "debiantesting", name="debiandaily")
_add(DAILY_DEBIAN_URL % ("arm64"), "debiantesting",
    name="debiandailyarm64", hasxen=False)


_set_distro(UbuntuDistro)
# One old ubuntu
_add(OLD_UBUNTU_URL % ("hardy", "amd64"), "ubuntu8.04",
     i686=OLD_UBUNTU_URL % ("hardy", "i386"), hasxen=False,
     testshortcircuit=True)
# Latest LTS
_add(UBUNTU_URL % ("precise", "amd64"), "ubuntu12.04")
# Latest release
_add(UBUNTU_URL % ("wily", "amd64"), "ubuntu15.10")


_set_distro(MandrivaDistro)
_add(MAGEIA_URL % ("5", "x86_64"), name="mageia5", hasxen=False)


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
        except Exception, e:
            if str(e).count("502"):
                logging.debug("Caught proxy error: %s", str(e))
                time.sleep(.5)
                continue
            raise
    raise  # pylint: disable=misplaced-bare-raise


def _testURL(fetcher, distname, arch, distroobj):
    """
    Test that our URL detection logic works for grabbing kernel, xen
    kernel, and boot.iso
    """
    import sys
    sys.stdout.write("\nTesting %-25s " % ("%s-%s:" % (distname, arch)))
    sys.stdout.flush()

    hvmguest.os.arch = arch
    xenguest.os.arch = arch
    if distroobj.testshortcircuit:
        hvmguest.os_variant = distroobj.detectdistro
        xenguest.os_variant = distroobj.detectdistro

    try:
        hvmstore = _storeForDistro(fetcher, hvmguest)
        xenstore = None
        if distroobj.hasxen:
            xenstore = _storeForDistro(fetcher, xenguest)
    except:
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
            distroobj.detectdistro != s.os_variant):
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
    if not distroobj.hasbootiso:
        logging.debug("Known lack of boot.iso in %s tree. Skipping.",
                      distname)
    else:
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
    if not xenstore:
        logging.debug("acquireKernel (xen): Hardcoded skipping.")
    else:
        kern = xenstore.acquireKernel(xenguest)
        logging.debug("acquireKernel (xen): %s", str(kern))

        if kern[0] is not True or kern[1] is not True:
            raise AssertionError("%s-%s: xen kernel fetching" %
                                 (distname, arch))


def _fetch_wrapper(url, cb, *args):
    fetcher = urlfetcher.fetcherForURI(url, "/tmp", meter)
    try:
        fetcher.prepareLocation()
        return cb(fetcher, *args)
    finally:
        fetcher.cleanupLocation()


def _make_test_wrapper(url, args):
    def cmdtemplate():
        return _fetch_wrapper(url, _testURL, *args)
    return lambda _self: cmdtemplate()


# Register tests to be picked up by unittest
# If local ISO tests requested, skip all other URL tests
class URLTests(unittest.TestCase):
    pass


def _make_tests():
    global urls

    if URLTEST_LOCAL_MEDIA:
        urls = {}
        newidx = 0
        arch = platform.machine()
        for p in URLTEST_LOCAL_MEDIA:
            newidx += 1

            d = _DistroURL(p, None, hasxen=False, hasbootiso=False,
                           name="path%s" % newidx)
            d.distroclass = None
            urls[d.name] = d

    keys = urls.keys()
    keys.sort()
    for key in keys:
        distroobj = urls[key]

        for arch, url in [("i686", distroobj.i686),
                          ("x86_64", distroobj.x86_64)]:
            if not url:
                continue
            args = (key, arch, distroobj)
            testfunc = _make_test_wrapper(url, args)
            setattr(URLTests, "testURL%s%s" % (key, arch), testfunc)

_make_tests()
