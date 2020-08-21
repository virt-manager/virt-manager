# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests.uitests import utils as uiutils


class CreateNet(uiutils.UITestCase):
    """
    UI tests for the createnet wizard
    """

    def _open_create_win(self, hostwin):
        hostwin.find("net-add", "push button").click()
        win = self.app.root.find(
                "Create a new virtual network", "frame")
        return win


    ##############
    # Test cases #
    ##############

    def testCreateNet(self):
        """
        Basic test with object state management afterwards
        """
        hostwin = self._open_host_window("Virtual Networks")
        win = self._open_create_win(hostwin)

        # Create a simple default network
        name = win.find("Name:", "text")
        finish = win.find("Finish", "push button")
        self.assertEqual(name.text, "network")
        newname = "a-test-new-net"
        name.text = newname
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
        self._click_alert_button("permanently delete the network", "Yes")

        # Ensure it's gone
        uiutils.check_in_loop(lambda: cell.dead)


    def testCreateNetXMLEditor(self):
        """
        Test the XML editor
        """
        self.app.open(xmleditor_enabled=True)
        hostwin = self._open_host_window("Virtual Networks")
        win = self._open_create_win(hostwin)
        name = win.find("Name:", "text")
        finish = win.find("Finish", "push button")

        # Create a new obj with XML edited name, verify it worked
        tmpname = "objtmpname"
        newname = "froofroo"
        name.text = tmpname
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        xmleditor.text = xmleditor.text.replace(
                ">%s<" % tmpname, ">%s<" % newname)
        finish.click()
        uiutils.check_in_loop(lambda: hostwin.active)
        cell = hostwin.find(newname, "table cell")
        cell.click()

        # Do standard xmleditor tests
        win = self._open_create_win(hostwin)
        self._test_xmleditor_interactions(win, finish)
        win.find("Cancel", "push button").click()
        uiutils.check_in_loop(lambda: not win.visible)

        # Ensure host window closes fine
        hostwin.click()
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)

    def testCreateNetMulti(self):
        """
        Test remaining create options
        """
        self.app.uri = "test:///default"
        hostwin = self._open_host_window(
                "Virtual Networks", conn_label="test default")
        win = self._open_create_win(hostwin)
        finish = win.find("Finish", "push button")

        # Create a network with a bunch of options
        win.find("Name:", "text").text = "default"
        win.find("net-mode").click()
        win.find("Isolated", "menu item").click()
        win.find("IPv4 configuration").click_expander()
        win.find("ipv4-network").text = "192.168.100.0/25"
        assert win.find("ipv4-start").text == "192.168.100.64"
        assert win.find("ipv4-end").text == "192.168.100.126"
        win.find("Enable DHCPv4").click()
        win.find("Enable IPv4").click()
        win.find("IPv6 configuration").click_expander()
        win.find("Enable IPv6").click()
        win.find("Enable DHCPv6").click()
        win.find("ipv6-network").text = "fd00:beef:10:6::1/64"
        win.find("ipv6-start").text = "fd00:beef:10:6::1:1"
        win.find("ipv6-end").text = "bad"
        win.find("DNS domain name").click_expander()
        win.find("Custom").click()
        win.find("domain-custom").text = "mydomain"
        finish.click()
        # Name collision validation
        self._click_alert_button("in use by another network", "Close")
        win.find("Name:", "text").text = "newnet1"
        finish.click()
        # XML define error
        self._click_alert_button("Error creating virtual network", "Close")
        win.find("ipv6-end").text = "fd00:beef:10:6::1:f1"
        finish.click()
        uiutils.check_in_loop(lambda: hostwin.active)

        # More option work
        win = self._open_create_win(hostwin)
        win.find("Name:", "text").text = "newnet2"
        devicelist = win.find("net-devicelist")
        uiutils.check_in_loop(lambda: not devicelist.visible)
        win.find("net-mode").click()
        win.find("SR-IOV", "menu item").click()
        uiutils.check_in_loop(lambda: devicelist.visible)
        # Just confirm this is here
        win.find("No available device", "menu item")
        win.find("net-mode").click()
        win.find("Routed", "menu item").click()
        win.find("net-forward").click()
        win.find("Physical device", "menu item").click()
        win.find("net-device").text = "fakedev0"
        finish.click()
        uiutils.check_in_loop(lambda: hostwin.active)

    def testCreateNetSRIOV(self):
        """
        We need the full URI to test the SRIOV method
        """
        self.app.open(xmleditor_enabled=True)
        hostwin = self._open_host_window("Virtual Networks")
        win = self._open_create_win(hostwin)
        finish = win.find("Finish", "push button")

        win.find("net-mode").click()
        win.find("SR-IOV", "menu item").click()
        win.find("net-devicelist").click()
        win.find_fuzzy("eth3", "menu item").click()
        finish.click()
