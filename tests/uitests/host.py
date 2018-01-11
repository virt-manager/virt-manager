from tests.uitests import utils as uiutils


class Host(uiutils.UITestCase):
    """
    UI tests for virt-manager's VM details window
    """

    ###################
    # Private helpers #
    ###################

    def _open_host_window(self, tab):
        conn_label = "test testdriver.xml"
        self.app.root.find_fuzzy(conn_label, "table cell").click()
        self.app.root.find_fuzzy("Edit", "menu").click()
        self.app.root.find_fuzzy("Connection Details", "menu item").click()
        win = self.app.root.find_fuzzy(
                "%s Connection Details" % conn_label, "frame")
        win.find_fuzzy(tab, "page tab").click()
        return win


    ##############
    # Test cases #
    ##############

    def testHostNetworkSmokeTest(self):
        """
        Verify that each virtual network displays, without error.
        """
        win = self._open_host_window("Virtual Networks")
        lst = win.find_pattern("net-list", "table")
        errlabel = win.find_pattern("net-error-label", "label")
        self._walkUIList(win, lst, lambda: errlabel.showing)

    def testHostStorageSmokeTest(self):
        """
        Verify that each storage pool displays, without error.
        """
        win = self._open_host_window("Storage")
        lst = win.find_pattern("pool-list", "table")
        errlabel = win.find_pattern("pool-error-label", "label")
        self._walkUIList(win, lst, lambda: errlabel.showing)

    def testHostInterfaceSmokeTest(self):
        """
        Verify that each interface displays, without error.
        """
        win = self._open_host_window("Network Interfaces")
        lst = win.find_pattern("interface-list", "table")
        errlabel = win.find_pattern("interface-error-label", "label")
        self._walkUIList(win, lst, lambda: errlabel.showing)
