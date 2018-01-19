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
        lst = win.find("net-list", "table")
        errlabel = win.find("net-error-label", "label")
        self._walkUIList(win, lst, lambda: errlabel.showing)

    def testHostStorageSmokeTest(self):
        """
        Verify that each storage pool displays, without error.
        """
        win = self._open_host_window("Storage")
        lst = win.find("pool-list", "table")
        errlabel = win.find("pool-error-label", "label")
        self._walkUIList(win, lst, lambda: errlabel.showing)

    def testHostInterfaceSmokeTest(self):
        """
        Verify that each interface displays, without error.
        """
        win = self._open_host_window("Network Interfaces")
        lst = win.find("interface-list", "table")
        errlabel = win.find("interface-error-label", "label")
        self._walkUIList(win, lst, lambda: errlabel.showing)
