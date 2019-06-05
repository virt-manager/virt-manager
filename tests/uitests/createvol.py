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
        uiutils.check_in_loop(lambda: win.active)
        return win


    ##############
    # Test cases #
    ##############

    def testCreateVol(self):
        hostwin = self._open_host_window("Storage")
        poolcell = hostwin.find("default-pool", "table cell")
        poolcell.click()
        win = self._open_create_win(hostwin)

        # Create a default qcow2 volume
        finish = win.find("Finish", "push button")
        name = win.find("Name:", "text")
        self.assertEqual(name.text, "vol")
        newname = "a-newvol"
        name.text = newname
        win.find("Max Capacity:", "spin button").text = "10.5"
        finish.click()

        # Delete it
        vollist = hostwin.find("vol-list", "table")
        volcell = vollist.find(newname + ".qcow2")
        volcell.click()
        hostwin.find("vol-refresh", "push button").click()
        hostwin.find("vol-delete", "push button").click()
        alert = self.app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("permanently delete the volume", "label")
        alert.find("Yes", "push button").click()
        uiutils.check_in_loop(lambda: volcell.dead)


        # Create a raw volume too
        win = self._open_create_win(hostwin)
        newname = "a-newvol.raw"
        name.text = newname
        combo = win.find("Format:", "combo box")
        combo.click_combo_entry()
        combo.find("raw", "menu item").click()
        win.find("Allocation:", "spin button").text = "0.5"
        finish.click()
        vollist.find(newname)

        # Ensure host window closes fine
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)


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
        uiutils.check_in_loop(lambda: hostwin.active)
        vollist.find(newname)

        # Do standard xmleditor tests
        win = self._open_create_win(hostwin)
        self._test_xmleditor_interactions(win, finish)
        win.find("Cancel", "push button").click()
        uiutils.check_in_loop(lambda: not win.visible)
