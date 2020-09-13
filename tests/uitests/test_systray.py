# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import tests.utils
from . import lib


class Systray(lib.testcase.UITestCase):
    """
    UI tests for virt-manager's systray using a fake testing backend
    """

    ##############
    # Test cases #
    ##############

    def testSystrayFake(self):
        self.app.open(
                keyfile="systray.ini",
                extra_opts=["--test-options=fake-systray"],
                window_name="Virtual Machine Manager")

        manager = self.app.topwin
        systray = self.app.root.find("vmm-fake-systray", check_active=False)
        manager.drag(1000, 1000)

        # Add a connection to trigger systray update
        uri = tests.utils.URIs.kvm
        manager.find("File", "menu").click()
        manager.find("Add Connection...", "menu item").click()
        win = self.app.root.find_fuzzy("Add Connection", "dialog")
        win.combo_select("Hypervisor", "Custom URI")
        win.find("uri-entry", "text").set_text(uri)
        win.find("Connect", "push button").click()

        # Hide the manager
        systray.click_title()
        systray.click()
        lib.utils.check(lambda: not manager.showing)
        lib.utils.check(lambda: self.app.is_running())

        systray.click(button=3)
        menu = self.app.root.find("vmm-systray-menu")

        def _get_conn_action(connstr, actionstr):
            if not menu.showing:
                systray.click(button=3)
            lib.utils.check(lambda: menu.showing)
            connmenu = menu.find(connstr, "menu")
            connmenu.point()
            return connmenu.find(actionstr, "menu")

        def _check_conn_action(connstr, actionstr):
            item = _get_conn_action(connstr, actionstr)
            lib.utils.check(lambda: item.showing)
            systray.click(button=3)
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
            systray.click(button=3)
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
        systray.click()
        lib.utils.check(lambda: manager.showing)
        lib.utils.check(lambda: self.app.is_running())

        # Close from the menu
        systray.click_title()
        systray.click(button=3)
        menu = self.app.root.find("vmm-systray-menu")
        menu.find("Quit", "menu item").click()

        lib.utils.check(lambda: not self.app.is_running())

    def testSystrayToggle(self):
        self.app.open(
                keyfile="systray.ini",
                extra_opts=["--test-options=fake-systray"],
                window_name="Virtual Machine Manager")

        manager = self.app.topwin
        systray = self.app.root.find("vmm-fake-systray", check_active=False)
        manager.find("Edit", "menu").click()
        manager.find("Preferences", "menu item").click()
        prefs = self.app.root.find_fuzzy("Preferences", "frame")

        # Close the system tray
        prefs.click_title()
        prefs.find_fuzzy("Enable system tray", "check").click()
        lib.utils.check(lambda: not systray.showing)

        # Close the manager
        manager.click_title()
        manager.keyCombo("<alt>F4")
        lib.utils.check(lambda: not self.app.is_running())
