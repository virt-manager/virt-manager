from tests.uitests import utils as uiutils


class CreateVol(uiutils.UITestCase):
    """
    UI tests for the createvol wizard
    """

    ##############
    # Test cases #
    ##############

    def testCreateVol(self):
        # Open the createnet dialog
        hostwin = self._open_host_window("Storage")
        poolcell = hostwin.find("default-pool", "table cell")
        poolcell.click()
        hostwin.find("vol-new", "push button").click()
        win = self.app.root.find(
                "Add a Storage Volume", "frame")

        # Create a default qcow2 volume
        newname = "a-newvol"
        finish = win.find("Finish", "push button")
        name = win.find("Name:", "text")
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
        hostwin.find("vol-new", "push button").click()
        uiutils.check_in_loop(lambda: win.active)
        newname = "a-newvol.raw"
        name.text = newname
        combo = win.find("Format:", "combo box")
        combo.click()
        combo.find("raw", "menu item").click()
        win.find("Allocation:", "spin button").text = "0.5"
        finish.click()
        vollist.find(newname)

        # Ensure host window closes fine
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)
