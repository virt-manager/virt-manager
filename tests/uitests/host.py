from tests.uitests import utils as uiutils


class Host(uiutils.UITestCase):
    """
    UI tests for virt-manager's VM details window
    """

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
