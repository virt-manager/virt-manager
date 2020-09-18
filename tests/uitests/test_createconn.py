# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


#############################################
# UI tests for the 'open connection' dialog #
#############################################


def testConnect(app):
    # Start with connection delete
    c = app.manager_conn_disconnect("test testdriver.xml")
    c.click(button=3)
    app.root.find("conn-delete", "menu item").click()
    app.click_alert_button("will remove the connection", "No")
    lib.utils.check(lambda: not c.dead)
    app.manager_conn_delete("test testdriver.xml")

    # Launch the dialog, grab some UI pointers
    win = app.manager_open_createconn()
    connect = win.find("Connect", "push button")
    remote = win.find_fuzzy("Connect to remote", "check box")
    user = win.find("Username", "text")
    host = win.find("Hostname", "text")
    urilabel = win.find("uri-label", "label")
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
    win = app.manager_open_createconn()
    lib.utils.check(lambda: ":///session" not in urilabel.text)

    # Relaunch the dialog, confirm it doesn't overwrite content
    win.combo_select("Hypervisor", ".*LXC.*")
    lib.utils.check(lambda: "lxc" in urilabel.text)
    win = app.manager_open_createconn()
    lib.utils.check(lambda: win.active)
    lib.utils.check(lambda: "lxc" in urilabel.text)

    # Enter a failing URI, make sure error is raised, and we can
    # fall back to the dialog
    win.combo_select("Hypervisor", "Xen")
    remote.click()
    user.set_text("fribuser")
    connect.click()
    app.click_alert_button("hostname is required", "OK")
    fakeipv6 = "fe80::1"
    host.set_text(fakeipv6)
    lib.utils.check(lambda: urilabel.text == "xen+ssh://fribuser@[%s]/" % fakeipv6)
    fakehost = "ix8khfyidontexistkdjur.com"
    host.set_text(fakehost + ":12345")
    lib.utils.check(lambda: urilabel.text == "xen+ssh://fribuser@%s:12345/" % fakehost)
    connect.click()

    lib.utils.check(lambda: win.showing is True)
    c = app.root.find_fuzzy(fakehost, "table cell")
    lib.utils.check(lambda: "Connecting..." not in c.text, timeout=10)
    app.click_alert_button("Unable to connect", "No")

    # Ensure dialog shows old contents for editing
    lib.utils.check(lambda: win.showing)
    lib.utils.check(lambda: fakehost in host.text)

    # This time say 'yes'
    connect.click()
    lib.utils.check(lambda: win.showing is True)
    c = app.root.find_fuzzy(fakehost, "table cell")
    lib.utils.check(lambda: "Connecting..." not in c.text, timeout=10)
    app.click_alert_button("Unable to connect", "Yes")
    c = app.root.find_fuzzy(fakehost, "table cell")
    lib.utils.check(lambda: win.showing is False)

    # Test with custom test:///default connection
    app.manager_createconn("test:///default")
    # Do it again to make sure things don't explode
    app.manager_createconn("test:///default")

    # Test connection double click
    c = app.manager_conn_disconnect("test default")
    c.doubleClick()
    lib.utils.check(lambda: "Not Connected" not in c.text)

    # Delete it
    app.manager_conn_disconnect("test default")
    app.manager_conn_delete("test default")
