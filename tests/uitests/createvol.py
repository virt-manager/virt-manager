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
        poolcell = hostwin.find_pattern("default-pool", "table cell")
        poolcell.click()
        hostwin.find_pattern("vol-new", "push button").click()
        win = self.app.root.find_pattern(
                "Add a Storage Volume", "frame")

        # Create a default qcow2 volume
        newname = "a-newvol"
        finish = win.find_pattern("Finish", "push button")
        name = win.find_pattern(None, "text", "Name:")
        name.text = newname
        win.find_pattern(None, "spin button", "Max Capacity:").text = "10.5"
        finish.click()

        # Delete it
        vollist = hostwin.find_pattern("vol-list", "table")
        volcell = vollist.find_pattern(newname + ".qcow2")
        volcell.click()
        hostwin.find_pattern("vol-refresh", "push button").click()
        hostwin.find_pattern("vol-delete", "push button").click()
        alert = self.app.root.find_pattern("vmm dialog", "alert")
        alert.find_fuzzy("permanently delete the volume", "label")
        alert.find_pattern("Yes", "push button").click()
        uiutils.check_in_loop(lambda: volcell.dead)


        # Create a raw volume too
        hostwin.find_pattern("vol-new", "push button").click()
        uiutils.check_in_loop(lambda: win.active)
        newname = "a-newvol.raw"
        name.text = newname
        combo = win.find_pattern(None, "combo box", "Format:")
        combo.click()
        combo.find_pattern("raw", "menu item").click()
        win.find_pattern(None, "spin button", "Allocation:").text = "0.5"
        finish.click()
        vollist.find_pattern(newname)

        # Ensure host window closes fine
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)
