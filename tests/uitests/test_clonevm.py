# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

import tests.utils
from . import lib


class _CloneRow:
    """
    Helper class for interacting with the clone row
    """
    def __init__(self, *args):
        self.chkcell = args[2]
        self.txtcell = args[5]

        self.is_cloneable = self.chkcell.showing
        self.is_share_requested = (
                not self.is_cloneable or not self.chkcell.checked)
        self.is_clone_requested = not self.is_share_requested

    def check_in_text(self, substr):
        lib.utils.check(lambda: substr in self.txtcell.text)

    def select(self):
        self.txtcell.click()


class CloneVM(lib.testcase.UITestCase):
    """
    UI tests for virt-manager's CloneVM wizard
    """

    ###################
    # Private helpers #
    ###################

    def _open_window(self, vmname):
        # Launch wizard via right click menu
        manager = self.app.topwin
        manager.click_title()
        lib.utils.check(lambda: manager.active)
        c = manager.find_fuzzy(vmname, "table cell")
        self.app.sleep(.3)
        c.click()
        c.click(button=3)
        item = self.app.root.find("Clone...", "menu item")
        item.point()
        self.app.sleep(.5)
        item.click()
        return self.app.root.find("Clone Virtual Machine", "frame")

    def _get_all_rows(self, win):
        slist = win.find("storage-list")
        def pred(node):
            return node.roleName == "table cell"
        cells = slist.findChildren(pred, isLambda=True)

        idx = 0
        rows = []
        cellcount = 6
        while idx < len(cells):
            rows.append(_CloneRow(*cells[idx:idx + cellcount]))
            idx += cellcount
            # Skip the next row which is always a separator
            idx += cellcount
        return rows


    ##############
    # Test cases #
    ##############

    def testCloneSimple(self):
        # Disable predictable so UUID generation doesn't collide
        uri = tests.utils.URIs.test_full.replace(",predictable", "")
        self.app.uri = uri

        # Clone 'test-clone-simple' which is the most basic case
        # Cancel, and reopen
        win = self._open_window("test-clone-simple")
        win.find("Cancel", "push button").click()
        lib.utils.check(lambda: not win.showing)

        # Do default clone
        win = self._open_window("test-clone-simple")
        rows = self._get_all_rows(win)
        assert len(rows) == 1
        assert rows[0].is_clone_requested
        rows[0].check_in_text("test-clone-simple.img")

        win.find("Clone", "push button").click()
        lib.utils.check(lambda: not win.showing)

        # Check path was generated correctly
        win = self._open_window("test-clone-simple-clone")
        rows = self._get_all_rows(win)
        assert len(rows) == 1
        assert rows[0].is_clone_requested
        rows[0].check_in_text("test-clone-simple-clone.img")

        # Share storage and deal with warnings
        rows[0].chkcell.click()
        rows[0].check_in_text("Share disk with")
        # Do 'cancel' first
        win.find("Clone", "push button").click()
        self.app.click_alert_button("cause data to be overwritten", "Cancel")
        lib.utils.check(lambda: win.active)
        win.find("Clone", "push button").click()
        self.app.click_alert_button("cause data to be overwritten", "OK")
        lib.utils.check(lambda: not win.active)

        # Verify the new VM shared storage
        win = self._open_window("test-clone-simple-clone1")
        rows = self._get_all_rows(win)
        assert len(rows) == 1
        rows[0].check_in_text("test-clone-simple-clone.img")

    def testCloneMulti(self):
        # Clone 'test-clone', check some results, make sure clone works
        win = self._open_window("test-clone\n")
        win.find("Clone", "push button").click()
        lib.utils.check(lambda: not win.showing)
        self.app.topwin.find("test-clone1", "table cell")

        # Check test-many-devices which will not work, but confirm
        # it errors gracefully
        self.app.topwin.find("test-many-devices").click()
        sbutton = self.app.topwin.find("Shut Down", "push button")
        sbutton.click()
        lib.utils.check(lambda: not sbutton.sensitive)
        self.app.sleep(.5)
        win = self._open_window("test-many-devices")
        win.find("Clone", "push button").click()
        self.app.click_alert_button("No such file or", "Close")
        win.keyCombo("<alt>F4")
        lib.utils.check(lambda: not win.showing)

    def testCloneStorageChange(self):
        # Disable predictable so UUID generation doesn't collide
        uri = tests.utils.URIs.test_full.replace(",predictable", "")
        self.app.uri = uri

        # Trigger some error handling scenarios
        win = self._open_window("test-clone-simple")
        newname = "test-aaabbb"
        win.find("Name:", "text").set_text(newname)
        win.find("Clone", "push button").click()
        lib.utils.check(lambda: not win.showing)

        win = self._open_window(newname)
        row = self._get_all_rows(win)[0]
        row.check_in_text(newname)
        oldnewname = newname
        newname = "test-aaazzzzbbb"
        win.find("Name:", "text").set_text(newname)
        row.select()

        win.find("Details", "push button").click()
        stgwin = self.app.root.find("Change storage path", "dialog")
        pathtxt = stgwin.find(None, "text", "New Path:")
        lib.utils.check(lambda: newname in pathtxt.text)
        stgwin.find("Browse", "push button").click()
        self.app.select_storagebrowser_volume("default-pool", "iso-vol")
        lib.utils.check(lambda: "iso-vol" in pathtxt.text)
        stgwin.find("OK").click()
        self.app.click_alert_button("overwrite the existing", "No")
        lib.utils.check(lambda: stgwin.showing)
        stgwin.find("OK").click()
        self.app.click_alert_button("overwrite the existing", "Yes")
        lib.utils.check(lambda: not stgwin.showing)
        # Can't clone onto existing storage volume
        win.find("Clone", "push button").click()
        self.app.click_alert_button(".*Clone onto existing.*", "Close")

        # Reopen dialog and request to share it
        win.find("Details", "push button").click()
        stgwin = self.app.root.find("Change storage path", "dialog")
        chkbox = stgwin.find("Create a new", "check")
        lib.utils.check(lambda: chkbox.checked)
        chkbox.click()

        # Cancel and reopen, confirm changes didn't stick
        stgwin.find("Cancel").click()
        lib.utils.check(lambda: not stgwin.showing)
        win.find("Details", "push button").click()
        stgwin = self.app.root.find("Change storage path", "dialog")
        chkbox = stgwin.find("Create a new", "check")
        lib.utils.check(lambda: chkbox.checked)
        # Requesting sharing again and exit
        chkbox.click()
        stgwin.find("OK").click()
        lib.utils.check(lambda: not stgwin.active)

        # Finish install, verify storage was shared
        win.find("Clone", "push button").click()
        self.app.click_alert_button("cause data to be overwritten", "OK")
        lib.utils.check(lambda: not win.active)
        win = self._open_window(newname)
        row = self._get_all_rows(win)[0].check_in_text(oldnewname)


    def testCloneError(self):
        # Trigger some error handling scenarios
        win = self._open_window("test-clone-full\n")
        win.find("Clone", "push button").click()
        self.app.click_alert_button("not enough free space", "Close")
        lib.utils.check(lambda: win.showing)
        win.keyCombo("<alt>F4")

        win = self._open_window("test-clone-simple")
        badname = "test/foo"
        win.find("Name:", "text").set_text(badname)
        rows = self._get_all_rows(win)
        rows[0].chkcell.click()
        rows[0].check_in_text("Share disk with")
        win.find("Clone", "push button").click()
        win.find("Clone", "push button").click()
        self.app.click_alert_button("cause data to be overwritten", "OK")
        self.app.click_alert_button(badname, "Close")
        lib.utils.check(lambda: win.active)


    def testCloneNonmanaged(self):
        # Verify unmanaged clone actual works
        import tempfile
        tmpsrc = tempfile.NamedTemporaryFile()
        tmpdst = tempfile.NamedTemporaryFile()

        open(tmpsrc.name, "w").write(__file__)

        self.app.open(xmleditor_enabled=True)
        manager = self.app.topwin

        win = self.app.open_details_window("test-clone-simple")
        win.find("IDE Disk 1", "table cell").click()
        win.find("XML", "page tab").click()
        xmleditor = win.find("XML editor")
        origpath = "/dev/default-pool/test-clone-simple.img"
        newpath = tmpsrc.name
        xmleditor.set_text(xmleditor.text.replace(origpath, newpath))
        win.find("config-apply").click()
        win.find("Details", "page tab").click()
        disksrc = win.find("disk-source-path")
        lib.utils.check(lambda: disksrc.text == newpath)
        win.keyCombo("<alt>F4")
        lib.utils.check(lambda: not win.active)

        lib.utils.check(lambda: manager.active)
        win = self._open_window("test-clone-simple")
        row = self._get_all_rows(win)[0]
        row.check_in_text(tmpsrc.name)
        row.select()

        win.find("Details", "push button").click()
        stgwin = self.app.root.find("Change storage path", "dialog")
        pathtxt = stgwin.find(None, "text", "New Path:")
        os.unlink(tmpdst.name)
        pathtxt.set_text(tmpdst.name)
        stgwin.find("OK").click()
        win.find("Clone", "push button").click()
        lib.utils.check(lambda: not win.active)
        lib.utils.check(lambda: os.path.exists(tmpdst.name))

        assert open(tmpsrc.name).read() == open(tmpdst.name).read()
