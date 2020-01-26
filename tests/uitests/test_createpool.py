# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests.uitests import utils as uiutils


class CreatePool(uiutils.UITestCase):
    """
    UI tests for the createpool wizard
    """

    def _open_create_win(self, hostwin):
        hostwin.find("pool-add", "push button").click()
        win = self.app.root.find(
                "Add a New Storage Pool", "frame")
        uiutils.check_in_loop(lambda: win.active)
        return win


    ##############
    # Test cases #
    ##############

    def testCreatePools(self):
        hostwin = self._open_host_window("Storage")
        win = self._open_create_win(hostwin)
        finish = win.find("Finish", "push button")
        name = win.find("Name:", "text")

        def _browse_local_path(winlabel, usepath):
            chooser = self.app.root.find(winlabel, "file chooser")
            # Enter the filename and select it
            chooser.find(usepath, "table cell").click()
            obutton = chooser.find("Open", "push button")
            uiutils.check_in_loop(lambda: obutton.sensitive)
            obutton.click()
            uiutils.check_in_loop(lambda: not chooser.showing)
            uiutils.check_in_loop(lambda: win.active)

        # Create a simple default dir pool
        self.assertEqual(name.text, "pool")
        newname = "a-test-new-pool"
        name.text = newname
        finish.click()

        # Select the new object in the host window, then do
        # stop->start->stop->delete, for lifecycle testing
        uiutils.check_in_loop(lambda: hostwin.active)
        cell = hostwin.find(newname, "table cell")
        delete = hostwin.find("pool-delete", "push button")
        start = hostwin.find("pool-start", "push button")
        stop = hostwin.find("pool-stop", "push button")

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
        alert.find_fuzzy("permanently delete the pool", "label")
        alert.find("Yes", "push button").click()

        # Ensure it's gone
        uiutils.check_in_loop(lambda: cell.dead)

        # Test a disk pool
        win = self._open_create_win(hostwin)
        typ = win.find("Type:", "combo box")
        newname = "a-disk-pool"
        name.text = "a-disk-pool"
        typ.click()
        win.find_fuzzy("Physical Disk", "menu item").click()
        win.find("source-browse").click()
        _browse_local_path("Choose source path", "console")
        finish.click()
        hostwin.find(newname, "table cell")

        # Test a iscsi pool
        win = self._open_create_win(hostwin)
        typ = win.find("Type:", "combo box")
        newname = "a-iscsi-pool"
        name.text = "a-iscsi-pool"
        typ.click()
        win.find_fuzzy("iSCSI", "menu item").click()
        win.find("target-browse").click()
        _browse_local_path("Choose target directory", "by-path")
        finish.click()
        # Catch example error
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("source host name", "label")
        alert.find("Close", "push button").click()
        win.find("Host Name:", "text").text = "example.com"
        win.find("pool-source-path-text").text = "foo-iqn"
        win.find_fuzzy("Initiator IQN:", "check").click()
        win.find("iqn-text", "text").text = "initiator-foo"
        finish.click()
        hostwin.find(newname, "table cell")

        # Test a logical pool
        win = self._open_create_win(hostwin)
        typ = win.find("Type:", "combo box")
        newname = "a-lvm-pool"
        name.text = "a-lvm-pool"
        typ.click()
        win.find_fuzzy("LVM", "menu item").click()
        srcname = win.find_fuzzy("Volgroup", "combo")
        srcnametext = win.find_fuzzy("pool-source-name-text")
        uiutils.check_in_loop(lambda: srcnametext.text == "testvg1")
        srcname.click_combo_entry()
        win.find_fuzzy("testvg2", "menu item").click()
        finish.click()
        hostwin.find(newname, "table cell")

        # Test a scsi pool
        win = self._open_create_win(hostwin)
        typ = win.find("Type:", "combo box")
        newname = "a-scsi-pool"
        name.text = "a-scsi-pool"
        typ.click()
        win.find_fuzzy("SCSI Host Adapter", "menu item").click()
        win.find_fuzzy("Source Adapter:", "combo").click_combo_entry()
        win.find_fuzzy("host2", "menu item").click()
        finish.click()
        hostwin.find(newname, "table cell")

        # Test a ceph pool
        win = self._open_create_win(hostwin)
        newname = "a-ceph-pool"
        name.text = "a-ceph-pool"
        typ.click()
        win.find_fuzzy("RADOS Block", "menu item").click()
        win.find_fuzzy("Host Name:", "text").text = "example.com:1234"
        win.find_fuzzy("pool-source-name-text", "text").typeText("frob")
        finish.click()
        hostwin.find(newname, "table cell")

        # Ensure host window closes fine
        hostwin.click()
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)


    def testCreatePoolXMLEditor(self):
        self.app.open(xmleditor_enabled=True)
        hostwin = self._open_host_window("Storage")
        win = self._open_create_win(hostwin)
        finish = win.find("Finish", "push button")
        name = win.find("Name:", "text")

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
