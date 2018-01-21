import os

import libvirt

from tests.uitests import utils as uiutils


def _vm_wrapper(vmname, uri="qemu:///system"):
    """
    Decorator to open a transient VM and clean it up
    """
    def wrap1(fn):
        def wrapper(self, *args, **kwargs):
            dom = None
            try:
                xmlfile = "%s/xml/%s.xml" % (os.path.dirname(__file__), vmname)
                conn = libvirt.open(uri)
                dom = conn.createXML(open(xmlfile).read(), 0)
                self.app.uri = uri
                self.app.open(extra_opts=["--show-domain-console", vmname])
                fn(self, *args, **kwargs)
            finally:
                self.app.stop()
                if dom:
                    dom.destroy()
        return wrapper
    return wrap1


class Console(uiutils.UITestCase):
    """
    Test live console connections with stub VMs
    """

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
