# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

import libvirt
import pytest

from virtinst import log

import tests
from . import lib


def _vm_wrapper(vmname, uri="qemu:///system", opts=None):
    """
    Decorator to define+start a VM and clean it up on exit
    """
    def wrap1(fn):
        def wrapper(app, *args, **kwargs):
            app.error_if_already_running()
            xmlfile = "%s/live/%s.xml" % (tests.utils.UITESTDATADIR, vmname)
            conn = libvirt.open(uri)
            dom = conn.defineXML(open(xmlfile).read())
            try:
                dom.create()
                app.uri = uri
                app.conn = conn
                extra_opts = (opts or [])
                extra_opts += ["--show-domain-console", vmname]
                # Enable stats for more code coverage
                keyfile = "statsonly.ini"
                app.open(extra_opts=extra_opts, keyfile=keyfile)
                fn(app, dom, *args, **kwargs)
            finally:
                try:
                    app.stop()
                except Exception:
                    pass
                try:
                    flags = 0
                    if "qemu" in uri:
                        flags = libvirt.VIR_DOMAIN_UNDEFINE_NVRAM
                    dom.undefineFlags(flags)
                    dom.destroy()
                except Exception:
                    pass
        return wrapper
    return wrap1


def _destroy(app, win):
    smenu = win.find("Menu", "toggle button")
    smenu.click()
    smenu.find("Force Off", "menu item").click()
    app.click_alert_button("you sure", "Yes")
    run = win.find("Run", "push button")
    lib.utils.check(lambda: run.sensitive)


###############################################
# Test live console connections with stub VMs #
###############################################

def _checkConsoleStandard(app, dom):
    """
    Shared logic for general console handling
    """
    ignore = dom
    win = app.topwin
    con = win.find("console-gfx-viewport")
    lib.utils.check(lambda: con.showing)

    win.find("Virtual Machine", "menu").click()
    win.find("Take Screenshot", "menu item").click()
    chooser = app.root.find(None, "file chooser")
    fname = chooser.find("Name", "text").text
    app.rawinput.pressKey("Enter")
    lib.utils.check(lambda: os.path.exists(fname))
    os.unlink(fname)
    lib.utils.check(lambda: win.active)

    win.find("Send Key", "menu").click()
    win.find(r"Ctrl\+Alt\+F1", "menu item").click()
    win.find("Send Key", "menu").click()
    win.find(r"Ctrl\+Alt\+F10", "menu item").click()
    win.find("Send Key", "menu").click()
    win.find(r"Ctrl\+Alt\+Delete", "menu item").click()

    # 'Resize to VM' testing
    oldsize = win.size
    win.find("^View$", "menu").click()
    win.find("Resize to VM", "menu item").click()
    newsize = win.size
    lib.utils.check(lambda: oldsize != newsize)

    # Fullscreen testing
    win.find("^View$", "menu").click()
    win.find("Fullscreen", "check menu item").click()
    fstb = win.find("Fullscreen Toolbar")
    lib.utils.check(lambda: fstb.showing)
    lib.utils.check(lambda: win.size != newsize)

    # Wait for toolbar to hide, then reveal it again
    lib.utils.check(lambda: not fstb.showing, timeout=5)
    app.rawinput.point(win.position[0] + win.size[0] / 2, 0)
    lib.utils.check(lambda: fstb.showing)
    # Move it off and have it hide again
    win.point()
    lib.utils.check(lambda: not fstb.showing, timeout=5)
    app.rawinput.point(win.position[0] + win.size[0] / 2, 0)
    lib.utils.check(lambda: fstb.showing)

    # Click stuff and exit fullscreen
    win.find("Fullscreen Send Key").click()
    app.rawinput.pressKey("Escape")
    win.find("Fullscreen Exit").click()
    lib.utils.check(lambda: win.size == newsize)

    # Trigger pointer grab, verify title was updated
    win.click()
    lib.utils.check(lambda: "Control_L" in win.name)
    # Ungrab
    win.keyCombo("<ctrl><alt>")
    lib.utils.check(lambda: "Control_L" not in win.name)

    # Tweak scaling
    win.window_maximize()
    win.find("^View$", "menu").click()
    scalemenu = win.find("Scale Display", "menu")
    scalemenu.point()
    scalemenu.find("Always", "radio menu item").click()
    win.find("^View$", "menu").click()
    scalemenu = win.find("Scale Display", "menu")
    scalemenu.point()
    scalemenu.find("Never", "radio menu item").click()
    win.find("^View$", "menu").click()
    scalemenu = win.find("Scale Display", "menu")
    scalemenu.point()
    scalemenu.find("Only", "radio menu item").click()

    win.window_close()


@_vm_wrapper("uitests-vnc-standard")
def testConsoleVNCStandard(app, dom):
    return _checkConsoleStandard(app, dom)


@_vm_wrapper("uitests-spice-standard")
def testConsoleSpiceStandard(app, dom):
    return _checkConsoleStandard(app, dom)


def _checkConsoleFocus(app, dom):
    """
    Shared logic for console keyboard grab handling
    """
    win = app.topwin
    con = win.find("console-gfx-viewport")
    lib.utils.check(lambda: con.showing)

    # Check that modifiers don't work when console grabs pointer
    win.click()
    app.sleep(.5)  # make sure window code has time to adjust modifiers
    win.keyCombo("<ctrl><shift>w")
    lib.utils.check(lambda: win.showing)
    dom.destroy()
    win.find("Guest is not running.")
    win.grab_focus()
    app.sleep(.5)  # make sure window code has time to adjust modifiers
    win.keyCombo("<ctrl><shift>w")
    lib.utils.check(lambda: not win.showing)


@_vm_wrapper("uitests-vnc-standard")
def testConsoleVNCFocus(app, dom):
    return _checkConsoleFocus(app, dom)


@_vm_wrapper("uitests-spice-standard")
def testConsoleSpiceFocus(app, dom):
    return _checkConsoleFocus(app, dom)


def _checkPassword(app):
    """
    Shared logic for password handling
    """
    win = app.topwin
    con = win.find("console-gfx-viewport")
    lib.utils.check(lambda: not con.showing)
    passwd = win.find("Password:", "password text")
    lib.utils.check(lambda: passwd.showing)

    # Check wrong password handling
    passwd.typeText("xx")
    win.find("Login", "push button").click()
    app.click_alert_button("Viewer authentication error", "OK")
    savecheck = win.find("Save this password", "check box")
    if not savecheck.checked:
        savecheck.click()
    passwd.typeText("yy")
    app.rawinput.pressKey("Enter")
    app.click_alert_button("Viewer authentication error", "OK")

    # Check proper password
    passwd.text = ""
    passwd.typeText("goodp")
    win.find("Login", "push button").click()
    lib.utils.check(lambda: con.showing)

    # Restart VM to retrigger console connect
    _destroy(app, win)
    win.find("Run", "push button").click()
    lib.utils.check(lambda: passwd.showing)
    # Password should be filled in
    lib.utils.check(lambda: bool(passwd.text))
    # Uncheck 'Save password' and login, which will delete it from keyring
    savecheck.click()
    win.find("Login", "push button").click()
    lib.utils.check(lambda: con.showing)

    # Restart VM to retrigger console connect
    _destroy(app, win)
    win.find("Run", "push button").click()
    lib.utils.check(lambda: passwd.showing)
    # Password should be empty now
    lib.utils.check(lambda: not bool(passwd.text))


@_vm_wrapper("uitests-vnc-password")
def testConsoleVNCPassword(app, dom):
    ignore = dom
    return _checkPassword(app)


@_vm_wrapper("uitests-spice-password")
def testConsoleSpicePassword(app, dom):
    ignore = dom
    return _checkPassword(app)


@_vm_wrapper("uitests-vnc-password",
             opts=["--test-options=fake-vnc-username"])
def testConsoleVNCPasswordUsername(app, dom):
    ignore = dom
    win = app.topwin
    con = win.find("console-gfx-viewport")
    lib.utils.check(lambda: not con.showing)
    passwd = win.find("Password:", "password text")
    lib.utils.check(lambda: passwd.showing)
    username = win.find("Username:", "text")
    lib.utils.check(lambda: username.showing)

    # Since we are mocking the username, sending the credentials
    # is ignored, so with the correct password this succeeds
    username.text = "fakeuser"
    passwd.typeText("goodp")
    win.find("Login", "push button").click()
    lib.utils.check(lambda: con.showing)


@_vm_wrapper("uitests-vnc-socket")
def testConsoleVNCSocket(app, dom):
    ignore = dom
    win = app.topwin
    con = win.find("console-gfx-viewport")
    lib.utils.check(lambda: con.showing)

    def _click_textconsole_menu(msg):
        vmenu = win.find("^View$", "menu")
        vmenu.click()
        tmenu = win.find("Consoles", "menu")
        tmenu.point()
        app.sleep(.5)  # give console menu time to dynamically populate
        tmenu.find(msg, "radio menu item").click()

    # A bit of an extra test, make sure selecting Graphical Console works
    _click_textconsole_menu("Serial 1")
    lib.utils.check(lambda: not con.showing)
    _click_textconsole_menu("Graphical Console")
    lib.utils.check(lambda: con.showing)


@_vm_wrapper("uitests-spice-standard")
def testConsoleAutoconnect(app, dom):
    ignore = dom
    win = app.topwin
    con = win.find("console-gfx-viewport")
    lib.utils.check(lambda: con.showing)

    # Disable autoconnect
    vmenu = win.find("^View$", "menu")
    vmenu.click()
    vmenu.find("Autoconnect").click()
    dom.destroy()
    label = win.find("Guest is not running.")
    label.check_onscreen()
    dom.create()
    label.check_not_onscreen()
    button = win.find("Connect to console", "push button")
    button.check_onscreen()
    lib.utils.check(lambda: not con.showing)
    button.click()
    lib.utils.check(lambda: con.showing)


@_vm_wrapper("uitests-lxc-serial", uri="lxc:///")
def testConsoleLXCSerial(app, dom):
    """
    Ensure LXC has serial open, and we can send some data
    """
    win = app.topwin
    term = win.find("Serial Terminal")
    lib.utils.check(lambda: term.showing)
    term.typeText("help\n")
    lib.utils.check(lambda: "COMMANDS" in term.text)

    term.doubleClick()
    term.click(button=3)
    menu = app.root.find("serial-popup-menu")
    menu.find("Copy", "menu item").click()

    term.click()
    term.click(button=3)
    menu = app.root.find("serial-popup-menu")
    menu.find("Paste", "menu item").click()

    win.find("Details", "radio button").click()
    win.find("Console", "radio button").click()
    _destroy(app, win)
    view = app.root.find("^View$", "menu")
    view.click()
    # Triggers some tooltip cases
    textmenu = view.find("Consoles", "menu")
    textmenu.point()
    lib.utils.check(lambda: textmenu.showing)
    app.sleep(.5)  # give console menu time to dynamically populate
    item = textmenu.find("Text Console 1")
    lib.utils.check(lambda: not item.sensitive)

    # Restart the guest to trigger reconnect code
    view.click()
    win.find("Run", "push button").click()
    term = win.find("Serial Terminal")
    lib.utils.check(lambda: term.showing)

    # Ensure ctrl+w doesn't close the window, modifiers are disabled
    term.click()
    win.keyCombo("<ctrl><shift>w")
    lib.utils.check(lambda: win.showing)
    # Shut it down, ensure accelerator works again
    _destroy(app, win)
    lib.utils.check(lambda: not dom.isActive())
    win.click_title()
    app.sleep(.3)  # make sure window code has time to adjust modifiers
    win.keyCombo("<ctrl><shift>w")
    lib.utils.check(lambda: not win.showing)


@_vm_wrapper("uitests-spice-specific",
        opts=["--test-options=spice-agent",
              "--test-options=fake-console-resolution"])
def testConsoleSpiceSpecific(app, dom):
    """
    Spice specific behavior. Has lots of devices that will open
    channels, spice GL + local config, and usbredir
    """
    ignore = dom
    win = app.topwin
    con = win.find("console-gfx-viewport")
    lib.utils.check(lambda: con.showing)

    # Just ensure the dialog pops up, can't really test much more
    # than that
    win.find("Virtual Machine", "menu").click()
    win.find("Redirect USB", "menu item").click()

    usbwin = app.root.find("vmm dialog", "alert")
    usbwin.find("Select USB devices for redirection", "label")
    usbwin.find("SPICE CD", "check box").click()
    chooser = app.root.find(None, "file chooser")
    # Find the cwd bookmark on the left
    chooser.find("virt-manager", "label").click()
    chooser.find("virt-manager", "label").click()
    chooser.find("COPYING").click()
    app.rawinput.pressKey("Enter")
    lib.utils.check(lambda: not chooser.showing)
    usbwin.find("Close", "push button").click()

    # Test fake guest resize behavior
    def _click_auto():
        vmenu = win.find("^View$", "menu")
        vmenu.click()
        smenu = vmenu.find("Scale Display", "menu")
        smenu.point()
        smenu.find("Auto resize VM", "check menu item").click()
    _click_auto()
    win.click_title()
    win.window_maximize()
    _click_auto()
    win.click_title()
    win.click_title()


@_vm_wrapper("uitests-vnc-standard")
def testVNCSpecific(app, dom):
    from gi.repository import GtkVnc
    if not hasattr(GtkVnc.Display, "set_allow_resize"):
        pytest.skip("GtkVnc is too old")

    ignore = dom
    win = app.topwin
    con = win.find("console-gfx-viewport")
    lib.utils.check(lambda: con.showing)

    # Test guest resize behavior
    def _click_auto():
        vmenu = win.find("^View$", "menu")
        vmenu.click()
        smenu = vmenu.find("Scale Display", "menu")
        smenu.point()
        smenu.find("Auto resize VM", "check menu item").click()
    _click_auto()
    win.click_title()
    win.window_maximize()
    _click_auto()
    win.click_title()
    win.click_title()


def _testLiveHotplug(app, fname):
    win = app.topwin
    win.find("Details", "radio button").click()

    # Add a scsi disk, importing the passed path
    win.find("add-hardware", "push button").click()
    addhw = app.find_window("Add New Virtual Hardware")
    addhw.find("Storage", "table cell").click()
    tab = addhw.find("storage-tab", None)
    lib.utils.check(lambda: tab.showing)
    tab.find("Select or create", "radio button").click()
    tab.find("storage-entry").set_text(fname)
    tab.combo_select("Bus type:", "SCSI")
    addhw.find("Finish", "push button").click()

    # Verify permission dialog pops up, ask to change
    app.click_alert_button(
            "The emulator may not have search permissions", "Yes")

    # Verify no errors
    lib.utils.check(lambda: not addhw.showing)
    lib.utils.check(lambda: win.active)

    # Hot unplug the disk
    win.find("SCSI Disk 1", "table cell").click()
    tab = win.find("disk-tab", None)
    lib.utils.check(lambda: tab.showing)
    win.find("config-remove").click()
    delete = app.find_window("Remove Disk")
    delete.find_fuzzy("Delete", "button").click()
    lib.utils.check(lambda: not delete.active)
    lib.utils.check(lambda: os.path.exists(fname))

    # Change CDROM
    win.find("IDE CDROM 1", "table cell").click()
    tab = win.find("disk-tab", None)
    entry = win.find("media-entry")
    appl = win.find("config-apply")
    lib.utils.check(lambda: tab.showing)
    entry.set_text(fname)
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    lib.utils.check(lambda: entry.text == fname)
    entry.click_secondary_icon()
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    lib.utils.check(lambda: not entry.text)


@_vm_wrapper("uitests-hotplug")
def testLiveHotplug(app, dom):
    """
    Live test for basic hotplugging and media change, as well as
    testing our auto-poolify magic
    """
    ignore = dom
    import tempfile
    tmpdir = tempfile.TemporaryDirectory(prefix="uitests-tmp")
    dname = tmpdir.name
    try:
        fname = os.path.join(dname, "test.img")
        os.system("qemu-img create -f qcow2 %s 1M > /dev/null" % fname)
        os.system("chmod 700 %s" % dname)
        _testLiveHotplug(app, fname)
    finally:
        poolname = os.path.basename(dname)
        try:
            pool = app.conn.storagePoolLookupByName(poolname)
            pool.destroy()
            pool.undefine()
        except Exception:
            log.debug("Error cleaning up pool", exc_info=True)


@_vm_wrapper("uitests-firmware-efi")
def testFirmwareRename(app, dom):
    from virtinst import cli, DeviceDisk
    win = app.topwin
    dom.destroy()

    # First we refresh the 'nvram' pool, so we can reliably
    # check if nvram files are created/deleted as expected
    conn = cli.getConnection(app.conn.getURI())
    origname = dom.name()
    nvramdir = conn.get_libvirt_data_root_dir() + "/qemu/nvram"

    fakedisk = DeviceDisk(conn)
    fakedisk.set_source_path(nvramdir + "/FAKE-UITEST-FILE")
    nvram_pool = fakedisk.get_parent_pool()
    nvram_pool.refresh()

    origpath = "%s/%s_VARS.fd" % (nvramdir, origname)
    newname = "uitests-firmware-efi-renamed"
    newpath = "%s/%s_VARS.fd" % (nvramdir, newname)
    assert DeviceDisk.path_definitely_exists(app.conn, origpath)
    assert not DeviceDisk.path_definitely_exists(app.conn, newpath)

    # Now do the actual UI clickage
    win.find("Details", "radio button").click()
    win.find("Hypervisor Details", "label")
    win.find("Overview", "table cell").click()

    newname = "uitests-firmware-efi-renamed"
    win.find("Name:", "text").set_text(newname)
    appl = win.find("config-apply")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)

    # Confirm window was updated
    app.find_window("%s on" % newname)

    # Confirm nvram paths were altered as expected
    assert not DeviceDisk.path_definitely_exists(app.conn, origpath)
    assert DeviceDisk.path_definitely_exists(app.conn, newpath)
