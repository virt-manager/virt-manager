# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

import libvirt

from virtinst import log

import tests
from tests.uitests import utils as uiutils


def _vm_wrapper(vmname, uri="qemu:///system", opts=None):
    """
    Decorator to define+start a VM and clean it up on exit
    """
    def wrap1(fn):
        def wrapper(self, *args, **kwargs):
            self.app.error_if_already_running()
            xmlfile = "%s/live/%s.xml" % (tests.utils.UITESTDATADIR, vmname)
            conn = libvirt.open(uri)
            dom = conn.defineXML(open(xmlfile).read())
            try:
                dom.create()
                self.app.uri = uri
                self.conn = conn
                extra_opts = (opts or [])
                extra_opts += ["--show-domain-console", vmname]
                # Enable stats for more code coverage
                keyfile = "statsonly.ini"
                self.app.open(extra_opts=extra_opts, keyfile=keyfile)
                fn(self, dom, *args, **kwargs)
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
    extraopts = None

    def _destroy(self, win):
        smenu = win.find("Menu", "toggle button")
        smenu.click()
        smenu.find("Force Off", "menu item").click()
        self._click_alert_button("you sure", "Yes")
        run = win.find("Run", "push button")
        uiutils.check(lambda: run.sensitive)


    ##############
    # Test cases #
    ##############

    def _checkConsoleStandard(self, dom):
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
        # Move it off and have it hide again
        win.point()
        uiutils.check(lambda: not fstb.showing, timeout=5)
        self.point(win.position[0] + win.size[0] / 2, 0)
        uiutils.check(lambda: fstb.showing)

        # Click stuff and exit fullscreen
        win.find("Fullscreen Send Key").click()
        self.pressKey("Escape")
        win.find("Fullscreen Exit").click()
        uiutils.check(lambda: win.size == newsize)

        # Trigger pointer grab, verify title was updated
        win.click()
        uiutils.check(lambda: "Control_L" in win.name)
        # Ungrab
        win.keyCombo("<ctrl><alt>")
        uiutils.check(lambda: "Control_L" not in win.name)

        # Tweak scaling
        win.click_title()
        win.click_title()
        win.find("^View$", "menu").click()
        scalemenu = win.find("Scale Display", "menu")
        scalemenu.point()
        scalemenu.find("Always", "radio menu item").click()
        win.find("^View$", "menu").click()
        scalemenu = win.find("Scale Display", "menu")
        scalemenu.point()
        scalemenu.find("Never", "radio menu item").click()
        win.find("^View$", "menu").click()
        scalemenu = win.find("Scale Display", "menu")
        scalemenu.point()
        scalemenu.find("Only", "radio menu item").click()

        # Check that modifiers don't work
        win.click()
        self.sleep(1)
        win.keyCombo("<ctrl>w")
        uiutils.check(lambda: win.showing)
        dom.destroy()
        win.find("Guest is not running.")
        win.click_title()
        self.sleep(1)
        win.keyCombo("<ctrl>w")
        uiutils.check(lambda: not win.showing)

    @_vm_wrapper("uitests-vnc-standard")
    def testConsoleVNCStandard(self, dom):
        return self._checkConsoleStandard(dom)
    @_vm_wrapper("uitests-spice-standard")
    def testConsoleSpiceStandard(self, dom):
        return self._checkConsoleStandard(dom)

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
        savecheck = win.find("Save this password", "check box")
        if not savecheck.checked:
            savecheck.click()
        passwd.typeText("yy")
        self.pressKey("Enter")
        self._click_alert_button("Viewer authentication error", "OK")

        # Check proper password
        passwd.text = ""
        passwd.typeText("goodp")
        win.find("Login", "push button").click()
        uiutils.check(lambda: con.showing)

        # Restart VM to retrigger console connect
        self._destroy(win)
        win.find("Run", "push button").click()
        uiutils.check(lambda: passwd.showing)
        # Password should be filled in
        uiutils.check(lambda: bool(passwd.text))
        # Uncheck 'Save password' and login, which will delete it from keyring
        savecheck.click()
        win.find("Login", "push button").click()
        uiutils.check(lambda: con.showing)

        # Restart VM to retrigger console connect
        self._destroy(win)
        win.find("Run", "push button").click()
        uiutils.check(lambda: passwd.showing)
        # Password should be empty now
        uiutils.check(lambda: not bool(passwd.text))

    @_vm_wrapper("uitests-vnc-password")
    def testConsoleVNCPassword(self, dom):
        ignore = dom
        return self._checkPassword()
    @_vm_wrapper("uitests-spice-password")
    def testConsoleSpicePassword(self, dom):
        ignore = dom
        return self._checkPassword()

    @_vm_wrapper("uitests-vnc-password",
                 opts=["--test-options=fake-vnc-username"])
    def testConsoleVNCPasswordUsername(self, dom):
        ignore = dom
        win = self.app.topwin
        con = win.find("console-gfx-viewport")
        uiutils.check(lambda: not con.showing)
        passwd = win.find("Password:", "password text")
        uiutils.check(lambda: passwd.showing)
        username = win.find("Username:", "text")
        uiutils.check(lambda: username.showing)

        # Since we are mocking the username, sending the credentials
        # is ignored, so with the correct password this succeeds
        username.text = "fakeuser"
        passwd.typeText("goodp")
        win.find("Login", "push button").click()
        uiutils.check(lambda: con.showing)

    @_vm_wrapper("uitests-vnc-socket")
    def testConsoleVNCSocket(self, dom):
        ignore = dom
        win = self.app.topwin
        con = win.find("console-gfx-viewport")
        uiutils.check(lambda: con.showing)

        def _click_textconsole_menu(msg):
            vmenu = win.find("^View$", "menu")
            vmenu.click()
            tmenu = win.find("Consoles", "menu")
            tmenu.point()
            tmenu.find(msg, "radio menu item").click()

        # A bit of an extra test, make sure selecting Graphical Console works
        _click_textconsole_menu("Serial 1")
        uiutils.check(lambda: not con.showing)
        _click_textconsole_menu("Graphical Console")
        uiutils.check(lambda: con.showing)

    @_vm_wrapper("uitests-lxc-serial", uri="lxc:///")
    def testConsoleLXCSerial(self, dom):
        """
        Ensure LXC has serial open, and we can send some data
        """
        ignore = dom
        win = self.app.topwin
        term = win.find("Serial Terminal")
        uiutils.check(lambda: term.showing)
        term.typeText("help\n")
        uiutils.check(lambda: "COMMANDS" in term.text)

        term.doubleClick()
        term.click(button=3)
        menu = self.app.root.find("serial-popup-menu")
        menu.find("Copy", "menu item").click()

        term.click()
        term.click(button=3)
        menu = self.app.root.find("serial-popup-menu")
        menu.find("Paste", "menu item").click()

        win.find("Details", "radio button").click()
        win.find("Console", "radio button").click()
        self._destroy(win)
        view = self.app.root.find("^View$", "menu")
        view.click()
        # Triggers some tooltip cases
        textmenu = view.find("Consoles", "menu")
        textmenu.point()
        uiutils.check(lambda: textmenu.showing)
        item = textmenu.find("Text Console 1")
        uiutils.check(lambda: not item.sensitive)

        # Restart the guest to trigger reconnect code
        view.click()
        win.find("Run", "push button").click()
        term = win.find("Serial Terminal")
        uiutils.check(lambda: term.showing)

        # Ensure ctrl+w doesn't close the window, modifiers are disabled
        term.click()
        win.keyCombo("<ctrl>w")
        uiutils.check(lambda: win.showing)
        # Shut it down, ensure <ctrl>w works again
        self._destroy(win)
        win.click_title()
        self.sleep(1)
        win.keyCombo("<ctrl>w")
        uiutils.check(lambda: not win.showing)


    @_vm_wrapper("uitests-spice-specific",
            opts=["--test-options=spice-agent",
                  "--test-options=fake-console-resolution"])
    def testConsoleSpiceSpecific(self, dom):
        """
        Spice specific behavior. Has lots of devices that will open
        channels, spice GL + local config, and usbredir
        """
        ignore = dom
        win = self.app.topwin
        con = win.find("console-gfx-viewport")
        uiutils.check(lambda: con.showing)

        # Just ensure the dialog pops up, can't really test much more
        # than that
        win.find("Virtual Machine", "menu").click()
        win.find("Redirect USB", "menu item").click()

        usbwin = self.app.root.find("vmm dialog", "alert")
        usbwin.find("Select USB devices for redirection", "label")
        usbwin.find("SPICE CD", "check box").click()
        chooser = self.app.root.find(None, "file chooser")
        # Find the cwd bookmark on the left
        chooser.find("virt-manager", "label").click()
        chooser.find("virt-manager", "label").click()
        chooser.find("COPYING").click()
        self.pressKey("Enter")
        uiutils.check(lambda: not chooser.showing)
        usbwin.find("Close", "push button").click()

        # Test fake guest resize behavior
        def _click_auto():
            vmenu = win.find("^View$", "menu")
            vmenu.click()
            smenu = vmenu.find("Scale Display", "menu")
            smenu.point()
            smenu.find("Auto resize VM", "check menu item").click()
        _click_auto()
        win.click_title()
        win.click_title()
        _click_auto()
        win.click_title()
        win.click_title()

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
        tab.find("storage-entry").set_text(fname)
        tab.combo_select("Bus type:", "SCSI")
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
        entry.set_text(fname)
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        uiutils.check(lambda: entry.text == fname)
        entry.click_secondary_icon()
        appl.click()
        uiutils.check(lambda: not appl.sensitive)
        uiutils.check(lambda: not entry.text)


    @_vm_wrapper("uitests-hotplug")
    def testLiveHotplug(self, dom):
        """
        Live test for basic hotplugging and media change, as well as
        testing our auto-poolify magic
        """
        ignore = dom
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
