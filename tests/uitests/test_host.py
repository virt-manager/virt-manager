# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


#################################################
# UI tests for virt-manager's VM details window #
#################################################

def testHostNetworkSmokeTest(app):
    """
    Verify that each virtual network displays, without error.
    """
    win = app.manager_open_host("Virtual Networks")
    lst = win.find("net-list", "table")
    errlabel = win.find("net-error-label", "label")
    lib.utils.walkUIList(app, win, lst, lambda: errlabel.showing)

    # Select XML editor, and reverse walk the list
    win.find("network-grid").find("XML", "page tab").click()
    lib.utils.walkUIList(app, win, lst, lambda: errlabel.showing, reverse=True)


def testHostNetworkEdit(app):
    """
    Test edits to net config
    """
    app.open(xmleditor_enabled=True)
    win = app.manager_open_host("Virtual Networks").find("network-grid")
    finish = win.find("Apply", "push button")

    # Shut it off, do an XML edit, verify it
    win.find("default", "table cell").click()
    delete = win.find("net-delete", "push button")
    stop = win.find("net-stop", "push button")
    stop.click()
    lib.utils.check(lambda: delete.sensitive)
    win.find("XML", "page tab").click()
    xmleditor = win.find("XML editor")
    origdev = "virbr0"
    newdev = "virbr77"
    xmleditor.set_text(xmleditor.text.replace(origdev, newdev))
    finish.click()
    win.find("Details", "page tab").click()
    netdev = win.find("net-device")
    lib.utils.check(lambda: netdev.text == newdev)

    # Rename it
    win.find("default", "table cell").click()
    win.find("net-name").set_text("newsort-default")
    finish.click()

    # Change autostart, trigger it by clicking away
    win.find("newsort-default", "table cell").click()
    win.find("net-autostart").click()
    win.find("netboot", "table cell").click()
    app.click_alert_button("There are unapplied changes", "Yes")

    # Do standard xmleditor tests
    lib.utils.test_xmleditor_interactions(app, win, finish)



def testHostStorageSmokeTest(app):
    """
    Verify that each storage pool displays, without error.
    """
    win = app.manager_open_host("Storage")
    lst = win.find("pool-list", "table")
    errlabel = win.find("pool-error-label", "label")
    lib.utils.walkUIList(app, win, lst, lambda: errlabel.showing)

    # Select XML editor, and reverse walk the list
    win.find("storage-grid").find("XML", "page tab").click()
    lib.utils.walkUIList(app, win, lst, lambda: errlabel.showing, reverse=True)


def testHostStorageEdit(app):
    """
    Test edits to pool config
    """
    app.open(xmleditor_enabled=True)
    win = app.manager_open_host("Storage").find("storage-grid")
    finish = win.find("Apply", "push button")

    # Shut off a pool, do an XML edit, verify it
    win.find("default-pool", "table cell").click()
    delete = win.find("pool-delete", "push button")
    stop = win.find("pool-stop", "push button")
    stop.click()
    lib.utils.check(lambda: delete.sensitive)
    win.find("XML", "page tab").click()
    xmleditor = win.find("XML editor")
    origpath = "/dev/default-pool"
    newpath = "/dev/foo/bar/baz"
    xmleditor.set_text(xmleditor.text.replace(origpath, newpath))
    finish.click()
    win.find("Details", "page tab").click()
    poolloc = win.find("pool-location")
    lib.utils.check(lambda: poolloc.text == newpath)

    # Rename it
    win.find("default", "table cell").click()
    win.find("pool-name").set_text("newsort-default")
    finish.click()

    # Change autostart. Trigger it by clicking on new cell
    win.find("newsort-default", "table cell").click()
    win.find("pool-autostart").click()
    win.find("disk-pool", "table cell").click()
    app.click_alert_button("There are unapplied changes", "Yes")

    # Do standard xmleditor tests
    lib.utils.test_xmleditor_interactions(app, win, finish)


def testHostStorageVolMisc(app):
    """
    Misc actions involving volumes
    """
    win = app.manager_open_host("Storage").find("storage-grid")
    win.find_fuzzy("default-pool", "table cell").click()
    vollist = win.find("vol-list", "table")

    vol1 = vollist.find("backingl1.img", "table cell")
    vol2 = vollist.find("UPPER", "table cell")
    vol1.check_onscreen()
    vol2.check_not_onscreen()
    win.find("Size", "table column header").click()
    win.find("Size", "table column header").click()
    vol1.check_not_onscreen()
    vol2.check_onscreen()

    vol2.click(button=3)
    app.root.find("Copy Volume Path", "menu item").click()
    from gi.repository import Gdk, Gtk
    clipboard = Gtk.Clipboard.get_default(Gdk.Display.get_default())
    lib.utils.check(lambda: clipboard.wait_for_text() == "/dev/default-pool/UPPER")


def testHostConn(app):
    """
    Change some connection parameters
    """
    manager = app.topwin
    # Disconnect the connection
    app.manager_conn_disconnect("test testdriver.xml")

    # Open Host Details from right click menu
    c = manager.find("test testdriver.xml", "table cell")
    c.click(button=3)
    app.root.find("conn-details", "menu item").click()
    win = app.find_window("test testdriver.xml - Connection Details")

    # Click the tabs and then back
    win.find_fuzzy("Storage", "tab").click()
    win.find_fuzzy("Network", "tab").click()
    win.find_fuzzy("Overview", "tab").click()

    # Toggle autoconnect
    win.find("Autoconnect:", "check box").click()
    win.find("Autoconnect:", "check box").click()

    # Change the name, verify that title bar changed
    win.find("Name:", "text").set_text("FOOBAR")
    app.find_window("FOOBAR - Connection Details")

    # Open the manager window
    win.find("File", "menu").click()
    win.find("View Manager", "menu item").click()
    lib.utils.check(lambda: manager.active)
    # Confirm connection row is named differently in manager
    manager.find("FOOBAR", "table cell")

    # Close the manager
    manager.window_close()
    lib.utils.check(lambda: win.active)

    # Quit app from the file menu
    win.find("File", "menu").click()
    win.find("Quit", "menu item").click()
    lib.utils.check(lambda: not app.is_running())
