# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

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
        c = self.app.root.find("test testdriver.xml", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect",
                             "menu item").click()
        uiutils.check_in_loop(lambda: "Not Connected" in c.text)
        c.click(button=3)
        self.app.root.find("conn-delete", "menu item").click()
        self._click_alert_button("will remove the connection", "Yes")
        uiutils.check_in_loop(lambda: c.dead)

        # Launch the dialog, grab some UI pointers
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")

        connect = win.find("Connect", "push button")
        remote = win.find_fuzzy("Connect to remote", "check box")
        user = win.find("Username", "text")
        host = win.find("Hostname", "text")
        urilabel = win.find("uri-label", "label")
        urientry = win.find("uri-entry", "text")
        self.assertTrue(user.showing is host.showing is True)

        win.find_fuzzy("Hypervisor", "combo box").click()
        win.find_fuzzy("QEMU/KVM user session", "menu item").click()
        self.assertTrue(user.showing is host.showing is False)
        self.assertTrue(urilabel.text == "qemu:///session")

        # Enter a failing URI, make sure error is raised, and we can
        # fall back to the dialog
        win.find_fuzzy("Hypervisor", "combo box").click()
        win.find_fuzzy("Xen", "menu item").click()
        remote.click()
        user.text = "fribuser"
        fakehost = "ix8khfyidontexistkdjur.com"
        host.text = fakehost + ":12345"
        self.assertTrue(
                urilabel.text == "xen+ssh://fribuser@%s:12345/" % fakehost)
        connect.click()

        uiutils.check_in_loop(lambda: win.showing is True)
        c = self.app.root.find_fuzzy(fakehost, "table cell")
        uiutils.check_in_loop(lambda: "Connecting..." not in c.text,
                timeout=10)
        self._click_alert_button("Unable to connect", "No")

        # Ensure dialog shows old contents for editing
        uiutils.check_in_loop(lambda: win.showing)
        self.assertTrue(fakehost in host.text)

        # This time say 'yes'
        connect.click()
        uiutils.check_in_loop(lambda: win.showing is True)
        c = self.app.root.find_fuzzy(fakehost, "table cell")
        uiutils.check_in_loop(lambda: "Connecting..." not in c.text,
                timeout=10)
        self._click_alert_button("Unable to connect", "Yes")
        c = self.app.root.find_fuzzy(fakehost, "table cell")

        # Test with custom test:///default connection
        uiutils.check_in_loop(lambda: win.showing is False)
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        win.find_fuzzy("Hypervisor", "combo box").click()
        win.find_fuzzy("Custom URI", "menu item").click()
        urientry.text = "test:///default"
        connect.click()

        # Try various connect/disconnect routines
        uiutils.check_in_loop(lambda: win.showing is False)
        c = self.app.root.find("test default", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()
        uiutils.check_in_loop(lambda: "Not Connected" in c.text)
        c.click(button=3)
        self.app.root.find("conn-connect", "menu item").click()
        c = self.app.root.find("test default", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()
        uiutils.check_in_loop(lambda: "Not Connected" in c.text)
        c.doubleClick()
        c = self.app.root.find("test default", "table cell")
        c.click()