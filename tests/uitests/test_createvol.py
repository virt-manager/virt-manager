# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests.uitests import utils as uiutils


class CreateVol(uiutils.UITestCase):
    """
    UI tests for the createvol wizard
    """

    def _open_create_win(self, hostwin):
        hostwin.find("vol-new", "push button").click()
        win = self.app.root.find(
                "Add a Storage Volume", "frame")
        uiutils.check(lambda: win.active)
        return win


    ##############
    # Test cases #
    ##############

    def testCreateVolDefault(self):
        """
        Create default volume, clean it up
        """
        hostwin = self._open_host_window("Storage")
        poolcell = hostwin.find("default-pool", "table cell")
        poolcell.click()
        vollist = hostwin.find("vol-list", "table")
        win = self._open_create_win(hostwin)
        finish = win.find("Finish", "push button")
        name = win.find("Name:", "text")

        # Create a default qcow2 volume
        uiutils.check(lambda: name.text == "vol")
        newname = "a-newvol"
        name.text = newname
        win.find("Max Capacity:", "spin button").text = "10.5"
        finish.click()

        # Delete it, clicking 'No' first
        volcell = vollist.find(newname + ".qcow2")
        volcell.click()
        hostwin.find("vol-refresh", "push button").click()
        hostwin.find("vol-delete", "push button").click()
        self._click_alert_button("permanently delete the volume", "No")
        volcell = vollist.find(newname + ".qcow2")
        hostwin.find("vol-delete", "push button").click()
        self._click_alert_button("permanently delete the volume", "Yes")
        uiutils.check(lambda: volcell.dead)

        # Ensure host window closes fine
        hostwin.keyCombo("<ctrl>w")
        uiutils.check(lambda: not hostwin.showing and
                not hostwin.active)

    def testCreateVolMisc(self):
        """
        Cover all createvol options
        """
        hostwin = self._open_host_window("Storage")
        poolcell = hostwin.find("default-pool", "table cell")
        poolcell.click()
        win = self._open_create_win(hostwin)
        name = win.find("Name:", "text")
        finish = win.find("Finish", "push button")
        vollist = hostwin.find("vol-list", "table")

        # Create a qcow2 with backing file
        newname = "aaa-qcow2-backing.qcow2"
        name.text = newname
        combo = win.find("Format:", "combo box")
        combo.click_combo_entry()
        combo.find("qcow2", "menu item").click()
        win.find("Backing store").click_expander()
        win.find("Browse...").click()
        browsewin = self.app.root.find("vmm-storage-browser")
        # Test cancel button
        browsewin.find("Cancel", "push button").click()
        uiutils.check(lambda: not browsewin.active)
        win.find("Browse...").click()
        browsewin = self.app.root.find("vmm-storage-browser")
        # Test browse local opening
        browsewin.find("Browse Local", "push button").click()
        chooser = self.app.root.find(
                "Locate existing storage", "file chooser")
        chooser.keyCombo("<alt>F4")
        self._select_storagebrowser_volume(
                "default-pool", "bochs-vol", doubleclick=True)
        backingstore = win.find("backing-store")
        uiutils.check(lambda: "bochs-vol" in backingstore.text)
        finish.click()
        vollist.find(newname)

        # Create a raw volume with some size tweaking
        win = self._open_create_win(hostwin)
        # Using previous name so we collide
        name.text = newname
        combo = win.find("Format:", "combo box")
        combo.click_combo_entry()
        combo.find("raw", "menu item").click()
        cap = win.find("Max Capacity:", "spin button")
        alloc = win.find("Allocation:", "spin button")
        alloc.text = "50.0"
        alloc.click()
        self.pressKey("Enter")
        uiutils.check(lambda: cap.text == "50.0")
        cap.text = "1.0"
        cap.click()
        self.pressKey("Enter")
        uiutils.check(lambda: alloc.text == "1.0")
        alloc.text = "0.5"
        alloc.click()
        self.pressKey("Enter")
        uiutils.check(lambda: cap.text == "1.0")

        finish.click()
        self._click_alert_button("Error validating volume", "Close")
        newname = "a-newvol.raw"
        name.text = newname
        finish.click()
        vollist.find(newname)

        # Create LVM backing store
        hostwin.find("disk-pool", "table cell").click()
        win = self._open_create_win(hostwin)
        newname = "aaa-lvm"
        name.text = newname
        win.find("Backing store").click_expander()
        win.find("Browse...").click()
        self._select_storagebrowser_volume("disk-pool", "diskvol7")
        finish.click()
        vollist.find(newname)


    def testCreateVolXMLEditor(self):
        self.app.open(xmleditor_enabled=True)
        hostwin = self._open_host_window("Storage")
        poolcell = hostwin.find("default-pool", "table cell")
        poolcell.click()
        win = self._open_create_win(hostwin)
        finish = win.find("Finish", "push button")
        name = win.find("Name:", "text")
        vollist = hostwin.find("vol-list", "table")

        # Create a new obj with XML edited name, verify it worked
        tmpname = "objtmpname"
        newname = "aafroofroo"
        name.text = tmpname
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        xmleditor.text = xmleditor.text.replace(
                ">%s.qcow2<" % tmpname, ">%s<" % newname)
        finish.click()
        uiutils.check(lambda: hostwin.active)
        vollist.find(newname)

        # Do standard xmleditor tests
        win = self._open_create_win(hostwin)
        self._test_xmleditor_interactions(win, finish)
        win.find("Cancel", "push button").click()
        uiutils.check(lambda: not win.visible)
