# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import sys
import unittest


_alldistros = {}

DEVFEDORA_URL = "http://dl.fedoraproject.org/pub/fedora/linux/development/%s/Server/%s/os/"
FEDORA_URL = "http://dl.fedoraproject.org/pub/fedora/linux/releases/%s/Server/%s/os/"

(WARN_RHEL5,
 WARN_DEBIAN,
 WARN_FEDORA) = range(1, 4)


def prompt():
    sys.stdout.write("(press enter to continue)")
    sys.stdout.flush()
    return sys.stdin.readline()


KSOLD = "tests/inject-data/old-kickstart.ks"
KSNEW = "tests/inject-data/new-kickstart.ks"
PRESEED = "tests/inject-data/preseed.cfg"


class Distro(object):
    def __init__(self, name, url, filename, warntype=WARN_FEDORA):
        self.name = name
        self.url = url
        self.warntype = warntype
        self.filename = filename

        self.kernel = None
        self.initrd = None


def _add(*args, **kwargs):
    _d = Distro(*args, **kwargs)
    _alldistros[_d.name] = _d


_add("centos-5.11", "http://vault.centos.org/5.11/os/x86_64/",
     warntype=WARN_RHEL5, filename=KSOLD)
_add("centos-6-latest", "http://ftp.linux.ncsu.edu/pub/CentOS/6/os/x86_64/",
     warntype=WARN_RHEL5, filename=KSOLD)
_add("centos-7-latest", "http://ftp.linux.ncsu.edu/pub/CentOS/7/os/x86_64/",
     filename=KSNEW)
_add("fedora-27", FEDORA_URL % ("27", "x86_64"), filename=KSNEW)
_add("debian-9",
     "http://ftp.us.debian.org/debian/dists/stretch/main/installer-amd64/",
     filename=PRESEED, warntype=WARN_DEBIAN)


def _test_distro(distro):
    os.system("clear")
    print("\n")
    if distro.warntype == WARN_RHEL5:
        print("RHEL5, RHEL6, Fedora < 17: You'll get an error about a ")
        print("bogus bootproto ITREADTHEKICKSTART. This means anaconda ")
        print("read our busted kickstart.")
    elif distro.warntype == WARN_DEBIAN:
        print("Debian: Won't ask any questions, will autoconfig network, "
              "then print a big red text box about a bad mirror config.")
    elif distro.warntype == WARN_FEDORA:
        print("RHEL7, Fedora >= 17: Chokes on the bogus URI in the early ")
        print("console screen when fetching the installer squashfs image.")

    os.environ.pop("VIRTINST_TEST_SUITE", None)
    os.environ["VIRTINST_INITRD_TEST"] = "1"

    if distro.warntype == WARN_DEBIAN:
        append = "auto=true"
    else:
        append = "\"ks=file:/%s\"" % os.path.basename(distro.filename)
    cmd = ("./virt-install --connect qemu:///system "
        "--name __virtinst__test__initrd__ --ram 2048 "
        "--transient --destroy-on-exit --disk none "
        "--location %s --initrd-inject %s --extra-args %s" %
        (distro.url, distro.filename, append))
    print("\n\n" + cmd)
    os.system(cmd)


_printinitrd = False


class InjectTests(unittest.TestCase):
    def setUp(self):
        global _printinitrd
        if _printinitrd:
            return

        print("""


This is an interactive test suite.

We are going to launch various transient virt-installs, using initrd
injections, that will cause installs to quickly fail. Look for the
failure pattern to confirm that initrd injections are working as expected.

""")
        prompt()
        _printinitrd = True


def _make_tests():
    def _make_check_cb(_d):
        return lambda s: _test_distro(_d)

    idx = 0
    for dname, dobj in _alldistros.items():
        idx += 1
        setattr(InjectTests, "testInitrd%.3d_%s" %
                (idx, dname.replace("-", "_")), _make_check_cb(dobj))

_make_tests()
