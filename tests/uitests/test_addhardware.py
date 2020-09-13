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
    def wrapper(self, *args, **kwargs):
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
            fn(self, uri, tmpdir, *args, **kwargs)
        finally:
            os.chmod(tmpdir, 0o777)
    return wrapper


class AddHardware(lib.testcase.UITestCase):
    """
    UI tests for virt-manager's VM addhardware window
    """

    ###################
    # Private helpers #
    ###################

    def _open_addhw_window(self, details):
        details.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        return addhw

    def _select_hw(self, addhw, hwname, tabname):
        addhw.find(hwname, "table cell").click()
        tab = addhw.find(tabname, None)
        lib.utils.check(lambda: tab.showing)
        return tab

    def _finish(self, addhw, check):
        addhw.find("Finish", "push button").click()
        lib.utils.check(lambda: not addhw.active)
        if check:
            lib.utils.check(lambda: check.active)


    ##############
    # Test cases #
    ##############

    def testAddControllers(self):
        """
        Add various controller configs
        """
        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # Default SCSI
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        tab.combo_select("Type:", "SCSI")
        self._finish(addhw, check=details)

        # Virtio SCSI
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        tab.combo_select("Type:", "SCSI")
        tab.combo_select("Model:", "VirtIO SCSI")
        self._finish(addhw, check=details)

        # USB 2
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        tab.combo_select("Type:", "USB")
        tab.combo_select("Model:", "USB 2")
        self._finish(addhw, check=details)

        # USB 3
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        tab.combo_select("Type:", "USB")
        tab.combo_select("Model:", "USB 3")
        # Can't add more than 1 USB controller, so finish isn't sensitive
        finish = addhw.find("Finish", "push button")
        lib.utils.check(lambda: not finish.sensitive)

    def testAddCephDisk(self):
        """
        Add a disk with a ceph volume, ensure it maps correctly
        """
        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # Select ceph volume for disk
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        tab.find("storage-browse", "push button").click()
        browse = self.app.root.find("vmm-storage-browser")
        browse.find_fuzzy("rbd-ceph", "table cell").bring_on_screen().click()
        browse.find_fuzzy("some-rbd-vol", "table cell").click()
        browse.find("Choose Volume", "push button").click()
        self._finish(addhw, check=details)

        # Check disk details, make sure it correctly selected volume
        details.find("IDE Disk 2", "table cell").click()
        tab = details.find("disk-tab")
        lib.utils.check(lambda: tab.showing)
        disk_path = tab.find("disk-source-path")
        lib.utils.check(lambda: "rbd://" in disk_path.text)

    def testAddDisks(self):
        """
        Add various disk configs and test storage browser
        """
        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # Default disk
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        self._finish(addhw, check=details)

        # Disk with some tweaks
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.combo_select("Bus type:", "VirtIO")
        tab.find("Advanced options", "toggle button").click_expander()
        tab.find("Shareable:", "check box").click()
        tab.find("Readonly:", "check box").click()
        tab.find("Serial:", "text").set_text("ZZZZ")
        tab.combo_select("Cache mode:", "none")
        tab.combo_select("Discard mode:", "ignore")
        tab.combo_select("Detect zeroes:", "unmap")
        # Size too big
        tab.find("GiB", "spin button").set_text("2000")
        self._finish(addhw, check=None)
        self.app.click_alert_button("not enough free space", "Close")
        tab.find("GiB", "spin button").set_text("1.5")
        self._finish(addhw, check=details)

        # USB disk with removable setting
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.combo_select("Bus type:", "USB")
        tab.find("Advanced options", "toggle button").click_expander()
        tab.find("Removable:", "check box").click()
        self._finish(addhw, check=details)

        # Managed storage tests
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        self._finish(addhw, check=None)
        self.app.click_alert_button("storage path must be specified", "OK")
        tab.find("storage-browse", "push button").click()
        browse = self.app.root.find("vmm-storage-browser")

        # Create a vol, refresh, then delete it
        browse.find_fuzzy("default-pool", "table cell").click()
        browse.find("vol-new", "push button").click()
        newvol = self.app.root.find("Add a Storage Volume", "frame")
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
        self.app.click_alert_button("permanently delete the volume", "Yes")
        lib.utils.check(lambda: volcell.dead)

        # Test browse local
        browse.find("Browse Local", "push button").click()
        chooser = self.app.root.find(
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
        browse = self.app.root.find("vmm-storage-browser")

        browse.find_fuzzy("disk-pool", "table cell").click()
        browse.find("diskvol1", "table cell").click()
        browse.find("Choose Volume", "push button").click()
        lib.utils.check(lambda: "/diskvol1" in storageent.text)
        self._finish(addhw, check=None)
        self.app.click_alert_button("already in use by", "No")
        self._finish(addhw, check=None)
        self.app.click_alert_button("already in use by", "Yes")
        lib.utils.check(lambda: details.active)


        # choose file for floppy
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.combo_select("Device type:", "Floppy device")
        diskradio = tab.find_fuzzy("Create a disk image", "radio")
        lib.utils.check(lambda: not diskradio.sensitive)
        tab.find("storage-entry").set_text("/dev/default-pool/bochs-vol")
        self._finish(addhw, check=details)

        # empty cdrom
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.combo_select("Device type:", "CDROM device")
        tab.combo_select("Bus type:", "SCSI")
        self._finish(addhw, check=details)

    @_search_permissions_decorator
    def testAddDiskSearchPermsCheckbox(self, uri, tmpdir):
        """
        Test search permissions 'no' and checkbox case
        """
        self.app.uri = uri
        details = self.app.open_details_window("test-clone-simple")

        # Say 'No' but path should still work due to test driver
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo1.img"
        tab.find("storage-entry").set_text(path)
        self._finish(addhw, check=None)
        self.app.click_alert_button("emulator may not have", "No")
        lib.utils.check(lambda: details.active)

        # Say 'don't ask again'
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo2.img"
        tab.find("storage-entry").set_text(path)
        self._finish(addhw, check=None)
        alert = self.app.root.find_fuzzy("vmm dialog", "alert")
        alert.find_fuzzy("Don't ask", "check box").click()
        self.app.click_alert_button("emulator may not have", "No")
        lib.utils.check(lambda: details.active)

        # Confirm it doesn't ask about path again
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo3.img"
        tab.find("storage-entry").set_text(path)
        self._finish(addhw, check=details)

    @_search_permissions_decorator
    def testAddDiskSearchPermsSuccess(self, uri, tmpdir):
        """
        Select 'Yes' for search perms fixing
        """
        self.app.uri = uri
        details = self.app.open_details_window("test-clone-simple")

        # Say 'Yes'
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo1.img"
        tab.find("storage-entry").set_text(path)
        self._finish(addhw, check=None)
        self.app.click_alert_button("emulator may not have", "Yes")
        lib.utils.check(lambda: details.active)

        # Confirm it doesn't ask about path again
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo3.img"
        tab.find("storage-entry").set_text(path)
        self._finish(addhw, check=details)

    @_search_permissions_decorator
    def testAddDiskSearchPermsFail(self, uri, tmpdir):
        """
        Force perms fixing to fail
        """
        self.app.uri = uri
        self.app.open(break_setfacl=True)
        details = self.app.open_details_window("test-clone-simple")

        # Say 'Yes' and it should fail, then blacklist the paths
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo1.img"
        tab.find("storage-entry").set_text(path)
        self._finish(addhw, check=None)
        self.app.click_alert_button("emulator may not have", "Yes")
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Errors were encountered", "label")
        alert.find_fuzzy("Don't ask", "check box").click()
        alert.find_fuzzy("OK", "push button").click()
        lib.utils.check(lambda: details.active)

        # Confirm it doesn't ask about path again
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo2.img"
        tab.find("storage-entry").set_text(path)
        self._finish(addhw, check=details)

    def testAddNetworks(self):
        """
        Test various network configs
        """
        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # Basic network + opts
        tab = self._select_hw(addhw, "Network", "network-tab")
        tab.combo_select("net-source", "Virtual network 'default'")
        tab.find("MAC Address Field", "text").set_text("00:11:00:11:00:11")
        tab.combo_select("Device model:", "virtio")
        self._finish(addhw, check=details)

        # Manual macvtap
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Network", "network-tab")
        tab.combo_select("net-source", "Macvtap device...")
        tab.find("Device name:", "text").set_text("macvtapfoo7")
        self._finish(addhw, check=details)

        # Manual bridge. Also trigger MAC collision
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Network", "network-tab")
        tab.find("mac-address-enable", "check box").click()
        tab.combo_select("net-source", "Bridge device...")
        tab.find("Device name:", "text").set_text("zbr0")
        self._finish(addhw, check=None)
        # Check MAC validation error
        self.app.click_alert_button("00:11:22:33:44:55", "Close")

        # Fix MAC
        tab.find("mac-address-enable", "check box").click()
        tab.find("MAC Address Field", "text").set_text("00:11:0A:11:00:11")
        self._finish(addhw, check=details)


    def testAddGraphics(self):
        """
        Graphics device testing
        """
        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # VNC example
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
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
        self._finish(addhw, check=None)
        # Catch a port error
        self.app.click_alert_button("Port must be above 5900", "Close")
        tab.find("graphics-port", "spin button").set_text("5920")
        self._finish(addhw, check=details)

        # Spice regular example
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.combo_select("Type:", "Spice")
        self._finish(addhw, check=details)

        # Spice GL example
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.combo_select("Type:", "Spice")
        tab.combo_select("Listen type:", "None")
        tab.find("OpenGL:", "check box").click()
        tab.combo_check_default("graphics-rendernode", "0000")
        self._finish(addhw, check=details)

    def testAddHosts(self):
        """
        Add a few different USB and PCI devices
        """
        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # Add USB device dup1
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("HP Dup USB 1", "table cell").click()
        self._finish(addhw, check=None)
        self.app.click_alert_button("device is already in use by", "No")
        self._finish(addhw, check=None)
        self.app.click_alert_button("device is already in use by", "Yes")
        lib.utils.check(lambda: details.active)

        # Add USB device dup2
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("HP Dup USB 2", "table cell").click()
        self._finish(addhw, check=None)
        self.app.click_alert_button("device is already in use by", "Yes")
        lib.utils.check(lambda: details.active)

        # Add another USB device
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("Cruzer Micro 256", "table cell").click()
        self._finish(addhw, check=details)

        # Add PCI device
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "PCI Host Device", "host-tab")
        tab.find_fuzzy("(Interface eth0)", "table cell").click()
        self._finish(addhw, check=None)
        self.app.click_alert_button("device is already in use by", "Yes")
        lib.utils.check(lambda: details.active)


    def testAddChars(self):
        """
        Add a bunch of char devices
        """
        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # Add console device
        tab = self._select_hw(addhw, "Console", "char-tab")
        tab.combo_select("Device Type:", "Pseudo TTY")
        tab.combo_select("Type:", "Hypervisor default")
        self._finish(addhw, check=details)

        # Add serial+file
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Serial", "char-tab")
        tab.combo_select("Device Type:", "Output to a file")
        tab.find("Path:", "text").set_text("/tmp/foo.log")
        self._finish(addhw, check=details)

        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Parallel", "char-tab")
        tab.combo_select("Device Type:", "UNIX")
        self._finish(addhw, check=details)

        # Add spicevmc channel
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Channel", "char-tab")
        tab.combo_check_default("char-target-name", ".*redhat.spice.0.*")
        tab.combo_select("char-target-name", ".*webdav.*")
        tab.combo_select("char-target-name", ".*org.qemu.guest_agent*")
        self._finish(addhw, check=details)


    def testAddLXCFilesystem(self):
        """
        Adding LXC specific filesystems
        """
        self.app.uri = tests.utils.URIs.lxc

        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # Add File+nbd share
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.combo_select("Type:", "File")
        tab.combo_select("Driver:", "Nbd")
        tab.combo_select("Format:", "qcow2")

        source = tab.find("Source path:", "text")
        source.set_text("/foo/source")
        tab.find("Browse...", "push button").click()
        # Specific testing for dir vol handling for filesystem browse
        browsewin = self.app.root.find("vmm-storage-browser")
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
        self._finish(addhw, check=None)
        self.app.click_alert_button("aaa...", "Close")
        tab.find("Target path:", "text").set_text("/foo/target")
        self._finish(addhw, check=details)

        # Add RAM type
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.combo_select("Type:", "Ram")
        tab.find("Usage:", "spin button").set_text("12345")
        tab.find("Target path:", "text").set_text("/mem")
        self._finish(addhw, check=details)


    def testAddHWMisc1(self):
        """
        Add some simple devices
        """
        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # Add input
        tab = self._select_hw(addhw, "Input", "input-tab")
        tab.combo_select("Type:", "EvTouch")
        self._finish(addhw, check=details)

        # Add sound
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Sound", "sound-tab")
        tab.combo_select("Model:", "HDA")
        self._finish(addhw, check=details)

        # Add video
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Video", "video-tab")
        tab.combo_select("Model:", "Virtio")
        self._finish(addhw, check=details)

        # Add watchdog
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Watchdog", "watchdog-tab")
        tab.combo_select("Model:", "I6300")
        tab.combo_select("Action:", "Pause the guest")
        self._finish(addhw, check=details)

        # Add smartcard
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Smartcard", "smartcard-tab")
        tab.combo_select("Mode:", "Passthrough")
        self._finish(addhw, check=details)

        # Add TPM emulated
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "TPM", "tpm-tab")
        self._finish(addhw, check=details)

    def testAddHWMisc2(self):
        """
        Add some more simple devices"
        """
        details = self.app.open_details_window("test-clone-simple")
        addhw = self._open_addhw_window(details)

        # Add usb controller, to make usbredir work
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        tab.combo_select("Type:", "USB")
        self._finish(addhw, check=details)

        # Add usb redir
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "USB Redirection", "usbredir-tab")
        tab.combo_select("Type:", "Spice")
        self._finish(addhw, check=details)

        # Add basic filesystem
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find("Source path:", "text").set_text("/foo/source")
        tab.find("Target path:", "text").set_text("/foo/target")
        self._finish(addhw, check=details)

        # Add TPM passthrough
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "TPM", "tpm-tab")
        tab.combo_select("Model:", "TIS")
        tab.combo_select("Backend:", "Passthrough")
        tab.find("Device Path:", "text").set_text("/tmp/foo")
        self._finish(addhw, check=details)

        # Add RNG
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "RNG", "rng-tab")
        tab.find("Host Device:", "text").set_text("/dev/random")
        self._finish(addhw, check=details)

        # Add Panic
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Panic", "panic-tab")
        tab.combo_select("Model:", "Hyper-V")
        self._finish(addhw, check=details)

        # Add vsock
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "VirtIO VSOCK", "vsock-tab")
        tab.find("vsock-auto").click()
        tab.find("vsock-cid").set_text("7")
        self._finish(addhw, check=details)

    def testAddHWUSBNone(self):
        """
        Test some special case handling when VM has controller usb model='none'
        """
        details = self.app.open_details_window("test alternate devs title",
                shutdown=True)
        addhw = self._open_addhw_window(details)

        # Add usb controller
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        tab.combo_select("Type:", "USB")
        self._finish(addhw, check=details)

        # Trigger a libvirt error to test error handling
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        combo = tab.find("Type:", "combo box")
        combo.find(None, "text").set_text("foobar")
        self._finish(addhw, check=None)
        self.app.click_alert_button("Unable to add device", "Close")
        lib.utils.check(lambda: addhw.active)

    def testAddHWCornerCases(self):
        """
        Random addhardware related tests
        """
        details = self.app.open_details_window("test-many-devices")
        addhw = self._open_addhw_window(details)

        # Test cancel
        addhw.find("Cancel", "push button").click()

        # Test live adding, error dialog, click no
        self._open_addhw_window(details)
        self._finish(addhw, check=None)
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find(
                "This device could not be attached to the running machine",
                "label")
        alert.find("Details", "toggle button").click_expander()
        alert.find("No", "push button").click()
        lib.utils.check(lambda: details.active)

        # Test live adding, error dialog, click yes
        self._open_addhw_window(details)
        self._finish(addhw, check=None)
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find(
                "This device could not be attached to the running machine",
                "label")
        alert.find("Details", "toggle button").click_expander()
        alert.find("Yes", "push button").click()
        lib.utils.check(lambda: alert.dead)

    def testAddHWXMLEdit(self):
        """
        Test XML editor integration
        """
        self.app.open(xmleditor_enabled=True)
        details = self.app.open_details_window("test-clone-simple")
        win = self._open_addhw_window(details)

        # Disk test, change path and make sure we error it is missing
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        origpath = "/var/lib/libvirt/images/test-clone-simple.qcow2"
        newpath = "/FOO/XMLEDIT/test1.img"
        xmleditor.set_text(xmleditor.text.replace(origpath, newpath))
        self._finish(win, check=None)
        self.app.click_alert_button("non-existent path", "Close")

        # Undo the bad change, change bus/target
        xmleditor.set_text(xmleditor.text.replace(newpath, origpath))
        xmleditor.set_text(xmleditor.text.replace("hdb", "xvda"))
        xmleditor.set_text(xmleditor.text.replace("ide", "xen"))
        self._finish(win, check=details)

        # Verify the changes applied
        details.find("Xen Disk 1").click()
        lib.utils.check(lambda: details.active)
        win = self._open_addhw_window(details)
        tab = self._select_hw(win, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        tab.find("storage-browse", "push button").click()
        browse = self.app.root.find("vmm-storage-browser")
        browse.find(os.path.basename(origpath))
        browse.find("Cancel").click()

        # Select XML, switch to new dev type, verify we change focus
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        lib.utils.check(lambda: xmleditor.showing)
        tab = self._select_hw(win, "Network", "network-tab")
        lib.utils.check(lambda: not xmleditor.showing)

        # Do standard xmleditor tests
        finish = win.find("Finish", "push button")
        lib.utils.test_xmleditor_interactions(self.app, win, finish)
        win.find("Cancel", "push button").click()
        lib.utils.check(lambda: not win.visible)
