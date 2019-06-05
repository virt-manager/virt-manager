# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from tests.uitests import utils as uiutils


class CreateNet(uiutils.UITestCase):
    """
    UI tests for the createnet wizard
    """

    def _open_create_win(self, hostwin):
        hostwin.find("net-add", "push button").click()
        win = self.app.root.find(
                "Create a new virtual network", "frame")
        return win


    ##############
    # Test cases #
    ##############

    def testCreateNet(self):
        hostwin = self._open_host_window("Virtual Networks")
        win = self._open_create_win(hostwin)

        # Create a simple default network
        name = win.find("Name:", "text")
        finish = win.find("Finish", "push button")
        self.assertEqual(name.text, "network")
        newname = "a-test-new-net"
        name.text = newname
        finish.click()

        # Select the new network in the host window, then do
        # stop->start->stop->delete, for lifecycle testing
        uiutils.check_in_loop(lambda: hostwin.active)
        cell = hostwin.find(newname, "table cell")
        delete = hostwin.find("net-delete", "push button")
        start = hostwin.find("net-start", "push button")
        stop = hostwin.find("net-stop", "push button")

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
        alert.find_fuzzy("permanently delete the network", "label")
        alert.find("Yes", "push button").click()

        # Ensure it's gone
        uiutils.check_in_loop(lambda: cell.dead)


    def testCreateNetXMLEditor(self):
        self.app.open(xmleditor_enabled=True)
        hostwin = self._open_host_window("Virtual Networks")
        win = self._open_create_win(hostwin)
        name = win.find("Name:", "text")
        finish = win.find("Finish", "push button")

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

        # Ensure host window closes fine
        hostwin.click()
        hostwin.keyCombo("<ctrl>w")
        uiutils.check_in_loop(lambda: not hostwin.showing and
                not hostwin.active)
