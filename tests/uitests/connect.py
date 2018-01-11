from tests.uitests import utils as uiutils


class VMMConnect(uiutils.UITestCase):
    """
    UI tests for the 'open connection' dialog
    """

    ##############
    # Test cases #
    ##############

    def testConnect(self):
        # Start with connection delete
        c = self.app.root.find_pattern("test testdriver.xml", "table cell")
        c.click(button=3)
        self.app.root.find_pattern("conn-disconnect",
                             "menu item").click()
        uiutils.check_in_loop(lambda: "Not Connected" in c.text)
        c.click(button=3)
        self.app.root.find_pattern("conn-delete", "menu item").click()
        err = self.app.root.find_pattern("vmm dialog", "alert")
        err.find_fuzzy("will remove the connection", "label")
        err.find_fuzzy("Yes", "push button").click()
        uiutils.check_in_loop(lambda: c.dead)

        # Launch the dialog, grab some UI pointers
        self.app.root.find_pattern("File", "menu").click()
        self.app.root.find_pattern("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")

        connect = win.find_pattern("Connect", "push button")
        remote = win.find_fuzzy("Connect to remote", "check box")
        meth = win.find_pattern("Method", "combo box")
        user = win.find_pattern("Username", "text")
        host = win.find_pattern("Hostname", "text")
        urilabel = win.find_pattern("uri-label", "label")
        urientry = win.find_pattern("uri-entry", "text")
        self.assertTrue(meth.showing is user.showing is host.showing is True)

        win.find_fuzzy("Hypervisor", "combo box").click()
        win.find_fuzzy("QEMU/KVM user session", "menu item").click()
        self.assertTrue(meth.showing is user.showing is host.showing is False)
        self.assertTrue(urilabel.text == "qemu:///session")

        # Enter a failing URI, make sure error is raised, and we can
        # fall back to the dialog
        win.find_fuzzy("Hypervisor", "combo box").click()
        win.find_fuzzy("Xen", "menu item").click()
        remote.click()
        meth.click()
        win.find_fuzzy("Kerberos", "menu item").click()
        user.text = "fribuser"
        host.text = "redhat.com:12345"
        self.assertTrue(
                urilabel.text == "xen+tcp://fribuser@redhat.com:12345/")
        connect.click()

        err = self.app.root.find_fuzzy("vmm dialog", "alert")
        err.find_fuzzy("No", "push button").click()

        # Test with custom test:///default connection
        win.find_fuzzy("Hypervisor", "combo box").click()
        win.find_fuzzy("Custom URI", "menu item").click()
        urientry.text = "test:///default"
        connect.click()

        uiutils.check_in_loop(lambda: win.showing is False)
        c = self.app.root.find_pattern("test default", "table cell")
        c.click()
