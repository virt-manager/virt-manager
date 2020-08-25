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
        uiutils.check(lambda: "Not Connected" in c.text)
        c.click(button=3)
        self.app.root.find("conn-delete", "menu item").click()
        self._click_alert_button("will remove the connection", "Yes")
        uiutils.check(lambda: c.dead)

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
        uiutils.check(lambda: user.showing is host.showing is True)

        # Select all HV options
        win.combo_select("Hypervisor", "QEMU/KVM user session")
        win.combo_select("Hypervisor", r"^QEMU/KVM$")
        win.combo_select("Hypervisor", "Xen")
        win.combo_select("Hypervisor", "Bhyve")
        win.combo_select("Hypervisor", "Virtuozzo")
        win.combo_select("Hypervisor", r".*LXC.*")

        # Test a simple selection
        win.combo_select("Hypervisor", "QEMU/KVM user session")
        uiutils.check(lambda: user.showing is host.showing is False)
        uiutils.check(lambda: urilabel.text == "qemu:///session")

        # Cancel the dialog
        win.find_fuzzy("Cancel", "push button").click()
        uiutils.check(lambda: not win.showing)

        # Reopen it, confirm content changed
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        uiutils.check(lambda: ":///session" not in urilabel.text)

        # Relaunch the dialog, confirm it doesn't overwrite content
        win.combo_select("Hypervisor", ".*LXC.*")
        uiutils.check(lambda: "lxc" in urilabel.text)
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        uiutils.check(lambda: win.active)
        uiutils.check(lambda: "lxc" in urilabel.text)

        # Enter a failing URI, make sure error is raised, and we can
        # fall back to the dialog
        win.combo_select("Hypervisor", "Xen")
        remote.click()
        user.text = "fribuser"
        connect.click()
        self._click_alert_button("hostname is required", "OK")
        fakeipv6 = "fe80::1"
        host.text = fakeipv6
        uiutils.check(lambda: urilabel.text == "xen+ssh://fribuser@[%s]/" % fakeipv6)
        fakehost = "ix8khfyidontexistkdjur.com"
        host.text = fakehost + ":12345"
        uiutils.check(lambda: urilabel.text == "xen+ssh://fribuser@%s:12345/" % fakehost)
        connect.click()

        uiutils.check(lambda: win.showing is True)
        c = self.app.root.find_fuzzy(fakehost, "table cell")
        uiutils.check(lambda: "Connecting..." not in c.text, timeout=10)
        self._click_alert_button("Unable to connect", "No")

        # Ensure dialog shows old contents for editing
        uiutils.check(lambda: win.showing)
        uiutils.check(lambda: fakehost in host.text)

        # This time say 'yes'
        connect.click()
        uiutils.check(lambda: win.showing is True)
        c = self.app.root.find_fuzzy(fakehost, "table cell")
        uiutils.check(lambda: "Connecting..." not in c.text, timeout=10)
        self._click_alert_button("Unable to connect", "Yes")
        c = self.app.root.find_fuzzy(fakehost, "table cell")

        # Test with custom test:///default connection
        uiutils.check(lambda: win.showing is False)
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        win.combo_select("Hypervisor", "Custom URI")
        urientry.text = "test:///default"
        connect.click()

        # Do it again to make sure things don't explode
        uiutils.check(lambda: win.showing is False)
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        win.combo_select("Hypervisor", "Custom URI")
        urientry.text = "test:///default"
        connect.click()

        # Try various connect/disconnect routines
        uiutils.check(lambda: win.showing is False)
        c = self.app.root.find("test default", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()
        uiutils.check(lambda: "Not Connected" in c.text)
        c.click(button=3)
        self.app.root.find("conn-connect", "menu item").click()
        c = self.app.root.find("test default", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()
        uiutils.check(lambda: "Not Connected" in c.text)
        c.doubleClick()
        c = self.app.root.find("test default", "table cell")
        c.click()
