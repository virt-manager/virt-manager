# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

import tests
from . import lib


#############################################
# UI tests for details storage media change #
#############################################

def testMediaChange(app):
    vmname = "test-many-devices"
    app.uri = tests.utils.URIs.test_remote
    app.open(show_console=vmname)
    win = app.find_details_window(vmname,
            click_details=True, shutdown=True)
    hw = win.find("hw-list")
    tab = win.find("disk-tab")
    combo = win.find("media-combo")
    entry = win.find("media-entry")
    appl = win.find("config-apply")

    # Floppy + physical
    hw.find("Floppy 1", "table cell").click()
    combo.click_combo_entry()
    combo.find(r"Floppy_install_label \(/dev/fdb\)")
    lib.utils.check(lambda: entry.text == "No media detected (/dev/fda)")
    entry.click()
    entry.click_secondary_icon()
    lib.utils.check(lambda: not entry.text)
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    lib.utils.check(lambda: not entry.text)

    # Enter /dev/fdb, after apply it should change to pretty label
    entry.set_text("/dev/fdb")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    lib.utils.check(lambda:
        entry.text == "Floppy_install_label (/dev/fdb)")

    # Specify manual path
    path = "/pool-dir/UPPER"
    entry.set_text(path)
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    lib.utils.check(lambda: entry.text == path)

    # Go to Floppy 2, make sure previous path is in recent list
    hw.find("Floppy 2", "table cell").click()
    combo.click_combo_entry()
    combo.find(path)
    entry.click()
    # Use the storage browser to select new floppy storage
    tab.find("Browse", "push button").click()
    app.select_storagebrowser_volume("pool-dir", "iso-vol")
    appl.click()

    # Browse for image
    hw.find("IDE CDROM 1", "table cell").click()
    combo.click_combo_entry()
    combo.find(r"Fedora12_media \(/dev/sr0\)")
    entry.click()
    tab.find("Browse", "push button").click()
    app.select_storagebrowser_volume("pool-dir", "backingl1.img")
    # Check 'already in use' dialog
    appl.click()
    app.click_alert_button("already in use by", "No")
    lib.utils.check(lambda: appl.sensitive)
    appl.click()
    app.click_alert_button("already in use by", "Yes")
    lib.utils.check(lambda: not appl.sensitive)
    lib.utils.check(lambda: "backing" in entry.text)
    entry.set_text("")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    lib.utils.check(lambda: not entry.text)



def testMediaHotplug(app):
    """
    Test in the case of a running VM
    """
    vmname = "test-many-devices"
    app.open(show_console=vmname)
    win = app.find_details_window(vmname, click_details=True)
    hw = win.find("hw-list")
    entry = win.find("media-entry")
    appl = win.find("config-apply")

    hw.find("IDE CDROM 1", "table cell").click()
    lib.utils.check(lambda: not entry.text)
    # Catch path does not exist error
    entry.set_text("/dev/sr7")
    appl.click()
    app.click_alert_button("non-existent path '/dev/sr7", "Close")

    # Check relative path while we are at it
    path = "virt-install"
    entry.set_text(path)
    appl.click()
    app.click_alert_button("changes will take effect", "OK")
    lib.utils.check(lambda: not appl.sensitive)
    lib.utils.check(lambda: not entry.text)

    # Shutdown the VM, verify change shows up
    win.find("Shut Down", "push button").click()
    run = win.find("Run", "push button")
    lib.utils.check(lambda: run.sensitive)
    lib.utils.check(lambda: entry.text == os.path.abspath(path))
