#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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
import sys

import urlgrabber.progress

from tests import utils

from virtinst import Guest
from virtinst import urlfetcher
from virtinst.urlfetcher import FedoraDistro
from virtinst.urlfetcher import SuseDistro
from virtinst.urlfetcher import DebianDistro
from virtinst.urlfetcher import CentOSDistro
from virtinst.urlfetcher import SLDistro
from virtinst.urlfetcher import UbuntuDistro
from virtinst.urlfetcher import MandrivaDistro


# pylint: disable=W0212
# Access to protected member, needed to unittest stuff

# Variable used to store a local iso or dir path to check for a distro
# Specified via 'python setup.py test_urls --path"
LOCAL_MEDIA = []

OLD_FEDORA_URL = "https://archives.fedoraproject.org/pub/archive/fedora/linux/releases/%s/Fedora/%s/os/"
DEVFEDORA_URL = "http://download.fedoraproject.org/pub/fedora/linux/development/%s/%s/os/"
FEDORA_URL = "http://download.fedoraproject.org/pub/fedora/linux/releases/%s/Fedora/%s/os/"

OLD_CENTOS_URL = "http://vault.centos.org/%s/os/%s"
CENTOS_URL = "http://ftp.linux.ncsu.edu/pub/CentOS/%s/os/%s/"
OLD_SCIENTIFIC_URL = "http://ftp.scientificlinux.org/linux/scientific/%s/%s/"
SCIENTIFIC_URL = "http://ftp.scientificlinux.org/linux/scientific/%s/%s/os"

OPENSUSE10 = "http://ftp.hosteurope.de/mirror/ftp.opensuse.org/discontinued/10.0"
OLD_OPENSUSE_URL = "http://ftp5.gwdg.de/pub/opensuse/discontinued/distribution/%s/repo/oss"
OPENSUSE_URL = "http://download.opensuse.org/distribution/%s/repo/oss/"

OLD_UBUNTU_URL = "http://old-releases.ubuntu.com/ubuntu/dists/%s/main/installer-%s"
UBUNTU_URL = "http://us.archive.ubuntu.com/ubuntu/dists/%s/main/installer-%s"

OLD_DEBIAN_URL = "http://archive.debian.org/debian/dists/%s/main/installer-%s/"
DAILY_DEBIAN_URL = "http://d-i.debian.org/daily-images/%s/"
DEBIAN_URL = "http://ftp.us.debian.org/debian/dists/%s/main/installer-%s/"

MANDRIVA_URL = "http://ftp.uwsg.indiana.edu/linux/mandrake/official/%s/%s/"


urls = {}
_distro = None


class _DistroURL(object):
    def __init__(self, x86_64, detectdistro="linux", i686=None,
                 hasxen=True, hasbootiso=True, name=None):
        self.x86_64 = x86_64
        self.i686 = i686
        self.detectdistro = detectdistro
        self.hasxen = hasxen
        self.hasbootiso = hasbootiso
        self.name = name or self.detectdistro
        self.distroclass = _distro


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
_add(OLD_FEDORA_URL % ("14", "x86_64"), "fedora14",
     i686=OLD_FEDORA_URL % ("14", "i386"))
# 2 Latest releases
_add(FEDORA_URL % ("18", "x86_64"), "fedora18")
_add(FEDORA_URL % ("19", "x86_64"), "fedora19")
# Any Dev release
_add(DEVFEDORA_URL % ("20", "x86_64"), "fedora20")
# Rawhide w/ i686 test
_add(DEVFEDORA_URL % ("rawhide", "x86_64"), "fedora20",
     i686=DEVFEDORA_URL % ("rawhide", "i386"),
     name="fedora-rawhide")


_set_distro(CentOSDistro)
# One old and new centos 4. No distro detection since there's no treeinfo
_add(OLD_CENTOS_URL % ("4.0", "x86_64"), hasxen=False, name="centos-4.0")
_add(OLD_CENTOS_URL % ("4.9", "x86_64"), name="centos-4.9")
# One old centos 5
_add(OLD_CENTOS_URL % ("5.0", "x86_64"), name="centos-5.0")
# Latest centos 5 w/ i686
_add(CENTOS_URL % ("5", "x86_64"), "rhel5.4", name="centos-5-latest",
     i686=CENTOS_URL % ("5", "i386"))
# Latest centos 6 w/ i686
_add(CENTOS_URL % ("6", "x86_64"), "rhel6", name="centos-6-latest",
     i686=CENTOS_URL % ("6", "i386"))


_set_distro(SLDistro)
# Latest scientific 5
_add(OLD_SCIENTIFIC_URL % ("55", "x86_64"), "rhel5.4", name="sl-5latest")
# Latest scientific 6
_add(SCIENTIFIC_URL % ("6", "x86_64"), "rhel6", name="sl-6latest")


_set_distro(SuseDistro)
# opensuse 10.0 uses different paths, so keep this around
_add(OPENSUSE10, i686=OPENSUSE10, hasxen=False, hasbootiso=False,
     name="opensuse-10.0")
# Latest 10 series
_add(OLD_OPENSUSE_URL % ("10.3"), hasbootiso=False, name="opensuse-10.3")
# Latest 11 series
_add(OLD_OPENSUSE_URL % ("11.4"), hasbootiso=False, name="opensuse-11.4")
# Latest 12 series
# Only keep i686 for the latest opensuse
_add(OPENSUSE_URL % ("12.3"), i686=OPENSUSE_URL % ("12.3"), hasbootiso=False,
     name="opensuse-12.3")


_set_distro(DebianDistro)
# Debian releases rarely enough that we can just do every release since lenny
_add(OLD_DEBIAN_URL % ("lenny", "amd64"), hasxen=False, name="debian-lenny")
_add(DEBIAN_URL % ("squeeze", "amd64"), name="debian-squeeze")
_add(DEBIAN_URL % ("wheezy", "amd64"), name="debian-wheezy")
# And daily builds, since we specially handle that URL
_add(DAILY_DEBIAN_URL % ("amd64"), name="debian-daily")


_set_distro(UbuntuDistro)
# One old ubuntu
_add(OLD_UBUNTU_URL % ("hardy", "amd64"),
     i686=OLD_UBUNTU_URL % ("hardy", "i386"),
     hasxen=False, name="ubuntu-hardy")
# Latest LTS
_add(UBUNTU_URL % ("precise", "amd64"), name="ubuntu-precise")
# Latest release
_add(UBUNTU_URL % ("raring", "amd64"), name="ubuntu-raring")


_set_distro(MandrivaDistro)
# One old mandriva
_add(MANDRIVA_URL % ("2010.2", "x86_64"),
     i686=MANDRIVA_URL % ("2010.2", "i586"),
     hasxen=False, name="mandriva-2010.2")


testconn = utils.open_testdefault()
hvmguest = Guest(testconn)
hvmguest.os.os_type = "hvm"
xenguest = Guest(testconn)
xenguest.os.os_type = "xen"

meter = urlgrabber.progress.BaseMeter()
if utils.get_debug():
    meter = urlgrabber.progress.TextMeter(fo=sys.stdout)


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
    raise


def _testLocalMedia(fetcher, path):
    """
    Test a local path explicitly requested by the user
    """
    print "\nChecking local path: %s" % path
    arch = platform.machine()

    # Make sure we detect _a_ distro
    hvmguest.os.arch = arch
    hvmstore = _storeForDistro(fetcher, hvmguest)
    logging.debug("Local distro detected as: %s", hvmstore)


def _testURL(fetcher, distname, arch, distroobj):
    """
    Test that our URL detection logic works for grabbing kernel, xen
    kernel, and boot.iso
    """
    print "\nTesting %s-%s" % (distname, arch)
    hvmguest.os.arch = arch
    xenguest.os.arch = arch

    hvmstore = _storeForDistro(fetcher, hvmguest)
    xenstore = None
    if distroobj.hasxen:
        xenstore = _storeForDistro(fetcher, xenguest)

    for s in [hvmstore, xenstore]:
        if s and not isinstance(s, distroobj.distroclass):
            raise AssertionError("(%s): expected store %s, was %s" %
                                 (distname, distroobj.distroclass, s))

        # Make sure the stores are reporting correct distro name/variant
        if s and distroobj.detectdistro != s.os_variant:
            raise AssertionError("Store distro/variant did not match "
                "expected values: store=%s, found=%s expect=%s" %
                (s, s.os_variant, distroobj.detectdistro))

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


def _make_test_wrapper(url, cb, args):
    def cmdtemplate():
        return _fetch_wrapper(url, cb, *args)
    return lambda _self: cmdtemplate()


# Register tests to be picked up by unittest
# If local ISO tests requested, skip all other URL tests
class URLTests(unittest.TestCase):
    pass


def _make_tests():
    if LOCAL_MEDIA:
        newidx = 0
        for p in LOCAL_MEDIA:
            newidx += 1
            args = (p,)
            testfunc = _make_test_wrapper(p, _testLocalMedia, args)
            setattr(URLTests, "testLocalMedia%s" % newidx, testfunc)
    else:
        keys = urls.keys()
        keys.sort()
        for key in keys:
            distroobj = urls[key]

            for arch, url in [("i686", distroobj.i686),
                              ("x86_64", distroobj.x86_64)]:
                if not url:
                    continue
                args = (key, arch, distroobj)
                testfunc = _make_test_wrapper(url, _testURL, args)
                setattr(URLTests, "testURL%s%s" % (key, arch), testfunc)

_make_tests()
