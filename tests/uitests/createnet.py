from tests.uitests import utils as uiutils


class CreateNet(uiutils.UITestCase):
    """
    UI tests for the createnet wizard
    """

    ##############
    # Test cases #
    ##############

    def testCreateNet(self):
        # Open the createnet dialog
        hostwin = self._open_host_window("Virtual Networks")
        hostwin.find_pattern("net-add", "push button").click()
        win = self.app.root.find_pattern(
                "Create a new virtual network", "frame")

        # Create a simple default network
        newname = "a-test-new-net"
        forward = win.find_pattern("Forward", "push button")
        finish = win.find_pattern("Finish", "push button")
        name = win.find_pattern(None, "text", "Network Name:")
        name.text = newname
        forward.click()
        forward.click()
        forward.click()
        finish.click()

        # Select the new network in the host window, then do
        # stop->start->stop->delete, for lifecycle testing
        uiutils.check_in_loop(lambda: hostwin.active)
        cell = hostwin.find_pattern(newname, "table cell")
        delete = hostwin.find_pattern("net-delete", "push button")
        start = hostwin.find_pattern("net-start", "push button")
        stop = hostwin.find_pattern("net-stop", "push button")

        cell.click()
        stop.click()
        uiutils.check_in_loop(lambda: start.sensitive)
        start.click()
        uiutils.check_in_loop(lambda: stop.sensitive)
        stop.click()
        uiutils.check_in_loop(lambda: delete.sensitive)

        # Delete it
        delete.click()
        alert = self.app.root.find_pattern("vmm dialog", "alert")
        alert.find_fuzzy("permanently delete the network", "label")
        alert.find_pattern("Yes", "push button").click()

        # Ensure it's gone
        uiutils.check_in_loop(lambda: cell.dead)

        # Ensure host window closes fine
        hostwin.click()
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)
