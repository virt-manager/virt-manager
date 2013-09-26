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
import re
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

FEDORA_BASEURL = "http://download.fedoraproject.org/pub/fedora/linux/releases/%s/Fedora/%s/os/"
OPENSUSE_BASEURL = "http://download.opensuse.org/distribution/%s/repo/oss/"
OLD_OPENSUSE_BASEURL = "http://ftp5.gwdg.de/pub/opensuse/discontinued/distribution/%s/repo/oss"

OLDUBUNTU_BASEURL = "http://old-releases.ubuntu.com/ubuntu/dists/%s/main/installer-%s"
UBUNTU_BASEURL = "http://us.archive.ubuntu.com/ubuntu/dists/%s/main/installer-%s"
OLDDEBIAN_BASEURL = "http://archive.debian.org/debian/dists/%s/main/installer-%s/"
DEBIAN_BASEURL = "http://ftp.us.debian.org/debian/dists/%s/main/installer-%s/"

CURCENTOS_BASEURL = "http://ftp.linux.ncsu.edu/pub/CentOS/%s/os/%s/"
OLDCENTOS_BASEURL = "http://vault.centos.org/%s/os/%s"
MANDRIVA_BASEURL = "http://ftp.uwsg.indiana.edu/linux/mandrake/official/%s/%s/"
SCIENTIFIC_BASEURL = "http://ftp.scientificlinux.org/linux/scientific/%s/%s/"

# Doesn't appear to be a simple boot iso in newer suse trees
NOBOOTISO_FILTER = ".*opensuse12.*|.*opensuse11.*|.*opensuse10.3.*|.*opensuse10.0.*"


# Return the expected Distro class for the passed distro label
def distroClass(distname):
    if re.match(r".*fedora.*", distname):
        return FedoraDistro
    elif re.match(r".*suse.*", distname):
        return SuseDistro
    elif re.match(r".*debian.*", distname):
        return DebianDistro
    elif re.match(r".*centos.*", distname):
        return CentOSDistro
    elif re.match(r".*ubuntu.*", distname):
        return UbuntuDistro
    elif re.match(r".*mandriva.*", distname):
        return MandrivaDistro
    elif re.match(r".*scientific.*", distname):
        return SLDistro
    raise RuntimeError("distroClass: no distro registered for '%s'" % distname)


# Dictionary with all the test data
urls = {

    # Fedora Distros
    "fedora15" : {
        'x86_64': FEDORA_BASEURL % ("18", "x86_64"),
        'distro': "fedora18"
   },
    "fedora16" : {
        'x86_64': FEDORA_BASEURL % ("19", "x86_64"),
        'distro': "fedora19"
   },

    # SUSE Distros
    "opensuse10.2" : {
        'x86_64': OLD_OPENSUSE_BASEURL % ("10.2")
   },
    "opensuse10.3" : {
        'x86_64': OLD_OPENSUSE_BASEURL % ("10.3")
   },
    "opensuse11.4" : {
        'x86_64': OPENSUSE_BASEURL % ("11.4")
   },
    # Only keep i686 for the latest
    "opensuse12.1" : {
        'i386'  : OPENSUSE_BASEURL % ("12.1"),
        'x86_64': OPENSUSE_BASEURL % ("12.1")
   },

    # Debian Distros
    "debian-lenny-64" : {
        "noxen": True,
        'x86_64': OLDDEBIAN_BASEURL % ("lenny", "amd64"),
        'distro': "linux"
   },
    "debian-squeeze" : {
        'i386' : DEBIAN_BASEURL % ("squeeze", "i386"),
        'x86_64': DEBIAN_BASEURL % ("squeeze", "amd64"),
        'distro': "linux"
   },
    "debian-wheezy" : {
        'x86_64': DEBIAN_BASEURL % ("wheezy", "amd64"),
        'distro': "linux"
   },
    "debian-sid" : {
        'x86_64': DEBIAN_BASEURL % ("sid", "amd64"),
        'distro': "linux"
   },
    "debian-daily" : {
        'i386' : "http://d-i.debian.org/daily-images/amd64/",
        'distro': "linux"
   },

    # CentOS Distros
    "centos-6-latest" : {
        'i386' : CURCENTOS_BASEURL % ("6", "i386"),
        'x86_64' : CURCENTOS_BASEURL % ("6", "x86_64"),
        'distro': "rhel6"
   },
    "centos-5-latest" : {
        'i386' : CURCENTOS_BASEURL % ("5", "i386"),
        'x86_64' : CURCENTOS_BASEURL % ("5", "x86_64"),
        'distro': "rhel5.4"
   },
    "centos-5.0" : {
        'x86_64' : OLDCENTOS_BASEURL % ("5.0", "x86_64"),
        'distro': "linux"
   },
    "centos-4.0" : {
        "noxen": True,
        'x86_64' : OLDCENTOS_BASEURL % ("4.0", "x86_64"),
        'distro': "linux"
   },
    "centos-4.9" : {
        'x86_64' : OLDCENTOS_BASEURL % ("4.9", "x86_64"),
        'distro': "linux"
   },

    # Scientific Linux
    "scientific-5.4" : {
        'x86_64': SCIENTIFIC_BASEURL % ("54", "x86_64"),
        'distro': "rhel5.4"
   },
    "scientific-5.2" : {
        'x86_64': SCIENTIFIC_BASEURL % ("52", "x86_64"),
        'distro': "rhel5"
   },
    "scientific-5.0" : {
        'x86_64': SCIENTIFIC_BASEURL % ("50", "x86_64"),
        'distro': "linux"
   },

    # Ubuntu
    "ubuntu-hardy" : {
        "noxen": True,
        'i386': OLDUBUNTU_BASEURL % ("hardy", "i386"),
        'x86_64': OLDUBUNTU_BASEURL % ("hardy", "amd64"),
        'distro': "linux"
   },
    "ubuntu-maverick" : {
        'i386': OLDUBUNTU_BASEURL % ("maverick", "i386"),
        'x86_64': OLDUBUNTU_BASEURL % ("maverick", "amd64"),
        'distro': "linux"
   },
    "ubuntu-natty" : {
        'i386': OLDUBUNTU_BASEURL % ("natty", "i386"),
        'x86_64': OLDUBUNTU_BASEURL % ("natty", "amd64"),
        'distro': "linux"
   },
    "ubuntu-oneiric" : {
        'i386': UBUNTU_BASEURL % ("oneiric", "i386"),
        'x86_64': UBUNTU_BASEURL % ("oneiric", "amd64"),
        'distro': "linux"
   },
    "ubuntu-precise" : {
        'i386': UBUNTU_BASEURL % ("precise", "i386"),
        'x86_64': UBUNTU_BASEURL % ("precise", "amd64"),
        'distro': "linux"
   },

    # Mandriva
    "mandriva-2009.1" : {
        "noxen": True,
        'i586': MANDRIVA_BASEURL % ("2009.1", "i586"),
        'x86_64': MANDRIVA_BASEURL % ("2009.1", "x86_64"),
        'distro': "linux"
   },
    "mandriva-2010.2" : {
        "noxen": True,
        'i586': MANDRIVA_BASEURL % ("2010.2", "i586"),
        'x86_64': MANDRIVA_BASEURL % ("2010.2", "x86_64"),
        'distro': "linux"
   },
}


testconn = utils.open_testdefault()
testguest = Guest(testconn)
meter = urlgrabber.progress.BaseMeter()
if utils.get_debug():
    meter = urlgrabber.progress.TextMeter(fo=sys.stdout)


def _storeForDistro(fetcher, url, _type, arch):
    """
    Helper to lookup the Distro store object, basically detecting the
    URL. Handle occasional proxy errors
    """
    for ignore in range(0, 10):
        try:
            return urlfetcher._storeForDistro(fetcher=fetcher, baseuri=url,
                                            progresscb=meter,
                                            arch=arch, typ=_type)
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
    hvmstore = _storeForDistro(fetcher, path, "hvm", arch)
    logging.debug("Local distro detected as: %s", hvmstore)


def _testURL(fetcher, distname, url, arch, detect_distro, check_xen):
    """
    Test that our URL detection logic works for grabbing kernel, xen
    kernel, and boot.iso
    """
    print "\nTesting %s-%s" % (distname, arch)

    hvmstore = _storeForDistro(fetcher, url, "hvm", arch)
    xenstore = None
    if check_xen:
        xenstore = _storeForDistro(fetcher, url, "xen", arch)

    exp_store = distroClass(distname)
    for s in [hvmstore, xenstore]:
        if s and not isinstance(s, exp_store):
            raise AssertionError("(%s): expected store %s, was %s" %
                                 (distname, exp_store, s))

        # Make sure the stores are reporting correct distro name/variant
        if s and detect_distro and detect_distro != s.os_variant:
            raise AssertionError("Store distro/variant did not match "
                "expected values: store=%s, found=%s expect=%s" %
                (s, s.os_variant, detect_distro))

    # Do this only after the distro detection, since we actually need
    # to fetch files for that part
    def fakeAcquireFile(filename, _meter):
        ignore = _meter
        logging.debug("Fake acquiring %s", filename)
        return fetcher.hasFile(filename)
    fetcher.acquireFile = fakeAcquireFile

    # Fetch boot iso
    if re.match(r"%s" % NOBOOTISO_FILTER, distname):
        logging.debug("Known lack of boot.iso in %s tree. Skipping.",
                      distname)
    else:
        boot = hvmstore.acquireBootDisk(testguest, fetcher, meter)
        logging.debug("acquireBootDisk: %s", str(boot))

        if boot is not True:
            raise AssertionError("%s-%s: bootiso fetching failed" %
                                 (distname, arch))

    # Fetch regular kernel
    kern = hvmstore.acquireKernel(testguest, fetcher, meter)
    logging.debug("acquireKernel (hvm): %s", str(kern))

    if kern[0] is not True or kern[1] is not True:
        AssertionError("%s-%s: hvm kernel fetching failed" %
                       (distname, arch))

    # Fetch xen kernel
    if xenstore and check_xen:
        kern = xenstore.acquireKernel(testguest, fetcher, meter)
        logging.debug("acquireKernel (xen): %s", str(kern))

        if kern[0] is not True or kern[1] is not True:
            raise AssertionError("%s-%s: xen kernel fetching" %
                                 (distname, arch))
    else:
        logging.debug("acquireKernel (xen): Hardcoded skipping.")



def _fetch_wrapper(url, cb, *args):
    fetcher = urlfetcher._fetcherForURI(url, "/tmp")
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
            distro_dict = urls[key]
            detect_distro = distro_dict.pop("distro", "linux")
            check_xen = not distro_dict.pop("noxen", False)

            for arch, url in distro_dict.items():
                args = (key, url, arch, detect_distro, check_xen)
                testfunc = _make_test_wrapper(url, _testURL, args)
                setattr(URLTests, "testURL%s%s" % (key, arch), testfunc)

_make_tests()
