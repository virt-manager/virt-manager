# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


class Snapshots(lib.testcase.UITestCase):
    """
    UI tests for virt-manager's VM snapshots
    """

    ###################
    # Private helpers #
    ###################

    def _open_snapshots_window(self, vmname="test-snapshots"):
        self.app.root.find_fuzzy(vmname, "table cell").click(button=3)
        self.app.root.find("Open", "menu item").click()

        win = self.app.root.find("%s on" % vmname, "frame")
        win.find("Snapshots", "radio button").click()
        return win


    ##############
    # Test cases #
    ##############

    def testSnapshotsSmokeTest(self):
        """
        Smoke test to ensure all snapshots show correctly
        """
        win = self._open_snapshots_window()
        errlabel = win.find("snapshot-error-label", "label")
        lst = win.find("snapshot-list", "table")
        lib.utils.walkUIList(self.app, win, lst, lambda: errlabel.showing)

    def testSnapshotLifecycle(self):
        """
        Create/delete/start/stop snapshots
        """
        win = self._open_snapshots_window()
        vmrun = win.find("Run", "push button")
        vmpause = win.find("Pause", "toggle button")
        snaprun = win.find("snapshot-start", "push button")

        # Start already running snapshot
        snapname = "internal-root"
        win.find(snapname, "table cell").click()
        snaprun.click()
        self.app.click_alert_button("run the snapshot '%s'" % snapname, "Yes")
        lib.utils.check(lambda: not vmrun.sensitive)

        # Start offline snapshot
        snapname = "offline-root"
        win.find(snapname, "table cell").click()
        snaprun.click()
        self.app.click_alert_button("run the snapshot '%s'" % snapname, "No")
        lib.utils.check(lambda: not vmrun.sensitive)
        snaprun.click()
        self.app.click_alert_button("run the snapshot '%s'" % snapname, "Yes")
        lib.utils.check(lambda: vmrun.sensitive)

        # Start paused snapshot
        snapname = "snap-paused"
        win.find(snapname, "table cell").click()
        snaprun.click()
        self.app.click_alert_button("run the snapshot '%s'" % snapname, "Yes")
        lib.utils.check(lambda: vmpause.checked)

        # Edit snapshot
        descui = win.find("snapshot-description")
        desc = "TESTSNAP"
        descui.set_text(desc)
        win.find("snapshot-apply", "push button").click()
        win.find("snapshot-refresh", "push button").click()
        lib.utils.check(lambda: descui.text == desc)
        # Apply by clicking away
        desc += " ROUND2"
        descui.set_text(desc)
        win.find("internal-root", "table cell").click()
        self.app.click_alert_button("There are unapplied changes", "Yes")

        # Create new snapshot
        win.find("snapshot-add", "push button").click()
        newwin = self.app.root.find("Create snapshot", "frame")
        snapname = "testnewsnap"
        newwin.find("Name:", "text").set_text(snapname)
        newwin.find("Description:", "text").set_text("testdesc")
        newwin.find("Finish", "push button").click()
        lib.utils.check(lambda: not newwin.showing)
        newc = win.find(snapname, "table cell")
        lib.utils.check(lambda: newc.state_selected)

        # Delete it
        win.find("snapshot-delete", "push button").click()
        self.app.click_alert_button("permanently delete", "No")
        lib.utils.check(lambda: not newc.dead)
        win.find("snapshot-delete", "push button").click()
        self.app.click_alert_button("permanently delete", "Yes")
        lib.utils.check(lambda: newc.dead)

        # Recreate another snapshot with the same name
        win.find("snapshot-add", "push button").click()
        newwin = self.app.root.find("Create snapshot", "frame")
        snapname = "testnewsnap"
        newwin.find("Name:", "text").set_text(snapname)
        newwin.find("Finish", "push button").click()
        lib.utils.check(lambda: not newwin.showing)
        newc = win.find(snapname, "table cell")
        lib.utils.check(lambda: newc.state_selected)

        # Switch out of window
        win.find("Details", "radio button").click()
        lib.utils.check(lambda: not snaprun.showing)

    def testSnapshotMisc1(self):
        """
        Test snapshot corner cases
        """
        manager = self.app.topwin
        manager.find("vm-list").click()
        for ignore in range(8):
            self.app.rawinput.pressKey("Down")
        vmname = "test-state-managedsave"
        cell = manager.find_fuzzy(vmname, "table cell")
        cell.bring_on_screen()

        win = self._open_snapshots_window(vmname=vmname)
        vmrun = win.find("Restore", "push button")

        # Create new snapshot
        win.find("snapshot-add", "push button").click()
        self.app.click_alert_button("not become part of the snapshot", "Cancel")
        lib.utils.check(lambda: win.active)
        win.find("snapshot-add", "push button").click()
        self.app.click_alert_button("not become part of the snapshot", "OK")
        newwin = self.app.root.find("Create snapshot", "frame")
        snapname1 = "testnewsnap1"
        newwin.find("Name:", "text").set_text(snapname1)
        newwin.find("Finish", "push button").click()
        lib.utils.check(lambda: not newwin.showing)
        newc = win.find(snapname1, "table cell")
        lib.utils.check(lambda: newc.state_selected)

        # Start the VM, create another snapshot
        vmrun.click()
        lib.utils.check(lambda: not vmrun.sensitive)
        win.find("snapshot-add", "push button").click()
        newwin = self.app.root.find("Create snapshot", "frame")
        # Force validation error
        newwin.find("Name:", "text").set_text("bad name")
        newwin.find("Finish", "push button").click()
        self.app.click_alert_button("validating snapshot", "OK")
        # Force name collision
        newwin.find("Name:", "text").set_text(snapname1)
        newwin.find("Finish", "push button").click()
        self.app.click_alert_button(snapname1, "Close")
        # Make it succeed
        snapname2 = "testnewsnap2"
        newwin.find("Name:", "text").set_text(snapname2)
        newwin.find("Finish", "push button").click()
        lib.utils.check(lambda: not newwin.showing)
        newc = win.find(snapname2, "table cell")
        lib.utils.check(lambda: newc.state_selected)

        # Trigger another managed save warning
        smenu = win.find("Menu", "toggle button")
        smenu.click()
        save = smenu.find("Save", "menu item")
        save.click()
        lib.utils.check(lambda: vmrun.sensitive)
        win.find(snapname1, "table cell").click(button=3)
        self.app.root.find("Start snapshot", "menu item").click()
        self.app.click_alert_button("run the snapshot '%s'" % snapname1, "Yes")
        self.app.click_alert_button("no memory state", "Cancel")
        win.find("snapshot-start").click()
        self.app.click_alert_button("run the snapshot '%s'" % snapname1, "Yes")
        self.app.click_alert_button("no memory state", "OK")

        # Multi select
        cell1 = win.find(snapname1, "table cell")
        cell2 = win.find(snapname2, "table cell")
        cell1.click()
        self.app.rawinput.holdKey("Shift_L")
        self.app.rawinput.pressKey("Down")
        self.app.rawinput.releaseKey("Shift_L")
        win.find("snapshot-delete").click()
        self.app.click_alert_button("permanently delete", "Yes")
        lib.utils.check(lambda: cell1.dead)
        lib.utils.check(lambda: cell2.dead)
        lib.utils.check(lambda: win.active)
