# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

import libvirt

from virtinst import log

from tests.uitests import utils as uiutils


def _vm_wrapper(vmname, uri="qemu:///system"):
    """
    Decorator to open a transient VM and clean it up
    """
    def wrap1(fn):
        def wrapper(self, *args, **kwargs):
            self.app.error_if_already_running()
            xmlfile = "%s/data/live/%s.xml" % (
                    os.path.dirname(__file__), vmname)
            conn = libvirt.open(uri)
            dom = conn.defineXML(open(xmlfile).read())
            try:
                dom.create()
                self.app.uri = uri
                self.conn = conn
                self.app.open(extra_opts=["--show-domain-console", vmname])
                fn(self, *args, **kwargs)
            finally:
                try:
                    self.app.stop()
                except Exception:
                    pass
                try:
                    dom.undefine()
                    dom.destroy()
                except Exception:
                    pass
        return wrapper
    return wrap1


class Console(uiutils.UITestCase):
    """
    Test live console connections with stub VMs
    """

    conn = None

    ##############
    # Test cases #
    ##############

    def _checkConsoleStandard(self):
        """
        Shared logic for general console handling
        """
        win = self.app.topwin
        con = win.find("console-gfx-viewport")
        uiutils.check(lambda: con.showing)

        win.find("Virtual Machine", "menu").click()
        win.find("Take Screenshot", "menu item").click()
        chooser = self.app.root.find(None, "file chooser")
        fname = chooser.find("Name", "text").text
        self.pressKey("Enter")
        uiutils.check(lambda: os.path.exists(fname))
        os.unlink(fname)
        uiutils.check(lambda: win.active)

        win.find("Send Key", "menu").click()
        win.find(r"Ctrl\+Alt\+F1", "menu item").click()
        win.find("Send Key", "menu").click()
        win.find(r"Ctrl\+Alt\+F10", "menu item").click()
        win.find("Send Key", "menu").click()
        win.find(r"Ctrl\+Alt\+Delete", "menu item").click()

        # 'Resize to VM' testing
        oldsize = win.size
        win.find("^View$", "menu").click()
        win.find("Resize to VM", "menu item").click()
        newsize = win.size
        uiutils.check(lambda: oldsize != newsize)

        # Fullscreen testing
        win.find("^View$", "menu").click()
        win.find("Fullscreen", "check menu item").click()
        fstb = win.find("Fullscreen Toolbar")
        uiutils.check(lambda: fstb.showing)
        uiutils.check(lambda: win.size != newsize)

        # Wait for toolbar to hide, then reveal it again
        uiutils.check(lambda: not fstb.showing, timeout=5)
        self.point(win.position[0] + win.size[0] / 2, 0)
        uiutils.check(lambda: fstb.showing)

        # Click stuff and exit fullscreen
        win.find("Fullscreen Send Key").click()
        self.pressKey("Escape")
        win.find("Fullscreen Exit").click()
        uiutils.check(lambda: win.size == newsize)

    @_vm_wrapper("uitests-vnc-standard")
    def testConsoleVNCStandard(self):
        return self._checkConsoleStandard()
    @_vm_wrapper("uitests-spice-standard")
    def testConsoleSpiceStandard(self):
        return self._checkConsoleStandard()


    def _checkPassword(self):
        """
        Shared logic for password handling
        """
        win = self.app.topwin
        con = win.find("console-gfx-viewport")
        uiutils.check(lambda: not con.showing)
        passwd = win.find("Password:", "password text")
        uiutils.check(lambda: passwd.showing)

        # Check wrong password handling
        passwd.typeText("xx")
        win.find("Login", "push button").click()
        self._click_alert_button("Viewer authentication error", "OK")

        # Check proper password
        passwd.typeText("goodp")
        win.find("Login", "push button").click()
        uiutils.check(lambda: con.showing)

    @_vm_wrapper("uitests-vnc-password")
    def testConsoleVNCPassword(self):
        return self._checkPassword()
    @_vm_wrapper("uitests-spice-password")
    def testConsoleSpicePassword(self):
        return self._checkPassword()


    @_vm_wrapper("uitests-lxc-serial", uri="lxc:///")
    def testConsoleLXCSerial(self):
        """
        Ensure LXC has serial open, and we can send some data
        """
        win = self.app.topwin
        term = win.find("Serial Terminal")
        uiutils.check(lambda: term.showing)
        term.typeText("help\n")
        uiutils.check(lambda: "COMMANDS" in term.text)


    @_vm_wrapper("uitests-spice-specific")
    def testConsoleSpiceSpecific(self):
        """
        Spice specific behavior. Has lots of devices that will open
        channels, spice GL + local config, and usbredir
        """
        win = self.app.topwin
        con = win.find("console-gfx-viewport")
        uiutils.check(lambda: con.showing)

        # Just ensure the dialog pops up, can't really test much more
        # than that
        win.find("Virtual Machine", "menu").click()
        win.find("Redirect USB", "menu item").click()
        self.app.root.find("Select USB devices for redirection", "label")


    def _testLiveHotplug(self, fname):
        win = self.app.topwin
        win.find("Details", "radio button").click()

        # Add a scsi disk, importing the passed path
        win.find("add-hardware", "push button").click()
        addhw = self.app.root.find("Add New Virtual Hardware", "frame")
        addhw.find("Storage", "table cell").click()
        tab = addhw.find("storage-tab", None)
        uiutils.check(lambda: tab.showing)
        tab.find("Select or create", "radio button").click()
        tab.find("storage-entry").text = fname
        tab.find("Bus type:", "combo box").click()
        tab.find("SCSI", "menu item").click()
        addhw.find("Finish", "push button").click()

        # Verify permission dialog pops up, ask to change
        self._click_alert_button(
                "The emulator may not have search permissions", "Yes")

        # Verify no errors
        uiutils.check(lambda: not addhw.showing)
        uiutils.check(lambda: win.active)

        # Hot unplug the disk
        win.find("SCSI Disk 1", "table cell").click()
        tab = win.find("disk-tab", None)
        uiutils.check(lambda: tab.showing)
        win.find("config-remove").click()
        delete = self.app.root.find_fuzzy("Remove Disk", "frame")
        delete.find_fuzzy("Delete", "button").click()
        uiutils.check(lambda: not delete.active)
        uiutils.check(lambda: os.path.exists(fname))

        # Change CDROM
        win.find("IDE CDROM 1", "table cell").click()
        tab = win.find("disk-tab", None)
        entry = win.find("media-entry")
        appl = win.find("config-apply")
        uiutils.check(lambda: tab.showing)
        entry.text = fname
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        uiutils.check(lambda: entry.text == fname)
        entry.click_secondary_icon()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        uiutils.check(lambda: not entry.text)


    @_vm_wrapper("uitests-hotplug")
    def testLiveHotplug(self):
        """
        Live test for basic hotplugging and media change, as well as
        testing our auto-poolify magic
        """
        import tempfile
        tmpdir = tempfile.TemporaryDirectory(prefix="uitests-tmp")
        dname = tmpdir.name
        try:
            fname = os.path.join(dname, "test.img")
            os.system("qemu-img create -f qcow2 %s 1M > /dev/null" % fname)
            os.system("chmod 700 %s" % dname)
            self._testLiveHotplug(fname)
        finally:
            poolname = os.path.basename(dname)
            try:
                pool = self.conn.storagePoolLookupByName(poolname)
                pool.destroy()
                pool.undefine()
            except Exception:
                log.debug("Error cleaning up pool", exc_info=True)
