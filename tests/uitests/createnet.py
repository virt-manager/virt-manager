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
        hostwin.find("net-add", "push button").click()
        win = self.app.root.find(
                "Create a new virtual network", "frame")

        # Create a simple default network
        newname = "a-test-new-net"
        forward = win.find("Forward", "push button")
        finish = win.find("Finish", "push button")
        name = win.find("Network Name:", "text")
        name.text = newname
        forward.click()
        forward.click()
        forward.click()
        finish.click()

        # Select the new network in the host window, then do
        # stop->start->stop->delete, for lifecycle testing
        uiutils.check_in_loop(lambda: hostwin.active)
        cell = hostwin.find(newname, "table cell")
        delete = hostwin.find("net-delete", "push button")
        start = hostwin.find("net-start", "push button")
        stop = hostwin.find("net-stop", "push button")

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
        alert.find_fuzzy("permanently delete the network", "label")
        alert.find("Yes", "push button").click()

        # Ensure it's gone
        uiutils.check_in_loop(lambda: cell.dead)

        # Ensure host window closes fine
        hostwin.click()
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)
