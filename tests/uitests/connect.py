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
        c = uiutils.find_pattern(self.app.root,
                                 "test testdriver.xml", "table cell")
        c.click(button=3)
        uiutils.find_pattern(self.app.root, "conn-disconnect",
                             "menu item").click()
        uiutils.check_in_loop(lambda: "Not Connected" in c.text)
        c.click(button=3)
        uiutils.find_pattern(self.app.root, "conn-delete", "menu item").click()
        err = uiutils.find_pattern(self.app.root, "vmm simple dialog", "alert")
        uiutils.find_fuzzy(err, "will remove the connection", "label")
        uiutils.find_fuzzy(err, "Yes", "push button").click()
        uiutils.check_in_loop(lambda: c.dead)

        # Launch the dialog, grab some UI pointers
        uiutils.find_pattern(self.app.root, "File", "menu").click()
        uiutils.find_pattern(self.app.root,
                             "Add Connection...", "menu item").click()
        win = uiutils.find_fuzzy(self.app.root, "Add Connection", "dialog")

        connect = uiutils.find_pattern(win, "Connect", "push button")
        remote = uiutils.find_fuzzy(win, "Connect to remote", "check box")
        meth = uiutils.find_pattern(win, "Method", "combo box")
        user = uiutils.find_pattern(win, "Username", "text")
        host = uiutils.find_pattern(win, "Hostname", "text")
        urilabel = uiutils.find_pattern(win, "uri-label", "label")
        urientry = uiutils.find_pattern(win, "uri-entry", "text")
        self.assertTrue(meth.showing is user.showing is host.showing is True)

        uiutils.find_fuzzy(win, "Hypervisor", "combo box").click()
        uiutils.find_fuzzy(win, "QEMU/KVM user session", "menu item").click()
        self.assertTrue(meth.showing is user.showing is host.showing is False)
        self.assertTrue(urilabel.text == "qemu:///session")

        # Enter a failing URI, make sure error is raised, and we can
        # fall back to the dialog
        uiutils.find_fuzzy(win, "Hypervisor", "combo box").click()
        uiutils.find_fuzzy(win, "Xen", "menu item").click()
        remote.click()
        meth.click()
        uiutils.find_fuzzy(win, "Kerberos", "menu item").click()
        user.text = "fribuser"
        host.text = "redhat.com:12345"
        self.assertTrue(
                urilabel.text == "xen+tcp://fribuser@redhat.com:12345/")
        connect.click()

        err = uiutils.find_fuzzy(self.app.root, "vmm error dialog", "alert")
        uiutils.find_fuzzy(err, "No", "push button").click()

        # Test with custom test:///default connection
        uiutils.find_fuzzy(win, "Hypervisor", "combo box").click()
        uiutils.find_fuzzy(win, "Custom URI", "menu item").click()
        urientry.text = "test:///default"
        connect.click()

        uiutils.check_in_loop(lambda: win.showing is False)
        c = uiutils.find_pattern(self.app.root, "test default", "table cell")
        c.click()
