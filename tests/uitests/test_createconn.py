# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


class VMMConnect(lib.testcase.UITestCase):
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
        self.app.root.find("conn-disconnect", "menu item").click()
        lib.utils.check(lambda: "Not Connected" in c.text)
        c.click(button=3)
        self.app.root.find("conn-delete", "menu item").click()
        self.app.click_alert_button("will remove the connection", "No")
        lib.utils.check(lambda: not c.dead)
        c.click(button=3)
        self.app.root.find("conn-delete", "menu item").click()
        self.app.click_alert_button("will remove the connection", "Yes")
        lib.utils.check(lambda: c.dead)

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
        lib.utils.check(lambda: user.showing is host.showing is True)

        # Select all HV options
        win.combo_select("Hypervisor", "QEMU/KVM user session")
        win.combo_select("Hypervisor", r"^QEMU/KVM$")
        win.combo_select("Hypervisor", "Xen")
        win.combo_select("Hypervisor", "Bhyve")
        win.combo_select("Hypervisor", "Virtuozzo")
        win.combo_select("Hypervisor", r".*LXC.*")

        # Test a simple selection
        win.combo_select("Hypervisor", "QEMU/KVM user session")
        lib.utils.check(lambda: user.showing is host.showing is False)
        lib.utils.check(lambda: urilabel.text == "qemu:///session")

        # Cancel the dialog
        win.find_fuzzy("Cancel", "push button").click()
        lib.utils.check(lambda: not win.showing)

        # Reopen it, confirm content changed
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        lib.utils.check(lambda: ":///session" not in urilabel.text)

        # Relaunch the dialog, confirm it doesn't overwrite content
        win.combo_select("Hypervisor", ".*LXC.*")
        lib.utils.check(lambda: "lxc" in urilabel.text)
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        lib.utils.check(lambda: win.active)
        lib.utils.check(lambda: "lxc" in urilabel.text)

        # Enter a failing URI, make sure error is raised, and we can
        # fall back to the dialog
        win.combo_select("Hypervisor", "Xen")
        remote.click()
        user.set_text("fribuser")
        connect.click()
        self.app.click_alert_button("hostname is required", "OK")
        fakeipv6 = "fe80::1"
        host.set_text(fakeipv6)
        lib.utils.check(lambda: urilabel.text == "xen+ssh://fribuser@[%s]/" % fakeipv6)
        fakehost = "ix8khfyidontexistkdjur.com"
        host.set_text(fakehost + ":12345")
        lib.utils.check(lambda: urilabel.text == "xen+ssh://fribuser@%s:12345/" % fakehost)
        connect.click()

        lib.utils.check(lambda: win.showing is True)
        c = self.app.root.find_fuzzy(fakehost, "table cell")
        lib.utils.check(lambda: "Connecting..." not in c.text, timeout=10)
        self.app.click_alert_button("Unable to connect", "No")

        # Ensure dialog shows old contents for editing
        lib.utils.check(lambda: win.showing)
        lib.utils.check(lambda: fakehost in host.text)

        # This time say 'yes'
        connect.click()
        lib.utils.check(lambda: win.showing is True)
        c = self.app.root.find_fuzzy(fakehost, "table cell")
        lib.utils.check(lambda: "Connecting..." not in c.text, timeout=10)
        self.app.click_alert_button("Unable to connect", "Yes")
        c = self.app.root.find_fuzzy(fakehost, "table cell")

        # Test with custom test:///default connection
        lib.utils.check(lambda: win.showing is False)
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        win.combo_select("Hypervisor", "Custom URI")
        urientry.set_text("test:///default")
        connect.click()

        # Do it again to make sure things don't explode
        lib.utils.check(lambda: win.showing is False)
        self.app.root.find("File", "menu").click()
        self.app.root.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        win.combo_select("Hypervisor", "Custom URI")
        urientry.set_text("test:///default")
        connect.click()

        # Try various connect/disconnect routines
        lib.utils.check(lambda: win.showing is False)
        c = self.app.root.find("test default", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()
        lib.utils.check(lambda: "Not Connected" in c.text)
        c.click(button=3)
        self.app.root.find("conn-connect", "menu item").click()
        c = self.app.root.find("test default", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()
        lib.utils.check(lambda: "Not Connected" in c.text)
        c.doubleClick()
        c = self.app.root.find("test default", "table cell")
        c.click()
        # Delete it
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()
        lib.utils.check(lambda: "Not Connected" in c.text)
        c.click(button=3)
        self.app.root.find("conn-delete", "menu item").click()
        self.app.click_alert_button("will remove the connection", "Yes")
        lib.utils.check(lambda: c.dead)
