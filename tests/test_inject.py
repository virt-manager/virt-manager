#!/usr/bin/python
# Copyright (C) 2013 Red Hat, Inc.

import atexit
import os
import sys
import unittest

import urlgrabber

from tests import INITRD_TEST_DISTROS
from tests import utils

from virtinst import Guest
from virtinst import urlfetcher
from virtinst.distroinstaller import _perform_initrd_injections

cleanup = []
_alldistros = {}

testconn = utils.open_testdefault()
guest = Guest(testconn)
guest.os.os_type = "hvm"
guest.os.arch = "x86_64"
meter = urlgrabber.progress.TextMeter(fo=sys.stdout)

DEVFEDORA_URL = "http://download.fedoraproject.org/pub/fedora/linux/development/%s/%s/os/"
OLD_FEDORA_URL = "https://archives.fedoraproject.org/pub/archive/fedora/linux/releases/%s/Fedora/%s/os/"
FEDORA_URL = "http://download.fedoraproject.org/pub/fedora/linux/releases/%s/Fedora/%s/os/"


def prompt():
    sys.stdout.write("(press enter to continue)")
    return sys.stdin.readline()


class Distro(object):
    def __init__(self, name, url, ks2=False, virtio=True):
        self.name = name
        self.url = url
        self.virtio = virtio

        self.ks = "tests/inject-data/old-kickstart.ks"
        if ks2:
            self.ks = "tests/inject-data/new-kickstart.ks"

        self.kernel = None
        self.initrd = None




def _add(*args, **kwargs):
    _d = Distro(*args, **kwargs)
    _alldistros[_d.name] = _d


_add("centos-4.9", "http://vault.centos.org/4.9/os/x86_64",
     ks2=True, virtio=False)
_add("centos-5-latest", "http://ftp.linux.ncsu.edu/pub/CentOS/5/os/x86_64/")
_add("centos-6-latest", "http://ftp.linux.ncsu.edu/pub/CentOS/6/os/x86_64/")
_add("fedora-14", OLD_FEDORA_URL % ("14", "x86_64"))
_add("fedora-15", OLD_FEDORA_URL % ("15", "x86_64"))
_add("fedora-16", OLD_FEDORA_URL % ("16", "x86_64"))
_add("fedora-17", OLD_FEDORA_URL % ("17", "x86_64"))
_add("fedora-18", FEDORA_URL % ("18", "x86_64"), ks2=True)
_add("fedora-19", FEDORA_URL % ("19", "x86_64"), ks2=True)
_add("fedora-20", DEVFEDORA_URL % ("20", "x86_64"), ks2=True)


def exit_cleanup():
    for f in cleanup or []:
        try:
            os.unlink(f)
        except:
            pass
atexit.register(exit_cleanup)


def _fetch_distro(distro):
    print "Fetching distro=%s" % distro.name

    fetcher = urlfetcher.fetcherForURI(distro.url, "/tmp", meter)
    try:
        fetcher.prepareLocation()
        store = urlfetcher.getDistroStore(guest, fetcher)
        kernel, initrd, ignore = store.acquireKernel(guest)
        cleanup.append(kernel)
        cleanup.append(initrd)
        distro.kernel = kernel
        distro.initrd = initrd
    finally:
        fetcher.cleanupLocation()


def _test_distro(distro):
    originitrd = distro.initrd
    kernel = distro.kernel
    newinitrd = originitrd + ".copy"
    injectfile = distro.ks

    os.system("cp -f %s %s" % (originitrd, newinitrd))
    cleanup.append(newinitrd)
    _perform_initrd_injections(newinitrd, [injectfile], ".")

    nic = distro.virtio and "virtio" or "rtl8139"
    append = "-append \"ks=file:/%s\"" % os.path.basename(injectfile)
    print os.environ["DISPLAY"]
    cmd = ("sudo qemu-kvm -enable-kvm -name %s "
           "-cpu host -m 1500 -sdl "
           "-net bridge,br=virbr0 -net nic,model=%s "
           "-kernel %s -initrd %s %s" %
           (distro.name, nic, kernel, newinitrd, append))
    print "\n\n" + cmd
    os.system(cmd)


_printinitrd = False
_printfetch = False


class FetchTests(unittest.TestCase):
    def setUp(self):
        global _printfetch
        if _printfetch:
            return
        print """



This is an interactive test.

First step is we need to go and fetch a bunch of distro kernel/initrd
from public trees. This is going to take a while. Let it run then come
back later and we will be waiting to continue.

"""
        prompt()
        _printfetch = True


class InjectTests(unittest.TestCase):
    def setUp(self):
        global _printinitrd
        if _printinitrd:
            return
        print """



Okay, we have all the media. We are going to perform the initrd injection
of some stock kickstarts, then manually launch a qemu instance to verify
it's working. How you know it's working depends on the distro (look at
the qemu window title):

RHEL4: Makes its way to the text installer, then chokes on our bogus URI
http://HEY-THIS-IS-OUR-BAD-KICKSTART-URL.com/

RHEL5, RHEL6, Fedora < 17: You'll get an error about a bogus bootproto
ITREADTHEKICKSTART. This means anaconda read our busted kickstart.

Fedora >= 17: Chokes on the bogus URI in the early console screen when
fetching the installer squashfs image.

"""
        prompt()
        _printinitrd = True


def _make_tests():
    def _make_fetch_cb(_d):
        return lambda s: _fetch_distro(_d)
    def _make_check_cb(_d):
        return lambda s: _test_distro(_d)

    distros = INITRD_TEST_DISTROS or _alldistros.keys()
    idx = 0
    for d in distros:
        dobj = _alldistros[d]
        idx += 1
        setattr(FetchTests, "testFetch%.3d" % idx, _make_fetch_cb(dobj))
        setattr(InjectTests, "testInitrd%.3d" % idx, _make_check_cb(dobj))

_make_tests()
