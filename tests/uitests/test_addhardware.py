# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import tempfile

import tests
from tests.uitests import utils as uiutils


def _search_permissions_decorator(fn):
    """
    Decorator to set up necessary bits to test disk permission search
    """
    def wrapper(self, *args, **kwargs):
        # Generate capabilities XML from a template, with out
        # UID/GID inserted as the intended emulator permissions
        capsfile = (os.path.dirname(__file__) +
                "/data/capabilities/dac-caps-template.xml")
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


class AddHardware(uiutils.UITestCase):
    """
    UI tests for virt-manager's VM addhardware window
    """

    ###################
    # Private helpers #
    ###################

    _default_vmname = "test-clone-simple"

    def _open_addhw_window(self, details):
        details.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        return addhw

    def _select_hw(self, addhw, hwname, tabname):
        addhw.find(hwname, "table cell").click()
        tab = addhw.find(tabname, None)
        uiutils.check(lambda: tab.showing)
        return tab


    ##############
    # Test cases #
    ##############

    def testAddControllers(self):
        """
        Add various controller configs
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Default SCSI
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        typ = tab.find("Type:", "combo box")
        typ.click_combo_entry()
        tab.find("SCSI", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Virtio SCSI
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        typ.click_combo_entry()
        tab.find("SCSI", "menu item").click()
        tab.find("Model:", "combo box").click_combo_entry()
        tab.find("VirtIO SCSI", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # USB 2
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        typ.click_combo_entry()
        tab.find("USB", "menu item").click()
        tab.find("Model:", "combo box").click_combo_entry()
        tab.find("USB 2", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # USB 3
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Controller", "controller-tab")
        typ.click_combo_entry()
        tab.find("^USB$", "menu item").click()
        tab.find("Model:", "combo box").click_combo_entry()
        tab.find("USB 3", "menu item").click()
        # Can't add more than 1 USB controller, so finish isn't sensitive
        uiutils.check(lambda: not finish.sensitive)

    def testAddCephDisk(self):
        """
        Add a disk with a ceph volume, ensure it maps correctly
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Select ceph volume for disk
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        tab.find("storage-browse", "push button").click()
        browse = self.app.root.find("vmm-storage-browser")
        browse.find_fuzzy("rbd-ceph", "table cell").bring_on_screen().click()
        browse.find_fuzzy("some-rbd-vol", "table cell").click()
        browse.find("Choose Volume", "push button").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Check disk details, make sure it correctly selected volume
        details.find("IDE Disk 2", "table cell").click()
        tab = details.find("disk-tab")
        uiutils.check(lambda: tab.showing)
        disk_path = tab.find("disk-source-path")
        uiutils.check(lambda: "rbd://" in disk_path.text)

    def testAddDisks(self):
        """
        Add various disk configs and test storage browser
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Default disk
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        finish.click()
        uiutils.check(lambda: details.active)

        # Disk with some tweaks
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find("Bus type:", "combo box").click()
        tab.find("VirtIO", "menu item").click()
        tab.find("Advanced options", "toggle button").click_expander()
        tab.find("Cache mode:", "combo box").click()
        tab.find("none", "menu item").click()
        # Size too big
        tab.find("GiB", "spin button").text = "2000"
        finish.click()
        self._click_alert_button("not enough free space", "Close")
        tab.find("GiB", "spin button").text = "1.5"
        finish.click()
        uiutils.check(lambda: details.active)

        # Managed storage tests
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        finish.click()
        self._click_alert_button("storage path must be specified", "OK")
        tab.find("storage-browse", "push button").click()
        browse = self.app.root.find("vmm-storage-browser")

        # Create a vol, refresh, then delete it
        browse.find_fuzzy("default-pool", "table cell").click()
        browse.find("vol-new", "push button").click()
        newvol = self.app.root.find("Add a Storage Volume", "frame")
        newname = "a-newvol"
        newvol.find("Name:", "text").text = newname
        newvol.find("Finish", "push button").click()
        uiutils.check(lambda: not newvol.showing)
        volcell = browse.find(newname, "table cell")
        uiutils.check(lambda: volcell.selected)
        browse.find("vol-refresh", "push button").click()
        volcell = browse.find(newname, "table cell")
        uiutils.check(lambda: volcell.selected)
        browse.find("vol-delete", "push button").click()
        self._click_alert_button("permanently delete the volume", "Yes")
        uiutils.check(lambda: volcell.dead)

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
        uiutils.check(lambda: not chooser.showing)
        uiutils.check(lambda: addhw.active)
        storageent = tab.find("storage-entry")
        uiutils.check(lambda: ("/" + fname) in storageent.text)

        # Reopen dialog, select a volume, etic
        tab.find("storage-browse", "push button").click()
        browse = self.app.root.find("vmm-storage-browser")

        browse.find_fuzzy("disk-pool", "table cell").click()
        browse.find("diskvol1", "table cell").click()
        browse.find("Choose Volume", "push button").click()
        uiutils.check(lambda: "/diskvol1" in storageent.text)
        finish.click()
        self._click_alert_button("already in use by", "No")
        finish.click()
        self._click_alert_button("already in use by", "Yes")
        uiutils.check(lambda: details.active)


        # choose file for floppy
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find("Device type:", "combo box").click()
        tab.find("Floppy device", "menu item").click()
        diskradio = tab.find_fuzzy("Create a disk image", "radio")
        uiutils.check(lambda: not diskradio.sensitive)
        tab.find("storage-entry").text = "/dev/default-pool/bochs-vol"
        finish.click()
        uiutils.check(lambda: details.active)

        # empty cdrom
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find("Device type:", "combo box").click()
        tab.find("CDROM device", "menu item").click()
        tab.find("Bus type:", "combo box").click()
        tab.find("SCSI", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

    @_search_permissions_decorator
    def testAddDiskSearchPermsCheckbox(self, uri, tmpdir):
        """
        Test search permissions 'no' and checkbox case
        """
        self.app.uri = uri
        details = self._open_details_window()

        # Say 'No' but path should still work due to test driver
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo1.img"
        tab.find("storage-entry").text = path
        finish.click()
        self._click_alert_button("emulator may not have", "No")
        uiutils.check(lambda: details.active)

        # Say 'don't ask again'
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo2.img"
        tab.find("storage-entry").text = path
        finish.click()
        alert = self.app.root.find_fuzzy("vmm dialog", "alert")
        alert.find_fuzzy("Don't ask", "check box").click()
        self._click_alert_button("emulator may not have", "No")
        uiutils.check(lambda: details.active)

        # Confirm it doesn't ask about path again
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo3.img"
        tab.find("storage-entry").text = path
        finish.click()
        uiutils.check(lambda: details.active)

    @_search_permissions_decorator
    def testAddDiskSearchPermsSuccess(self, uri, tmpdir):
        """
        Select 'Yes' for search perms fixing
        """
        self.app.uri = uri
        details = self._open_details_window()

        # Say 'Yes'
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo1.img"
        tab.find("storage-entry").text = path
        finish.click()
        self._click_alert_button("emulator may not have", "Yes")
        uiutils.check(lambda: details.active)

        # Confirm it doesn't ask about path again
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo3.img"
        tab.find("storage-entry").text = path
        finish.click()
        uiutils.check(lambda: details.active)

    @_search_permissions_decorator
    def testAddDiskSearchPermsFail(self, uri, tmpdir):
        """
        Force perms fixing to fail
        """
        self.app.uri = uri
        self.app.open(break_setfacl=True)
        details = self._open_details_window()

        # Say 'Yes' and it should fail, then blacklist the paths
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo1.img"
        tab.find("storage-entry").text = path
        finish.click()
        self._click_alert_button("emulator may not have", "Yes")
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Errors were encountered", "label")
        alert.find_fuzzy("Don't ask", "check box").click()
        alert.find_fuzzy("OK", "push button").click()
        uiutils.check(lambda: details.active)

        # Confirm it doesn't ask about path again
        addhw = self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Storage", "storage-tab")
        tab.find_fuzzy("Select or create", "radio").click()
        path = tmpdir + "/foo2.img"
        tab.find("storage-entry").text = path
        finish.click()
        uiutils.check(lambda: details.active)

    def testAddNetworks(self):
        """
        Test various network configs
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Basic network + opts
        tab = self._select_hw(addhw, "Network", "network-tab")
        src = tab.find(None, "combo box", "Network source:")
        src.click()
        tab.find_fuzzy("Virtual network 'default' : NAT", "menu item").click()
        tab.find("MAC Address Field", "text").text = "00:11:00:11:00:11"
        tab.find("Device model:", "combo box").click_combo_entry()
        tab.find("virtio", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Manual macvtap
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Network", "network-tab")
        src.click()
        tab.find_fuzzy("Macvtap device...", "menu item").click()
        tab.find("Device name:", "text").text = "macvtapfoo7"
        finish.click()
        uiutils.check(lambda: details.active)

        # Manual bridge. Also trigger MAC collision
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Network", "network-tab")
        tab.find("mac-address-enable", "check box").click()
        src.click()
        self.pressKey("End")
        tab.find_fuzzy("Bridge device...", "menu item").click()
        tab.find("Device name:", "text").text = "zbr0"
        finish.click()

        # Check MAC validation error
        self._click_alert_button("00:11:22:33:44:55", "Close")

        # Fix MAC
        tab.find("mac-address-enable", "check box").click()
        tab.find("MAC Address Field", "text").text = "00:11:0A:11:00:11"
        finish.click()
        uiutils.check(lambda: details.active)


    def testAddGraphics(self):
        """
        Graphics device testing
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # VNC example
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.find("Type:", "combo box").click_combo_entry()
        tab.find_fuzzy("VNC", "menu item").click()
        tab.find("Listen type:", "combo box").click_combo_entry()
        tab.find_fuzzy("Address", "menu item").click()
        tab.find("Address:", "combo box").click_combo_entry()
        tab.find_fuzzy("All interfaces", "menu item").click()
        tab.find("graphics-port-auto", "check").click()
        tab.find("graphics-port", "spin button").text = "1234"
        tab.find("Password:", "check").click()
        passwd = tab.find_fuzzy("graphics-password", "text")
        newpass = "foobar"
        passwd.typeText(newpass)
        tab.find("Show password", "check").click()
        uiutils.check(lambda: passwd.text == newpass)
        tab.find("Show password", "check").click()
        uiutils.check(lambda: passwd.text != newpass)
        finish.click()

        # Catch a port error
        self._click_alert_button("Port must be above 5900", "Close")
        tab.find("graphics-port", "spin button").text = "5920"
        finish.click()
        uiutils.check(lambda: details.active)

        # Spice regular example
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.find("Type:", "combo box").click_combo_entry()
        tab.find_fuzzy("Spice", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Spice GL example
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Graphics", "graphics-tab")
        tab.find("Type:", "combo box").click_combo_entry()
        tab.find_fuzzy("Spice", "menu item").click()
        tab.find("Listen type:", "combo box").click_combo_entry()
        tab.find_fuzzy("None", "menu item").click()
        tab.find("OpenGL:", "check box").click()
        render = tab.find("graphics-rendernode", "combo box")
        m = tab.find_fuzzy("Intel Corp", "menu item")
        render.click_combo_entry()
        uiutils.check(lambda: m.selected)
        self.pressKey("Escape")
        finish.click()
        uiutils.check(lambda: details.active)

    def testAddHosts(self):
        """
        Add a few different USB and PCI devices
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Add USB device dup1
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("HP Dup USB 1", "table cell").click()
        finish.click()
        self._click_alert_button("device is already in use by", "Yes")
        uiutils.check(lambda: details.active)

        # Add USB device dup2
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("HP Dup USB 2", "table cell").click()
        finish.click()
        self._click_alert_button("device is already in use by", "Yes")
        uiutils.check(lambda: details.active)

        # Add another USB device
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "USB Host Device", "host-tab")
        tab.find_fuzzy("Cruzer Micro 256", "table cell").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Add PCI device
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "PCI Host Device", "host-tab")
        tab.find_fuzzy("(Interface eth0)", "table cell").click()
        finish.click()
        self._click_alert_button("device is already in use by", "Yes")
        uiutils.check(lambda: details.active)


    def testAddChars(self):
        """
        Add a bunch of char devices
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Add console device
        tab = self._select_hw(addhw, "Console", "char-tab")
        tab.find("Device Type:", "combo box").click()
        tab.find_fuzzy("Pseudo TTY", "menu item").click()
        tab.find("Type:", "combo box").click_combo_entry()
        tab.find_fuzzy("Hypervisor default", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Add serial+file
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Serial", "char-tab")
        tab.find("Device Type:", "combo box").click()
        tab.find_fuzzy("Output to a file", "menu item").click()
        tab.find("Path:", "text").text = "/tmp/foo.log"
        finish.click()
        uiutils.check(lambda: details.active)

        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Parallel", "char-tab")
        tab.find("Device Type:", "combo box").click()
        tab.find_fuzzy("UNIX", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Add spicevmc channel
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Channel", "char-tab")
        # Ensures that this is selected by default
        tab.find("com.redhat.spice.0", "combo box")
        finish.click()
        uiutils.check(lambda: details.active)


    def testAddLXCFilesystem(self):
        """
        Adding LXC specific filesystems
        """
        self.app.uri = tests.utils.URIs.lxc

        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Add File+nbd share
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find("Type:", "combo box").click()
        tab.find("File", "menu item").click()
        tab.find("Driver:", "combo box").click()
        tab.find("Nbd", "menu item").click()
        tab.find("Format:", "combo box").click_combo_entry()
        tab.find("qcow2", "menu item").click()

        source = tab.find("Source path:", "text")
        source.text = "/foo/source"
        tab.find("Browse...", "push button").click()
        # Specific testing for dir vol handling for filesystem browse
        browsewin = self.app.root.find("vmm-storage-browser")
        browsewin.find_fuzzy("default-pool", "table cell").click()
        browsewin.find_fuzzy("bochs-vol", "table cell").click()
        choose = browsewin.find("Choose Volume")
        uiutils.check(lambda: not choose.sensitive)
        browsewin.find_fuzzy("dir-vol", "table cell").click()
        uiutils.check(lambda: choose.sensitive)
        choose.click()
        uiutils.check(lambda: addhw.active)
        uiutils.check(
                lambda: source.text == "/dev/default-pool/dir-vol")

        tab.find_fuzzy("Export filesystem", "check").click()
        # Use this to test some error.py logic for truncating large errors
        badtarget = "a" * 1024
        tab.find("Target path:", "text").text = badtarget
        finish.click()
        self._click_alert_button("aaa...", "Close")
        tab.find("Target path:", "text").text = "/foo/target"
        finish.click()
        uiutils.check(lambda: details.active)

        # Add RAM type
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find("Type:", "combo box").click()
        tab.find("Ram", "menu item").click()
        tab.find("Usage:", "spin button").text = "12345"
        tab.find("Target path:", "text").text = "/mem"
        finish.click()
        uiutils.check(lambda: details.active)


    def testAddHWMisc(self):
        """
        Add one each of simple devices
        """
        details = self._open_details_window()
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Add input
        tab = self._select_hw(addhw, "Input", "input-tab")
        tab.find("Type:", "combo box").click()
        tab.find("EvTouch", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Add sound
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Sound", "sound-tab")
        tab.find("Model:", "combo box").click_combo_entry()
        tab.find("HDA", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Add video
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Video", "video-tab")
        tab.find("Model:", "combo box").click_combo_entry()
        tab.find("Virtio", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Add watchdog
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Watchdog", "watchdog-tab")
        tab.find("Model:", "combo box").click()
        tab.find("I6300", "menu item").click()
        tab.find("Action:", "combo box").click()
        tab.find("Pause the guest", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Add smartcard
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Smartcard", "smartcard-tab")
        tab.find("Mode:", "combo box").click()
        tab.find("Passthrough", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Add basic filesystem
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Filesystem", "filesystem-tab")
        tab.find("Source path:", "text").text = "/foo/source"
        tab.find("Target path:", "text").text = "/foo/target"
        finish.click()
        uiutils.check(lambda: details.active)

        # Add TPM
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "TPM", "tpm-tab")
        tab.find("Model:", "combo").click()
        tab.find("TIS", "menu item").click()
        tab.find("Backend:", "combo").click()
        tab.find("Passthrough", "menu item").click()
        tab.find("Device Path:", "text").text = "/tmp/foo"
        finish.click()
        uiutils.check(lambda: details.active)

        # Add RNG
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "RNG", "rng-tab")
        tab.find("Host Device:", "text").text = "/dev/random"
        finish.click()
        uiutils.check(lambda: details.active)

        # Add Panic
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "Panic", "panic-tab")
        tab.find("Model:", "combo box").click()
        tab.find("Hyper-V", "menu item").click()
        finish.click()
        uiutils.check(lambda: details.active)

        # Add vsock
        self._open_addhw_window(details)
        tab = self._select_hw(addhw, "VirtIO VSOCK", "vsock-tab")
        tab.find("vsock-auto").click()
        tab.find("vsock-cid").text = "7"
        finish.click()
        uiutils.check(lambda: details.active)


    def testAddHWCornerCases(self):
        """
        Random addhardware related tests
        """
        details = self._open_details_window("test-many-devices")
        addhw = self._open_addhw_window(details)
        finish = addhw.find("Finish", "push button")

        # Test cancel
        addhw.find("Cancel", "push button").click()

        # Test live adding, error dialog, click no
        self._open_addhw_window(details)
        finish.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find(
                "This device could not be attached to the running machine",
                "label")
        alert.find("Details", "toggle button").click_expander()
        alert.find("No", "push button").click()
        uiutils.check(lambda: details.active)

        # Test live adding, error dialog, click yes
        self._open_addhw_window(details)
        finish.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find(
                "This device could not be attached to the running machine",
                "label")
        alert.find("Details", "toggle button").click_expander()
        alert.find("Yes", "push button").click()
        uiutils.check(lambda: alert.dead)

    def testAddHWXMLEdit(self):
        """
        Test XML editor integration
        """
        self.app.open(xmleditor_enabled=True)
        details = self._open_details_window()
        win = self._open_addhw_window(details)
        finish = win.find("Finish", "push button")

        # Disk test, change path and make sure we error it is missing
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        origpath = "/var/lib/libvirt/images/test-clone-simple.qcow2"
        newpath = "/FOO/XMLEDIT/test1.img"
        xmleditor.text = xmleditor.text.replace(origpath, newpath)
        finish.click()
        self._click_alert_button("non-existent path", "Close")

        # Undo the bad change, change bus/target
        xmleditor.text = xmleditor.text.replace(newpath, origpath)
        xmleditor.text = xmleditor.text.replace("hdb", "xvda")
        xmleditor.text = xmleditor.text.replace("ide", "xen")
        finish.click()

        # Verify the changes applied
        details.find("Xen Disk 1").click()
        uiutils.check(lambda: details.active)
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
        uiutils.check(lambda: xmleditor.showing)
        tab = self._select_hw(win, "Network", "network-tab")
        uiutils.check(lambda: not xmleditor.showing)

        # Do standard xmleditor tests
        self._test_xmleditor_interactions(win, finish)
        win.find("Cancel", "push button").click()
        uiutils.check(lambda: not win.visible)
