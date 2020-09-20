# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


#####################################
# UI tests for the createvol wizard #
#####################################

def _open_createvol(app, hostwin):
    hostwin.find("vol-new", "push button").click()
    win = app.find_window("Add a Storage Volume")
    lib.utils.check(lambda: win.active)
    return win


def testCreateVolDefault(app):
    """
    Create default volume, clean it up
    """
    hostwin = app.manager_open_host("Storage")
    poolcell = hostwin.find("default-pool", "table cell")
    poolcell.click()
    vollist = hostwin.find("vol-list", "table")
    win = _open_createvol(app, hostwin)
    finish = win.find("Finish", "push button")
    name = win.find("Name:", "text")

    # Create a default qcow2 volume
    newname = "vol"
    lib.utils.check(lambda: name.text == newname)
    sparse = win.find("Allocate", "check box")
    lib.utils.check(lambda: not sparse.checked)
    finish.click()

    # Delete it, clicking 'No' first
    volcell = vollist.find(newname + ".qcow2")
    volcell.bring_on_screen()
    hostwin.find("vol-refresh", "push button").click()
    hostwin.find("vol-delete", "push button").click()
    app.click_alert_button("permanently delete the volume", "No")
    volcell = vollist.find(newname + ".qcow2")
    hostwin.find("vol-delete", "push button").click()
    app.click_alert_button("permanently delete the volume", "Yes")
    lib.utils.check(lambda: volcell.dead)

    # Ensure host window closes fine
    hostwin.keyCombo("<ctrl>w")
    lib.utils.check(lambda: not hostwin.showing and
            not hostwin.active)


def testCreateVolMisc(app):
    """
    Cover all createvol options
    """
    hostwin = app.manager_open_host("Storage")
    poolcell = hostwin.find("default-pool", "table cell")
    poolcell.click()
    win = _open_createvol(app, hostwin)
    name = win.find("Name:", "text")
    finish = win.find("Finish", "push button")
    vollist = hostwin.find("vol-list", "table")

    # Create a qcow2 with backing file
    newname = "aaa-qcow2-backing.qcow2"
    name.set_text(newname)
    win.combo_select("Format:", "qcow2")
    win.find("Backing store").click_expander()
    win.find("Browse...").click()
    browsewin = app.root.find("vmm-storage-browser")
    # Test cancel button
    browsewin.find("Cancel", "push button").click()
    lib.utils.check(lambda: not browsewin.active)
    win.find("Browse...").click()
    browsewin = app.root.find("vmm-storage-browser")
    # Test browse local opening
    browsewin.find("Browse Local", "push button").click()
    chooser = app.root.find(
            "Locate existing storage", "file chooser")
    chooser.window_close()
    app.select_storagebrowser_volume(
            "default-pool", "bochs-vol", doubleclick=True)
    backingstore = win.find("backing-store")
    lib.utils.check(lambda: "bochs-vol" in backingstore.text)
    finish.click()
    vollist.find(newname)

    # Create a raw volume with some size tweaking
    win = _open_createvol(app, hostwin)
    # Using previous name so we collide
    name.set_text(newname)
    win.combo_select("Format:", "raw")
    sparse = win.find("Allocate", "check box")
    lib.utils.check(lambda: sparse.checked)

    finish.click()
    app.click_alert_button("Error validating volume", "Close")
    newname = "a-newvol.raw"
    name.set_text(newname)
    finish.click()
    vollist.find(newname)

    # Create LVM backing store
    hostwin.find("disk-pool", "table cell").click()
    win = _open_createvol(app, hostwin)
    newname = "aaa-lvm"
    name.set_text(newname)
    win.find("Backing store").click_expander()
    win.find("Browse...").click()
    app.select_storagebrowser_volume("disk-pool", "diskvol7")
    sparse.check_not_onscreen()
    finish.click()
    vollist.find(newname)



def testCreateVolXMLEditor(app):
    app.open(xmleditor_enabled=True)
    hostwin = app.manager_open_host("Storage")
    poolcell = hostwin.find("default-pool", "table cell")
    poolcell.click()
    win = _open_createvol(app, hostwin)
    finish = win.find("Finish", "push button")
    name = win.find("Name:", "text")
    vollist = hostwin.find("vol-list", "table")

    # Create a new obj with XML edited name, verify it worked
    tmpname = "objtmpname"
    newname = "aafroofroo"
    name.set_text(tmpname)
    win.find("XML", "page tab").click()
    xmleditor = win.find("XML editor")
    newtext = xmleditor.text.replace(
                    ">%s.qcow2<" % tmpname, ">%s<" % newname)
    xmleditor.set_text(newtext)
    finish.click()
    lib.utils.check(lambda: hostwin.active)
    vollist.find(newname)

    # Do standard xmleditor tests
    win = _open_createvol(app, hostwin)
    lib.utils.test_xmleditor_interactions(app, win, finish)
    win.find("Cancel", "push button").click()
    lib.utils.check(lambda: not win.visible)
