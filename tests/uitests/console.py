import logging
import os

import libvirt

from tests.uitests import utils as uiutils


def _vm_wrapper(vmname, uri="qemu:///system"):
    """
    Decorator to open a transient VM and clean it up
    """
    def wrap1(fn):
        def wrapper(self, *args, **kwargs):
            xmlfile = "%s/xml/%s.xml" % (os.path.dirname(__file__), vmname)
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
        self.assertTrue(con.showing)

        win.find("Virtual Machine", "menu").click()
        win.find("Take Screenshot", "menu item").click()
        chooser = self.app.root.find(None, "file chooser")
        fname = chooser.find("Name", "text").text
        self.pressKey("Enter")
        uiutils.check_in_loop(lambda: os.path.exists(fname))
        os.unlink(fname)
        self.assertTrue(lambda: win.active)

        win.find("Send Key", "menu").click()
        win.find("Ctrl\+Alt\+F1", "menu item").click()
        win.find("Send Key", "menu").click()
        win.find("Ctrl\+Alt\+F10", "menu item").click()
        win.find("Send Key", "menu").click()
        win.find("Ctrl\+Alt\+Delete", "menu item").click()

        # 'Resize to VM' testing
        oldsize = win.size
        win.find("^View$", "menu").click()
        win.find("Resize to VM", "menu item").click()
        newsize = win.size
        self.assertTrue(oldsize != newsize)

        # Fullscreen testing
        win.find("^View$", "menu").click()
        win.find("Fullscreen", "check menu item").click()
        fstb = win.find("Fullscreen Toolbar")
        self.assertTrue(fstb.showing)
        self.assertTrue(win.size != newsize)

        # Wait for toolbar to hide, then reveal it again
        uiutils.check_in_loop(lambda: not fstb.showing, timeout=5)
        self.point(win.size[0] / 2, 0)
        uiutils.check_in_loop(lambda: fstb.showing)

        # Click stuff and exit fullscreen
        win.find("Fullscreen Send Key").click()
        self.pressKey("Escape")
        win.find("Fullscreen Exit").click()
        self.assertTrue(win.size == newsize)

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
        self.assertTrue(not con.showing)
        passwd = win.find("Password:", "password text")
        uiutils.check_in_loop(lambda: passwd.showing)

        # Check wrong password handling
        passwd.typeText("xx")
        win.find("Login", "push button").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Viewer authentication error", "label")
        alert.find("OK", "push button").click()

        # Check proper password
        passwd.typeText("goodp")
        win.find("Login", "push button").click()
        uiutils.check_in_loop(lambda: con.showing)

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
        self.assertTrue(term.showing)
        term.typeText("help\n")
        self.assertTrue("COMMANDS" in term.text)


    @_vm_wrapper("uitests-spice-specific")
    def testConsoleSpiceSpecific(self):
        """
        Spice specific behavior. Has lots of devices that will open
        channels, spice GL + local config, and usbredir
        """
        win = self.app.topwin
        con = win.find("console-gfx-viewport")
        self.assertTrue(con.showing)

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
        uiutils.check_in_loop(lambda: tab.showing)
        tab.find("Select or create", "radio button").click()
        tab.find("storage-entry").text = fname
        tab.find("Bus type:", "combo box").click()
        tab.find("SCSI", "menu item").click()
        addhw.find("Finish", "push button").click()

        # Hot unplug the disk
        win.find("SCSI Disk 1", "table cell").click()
        tab = win.find("disk-tab", None)
        uiutils.check_in_loop(lambda: tab.showing)
        self.assertTrue(tab.find("Storage format:", "text").text == "qcow2")
        win.find("config-remove").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Are you sure you want to remove", "label")
        alert.find("Yes", "push button").click()

        # Change CDROM
        win.find("IDE CDROM 1", "table cell").click()
        tab = win.find("disk-tab", None)
        uiutils.check_in_loop(lambda: tab.showing)
        tab.find("Connect", "push button").click()
        cm = self.app.root.find("Choose Media", "dialog")
        cm.find("Image Location", "radio button").click()
        cm.find("Location:", "text").text = fname
        cm.find("OK", "push button").click()
        self.assertTrue(tab.find("disk-source-path").text == fname)
        tab.find("Disconnect", "push button").click()
        self.assertTrue("-" in tab.find("disk-source-path").text)


    @_vm_wrapper("uitests-hotplug")
    def testLiveHotplug(self):
        """
        Live test for basic hotplugging and media change, as well as
        testing our auto-poolify magic
        """

        import shutil
        import tempfile
        dname = tempfile.mkdtemp(prefix="uitests-tmp")
        try:
            fname = os.path.join(dname, "test.img")
            os.system("qemu-img create -f qcow2 %s 1M > /dev/null" % fname)
            os.system("chmod -R 777 %s" % dname)
            self._testLiveHotplug(fname)
        finally:
            shutil.rmtree(dname)
            poolname = os.path.basename(dname)
            try:
                pool = self.conn.storagePoolLookupByName(poolname)
                pool.destroy()
                pool.undefine()
            except Exception:
                logging.debug("Error cleaning up pool", exc_info=True)
