from tests.uitests import utils as uiutils


class CreateInterface(uiutils.UITestCase):
    """
    UI tests for the createinterface wizard
    """

    ##############
    # Test cases #
    ##############

    def testCreateInterface(self):
        # Open the createnet dialog
        hostwin = self._open_host_window("Network Interfaces")
        hostwin.find_pattern("interface-add", "push button").click()
        win = self.app.root.find_pattern(
                "Configure network interface", "frame")

        # Create a simple default object
        newname = "a-test-new-iface"
        forward = win.find_pattern("Forward", "push button")
        finish = win.find_pattern("Finish", "push button")
        forward.click()
        win.find_pattern("bridge-configure", "push button").click()
        bridgewin = self.app.root.find_pattern(
                "Bridge configuration", "dialog")
        bridgewin.find_pattern(None,
                "spin button", "Forward delay:").text = "0.05"
        bridgewin.find_pattern("OK", "push button").click()
        name = win.find_pattern(None, "text", "Name:")
        name.text = newname
        finish.click()

        # Select the new object in the host window, then do
        # start->stop->delete, for lifecycle testing
        uiutils.check_in_loop(lambda: hostwin.active)
        cell = hostwin.find_pattern(newname, "table cell")
        delete = hostwin.find_pattern("interface-delete", "push button")
        start = hostwin.find_pattern("interface-start", "push button")
        stop = hostwin.find_pattern("interface-stop", "push button")

        cell.click()
        start.click()
        alert = self.app.root.find_pattern("vmm dialog", "alert")
        alert.find_fuzzy("sure you want to start the interface", "label")
        alert.find_pattern("Yes", "push button").click()

        uiutils.check_in_loop(lambda: stop.sensitive)
        stop.click()
        alert = self.app.root.find_pattern("vmm dialog", "alert")
        alert.find_fuzzy("sure you want to stop the interface", "label")
        alert.find_fuzzy("Don't ask me again", "check box").click()
        alert.find_pattern("Yes", "push button").click()

        # Delete it
        uiutils.check_in_loop(lambda: delete.sensitive)
        delete.click()
        alert = self.app.root.find_pattern("vmm dialog", "alert")
        alert.find_fuzzy("permanently delete the interface", "label")
        alert.find_pattern("Yes", "push button").click()

        # Ensure it's gone
        uiutils.check_in_loop(lambda: cell.dead)

        # Click some more UI, but just cancel it, it's a pain to
        # figure out clicking checked cell renderers for bond interfaces...
        hostwin.find_pattern("interface-add", "push button").click()
        uiutils.check_in_loop(lambda: win.active)
        typ = win.find_pattern(None, "combo box", "Interface type:")
        typ.click()
        typ.find_pattern("Bond", "menu item").click()
        forward.click()
        win.find_pattern("ip-configure", "push button").click()
        ipwin = self.app.root.find_pattern("IP Configuration", "dialog")
        ipwin.find_pattern("IPv6", "page tab").click()
        combo = ipwin.find_pattern("ipv6-mode", "combo box")
        combo.click()
        combo.find_pattern("DHCP", "menu item").click()
        ipwin.find_pattern("OK", "push button").click()

        win.find_pattern("bond-configure", "push button").click()
        bondwin = self.app.root.find_pattern("Bonding configuration", "dialog")
        combo = bondwin.find_pattern(None, "combo box", "Bond monitor mode:")
        combo.click()
        combo.find_pattern("miimon", "menu item").click()
        bondwin.find_pattern("OK", "push button").click()

        forward = win.find_pattern("Cancel", "push button").click()
        uiutils.check_in_loop(lambda: not win.active)
        uiutils.check_in_loop(lambda: hostwin.active)

        # Ensure host window closes fine
        hostwin.click()
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)
