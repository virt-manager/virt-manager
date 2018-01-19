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
        hostwin.find("interface-add", "push button").click()
        win = self.app.root.find(
                "Configure network interface", "frame")

        # Create a simple default object
        newname = "a-test-new-iface"
        forward = win.find("Forward", "push button")
        finish = win.find("Finish", "push button")
        forward.click()
        win.find("bridge-configure", "push button").click()
        bridgewin = self.app.root.find(
                "Bridge configuration", "dialog")
        bridgewin.find(None,
                "spin button", "Forward delay:").text = "0.05"
        bridgewin.find("OK", "push button").click()
        name = win.find("Name:", "text")
        name.text = newname
        finish.click()

        # Select the new object in the host window, then do
        # start->stop->delete, for lifecycle testing
        uiutils.check_in_loop(lambda: hostwin.active)
        cell = hostwin.find(newname, "table cell")
        delete = hostwin.find("interface-delete", "push button")
        start = hostwin.find("interface-start", "push button")
        stop = hostwin.find("interface-stop", "push button")

        cell.click()
        start.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("sure you want to start the interface", "label")
        alert.find("Yes", "push button").click()

        uiutils.check_in_loop(lambda: stop.sensitive)
        stop.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("sure you want to stop the interface", "label")
        alert.find_fuzzy("Don't ask me again", "check box").click()
        alert.find("Yes", "push button").click()

        # Delete it
        uiutils.check_in_loop(lambda: delete.sensitive)
        delete.click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("permanently delete the interface", "label")
        alert.find("Yes", "push button").click()

        # Ensure it's gone
        uiutils.check_in_loop(lambda: cell.dead)

        # Click some more UI, but just cancel it, it's a pain to
        # figure out clicking checked cell renderers for bond interfaces...
        hostwin.find("interface-add", "push button").click()
        uiutils.check_in_loop(lambda: win.active)
        typ = win.find("Interface type:", "combo box")
        typ.click()
        typ.find("Bond", "menu item").click()
        forward.click()
        win.find("ip-configure", "push button").click()
        ipwin = self.app.root.find("IP Configuration", "dialog")
        ipwin.find("IPv6", "page tab").click()
        combo = ipwin.find("ipv6-mode", "combo box")
        combo.click()
        combo.find("DHCP", "menu item").click()
        ipwin.find("OK", "push button").click()

        win.find("bond-configure", "push button").click()
        bondwin = self.app.root.find("Bonding configuration", "dialog")
        combo = bondwin.find("Bond monitor mode:", "combo box")
        combo.click()
        combo.find("miimon", "menu item").click()
        bondwin.find("OK", "push button").click()

        forward = win.find("Cancel", "push button").click()
        uiutils.check_in_loop(lambda: not win.active)
        uiutils.check_in_loop(lambda: hostwin.active)

        # Ensure host window closes fine
        hostwin.click()
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)
