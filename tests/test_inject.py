#!/usr/bin/env python2
# Copyright (C) 2013, 2014 Red Hat, Inc.

from __future__ import print_function

import atexit
import os
import sys
import unittest

from tests import utils

from virtinst import Guest
from virtinst import urlfetcher
from virtinst import util
from virtinst.initrdinject import perform_initrd_injections

cleanup = []
_alldistros = {}

testconn = utils.open_testdefault()
guest = Guest(testconn)
guest.os.os_type = "hvm"
guest.os.arch = "x86_64"
meter = util.make_meter(quiet=False)

DEVFEDORA_URL = "http://dl.fedoraproject.org/pub/fedora/linux/development/%s/Server/%s/os/"
FEDORA_URL = "http://dl.fedoraproject.org/pub/fedora/linux/releases/%s/Server/%s/os/"

(WARN_RHEL4,
 WARN_RHEL5,
 WARN_LATEST) = range(1, 4)


def prompt():
    sys.stdout.write("(press enter to continue)")
    return sys.stdin.readline()


class Distro(object):
    def __init__(self, name, url, warntype=WARN_LATEST,
                 ks2=False, virtio=True):
        self.name = name
        self.url = url
        self.virtio = virtio
        self.warntype = warntype

        self.ks = "tests/inject-data/old-kickstart.ks"
        if ks2:
            self.ks = "tests/inject-data/new-kickstart.ks"

        self.kernel = None
        self.initrd = None


def _add(*args, **kwargs):
    _d = Distro(*args, **kwargs)
    _alldistros[_d.name] = _d


_add("centos-4.9", "http://vault.centos.org/4.9/os/x86_64",
     warntype=WARN_RHEL4, ks2=True, virtio=False)
_add("centos-5.11", "http://vault.centos.org/5.11/os/x86_64/",
     warntype=WARN_RHEL5)
_add("centos-6-latest", "http://ftp.linux.ncsu.edu/pub/CentOS/6/os/x86_64/",
     warntype=WARN_RHEL5)
_add("centos-7-latest", "http://ftp.linux.ncsu.edu/pub/CentOS/7/os/x86_64/",
     ks2=True)
_add("fedora-25", FEDORA_URL % ("25", "x86_64"), ks2=True)
_add("fedora-26", DEVFEDORA_URL % ("26", "x86_64"), ks2=True)


def exit_cleanup():
    for f in cleanup or []:
        try:
            os.unlink(f)
        except Exception:
            pass
atexit.register(exit_cleanup)


def _fetch_distro(distro):
    print("Fetching distro=%s" % distro.name)

    fetcher = urlfetcher.fetcherForURI(distro.url, "/tmp", meter)
    origenv = os.environ.pop("VIRTINST_TEST_SUITE")
    try:
        fetcher.prepareLocation()
        store = urlfetcher.getDistroStore(guest, fetcher)
        kernel, initrd, ignore = store.acquireKernel(guest)
        cleanup.append(kernel)
        cleanup.append(initrd)
        distro.kernel = kernel
        distro.initrd = initrd
    except Exception as e:
        print("fetching distro=%s failed: %s" % (distro.name, e))
    finally:
        fetcher.cleanupLocation()
        if origenv:
            os.environ["VIRTINST_TEST_SUITE"] = origenv


def _test_distro(distro):
    os.system("clear")
    print("\n")
    if distro.warntype == WARN_RHEL4:
        print("RHEL4: Makes its way to the text installer, then chokes ")
        print("on our bogus URI http://HEY-THIS-IS-OUR-BAD-KICKSTART-URL.com/")
    elif distro.warntype == WARN_RHEL5:
        print("RHEL5, RHEL6, Fedora < 17: You'll get an error about a ")
        print("bogus bootproto ITREADTHEKICKSTART. This means anaconda ")
        print("read our busted kickstart.")
    else:
        print("RHEL7, Fedora >= 17: Chokes on the bogus URI in the early ")
        print("console screen when fetching the installer squashfs image.")

    originitrd = distro.initrd
    kernel = distro.kernel
    newinitrd = originitrd + ".copy"
    injectfile = distro.ks

    os.system("cp -f %s %s" % (originitrd, newinitrd))
    cleanup.append(newinitrd)
    perform_initrd_injections(newinitrd, [injectfile], ".")

    nic = distro.virtio and "virtio" or "rtl8139"
    append = "-append \"ks=file:/%s\"" % os.path.basename(injectfile)
    cmd = ("sudo qemu-kvm -enable-kvm -name %s "
           "-cpu host -m 1500 -display gtk "
           "-net bridge,br=virbr0 -net nic,model=%s "
           "-kernel %s -initrd %s %s" %
           (distro.name, nic, kernel, newinitrd, append))
    print("\n\n" + cmd)
    os.system(cmd)


_printinitrd = False
_printfetch = False


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.failfast = True
        global _printfetch
        if _printfetch:
            return
        print ("""



This is an interactive test.

First step is we need to go and fetch a bunch of distro kernel/initrd
from public trees. This is going to take a while. Let it run then come
back later and we will be waiting to continue.

""")
        prompt()
        _printfetch = True


class InjectTests(unittest.TestCase):
    def setUp(self):
        global _printinitrd
        if _printinitrd:
            return

        print("""


Okay, we have all the media. We are going to perform the initrd injection
of some broken kickstarts, then manually launch a qemu instance to verify
the kickstart is detected. How you know it's working depends on the distro.
When each test launches, we will print the manual verification instructions.

""")
        prompt()
        _printinitrd = True


def _make_tests():
    def _make_fetch_cb(_d):
        return lambda s: _fetch_distro(_d)
    def _make_check_cb(_d):
        return lambda s: _test_distro(_d)

    idx = 0
    for dname, dobj in _alldistros.items():
        idx += 1
        setattr(FetchTests, "testFetch%.3d_%s" %
                (idx, dname.replace("-", "_")), _make_fetch_cb(dobj))
        setattr(InjectTests, "testInitrd%.3d_%s" %
                (idx, dname.replace("-", "_")), _make_check_cb(dobj))

_make_tests()
