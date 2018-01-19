from tests.uitests import utils as uiutils


class Snapshots(uiutils.UITestCase):
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
        self._walkUIList(win, lst, lambda: errlabel.showing)

    def testSnapshotLifecycle(self):
        """
        Create/delete/start/stop snapshots
        """
        win = self._open_snapshots_window()
        vmrun = win.find("Run", "push button")
        vmpause = win.find("Pause", "toggle button")
        snaprun = win.find("snapshot-start", "push button")

        # Start offline snapshot
        snapname = "offline-root"
        win.find(snapname, "table cell").click()
        snaprun.click()
        alert = self.app.root.find_fuzzy("vmm dialog", "alert")
        alert.find_fuzzy(
                "sure you want to run snapshot '%s'" % snapname, "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: vmrun.sensitive)

        # Start paused snapshot
        snapname = "snap-paused"
        win.find(snapname, "table cell").click()
        snaprun.click()
        alert = self.app.root.find_fuzzy("vmm dialog", "alert")
        alert.find_fuzzy(
                "sure you want to run snapshot '%s'" % snapname, "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: vmpause.checked)

        # Edit snapshot
        desc = win.find("Description:", "text")
        desc.text = "Test description foofoo"
        win.find("snapshot-apply", "push button").click()
        win.find("snapshot-refresh", "push button").click()
        self.assertTrue("foofoo" in desc.text)

        # Create new snapshot
        win.find("snapshot-add", "push button").click()
        newwin = self.app.root.find("Create snapshot", "frame")
        snapname = "testnewsnap"
        newwin.find("Name:", "text").text = snapname
        newwin.find("Description:", "text").text = "testdesc"
        newwin.find("Finish", "push button").click()
        uiutils.check_in_loop(lambda: not newwin.showing)
        newc = win.find(snapname, "table cell")
        uiutils.check_in_loop(lambda: newc.state_selected)

        # Delete it
        win.find("snapshot-delete", "push button").click()
        alert = self.app.root.find_fuzzy("vmm dialog", "alert")
        alert.find_fuzzy("permanently delete", "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: newc.dead)

        # Switch out of window
        win.find("Details", "radio button").click()
        uiutils.check_in_loop(lambda: not snaprun.showing)
