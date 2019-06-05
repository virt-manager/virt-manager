# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

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

        # Select XML editor, and reverse walk the list
        win.find("network-grid").find("XML", "page tab").click()
        self._walkUIList(win, lst, lambda: errlabel.showing, reverse=True)

    def testHostNetworkEdit(self):
        """
        Test edits to net config
        """
        self.app.open(xmleditor_enabled=True)
        win = self._open_host_window("Virtual Networks").find("network-grid")
        finish = win.find("Apply", "push button")

        # Shut off a pool, do an XML edit, verify it
        win.find("default", "table cell").click()
        delete = win.find("net-delete", "push button")
        stop = win.find("net-stop", "push button")
        stop.click()
        uiutils.check_in_loop(lambda: delete.sensitive)
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        origdev = "virbr0"
        newdev = "virbr77"
        xmleditor.text = xmleditor.text.replace(origdev, newdev)
        finish.click()
        win.find("Details", "page tab").click()
        self.assertEqual(win.find("net-device").text, newdev)

        # Do standard xmleditor tests
        self._test_xmleditor_interactions(win, finish)


    def testHostStorageSmokeTest(self):
        """
        Verify that each storage pool displays, without error.
        """
        win = self._open_host_window("Storage")
        lst = win.find("pool-list", "table")
        errlabel = win.find("pool-error-label", "label")
        self._walkUIList(win, lst, lambda: errlabel.showing)

        # Select XML editor, and reverse walk the list
        win.find("storage-grid").find("XML", "page tab").click()
        self._walkUIList(win, lst, lambda: errlabel.showing, reverse=True)

    def testHostStorageEdit(self):
        """
        Test edits to pool config
        """
        self.app.open(xmleditor_enabled=True)
        win = self._open_host_window("Storage").find("storage-grid")
        finish = win.find("Apply", "push button")

        # Shut off a pool, do an XML edit, verify it
        win.find("default-pool", "table cell").click()
        delete = win.find("pool-delete", "push button")
        stop = win.find("pool-stop", "push button")
        stop.click()
        uiutils.check_in_loop(lambda: delete.sensitive)
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        origpath = "/dev/default-pool"
        newpath = "/dev/foo/bar/baz"
        xmleditor.text = xmleditor.text.replace(origpath, newpath)
        finish.click()
        win.find("Details", "page tab").click()
        self.assertEqual(win.find("pool-location").text, newpath)

        # Do standard xmleditor tests
        self._test_xmleditor_interactions(win, finish)
