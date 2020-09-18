# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


######################################
# UI tests for the createpool wizard #
######################################

def _open_createpool(app, hostwin):
    hostwin.find("pool-add", "push button").click()
    win = app.find_window("Add a New Storage Pool")
    lib.utils.check(lambda: win.active)
    return win


def testCreatePools(app):
    hostwin = app.manager_open_host("Storage")
    win = _open_createpool(app, hostwin)
    finish = win.find("Finish", "push button")
    name = win.find("Name:", "text")

    def _browse_local_path(winlabel, usepath):
        chooser = app.root.find(winlabel, "file chooser")
        # Enter the filename and select it
        chooser.find(usepath, "table cell").click()
        obutton = chooser.find("Open", "push button")
        lib.utils.check(lambda: obutton.sensitive)
        obutton.click()
        lib.utils.check(lambda: not chooser.showing)
        lib.utils.check(lambda: win.active)

    # Create a simple default dir pool
    lib.utils.check(lambda: name.text == "pool")
    newname = "a-test-new-pool"
    name.set_text(newname)
    finish.click()

    # Select the new object in the host window, then do
    # stop->start->stop->delete, for lifecycle testing
    lib.utils.check(lambda: hostwin.active)
    cell = hostwin.find(newname, "table cell")
    delete = hostwin.find("pool-delete", "push button")
    start = hostwin.find("pool-start", "push button")
    stop = hostwin.find("pool-stop", "push button")

    cell.click()
    stop.click()
    lib.utils.check(lambda: start.sensitive)
    start.click()
    lib.utils.check(lambda: stop.sensitive)
    stop.click()
    lib.utils.check(lambda: delete.sensitive)

    # Delete it, clicking 'No' first
    delete.click()
    app.click_alert_button("permanently delete the pool", "No")
    lib.utils.check(lambda: not cell.dead)
    delete.click()
    app.click_alert_button("permanently delete the pool", "Yes")
    # Ensure it's gone
    lib.utils.check(lambda: cell.dead)

    # Test a disk pool
    win = _open_createpool(app, hostwin)
    win.combo_select("Type:", "disk:")
    newname = "a-disk-pool"
    name.set_text("a-disk-pool")
    win.find("source-browse").click()
    _browse_local_path("Choose source path", "console")
    finish.click()
    hostwin.find(newname, "table cell")

    # Test a iscsi pool
    win = _open_createpool(app, hostwin)
    win.combo_select("Type:", "iscsi:")
    newname = "a-iscsi-pool"
    name.set_text("a-iscsi-pool")
    win.find("target-browse").click()
    _browse_local_path("Choose target directory", "by-path")
    finish.click()
    # Catch example error
    app.click_alert_button("source host name", "Close")
    win.find("Host Name:", "text").set_text("example.com")
    win.find("pool-source-path-text").set_text("foo-iqn")
    win.find_fuzzy("Initiator IQN:", "check").click()
    win.find("iqn-text", "text").set_text("initiator-foo")
    finish.click()
    hostwin.find(newname, "table cell")

    # Test a logical pool
    win = _open_createpool(app, hostwin)
    win.combo_select("Type:", "logical:")
    newname = "a-lvm-pool"
    name.set_text("a-lvm-pool")

    win.combo_check_default("Volgroup", "testvg1")
    win.combo_select("Volgroup", "testvg2")
    finish.click()
    hostwin.find(newname, "table cell")

    # Test a scsi pool
    win = _open_createpool(app, hostwin)
    win.combo_select("Type:", "scsi:")
    newname = "a-scsi-pool"
    name.set_text("a-scsi-pool")
    win.combo_select("Source Adapter:", "host2")
    finish.click()
    hostwin.find(newname, "table cell")

    # Test a ceph pool
    win = _open_createpool(app, hostwin)
    newname = "a-ceph-pool"
    name.set_text("a-ceph-pool")
    win.combo_select("Type:", "rbd:")
    win.find_fuzzy("Host Name:", "text").set_text("example.com:1234")
    win.find_fuzzy("pool-source-name-text", "text").typeText("frob")
    finish.click()
    lib.utils.check(lambda: not win.showing)
    lib.utils.check(lambda: hostwin.active)
    hostwin.find(newname, "table cell")

    # Ensure host window closes fine
    hostwin.click()
    hostwin.keyCombo("<ctrl>w")
    lib.utils.check(lambda: not hostwin.showing)



def testCreatePoolXMLEditor(app):
    app.open(xmleditor_enabled=True)
    hostwin = app.manager_open_host("Storage")
    win = _open_createpool(app, hostwin)
    finish = win.find("Finish", "push button")
    name = win.find("Name:", "text")

    # Create a new obj with XML edited name, verify it worked
    tmpname = "objtmpname"
    newname = "froofroo"
    name.set_text(tmpname)
    win.find("XML", "page tab").click()
    xmleditor = win.find("XML editor")
    newtext = xmleditor.text.replace(">%s<" % tmpname, ">%s<" % newname)
    xmleditor.set_text(newtext)
    finish.click()
    lib.utils.check(lambda: hostwin.active)
    cell = hostwin.find(newname, "table cell")
    cell.click()

    # Do standard xmleditor tests
    win = _open_createpool(app, hostwin)
    lib.utils.test_xmleditor_interactions(app, win, finish)
    win.find("Cancel", "push button").click()
    lib.utils.check(lambda: not win.visible)
