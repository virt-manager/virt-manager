from tests.uitests import utils as uiutils


class CreatePool(uiutils.UITestCase):
    """
    UI tests for the createpool wizard
    """

    ##############
    # Test cases #
    ##############

    def testCreatePool(self):
        # Open the createnet dialog
        hostwin = self._open_host_window("Storage")
        hostwin.find("pool-add", "push button").click()
        win = self.app.root.find(
                "Add a New Storage Pool", "frame")

        # Create a simple default dir pool
        newname = "a-test-new-pool"
        forward = win.find("Forward", "push button")
        finish = win.find("Finish", "push button")
        name = win.find("Name:", "text")
        name.text = newname
        forward.click()
        finish.click()

        # Select the new object in the host window, then do
        # stop->start->stop->delete, for lifecycle testing
        uiutils.check_in_loop(lambda: hostwin.active)
        cell = hostwin.find(newname, "table cell")
        delete = hostwin.find("pool-delete", "push button")
        start = hostwin.find("pool-start", "push button")
        stop = hostwin.find("pool-stop", "push button")

        cell.click()
        stop.click()
        uiutils.check_in_loop(lambda: start.sensitive)
        start.click()
        uiutils.check_in_loop(lambda: stop.sensitive)
        stop.click()
        uiutils.check_in_loop(lambda: delete.sensitive)

        # Delete it
        delete.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("permanently delete the pool", "label")
        alert.find("Yes", "push button").click()

        # Ensure it's gone
        uiutils.check_in_loop(lambda: cell.dead)


        # Test a scsi pool
        hostwin.find("pool-add", "push button").click()
        uiutils.check_in_loop(lambda: win.active)
        typ = win.find("Type:", "combo box")
        newname = "a-scsi-pool"
        name.text = "a-scsi-pool"
        typ.click()
        win.find_fuzzy("SCSI Host Adapter", "menu item").click()
        forward.click()
        finish.click()
        hostwin.find(newname, "table cell")

        # Test a ceph pool
        hostwin.find("pool-add", "push button").click()
        uiutils.check_in_loop(lambda: win.active)
        newname = "a-ceph-pool"
        name.text = "a-ceph-pool"
        typ.click()
        win.find_fuzzy("RADOS Block", "menu item").click()
        forward.click()
        win.find_fuzzy("Host Name:", "text").text = "example.com:1234"
        win.find_fuzzy("Source Name:", "text").typeText("frob")
        finish.click()
        hostwin.find(newname, "table cell")

        # Ensure host window closes fine
        hostwin.click()
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)
