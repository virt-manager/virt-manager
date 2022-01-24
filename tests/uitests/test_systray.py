# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import tests.utils
from . import lib


####################################################################
# UI tests for virt-manager's systray using a fake testing backend #
####################################################################

def testSystrayFake(app):
    app.open(
            keyfile="systray.ini",
            extra_opts=["--test-options=fake-systray"])

    systray = app.root.find("vmm-fake-systray", check_active=False)
    systray.grab_focus()
    manager = app.root.find("Virtual Machine Manager", check_active=False)

    # Add a connection to trigger systray update
    uri = tests.utils.URIs.kvm_x86
    manager.grab_focus()
    app.manager_createconn(uri=uri)

    # Hide the manager
    systray.grab_focus()
    systray.click()
    lib.utils.check(lambda: not manager.showing)
    lib.utils.check(lambda: app.is_running())

    systray.click(button=3)
    menu = app.root.find("vmm-systray-menu")

    def _get_conn_action(connstr, actionstr):
        if not menu.showing:
            systray.click(button=3)
        lib.utils.check(lambda: menu.showing)
        connmenu = menu.find(connstr, "menu")
        connmenu.point()
        ret = connmenu.find(actionstr, "menu")
        ret.check_onscreen()
        return ret

    def _check_conn_action(connstr, actionstr):
        item = _get_conn_action(connstr, actionstr)
        lib.utils.check(lambda: item.showing)
        app.rawinput.pressKey("Escape")
        lib.utils.check(lambda: not menu.showing)

    def _do_conn_action(connstr, actionstr):
        item = _get_conn_action(connstr, actionstr)
        item.click()
        lib.utils.check(lambda: not menu.showing)

    def _get_vm_action(connstr, vmname, action):
        vmenu = _get_conn_action(connstr, vmname)
        vmenu.point()
        return vmenu.find(action, "menu")

    def _check_vm_action(connstr, vmname, action):
        item = _get_vm_action(connstr, vmname, action)
        lib.utils.check(lambda: item.showing)
        app.rawinput.pressKey("Escape")
        lib.utils.check(lambda: not menu.showing)

    def _do_vm_action(connstr, vmname, action):
        item = _get_vm_action(connstr, vmname, action)
        item.click()
        lib.utils.check(lambda: not menu.showing)

    # Right click start a connection
    _check_conn_action("QEMU/KVM", "Disconnect")
    _do_conn_action("test default", "Connect")
    _check_conn_action("test default", "Disconnect")
    _do_conn_action("test testdriver", "Disconnect")
    _check_conn_action("test testdriver", "Connect")

    # Trigger VM change
    _do_vm_action("QEMU/KVM", "test-arm-kernel", "Pause")
    _check_vm_action("QEMU/KVM", "test-arm-kernel", "Resume")

    # Reshow the manager
    systray.grab_focus()
    systray.click()
    lib.utils.check(lambda: manager.showing)
    lib.utils.check(lambda: app.is_running())

    # Close from the menu
    systray.grab_focus()
    systray.click(button=3)
    menu = app.root.find("vmm-systray-menu")
    menu.find("Quit", "menu item").click()

    lib.utils.check(lambda: not app.is_running())


def testSystrayToggle(app):
    app.open(
            keyfile="systray.ini",
            extra_opts=["--test-options=fake-systray"])

    systray = app.root.find("vmm-fake-systray", check_active=False)
    systray.grab_focus()
    manager = app.root.find("Virtual Machine Manager", check_active=False)
    manager.grab_focus()

    manager.find("Edit", "menu").click()
    manager.find("Preferences", "menu item").click()
    prefs = app.find_window("Preferences")

    # Close the system tray
    prefs.grab_focus()
    prefs.find_fuzzy("Enable system tray", "check").click()
    lib.utils.check(lambda: not systray.showing)

    # Close the manager
    manager.window_close()
    lib.utils.check(lambda: not app.is_running())
