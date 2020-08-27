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

        # Shut it off, do an XML edit, verify it
        win.find("default", "table cell").click()
        delete = win.find("net-delete", "push button")
        stop = win.find("net-stop", "push button")
        stop.click()
        uiutils.check(lambda: delete.sensitive)
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        origdev = "virbr0"
        newdev = "virbr77"
        xmleditor.set_text(xmleditor.text.replace(origdev, newdev))
        finish.click()
        win.find("Details", "page tab").click()
        netdev = win.find("net-device")
        uiutils.check(lambda: netdev.text == newdev)

        # Rename it
        win.find("default", "table cell").click()
        win.find("net-name").set_text("newsort-default")
        finish.click()

        # Change autostart, trigger it by clicking away
        win.find("newsort-default", "table cell").click()
        win.find("net-autostart").click()
        win.find("netboot", "table cell").click()
        self._click_alert_button("There are unapplied changes", "Yes")

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
        uiutils.check(lambda: delete.sensitive)
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        origpath = "/dev/default-pool"
        newpath = "/dev/foo/bar/baz"
        xmleditor.set_text(xmleditor.text.replace(origpath, newpath))
        finish.click()
        win.find("Details", "page tab").click()
        poolloc = win.find("pool-location")
        uiutils.check(lambda: poolloc.text == newpath)

        # Rename it
        win.find("default", "table cell").click()
        win.find("pool-name").set_text("newsort-default")
        finish.click()

        # Change autostart. Trigger it by clicking on new cell
        win.find("newsort-default", "table cell").click()
        win.find("pool-autostart").click()
        win.find("disk-pool", "table cell").click()
        self._click_alert_button("There are unapplied changes", "Yes")

        # Do standard xmleditor tests
        self._test_xmleditor_interactions(win, finish)

    def testHostStorageVolMisc(self):
        """
        Misc actions involving volumes
        """
        win = self._open_host_window("Storage").find("storage-grid")
        win.find_fuzzy("default-pool", "table cell").click()
        vollist = win.find("vol-list", "table")

        vol1 = vollist.find("backingl1.img", "table cell")
        vol2 = vollist.find("UPPER", "table cell")
        uiutils.check(lambda: vol1.onscreen)
        uiutils.check(lambda: not vol2.onscreen)
        win.find("Size", "table column header").click()
        win.find("Size", "table column header").click()
        uiutils.check(lambda: not vol1.onscreen)
        uiutils.check(lambda: vol2.onscreen)

        vol2.click(button=3)
        self.app.root.find("Copy Volume Path", "menu item").click()
        from gi.repository import Gdk, Gtk
        clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
        uiutils.check(lambda: clipboard.wait_for_text() == "/dev/default-pool/UPPER")

    def testHostConn(self):
        """
        Change some connection parameters
        """
        manager = self.app.topwin
        # Disconnect the connection
        c = manager.find_fuzzy("testdriver.xml", "table cell")
        c.click(button=3)
        self.app.root.find("conn-disconnect", "menu item").click()
        uiutils.check(lambda: "Not Connected" in c.text)

        # Open Host Details from right click menu
        c.click(button=3)
        self.app.root.find("conn-details", "menu item").click()
        win = self.app.root.find_fuzzy("Connection Details", "frame")

        # Click the tabs and then back
        win.find_fuzzy("Storage", "tab").click()
        win.find_fuzzy("Network", "tab").click()
        win.find_fuzzy("Overview", "tab").click()

        # Unset autoconnect
        win.find("Autoconnect:", "check box").click()

        # Change the name, verify that title bar changed
        win.find("Name:", "text").set_text("FOOBAR")
        self.app.root.find("FOOBAR Connection Details", "frame")

        # Open the manager window
        win.find("File", "menu").click()
        win.find("View Manager", "menu item").click()
        uiutils.check(lambda: manager.active)
        # Confirm connection row is named differently in manager
        manager.find("FOOBAR", "table cell")

        # Close the manager
        manager.keyCombo("<alt>F4")
        uiutils.check(lambda: win.active)

        # Quit app from the file menu
        win.find("File", "menu").click()
        win.find("Quit", "menu item").click()
        uiutils.check(lambda: not self.app.is_running())
