# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import tempfile

import tests
from . import lib


def _search_permissions_decorator(fn):
    """
    Decorator to set up necessary bits to test disk permission search
    """
    def wrapper(app, *args, **kwargs):
        # Generate capabilities XML from a template, with out
        # UID/GID inserted as the intended emulator permissions
        capsfile = (tests.utils.UITESTDATADIR +
                "/capabilities/dac-caps-template.xml")
        capsdata = open(capsfile).read() % {
                "UID": os.getuid(), "GID": os.getgid()}
        tmpcaps = tempfile.NamedTemporaryFile(
                prefix="virt-manager-uitests-caps")
        tmpcapspath = tmpcaps.name
        open(tmpcapspath, "w").write(capsdata)

        # We mock a qemu URI to trigger the permissions check
        uri = (tests.utils.URIs.test_full +
                ",fakeuri=qemu:///system,caps=%s" % tmpcapspath)

        # Create a temporary directory that we can manipulate perms
        tmpobj = tempfile.TemporaryDirectory(
                prefix="virtinst-test-search")
        tmpdir = tmpobj.name
        try:
            os.chmod(tmpdir, 0o000)
            fn(app, uri, tmpdir, *args, **kwargs)
        finally:
            os.chmod(tmpdir, 0o777)
    return wrapper


def _select_hw(addhw, hwname, tabname):
    addhw.find(hwname, "table cell").click()
    tab = addhw.find(tabname, None)
    lib.utils.check(lambda: tab.showing)
    return tab


def _finish(addhw, check):
    addhw.find("Finish", "push button").click()
    lib.utils.check(lambda: not addhw.active)
    if check:
        lib.utils.check(lambda: check.active)


def _open_addhw(app, details):
    details.find("add-hardware", "push button").click()
    addhw = app.find_window("Add New Virtual Hardware")
    return addhw


def _open_app(app, vmname, title=None, shutdown=False, **kwargs):
    app.open(show_console=vmname, **kwargs)
    details = app.find_details_window(title or vmname,
            click_details=True, shutdown=shutdown)
    return details


##############
# Test cases #
##############


def testAddControllers(app):
    """
    Add various controller configs
    """
    details = _open_app(app, "test-clone-simple")
    addhw = _open_addhw(app, details)

    # Default SCSI
    tab = _select_hw(addhw, "Controller", "controller-tab")
    tab.combo_select("Type:", "SCSI")
    _finish(addhw, check=details)

    # Virtio SCSI
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Controller", "controller-tab")
    tab.combo_select("Type:", "SCSI")
    tab.combo_select("Model:", "VirtIO SCSI")
    _finish(addhw, check=details)

    # USB 2
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Controller", "controller-tab")
    tab.combo_select("Type:", "USB")
    tab.combo_select("Model:", "USB 2")
    _finish(addhw, check=details)

    # USB 3
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Controller", "controller-tab")
    tab.combo_select("Type:", "USB")
    tab.combo_select("Model:", "USB 3")
    # Can't add more than 1 USB controller, so finish isn't sensitive
    finish = addhw.find("Finish", "push button")
    lib.utils.check(lambda: not finish.sensitive)


def testAddCephDisk(app):
    """
    Add a disk with a ceph volume, ensure it maps correctly
    """
    details = _open_app(app, "test-clone-simple")
    addhw = _open_addhw(app, details)

    # Select ceph volume for disk
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    tab.find("storage-browse", "push button").click()
    browse = app.root.find("vmm-storage-browser")
    browse.find_fuzzy("rbd-ceph", "table cell").bring_on_screen().click()
    browse.find_fuzzy("some-rbd-vol", "table cell").click()
    browse.find("Choose Volume", "push button").click()
    _finish(addhw, check=details)

    # Check disk details, make sure it correctly selected volume
    details.find("IDE Disk 2", "table cell").click()
    tab = details.find("disk-tab")
    lib.utils.check(lambda: tab.showing)
    disk_path = tab.find("disk-source-path")
    lib.utils.check(lambda: "rbd-sourcename/some-rbd-vol" in disk_path.text)


def testAddDisks(app):
    """
    Add various disk configs and test storage browser
    """
    details = _open_app(app, "test-clone-simple")
    addhw = _open_addhw(app, details)

    # Default disk
    tab = _select_hw(addhw, "Storage", "storage-tab")
    _finish(addhw, check=details)

    # Disk with some tweaks
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.combo_select("Bus type:", "VirtIO")
    tab.find("Advanced options", "toggle button").click_expander()
    tab.find("Shareable:", "check box").click()
    tab.find("Readonly:", "check box").click()
    tab.find("Serial:", "text").set_text("ZZZZ")
    tab.combo_select("Cache mode:", "none")
    tab.combo_select("Discard mode:", "ignore")
    tab.combo_select("Detect zeroes:", "unmap")
    # High number but we are non-sparse by default so it won't complain
    tab.find("GiB", "spin button").set_text("200000")
    _finish(addhw, check=details)

    # USB disk with removable setting
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.combo_select("Bus type:", "USB")
    tab.find("Advanced options", "toggle button").click_expander()
    tab.find("Removable:", "check box").click()
    _finish(addhw, check=details)

    # Managed storage tests
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    _finish(addhw, check=None)
    app.click_alert_button("storage path must be specified", "OK")
    tab.find("storage-browse", "push button").click()
    browse = app.root.find("vmm-storage-browser")

    # Create a vol, refresh, then delete it
    browse.find_fuzzy("default-pool", "table cell").click()
    browse.find("vol-new", "push button").click()
    newvol = app.find_window("Add a Storage Volume")
    newname = "a-newvol"
    newvol.find("Name:", "text").set_text(newname)
    newvol.find("Finish", "push button").click()
    lib.utils.check(lambda: not newvol.showing)
    volcell = browse.find(newname, "table cell")
    lib.utils.check(lambda: volcell.selected)
    browse.find("vol-refresh", "push button").click()
    volcell = browse.find(newname, "table cell")
    lib.utils.check(lambda: volcell.selected)
    browse.find("vol-delete", "push button").click()
    app.click_alert_button("permanently delete the volume", "Yes")
    lib.utils.check(lambda: volcell.dead)

    # Test browse local
    browse.find("Browse Local", "push button").click()
    chooser = app.root.find(
            "Locate existing storage", "file chooser")

    # use filename that is near the beginning of the file list when sorted,
    # as the row in the file dialog may become scrolled out of the view and
    # cause the test to fail
    fname = "COPYING"
    chooser.find(fname, "table cell").click()
    chooser.find("Open", "push button").click()
    lib.utils.check(lambda: not chooser.showing)
    lib.utils.check(lambda: addhw.active)
    storageent = tab.find("storage-entry")
    lib.utils.check(lambda: ("/" + fname) in storageent.text)

    # Reopen dialog, select a volume, etic
    tab.find("storage-browse", "push button").click()
    browse = app.root.find("vmm-storage-browser")

    browse.find_fuzzy("disk-pool", "table cell").click()
    browse.find("diskvol1", "table cell").click()
    browse.find("Choose Volume", "push button").click()
    lib.utils.check(lambda: "/diskvol1" in storageent.text)
    _finish(addhw, check=None)
    app.click_alert_button("already in use by", "No")
    _finish(addhw, check=None)
    app.click_alert_button("already in use by", "Yes")
    lib.utils.check(lambda: details.active)


    # choose file for floppy
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.combo_select("Device type:", "Floppy device")
    diskradio = tab.find_fuzzy("Create a disk image", "radio")
    lib.utils.check(lambda: not diskradio.sensitive)
    tab.find("storage-entry").set_text("/dev/default-pool/bochs-vol")
    _finish(addhw, check=details)

    # empty cdrom
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.combo_select("Device type:", "CDROM device")
    tab.combo_select("Bus type:", "SCSI")
    _finish(addhw, check=details)


@_search_permissions_decorator
def testAddDiskSearchPermsCheckbox(app, uri, tmpdir):
    """
    Test search permissions 'no' and checkbox case
    """
    app.uri = uri
    details = _open_app(app, "test-clone-simple")

    # Say 'No' but path should still work due to test driver
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    path = tmpdir + "/foo1.img"
    tab.find("storage-entry").set_text(path)
    _finish(addhw, check=None)
    app.click_alert_button("emulator may not have", "No")
    lib.utils.check(lambda: details.active)

    # Say 'don't ask again'
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    path = tmpdir + "/foo2.img"
    tab.find("storage-entry").set_text(path)
    _finish(addhw, check=None)
    alert = app.root.find_fuzzy("vmm dialog", "alert")
    alert.find_fuzzy("Don't ask", "check box").click()
    app.click_alert_button("emulator may not have", "No")
    lib.utils.check(lambda: details.active)

    # Confirm it doesn't ask about path again
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    path = tmpdir + "/foo3.img"
    tab.find("storage-entry").set_text(path)
    _finish(addhw, check=details)


@_search_permissions_decorator
def testAddDiskSearchPermsSuccess(app, uri, tmpdir):
    """
    Select 'Yes' for search perms fixing
    """
    app.uri = uri
    details = _open_app(app, "test-clone-simple")

    # Say 'Yes'
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    path = tmpdir + "/foo1.img"
    tab.find("storage-entry").set_text(path)
    _finish(addhw, check=None)
    app.click_alert_button("emulator may not have", "Yes")
    lib.utils.check(lambda: details.active)

    # Confirm it doesn't ask about path again
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    path = tmpdir + "/foo3.img"
    tab.find("storage-entry").set_text(path)
    _finish(addhw, check=details)


@_search_permissions_decorator
def testAddDiskSearchPermsFail(app, uri, tmpdir):
    """
    Force perms fixing to fail
    """
    app.uri = uri
    details = _open_app(app, "test-clone-simple",
            break_setfacl=True)

    # Say 'Yes' and it should fail, then denylist the paths
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    path = tmpdir + "/foo1.img"
    tab.find("storage-entry").set_text(path)
    _finish(addhw, check=None)
    app.click_alert_button("emulator may not have", "Yes")
    alert = app.root.find("vmm dialog", "alert")
    alert.find_fuzzy("Errors were encountered", "label")
    alert.find_fuzzy("Don't ask", "check box").click()
    alert.find_fuzzy("OK", "push button").click()
    lib.utils.check(lambda: details.active)

    # Confirm it doesn't ask about path again
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    path = tmpdir + "/foo2.img"
    tab.find("storage-entry").set_text(path)
    _finish(addhw, check=details)


def testAddNetworks(app):
    """
    Test various network configs
    """
    details = _open_app(app, "test-clone-simple")
    addhw = _open_addhw(app, details)

    # Basic network + opts
    tab = _select_hw(addhw, "Network", "network-tab")
    tab.combo_select("net-source", "Virtual network 'default'")
    tab.find("MAC Address Field", "text").set_text("00:11:00:11:00:11")
    tab.combo_select("Device model:", "virtio")
    _finish(addhw, check=details)

    # Manual macvtap
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Network", "network-tab")
    tab.combo_select("net-source", "Macvtap device...")
    tab.find("Device name:", "text").set_text("macvtapfoo7")
    _finish(addhw, check=details)

    # Manual bridge. Also trigger MAC collision
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Network", "network-tab")
    tab.find("mac-address-enable", "check box").click()
    tab.combo_select("net-source", "Bridge device...")
    tab.find("Device name:", "text").set_text("zbr0")
    _finish(addhw, check=None)
    # Check MAC validation error
    app.click_alert_button("00:11:22:33:44:55", "Close")

    # Fix MAC
    tab.find("mac-address-enable", "check box").click()
    tab.find("MAC Address Field", "text").set_text("00:11:0A:11:00:11")
    _finish(addhw, check=details)



def testAddGraphics(app):
    """
    Graphics device testing
    """
    details = _open_app(app, "test-clone-simple")
    addhw = _open_addhw(app, details)

    # VNC example
    tab = _select_hw(addhw, "Graphics", "graphics-tab")
    tab.combo_select("Type:", "VNC")
    tab.combo_select("Listen type:", "Address")
    tab.combo_select("Address:", "All interfaces")
    tab.find("graphics-port-auto", "check").click()
    tab.find("graphics-port", "spin button").set_text("1234")
    tab.find("Password:", "check").click()
    passwd = tab.find_fuzzy("graphics-password", "text")
    newpass = "foobar"
    passwd.typeText(newpass)
    tab.find("Show password", "check").click()
    lib.utils.check(lambda: passwd.text == newpass)
    tab.find("Show password", "check").click()
    lib.utils.check(lambda: passwd.text != newpass)
    _finish(addhw, check=None)
    # Catch a port error
    app.click_alert_button("Port must be above 5900", "Close")
    tab.find("graphics-port", "spin button").set_text("5920")
    _finish(addhw, check=details)

    # Spice regular example
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Graphics", "graphics-tab")
    tab.combo_select("Type:", "Spice")
    _finish(addhw, check=details)

    # Spice GL example
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Graphics", "graphics-tab")
    tab.combo_select("Type:", "Spice")
    tab.combo_select("Listen type:", "None")
    tab.find("OpenGL:", "check box").click()
    tab.combo_check_default("graphics-rendernode", "0000")
    _finish(addhw, check=details)


def testAddHosts(app):
    """
    Add a few different USB and PCI devices
    """
    details = _open_app(app, "test-clone-simple")
    addhw = _open_addhw(app, details)

    # Add USB device dup1
    tab = _select_hw(addhw, "USB Host Device", "host-tab")
    tab.find_fuzzy("HP Dup USB 1", "table cell").click()
    _finish(addhw, check=None)
    app.click_alert_button("device is already in use by", "No")
    _finish(addhw, check=None)
    app.click_alert_button("device is already in use by", "Yes")
    lib.utils.check(lambda: details.active)

    # Add USB device dup2
    _open_addhw(app, details)
    tab = _select_hw(addhw, "USB Host Device", "host-tab")
    tab.find_fuzzy("HP Dup USB 2", "table cell").click()
    _finish(addhw, check=None)
    app.click_alert_button("device is already in use by", "Yes")
    lib.utils.check(lambda: details.active)

    # Add another USB device
    _open_addhw(app, details)
    tab = _select_hw(addhw, "USB Host Device", "host-tab")
    tab.find_fuzzy("Cruzer Micro 256", "table cell").click()
    _finish(addhw, check=details)

    # Add PCI device
    _open_addhw(app, details)
    tab = _select_hw(addhw, "PCI Host Device", "host-tab")
    tab.find_fuzzy("(Interface eth0)", "table cell").click()
    _finish(addhw, check=None)
    app.click_alert_button("device is already in use by", "Yes")
    lib.utils.check(lambda: details.active)



def testAddChars(app):
    """
    Add a bunch of char devices
    """
    details = _open_app(app, "test-clone-simple")
    addhw = _open_addhw(app, details)

    # Add console device
    tab = _select_hw(addhw, "Console", "char-tab")
    tab.combo_select("Device Type:", "Pseudo TTY")
    tab.combo_select("Type:", "Hypervisor default")
    _finish(addhw, check=details)

    # Add serial+file
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Serial", "char-tab")
    tab.combo_select("Device Type:", "Output to a file")
    tab.find("Path:", "text").set_text("/tmp/foo.log")
    _finish(addhw, check=details)

    _open_addhw(app, details)
    tab = _select_hw(addhw, "Parallel", "char-tab")
    tab.combo_select("Device Type:", "UNIX")
    _finish(addhw, check=details)

    # Add spicevmc channel
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Channel", "char-tab")
    tab.combo_check_default("char-target-name", ".*redhat.spice.0.*")
    tab.combo_select("char-target-name", ".*webdav.*")
    tab.combo_select("char-target-name", ".*org.qemu.guest_agent*")
    _finish(addhw, check=details)



def testAddLXCFilesystem(app):
    """
    Adding LXC specific filesystems
    """
    app.uri = tests.utils.URIs.lxc

    details = _open_app(app, "test-clone-simple")
    addhw = _open_addhw(app, details)

    # Add File+nbd share
    tab = _select_hw(addhw, "Filesystem", "filesystem-tab")
    tab.combo_select("Type:", "file")
    tab.combo_select("Driver:", "nbd")
    tab.combo_select("Format:", "qcow2")

    source = tab.find("Source path:", "text")
    source.set_text("/foo/source")
    tab.find("Browse...", "push button").click()
    # Specific testing for dir vol handling for filesystem browse
    browsewin = app.root.find("vmm-storage-browser")
    browsewin.find_fuzzy("default-pool", "table cell").click()
    browsewin.find_fuzzy("bochs-vol", "table cell").click()
    choose = browsewin.find("Choose Volume")
    lib.utils.check(lambda: not choose.sensitive)
    browsewin.find_fuzzy("dir-vol", "table cell").click()
    lib.utils.check(lambda: choose.sensitive)
    choose.click()
    lib.utils.check(lambda: addhw.active)
    lib.utils.check(
            lambda: source.text == "/dev/default-pool/dir-vol")

    tab.find_fuzzy("Export filesystem", "check").click()
    # Use this to test some error.py logic for truncating large errors
    badtarget = "a" * 1024
    tab.find("Target path:", "text").set_text(badtarget)
    _finish(addhw, check=None)
    app.click_alert_button("aaa...", "Close")
    tab.find("Target path:", "text").set_text("/foo/target")
    _finish(addhw, check=details)

    # Add RAM type
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Filesystem", "filesystem-tab")
    tab.combo_select("Type:", "ram")
    tab.find("Usage:", "spin button").set_text("12345")
    tab.find("Target path:", "text").set_text("/mem")
    _finish(addhw, check=details)



def testAddHWMisc1(app):
    """
    Add some simple devices
    """
    details = _open_app(app, "test-clone-simple",
            keyfile="rawdefault.ini")

    # Disk, verify that raw will fully allocate by default
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Storage", "storage-tab")
    # Size too big
    tab.find("GiB", "spin button").set_text("200000")
    _finish(addhw, check=None)
    app.click_alert_button("not enough free space", "Close")
    tab.find("GiB", "spin button").set_text("1.5")
    _finish(addhw, check=details)

    # Add input
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Input", "input-tab")
    tab.combo_select("Type:", "EvTouch")
    _finish(addhw, check=details)

    # Add sound
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Sound", "sound-tab")
    tab.combo_select("Model:", "HDA")
    _finish(addhw, check=details)

    # Add video
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Video", "video-tab")
    tab.combo_select("Model:", "Virtio")
    _finish(addhw, check=details)

    # Add watchdog
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Watchdog", "watchdog-tab")
    tab.combo_select("Model:", "I6300")
    tab.combo_select("Action:", "Pause the guest")
    _finish(addhw, check=details)

    # Add smartcard
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Smartcard", "smartcard-tab")
    tab.combo_select("Mode:", "Passthrough")
    _finish(addhw, check=details)

    # Add TPM emulated
    _open_addhw(app, details)
    tab = _select_hw(addhw, "TPM", "tpm-tab")
    _finish(addhw, check=details)


def testAddHWMisc2(app):
    """
    Add some more simple devices"
    """
    details = _open_app(app, "test-clone-simple")
    addhw = _open_addhw(app, details)

    # Add usb controller, to make usbredir work
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Controller", "controller-tab")
    tab.combo_select("Type:", "USB")
    _finish(addhw, check=details)

    # Add usb redir
    _open_addhw(app, details)
    tab = _select_hw(addhw, "USB Redirection", "usbredir-tab")
    tab.combo_select("Type:", "Spice")
    _finish(addhw, check=details)

    # Add basic filesystem
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Filesystem", "filesystem-tab")
    tab.find("Source path:", "text").set_text("/foo/source")
    tab.find("Target path:", "text").set_text("/foo/target")
    _finish(addhw, check=details)

    # Add TPM passthrough
    _open_addhw(app, details)
    tab = _select_hw(addhw, "TPM", "tpm-tab")
    tab.combo_select("Model:", "TIS")
    tab.combo_select("Backend:", "Passthrough")
    tab.find("Device Path:", "text").set_text("/tmp/foo")
    _finish(addhw, check=details)

    # Add RNG
    _open_addhw(app, details)
    tab = _select_hw(addhw, "RNG", "rng-tab")
    tab.find("Host Device:", "text").set_text("/dev/random")
    _finish(addhw, check=details)

    # Add Panic
    _open_addhw(app, details)
    tab = _select_hw(addhw, "Panic", "panic-tab")
    tab.combo_select("Model:", "Hyper-V")
    _finish(addhw, check=details)

    # Add vsock
    _open_addhw(app, details)
    tab = _select_hw(addhw, "VirtIO VSOCK", "vsock-tab")
    tab.find("vsock-auto").click()
    tab.find("vsock-cid").set_text("7")
    _finish(addhw, check=details)


def testAddHWUSBNone(app):
    """
    Test some special case handling when VM has controller usb model='none'
    """
    details = _open_app(app, "test-alternate-devs",
            title="test alternate devs title",
            shutdown=True)
    addhw = _open_addhw(app, details)

    # Add usb controller
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Controller", "controller-tab")
    tab.combo_select("Type:", "USB")
    _finish(addhw, check=details)

    # Trigger a libvirt error to test error handling
    addhw = _open_addhw(app, details)
    tab = _select_hw(addhw, "Controller", "controller-tab")
    combo = tab.find("Type:", "combo box")
    combo.find(None, "text").set_text("foobar")
    _finish(addhw, check=None)
    app.click_alert_button("Unable to add device", "Close")
    lib.utils.check(lambda: addhw.active)


def testAddHWCornerCases(app):
    """
    Random addhardware related tests
    """
    details = _open_app(app, "test-many-devices")
    addhw = _open_addhw(app, details)

    # Test cancel
    addhw.find("Cancel", "push button").click()

    # Test live adding, error dialog, click no
    _open_addhw(app, details)
    _finish(addhw, check=None)
    alert = app.root.find("vmm dialog", "alert")
    alert.find(
            "This device could not be attached to the running machine",
            "label")
    alert.find("Details", "toggle button").click_expander()
    alert.find("No", "push button").click()
    lib.utils.check(lambda: details.active)

    # Test live adding, error dialog, click yes
    _open_addhw(app, details)
    _finish(addhw, check=None)
    alert = app.root.find("vmm dialog", "alert")
    alert.find(
            "This device could not be attached to the running machine",
            "label")
    alert.find("Details", "toggle button").click_expander()
    alert.find("Yes", "push button").click()
    lib.utils.check(lambda: alert.dead)


def testAddHWXMLEdit(app):
    """
    Test XML editor integration
    """
    details = _open_app(app, "test-clone-simple",
            xmleditor_enabled=True)
    win = _open_addhw(app, details)

    # Disk test, change path and make sure we error it is missing
    win.find("XML", "page tab").click()
    xmleditor = win.find("XML editor")
    origpath = "/var/lib/libvirt/images/test-clone-simple.qcow2"
    newpath = "/FOO/XMLEDIT/test1.img"
    xmleditor.set_text(xmleditor.text.replace(origpath, newpath))
    _finish(win, check=None)
    app.click_alert_button("non-existent path", "Close")

    # Undo the bad change, change bus/target
    xmleditor.set_text(xmleditor.text.replace(newpath, origpath))
    xmleditor.set_text(xmleditor.text.replace("hdb", "xvda"))
    xmleditor.set_text(xmleditor.text.replace("ide", "xen"))
    _finish(win, check=details)

    # Verify the changes applied
    details.find("Xen Disk 1").click()
    lib.utils.check(lambda: details.active)
    win = _open_addhw(app, details)
    tab = _select_hw(win, "Storage", "storage-tab")
    tab.find_fuzzy("Select or create", "radio").click()
    tab.find("storage-browse", "push button").click()
    browse = app.root.find("vmm-storage-browser")
    browse.find(os.path.basename(origpath))
    browse.find("Cancel").click()

    # Select XML, switch to new dev type, verify we change focus
    win.find("XML", "page tab").click()
    xmleditor = win.find("XML editor")
    lib.utils.check(lambda: xmleditor.showing)
    tab = _select_hw(win, "Network", "network-tab")
    lib.utils.check(lambda: not xmleditor.showing)

    # Do standard xmleditor tests
    finish = win.find("Finish", "push button")
    lib.utils.test_xmleditor_interactions(app, win, finish)
    win.find("Cancel", "push button").click()
    lib.utils.check(lambda: not win.visible)
