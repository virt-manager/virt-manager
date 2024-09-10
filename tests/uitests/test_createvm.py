# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import unittest.mock

import tests
from . import lib


###################
# Private helpers #
###################

def _open_newvm(app):
    button = app.root.find("New", "push button")
    # Launching the dialog can be very flakey without this explicit
    # point() call, not sure why
    button.point()
    button.click()
    return app.find_window("New VM")


def _nav(newvm, forward, back, check):
    pagenumlabel = newvm.find("pagenum-label")
    oldtext = pagenumlabel.text
    ignore = back

    # Clicking is tough to manage, because when clicking
    # rapidly in succession the create wizard has a few
    # cases of stealing focus to better help the user
    # navigate the wizard, but this is very racy and
    # tough to deal with hear. Luckily accelerators
    # don't care too much about focus
    if forward:
        button = newvm.find("Forward", "push button")
        combo = "<alt>f"
    else:
        button = newvm.find("Back", "push button")
        combo = "<alt>b"

    button.check_onscreen()
    button.keyCombo(combo)
    if check:
        lib.utils.check(lambda: pagenumlabel.text != oldtext)


def _forward(newvm, check=True):
    _nav(newvm, forward=True, back=False, check=check)


def _back(newvm, check=True):
    _nav(newvm, forward=False, back=True, check=check)


############################################
# UI tests for virt-manager's NewVM wizard #
############################################

def testNewVMMultiConnection(app):
    """
    Test the wizard's multiple connection handling
    """
    manager = app.topwin

    # Check the dialog shows 'no connection' error
    app.sleep(1)  # give some time for the connection to connect
    manager.grab_focus()
    app.manager_conn_disconnect("test testdriver.xml")
    newvm = _open_newvm(app)
    newvm.find_fuzzy("No active connection to install on")
    newvm.window_close()
    lib.utils.check(lambda: manager.active)

    # Check the xen PV only startup warning
    def _capsopt(fname):
        capsdir = tests.utils.DATADIR + "/capabilities/"
        return ",caps=" + capsdir + fname

    def _add_conn(uri):
        return app.manager_createconn(uri)

    # Test empty qemu connection
    _add_conn(tests.utils.URIs.kvm_x86 + _capsopt("test-empty.xml"))
    newvm = _open_newvm(app)
    newvm.find(".*No hypervisor options were found.*KVM kernel modules.*")
    newvm.window_close()
    app.manager_conn_disconnect("QEMU/KVM")

    _add_conn(tests.utils.URIs.kvm_x86_session +
            _capsopt("test-qemu-no-kvm.xml"))
    newvm = _open_newvm(app)
    newvm.find(".*KVM is not available.*")
    newvm.window_close()

    _add_conn(tests.utils.URIs.lxc)
    _add_conn(tests.utils.URIs.test_full)
    _add_conn(tests.utils.URIs.test_default)

    # Open the new VM wizard, select a connection
    newvm = _open_newvm(app)
    newvm.combo_select("create-conn", ".*testdriver.xml.*")
    _forward(newvm)

    # Verify media-combo contents for testdriver.xml
    cdrom = newvm.find("media-combo")
    entry = newvm.find("media-entry")
    cdrom.click_combo_entry()
    cdrom.find_fuzzy(r"\(/dev/sr1\)")
    entry.click()
    # Launch this so we can verify storage browser is reset too
    newvm.find_fuzzy("install-iso-browse", "button").click()
    app.select_storagebrowser_volume("pool-dir", "iso-vol")
    newvm.find_fuzzy("Automatically detect", "check").click()
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)

    # Back up, select test:///default, verify media-combo is now empty
    newvm.window_close()
    newvm = _open_newvm(app)
    newvm.combo_select("create-conn", ".*test default.*")
    _forward(newvm)
    cdrom.click_combo_entry()
    lib.utils.check(lambda: "/dev/sr1" not in cdrom.fmt_nodes())
    app.rawinput.pressKey("Escape")
    newvm.find_fuzzy("install-iso-browse", "button").click()
    browsewin = app.root.find("vmm-storage-browser")
    lib.utils.check(lambda: "pool-logical" not in browsewin.fmt_nodes())


def testNewVMManualDefault(app):
    """
    Click through the New VM wizard with default values + manual, then
    delete the VM
    """
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Manual", "radio").click()
    _forward(newvm)
    osentry = newvm.find("oslist-entry")
    lib.utils.check(lambda: not osentry.text)

    # Make sure we throw an error if no OS selected
    _forward(newvm, check=False)
    app.click_alert_button("You must select", "OK")

    # Test activating the osentry to grab the popover selection
    osentry.click()
    osentry.typeText("generic")
    newvm.find("oslist-popover")
    osentry.click()
    app.rawinput.pressKey("Enter")
    lib.utils.check(lambda: "Generic" in osentry.text)

    # Verify back+forward still keeps Generic selected
    _back(newvm)
    _forward(newvm)
    lib.utils.check(lambda: "Generic" in osentry.text)
    osentry.check_onscreen()
    _forward(newvm)
    _forward(newvm)
    _forward(newvm)


    # Empty triggers a specific codepath
    newvm.find_fuzzy("Name", "text").set_text("")
    # Name collision failure
    newvm.find_fuzzy("Name", "text").set_text("test-many-devices")
    newvm.find_fuzzy("Finish", "button").click()
    app.click_alert_button("in use", "OK")
    newvm.find_fuzzy("Name", "text").set_text("vm1")
    newvm.find_fuzzy("Finish", "button").click()

    # Delete it from the VM window
    vmwindow = app.find_details_window("vm1")
    vmwindow.find("Virtual Machine", "menu").click()
    vmwindow.find("Delete", "menu item").click()

    delete = app.find_window("Delete")
    delete.find_fuzzy("Delete", "button").click()
    app.click_alert_button("Are you sure", "Yes")

    # Verify delete dialog and VM dialog are now gone
    lib.utils.check(lambda: vmwindow.showing is False)


def testNewVMStorage(app):
    """
    Test some storage specific paths
    """
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Manual", "radio").click()
    _forward(newvm)
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)

    # qcow2 default shouldn't trigger size error
    sizetext = newvm.find(None, "spin button", "GiB")
    sizetext.set_text("10000000")
    _forward(newvm)
    _back(newvm)

    # Use the storage browser to select a local file
    storagetext = newvm.find("storage-entry")
    newvm.find_fuzzy("Select or create", "radio").click()
    newvm.find("storage-browse").click()
    browse = app.root.find("vmm-storage-browser")
    browse.find("Browse Local", "push button").click()
    chooser = app.root.find(
            "Locate existing storage", "file chooser")
    fname = "COPYING"
    chooser.find(fname, "table cell").click()
    chooser.find("Open", "push button").click()
    lib.utils.check(lambda: newvm.active)
    lib.utils.check(lambda: "COPYING" in storagetext.text)

    # Start the install
    _forward(newvm)
    newvm.find("Finish", "push button").click()
    app.find_details_window("vm1")
    lib.utils.check(lambda: not newvm.showing)



def testNewVMCDROMRegular(app):
    """
    Create a new CDROM VM, choosing distro win8, and do some basic
    'Customize before install' before exiting
    """
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Local install media", "radio").click()
    _forward(newvm)

    # check prepopulated cdrom media
    combo = newvm.find("media-combo")
    combo.click_combo_entry()
    combo.find(r"No media detected \(/dev/sr1\)")
    combo.find(r"Fedora12_media \(/dev/sr0\)").click()

    # Catch validation error
    entry = newvm.find("media-entry")
    lib.utils.check(lambda: "/dev/sr0" in entry.text)
    entry.click()
    entry.set_text("")
    # Something about entry.set_text is flakey with focus,
    # this stuff is to try and fix focus
    app.rawinput.pressKey("Escape")
    newvm.click_title()
    _forward(newvm, check=False)
    app.click_alert_button("media selection is required", "OK")

    # test entry activation too
    entry.click()
    entry.set_text("/dev/sr0")
    app.rawinput.pressKey("Enter")

    # Select a fake iso
    newvm.find_fuzzy("install-iso-browse", "button").click()
    app.select_storagebrowser_volume("pool-dir", "iso-vol")

    osentry = newvm.find("oslist-entry")
    lib.utils.check(lambda: osentry.text == "None detected")

    # Change distro to win8
    newvm.find_fuzzy("Automatically detect", "check").click()
    osentry.click()
    osentry.set_text("windows 8")
    popover = newvm.find("oslist-popover")
    popover.check_onscreen()
    # Verify Escape resets the text entry
    app.rawinput.pressKey("Escape")
    popover.check_not_onscreen()
    lib.utils.check(lambda: osentry.text == "")
    # Re-enter text
    osentry.set_text("windows 8")
    popover.check_onscreen()
    popover.find_fuzzy("include-eol").click()
    popover.find_fuzzy(r"\(win8\)").click()
    popover.check_not_onscreen()
    foundtext = osentry.text
    # Start typing again, and exit, make sure it resets to previous entry
    osentry.click()
    osentry.set_text("foo")
    popover.check_onscreen()
    app.rawinput.pressKey("Escape")
    popover.check_not_onscreen()
    lib.utils.check(lambda: osentry.text == foundtext)
    _forward(newvm)

    # Verify that CPU values are non-default
    cpus = newvm.find("cpus", "spin button")
    lib.utils.check(lambda: int(cpus.text) > 1, timeout=5)
    _forward(newvm)
    _forward(newvm)

    # Select customize wizard
    newvm.find_fuzzy("Customize", "check").click()
    newvm.find_fuzzy("Finish", "button").click()

    # Verify CDROM media is inserted
    vmwindow = app.find_details_window("win8")
    vmwindow.find_fuzzy("IDE CDROM", "table cell").click()
    mediaent = vmwindow.find("media-entry")
    lib.utils.check(lambda: "iso-vol" in mediaent.text)

    # Change boot autostart
    vmwindow.find_fuzzy("Boot", "table cell").click()
    vmwindow.find_fuzzy("Start virtual machine", "check").click()
    vmwindow.find_fuzzy("config-apply").click()

    # Change to 'copy host CPU'
    vmwindow.find_fuzzy("CPUs", "table cell").click()
    cpucheck = vmwindow.find_fuzzy("Copy host", "check")
    cpucheck.click()
    vmwindow.find_fuzzy("config-apply").click()
    lib.utils.check(lambda: "host-passthrough" in cpucheck.name)

    # Add a default disk
    vmwindow.find("add-hardware", "push button").click()
    addhw = app.find_window("Add New Virtual Hardware")
    addhw.find("Finish", "push button").click()
    lib.utils.check(lambda: vmwindow.active)

    # Select the new disk, change the bus to USB
    vmwindow.find_fuzzy("IDE Disk 2", "table cell").click()
    appl = vmwindow.find("config-apply", "push button")
    hwlist = vmwindow.find("hw-list")
    tab = vmwindow.find("disk-tab")
    tab.find("Disk bus:", "text").set_text("usb")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    # Device is now 'USB Disk 1'
    c = hwlist.find("USB Disk 1", "table cell")
    lib.utils.check(lambda: c.state_selected)
    tab.find("Advanced options", "toggle button").click_expander()
    tab.find("Removable:", "check box").click()
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)

    # Change NIC mac
    vmwindow.find_fuzzy("NIC", "table cell").click()
    tab = vmwindow.find("network-tab")
    tab.find("mac-entry", "text").set_text("00:11:00:11:00:11")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)

    # Start the install, close via the VM window
    vmwindow.find_fuzzy("Begin Installation", "button").click()
    lib.utils.check(lambda: newvm.showing is False)
    vmwindow = app.find_details_window("win8")
    vmwindow.find_fuzzy("File", "menu").click()
    vmwindow.find_fuzzy("Quit", "menu item").click()
    lib.utils.check(lambda: app.is_running())


def testNewVMCDROMDetect(app):
    """
    CDROM with detection
    """
    cdrom = tests.utils.DATADIR + "/fakemedia/fake-win7.iso"
    newvm = _open_newvm(app)
    newvm.find_fuzzy("Local install media", "radio").click()
    _forward(newvm)
    newvm.find("media-entry").click()
    newvm.find("media-entry").set_text(cdrom)
    # Use forward to trigger detection
    _forward(newvm)
    _forward(newvm)
    _forward(newvm)
    newvm.find("Finish", "push button").click()
    app.find_details_window("win7")
    lib.utils.check(lambda: not newvm.showing)



def testNewVMURL(app):
    """
    New VM with URL and distro detection, plus having fun with
    the storage browser and network selection.
    """
    # Also test default UEFI from prefs
    app.open(keyfile="uefi.ini", uri=tests.utils.URIs.kvm_x86)
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Network Install", "radio").click()
    _forward(newvm)
    osentry = newvm.find("oslist-entry")
    lib.utils.check(lambda: osentry.text.startswith("Waiting"))

    newvm.find("install-url-entry").set_text("")
    _forward(newvm, check=False)
    app.click_alert_button("tree is required", "OK")

    url = "https://archives.fedoraproject.org/pub/archive/fedora/linux/releases/10/Fedora/x86_64/os/"
    oslabel = "Fedora 10"
    newvm.find("install-url-entry").set_text(url)
    newvm.find("install-url-entry").click()
    app.rawinput.pressKey("Enter")
    newvm.find("install-urlopts-expander").click_expander()
    newvm.find("install-urlopts-entry").set_text("foo=bar")

    lib.utils.check(lambda: osentry.text == oslabel, timeout=10)

    # Move forward, then back, ensure OS stays selected
    _forward(newvm)
    _back(newvm)
    lib.utils.check(lambda: osentry.text == oslabel)

    # Disable autodetect, make sure OS still selected
    newvm.find_fuzzy("Automatically detect", "check").click()
    lib.utils.check(lambda: osentry.text == oslabel)
    _forward(newvm)
    _back(newvm)

    # Ensure the EOL field was selected
    osentry.click()
    app.rawinput.pressKey("Down")
    popover = newvm.find("oslist-popover")
    lib.utils.check(lambda: popover.showing)
    includeeol = newvm.find("include-eol", "check")
    lib.utils.check(lambda: includeeol.isChecked)

    # Re-enable autodetect, check for detecting text
    newvm.find_fuzzy("Automatically detect", "check").click()
    lib.utils.check(lambda: not popover.showing)
    lib.utils.check(lambda: "Detecting" in osentry.text)
    lib.utils.check(lambda: osentry.text == oslabel, timeout=10)

    # Progress the install
    _forward(newvm)
    _forward(newvm)
    _forward(newvm)
    newvm.find_fuzzy("Finish", "button").click()

    progress = app.find_window("Creating Virtual Machine")
    lib.utils.check(lambda: not progress.showing, timeout=120)

    details = app.find_details_window("fedora10")
    lib.utils.check(lambda: not newvm.showing)

    # Re-run the newvm wizard, check that URL was remembered
    details.window_close()
    newvm = _open_newvm(app)
    newvm.find_fuzzy("Network Install", "radio").click()
    _forward(newvm)
    urlcombo = newvm.find("install-url-combo")
    lib.utils.check(lambda: urlcombo.showing)
    lib.utils.check(lambda: url in urlcombo.fmt_nodes())


def testNewKVMQ35Tweaks(app):
    """
    New VM that should default to Q35, but tweak things a bunch
    """
    app.uri = tests.utils.URIs.kvm_x86
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Import", "radio").click()
    _forward(newvm)
    newvm.find("import-entry").set_text("/pool-dir/testvol1.img")
    newvm.find("oslist-entry").set_text("fribfrob")
    popover = newvm.find("oslist-popover")
    popover.find_fuzzy("linux2020").click()
    _forward(newvm)
    _forward(newvm)

    # Select customize wizard, we will use this VM to
    # hit some code paths elsewhere
    newvm.find_fuzzy("Customize", "check").click()
    newvm.find_fuzzy("Finish", "button").click()
    vmname = "linux2020"
    details = app.find_details_window(vmname)
    appl = details.find("config-apply")

    # Tweak some Overview settings
    details.combo_check_default("Chipset:", "Q35")
    details.combo_check_default("Firmware:", "BIOS")

    # Unchanged machine
    details.combo_select("Chipset:", "i440FX")
    details.combo_select("Chipset:", "Q35")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    # Switch i440FX
    details.combo_select("Chipset:", "i440FX")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    # Switch back to Q35
    details.combo_select("Chipset:", "Q35")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    # Switch to UEFI, back to BIOS, back to UEFI
    details.combo_select("Firmware:", ".*x86_64.*")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    # Switch back to BIOS
    details.combo_select("Firmware:", "BIOS")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    # Switch back to UEFI
    details.combo_select("Firmware:", ".*x86_64.*")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)

    # Verify host-passthrough selected
    details.find_fuzzy("CPUs", "table cell").click()
    cpucheck = details.find_fuzzy("Copy host", "check")
    assert "host-passthrough" in cpucheck.name
    new_xml = lib.utils.get_xmleditor_xml(app, details)
    assert "host-passthrough" in new_xml

    # Add another network device
    details.find("add-hardware", "push button").click()
    addhw = app.find_window("Add New Virtual Hardware")
    addhw.find("Network", "table cell").click()
    tab = addhw.find("network-tab", None)
    lib.utils.check(lambda: tab.showing)
    addhw.find("Finish", "push button").click()
    lib.utils.check(lambda: not addhw.active)
    lib.utils.check(lambda: details.active)

    # Finish
    details.find_fuzzy("Begin Installation", "button").click()
    lib.utils.check(lambda: details.dead)
    app.find_details_window(vmname)


def testNewKVMQ35UEFI(app):
    """
    New VM that should default to Q35, and set UEFI
    """
    app.uri = tests.utils.URIs.kvm_x86
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Import", "radio").click()
    _forward(newvm)
    newvm.find("import-entry").set_text("/pool-dir/testvol1.img")
    newvm.find("oslist-entry").set_text("fedora30")
    popover = newvm.find("oslist-popover")
    popover.find("include-eol").click()
    popover.find_fuzzy("Fedora 30").click()
    _forward(newvm)
    _forward(newvm)

    # Select customize wizard, we will use this VM to
    # hit some PPC64 code paths elsewhere
    newvm.find_fuzzy("Customize", "check").click()
    newvm.find_fuzzy("Finish", "button").click()
    vmname = "fedora30"
    details = app.find_details_window(vmname)

    # Change to UEFI
    details.combo_check_default("Chipset:", "Q35")
    details.combo_check_default("Firmware:", "BIOS")
    details.combo_select("Firmware:", "UEFI")
    details.find("config-apply").click()
    new_xml = lib.utils.get_xmleditor_xml(app, details)
    assert "os firmware=\"efi\"" in new_xml

    # Finish
    details.find_fuzzy("Begin Installation", "button").click()
    lib.utils.check(lambda: details.dead)
    app.find_details_window(vmname)


def testNewPPC64(app):
    """
    New PPC64 VM to test architecture selection
    """
    app.uri = tests.utils.URIs.kvm_x86
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Architecture options", "toggle").click()
    newvm.combo_select("Architecture", ".*ppc64.*")
    newvm.combo_check_default("Machine Type", ".*pseries.*")

    newvm.find_fuzzy("Manual", "radio").click()
    _forward(newvm)
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)
    # Disable storage, we add some via customize
    newvm.find_fuzzy("Enable storage", "check box").click()
    _forward(newvm)

    # Select customize wizard, we will use this VM to
    # hit some PPC64 code paths elsewhere
    newvm.find_fuzzy("Customize", "check").click()
    newvm.find_fuzzy("Finish", "button").click()
    details = app.find_details_window("vm-ppc64")

    tab = details.find("overview-tab")
    tab.combo_check_default("machine-combo", "pseries")
    tab.combo_select("machine-combo", "pseries-2.1")
    appl = details.find("config-apply")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)

    # Add a TPM SPAPR device
    details.find("add-hardware", "push button").click()
    addhw = app.find_window("Add New Virtual Hardware")
    addhw.find("TPM", "table cell").click()
    tab = addhw.find("tpm-tab", None)
    lib.utils.check(lambda: tab.showing)
    addhw.find("Finish", "push button").click()
    lib.utils.check(lambda: not addhw.active)
    lib.utils.check(lambda: details.active)

    # Add a SCSI disk which also adds virtio-scsi controller
    details.find("add-hardware", "push button").click()
    addhw = app.find_window("Add New Virtual Hardware")
    addhw.find("Storage", "table cell").click()
    tab = addhw.find("storage-tab", None)
    lib.utils.check(lambda: tab.showing)
    tab.combo_select("Bus type:", "SCSI")
    addhw.find("Finish", "push button").click()
    lib.utils.check(lambda: not addhw.active)
    lib.utils.check(lambda: details.active)

    # Finish
    details.find_fuzzy("Begin Installation", "button").click()
    lib.utils.check(lambda: details.dead)
    app.find_details_window("vm-ppc64")


def testNewVMAArch64UEFI(app):
    """
    Test aarch64 UEFI usage
    """
    app.uri = tests.utils.URIs.kvm_aarch64
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Local install media", "radio").click()
    _forward(newvm)

    newvm.find_fuzzy("Automatically detect", "check").click()
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    newvm.find("media-entry").set_text("/pool-dir/testvol1.img")
    _forward(newvm)
    _forward(newvm)
    # Disable storage, this triggers a livecd code path in createvm.py
    newvm.find_fuzzy("Enable storage", "check box").click()
    _forward(newvm)
    newvm.find_fuzzy("Finish", "button").click()

    app.find_details_window("vm1")
    lib.utils.check(lambda: not newvm.showing)


def testNewVMArmKernel(app):
    """
    New arm VM that requires kernel/initrd/dtb
    """
    app.uri = tests.utils.URIs.kvm_armv7l_nodomcaps
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Architecture options", "toggle").click_expander()
    newvm.find_fuzzy("Virt Type", "combo").click()
    KVM = newvm.find_fuzzy("KVM", "menu item")
    TCG = newvm.find_fuzzy("TCG", "menu item")
    lib.utils.check(lambda: KVM.selected)
    lib.utils.check(lambda: TCG.showing)
    app.rawinput.pressKey("Esc")

    # Validate some initial defaults
    local = newvm.find_fuzzy("Local", "radio")
    lib.utils.check(lambda: not local.sensitive)
    newvm.find_fuzzy("Machine Type", "combo").click()
    newvm.find_fuzzy("canon", "menu item").click()
    newvm.find_fuzzy("Machine Type", "combo").click()
    newvm.find("virt", "menu item").click()
    importradio = newvm.find("Import", "radio")
    importradio.click()
    lib.utils.check(lambda: importradio.checked)
    _forward(newvm)

    newvm.find("import-entry").set_text("/pool-dir/default-vol")
    # Make sure the info box shows up
    newvm.find("Kernel/initrd settings can be configured")
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm, check=False)

    # Disk collision box pops up, hit ok
    app.click_alert_button("in use", "Yes")

    _forward(newvm)
    newvm.find_fuzzy("Finish", "button").click()

    lib.utils.check(lambda: not newvm.showing)
    app.find_details_window("vm1")



def testNewVMContainerApp(app):
    """
    Simple LXC app install
    """
    app.uri = tests.utils.URIs.lxc

    newvm = _open_newvm(app)
    newvm.find_fuzzy("Application", "radio").click()
    _forward(newvm)

    # Set custom init
    apptext = newvm.find_fuzzy(None, "text", "application path")
    apptext.set_text("")
    _forward(newvm, check=False)
    app.click_alert_button("path is required", "OK")
    newvm.find("install-app-browse").click()
    app.select_storagebrowser_volume("pool-dir", "aaa-unused.qcow2")
    lib.utils.check(lambda: "aaa-unused.qcow2" in apptext.text)

    _forward(newvm)
    _forward(newvm)
    # Trigger back, to ensure disk page skipping works
    _back(newvm)
    _back(newvm)
    _forward(newvm)
    _forward(newvm)

    # Select customize wizard, we will use this VM to hit specific
    # code paths
    newvm.find_fuzzy("Customize", "check").click()
    newvm.find_fuzzy("Finish", "button").click()
    vmname = "container1"
    details = app.find_details_window(vmname)

    # Tweak init values
    details.find("Boot Options", "table cell").click()
    tab = details.find("boot-tab")
    tab.find("Init path:", "text").set_text("")
    tab.find("Init args:", "text").set_text("some args")
    appl = details.find("config-apply")
    appl.click()
    app.click_alert_button("init path must be specified", "OK")
    lib.utils.check(lambda: appl.sensitive)
    tab.find("Init path:", "text").set_text("/some/path")
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)

    # Check that addhw container options are disabled
    details.find("add-hardware", "push button").click()
    addhw = app.find_window("Add New Virtual Hardware")
    addhw.find("PCI Host Device", "table cell").click()
    # Ensure the error label is showing
    label = addhw.find("Not supported for containers")
    label.check_onscreen()
    addhw.find("Cancel", "push button").click()
    lib.utils.check(lambda: not addhw.active)
    lib.utils.check(lambda: details.active)

    # Finish
    details.find_fuzzy("Begin Installation", "button").click()
    lib.utils.check(lambda: not newvm.showing)
    app.find_details_window(vmname)


def testNewVMCustomizeCancel(app):
    """
    Test cancelling out of the customize wizard
    """
    newvm = _open_newvm(app)
    newvm.find_fuzzy("Manual", "radio").click()
    _forward(newvm)
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)
    _forward(newvm)

    newvm.find_fuzzy("Customize", "check").click()
    newvm.find_fuzzy("Finish", "button").click()
    vmname = "vm1"
    details = app.find_details_window(vmname)

    details.find("Cancel Installation", "push button").click()
    app.click_alert_button("abort the installation", "No")
    lib.utils.check(lambda: details.active)
    details.find("Cancel Installation", "push button").click()
    app.click_alert_button("abort the installation", "Yes")
    lib.utils.check(lambda: not details.active)
    lib.utils.check(lambda: not newvm.active)


def testNewVMCustomizeMisc(app):
    """
    Some specific customize logic paths
    """
    app.open(keyfile="rawdefault.ini")
    newvm = _open_newvm(app)
    newvm.find_fuzzy("Manual", "radio").click()
    _forward(newvm)
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)

    # Raw default will be non-sparse, should trigger size error
    sizetext = newvm.find(None, "spin button", "GiB")
    sizetext.set_text("10000000")
    _forward(newvm, check=False)
    app.click_alert_button("Storage parameter error", "OK")
    sizetext.set_text("1")

    _forward(newvm)

    newvm.find_fuzzy("Customize", "check").click()
    newvm.find_fuzzy("Finish", "button").click()
    vmname = "vm1"
    details = app.find_details_window(vmname)

    # Test name change
    tab = details.find("overview-tab")
    nametext = tab.find("Name:", "text")
    nametext.set_text("foonewname")
    details.find("config-apply").click()
    app.find_details_window("foonewname")

    # Trigger XML failure to hit some codepaths
    nametext.set_text("")
    details.find("Begin Installation").click()
    app.click_alert_button("unapplied changes", "Yes")
    app.click_alert_button("name must be specified", "Close")
    lib.utils.check(lambda: details.showing)

    # Discard XML change and continue with install
    details.find("Begin Installation").click()
    app.click_alert_button("unapplied changes", "No")
    lib.utils.check(lambda: not details.showing)
    lib.utils.check(lambda: not newvm.showing)
    app.find_details_window("foonewname")



def testNewVMContainerTree(app):
    """
    Simple LXC tree install
    """
    app.uri = tests.utils.URIs.lxc

    newvm = _open_newvm(app)
    newvm.find_fuzzy("Operating system", "radio").click()
    _forward(newvm)

    # Set directory path
    dirtext = newvm.find_fuzzy(None, "text", "root directory")
    dirtext.set_text("")
    _forward(newvm, check=False)
    app.click_alert_button("path is required", "OK")

    newvm.find("install-oscontainer-browse").click()
    app.select_storagebrowser_volume("pool-dir", "dir-vol")
    lib.utils.check(lambda: "dir-vol" in dirtext.text)

    _forward(newvm)
    _forward(newvm)
    newvm.find_fuzzy("Finish", "button").click()

    lib.utils.check(lambda: not newvm.showing)
    app.find_details_window("container1")



def testNewVMContainerVZ(app):
    """
    Virtuozzo container install
    """
    app.uri = tests.utils.URIs.vz

    newvm = _open_newvm(app)
    newvm.find_fuzzy("Container", "radio").click()
    newvm.find_fuzzy("Virtual machine", "radio").click()
    newvm.find_fuzzy("Container", "radio").click()
    _forward(newvm)

    # Set directory path
    templatetext = newvm.find_fuzzy(None, "text", "container template")
    templatetext.set_text("")
    _forward(newvm, check=False)
    app.click_alert_button("template name is required", "OK")
    templatetext.set_text("centos-6-x86_64")
    _forward(newvm)
    _forward(newvm)
    newvm.find_fuzzy("Finish", "button").click()

    app.find_details_window("container1")
    lib.utils.check(lambda: not newvm.showing)



def testNewVMContainerBootstrap(app):
    app.open(uri=tests.utils.URIs.lxc,
            extra_opts=["--test-options=fake-virtbootstrap"])

    newvm = _open_newvm(app)
    newvm.find_fuzzy("Operating system", "radio").click()
    _forward(newvm)

    # Set directory path
    import tempfile
    tmpdir = tempfile.TemporaryDirectory()
    newvm.find_fuzzy("Create OS directory", "check box").click()

    uritext = newvm.find("install-oscontainer-source-uri")
    uritext.text = ""
    _forward(newvm, check=False)
    app.click_alert_button("Source URL is required", "OK")
    uritext.text = "docker://alpine"

    rootdir = newvm.find_fuzzy(None, "text", "root directory")
    lib.utils.check(lambda: ".local/share/libvirt" in rootdir.text)
    rootdir.set_text("/dev/null")
    _forward(newvm, check=False)
    app.click_alert_button("not directory", "OK")
    rootdir.set_text("/root")
    _forward(newvm, check=False)
    app.click_alert_button("No write permissions", "OK")
    rootdir.set_text("/tmp")
    _forward(newvm, check=False)
    app.click_alert_button("directory is not empty", "No")
    rootdir.set_text(tmpdir.name)
    newvm.find("install-oscontainer-root-passwd").set_text("foobar")
    # Invalid credentials to trigger failure
    newvm.find("Credentials", "toggle button").click_expander()
    newvm.find("bootstrap-registry-user").set_text("foo")
    _forward(newvm, check=None)
    app.click_alert_button("Please specify password", "OK")
    newvm.find("bootstrap-registry-password").set_text("bar")

    _forward(newvm)
    _forward(newvm)
    newvm.find_fuzzy("Finish", "button").click()
    app.click_alert_button("virt-bootstrap did not complete", "Close")
    _back(newvm)
    _back(newvm)
    newvm.find("bootstrap-registry-user").set_text("")
    newvm.find("bootstrap-registry-password").set_text("")

    _forward(newvm)
    _forward(newvm)
    newvm.find_fuzzy("Finish", "button").click()
    prog = app.find_window("Creating Virtual Machine")
    lib.utils.check(lambda: not prog.showing, timeout=30)

    lib.utils.check(lambda: not newvm.showing)
    app.find_details_window("container1")



def testNewVMXenPV(app):
    """
    Test the create wizard with a fake xen PV install
    """
    app.uri = tests.utils.URIs.xen
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Architecture options", "toggle").click()
    newvm.combo_select("Xen Type", ".*paravirt.*")

    newvm.find_fuzzy("Import", "radio").click()
    _forward(newvm)
    newvm.find("import-entry").set_text("/pool-dir/testvol1.img")
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)
    newvm.find_fuzzy("Finish", "button").click()

    app.find_details_window("vm1")
    lib.utils.check(lambda: not newvm.showing)



def testNewVMInstallFail(app):
    def dofail():
        _newvm = _open_newvm(app)
        _newvm.find_fuzzy("Manual", "radio").click()
        _forward(_newvm)
        _newvm.find("oslist-entry").set_text("generic")
        _newvm.find("oslist-popover").find_fuzzy("generic").click()
        _forward(_newvm)
        _forward(_newvm)
        _forward(_newvm)

        # '/' in name will trigger libvirt error
        _newvm.find_fuzzy("Name", "text").set_text("test/bad")
        _newvm.find_fuzzy("Finish", "button").click()
        app.click_alert_button("Unable to complete install", "Close")
        return _newvm

    newvm = dofail()
    pathlabel = newvm.find(".*test/bad.qcow2")
    generatedpath = pathlabel.text
    # Changing VM name should not generate a new path
    newvm.find_fuzzy("Name", "text").set_text("test/badfoo")
    lib.utils.check(lambda: pathlabel.text == generatedpath)
    newvm.find_fuzzy("Finish", "button").click()
    app.click_alert_button("Unable to complete install", "Close")
    # Closing dialog should trigger storage cleanup path
    newvm.find_fuzzy("Cancel", "button").click()
    lib.utils.check(lambda: not newvm.visible)

    # Run again
    newvm = dofail()
    _back(newvm)
    newvm.find_fuzzy("Select or create", "radio").click()

    newvm.find("storage-entry").set_text("/pool-dir/somenewvol1")
    _forward(newvm)
    newvm.find_fuzzy("Name", "text").set_text("test-foo")
    newvm.find_fuzzy("Finish", "button").click()

    app.find_details_window("test-foo")
    lib.utils.check(lambda: not newvm.showing)



def testNewVMCustomizeXMLEdit(app):
    """
    Test new VM with raw XML editing via customize wizard
    """
    app.open(xmleditor_enabled=True)
    newvm = _open_newvm(app)

    # Create a custom named VM, using CDROM media, and default storage
    vmname = "fooxmleditvm"
    newvm.find_fuzzy("Local install media", "radio").click()
    newvm.find_fuzzy("Forward", "button").click()
    nonexistpath = "/dev/foovmm-idontexist"
    existpath = "/pool-dir/testvol1.img"
    newvm.find("media-entry").set_text(nonexistpath)
    lib.utils.check(
            lambda: newvm.find("oslist-entry").text == "None detected")
    newvm.find_fuzzy("Automatically detect", "check").click()
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm, check=False)
    app.click_alert_button("Error setting installer", "OK")
    newvm.find("media-entry").set_text(existpath)
    _forward(newvm)
    _forward(newvm)
    _forward(newvm)
    newvm.find_fuzzy("Customize", "check").click()
    newvm.find_fuzzy("Name", "text").set_text(vmname)
    newvm.find_fuzzy("Finish", "button").click()
    win = app.find_details_window(vmname)
    xmleditor = win.find("XML editor")
    finish = win.find("config-apply")

    # Change a device setting with the XML editor
    win.find_fuzzy("IDE Disk 1", "table cell").click()
    tab = win.find("disk-tab")
    win.find("XML", "page tab").click()
    # Change the disk path via the XML editor
    fname = vmname + ".qcow2"
    lib.utils.check(lambda: fname in xmleditor.text)
    newx = xmleditor.text.replace(fname, "default-vol")
    xmleditor.set_text(newx)
    appl = win.find("config-apply")
    # This is kindof a bug, changing path in XML editor in Customize
    # doesn't take effect for storage with creation parameters, but
    # it's a pain to fix.
    appl.click()
    lib.utils.check(lambda: not appl.sensitive)
    lib.utils.check(lambda: vmname in xmleditor.text)

    # Change a VM setting and verify it
    win.find_fuzzy("Boot", "table cell").click()
    tab = win.find("boot-tab")
    bootmenu = tab.find("Enable boot menu", "check box")
    lib.utils.check(lambda: not bootmenu.checked)
    win.find("XML", "page tab").click()
    newtext = xmleditor.text.replace(
            "<os>", "<os><bootmenu enable='yes'/>")
    xmleditor.set_text(newtext)
    finish.click()
    win.find("Details", "page tab").click()
    lib.utils.check(lambda: bootmenu.checked)

    # Change a device setting with the XML editor
    win.find_fuzzy("NIC", "table cell").click()
    tab = win.find("network-tab")
    win.find("XML", "page tab").click()
    newbrname = "BRFAKE"
    newx = xmleditor.text.replace("network", "bridge")
    newx = newx.replace('bridge="default"', "bridge='%s'" % newbrname)
    xmleditor.set_text(newx)
    finish.click()

    # Finish install.
    win.find_fuzzy("Begin Installation", "button").click()
    lib.utils.check(lambda: win.dead)
    win = app.find_details_window(vmname)
    win.find("Details", "radio button").click()

    # Verify VM change stuck
    win.find_fuzzy("Boot", "table cell").click()
    tab = win.find("boot-tab")
    bootmenu = tab.find("Enable boot menu", "check box")
    lib.utils.check(lambda: bootmenu.checked)

    # Verify device change stuck
    win.find_fuzzy("NIC", "table cell").click()
    tab = win.find("network-tab")
    devname = tab.find("Device name:", "text")
    lib.utils.check(lambda: devname.text == newbrname)

    # Verify install media is handled correctly after XML customize
    win.find_fuzzy("IDE CDROM 1", "table cell").click()
    tab = win.find("disk-tab")
    mediaent = tab.find("media-entry")
    lib.utils.check(lambda: mediaent.text == existpath)
    win.find("Shut Down", "push button").click()
    run = win.find("Run", "push button")
    lib.utils.check(lambda: run.sensitive)
    lib.utils.check(lambda: mediaent.text == "")

    # Verify default disk storage was actually created. This has some
    # special handling in domain.py
    tab.find("Browse", "push button").click()
    browser = app.root.find("vmm-storage-browser")
    browser.find("%s.qcow2" % vmname, "table cell")


def testNewVMRemote(app):
    """
    Hit some is_remote code paths
    """
    app.uri = tests.utils.URIs.test_remote
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Import", "radio").click()
    _forward(newvm)
    importtext = newvm.find("import-entry")

    # Click forward, hitting missing Import path error
    _forward(newvm, check=False)
    app.click_alert_button("import is required", "OK")

    # Click forward, but Import path doesn't exist
    importtext.set_text("/pool-dir/idontexist")
    _forward(newvm, check=False)
    app.click_alert_button("import path must point", "OK")
    importtext.set_text("/pool-dir/default-vol")

    # Click forward, hitting missing OS error
    _forward(newvm, check=False)
    app.click_alert_button("select an OS", "OK")

    # Set OS
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()

    # Click forward, but Import path is in use, and exit
    _forward(newvm, check=False)
    app.click_alert_button("in use", "No")

    # storagebrowser bits
    newvm.find("install-import-browse").click()
    browsewin = app.root.find("vmm-storage-browser")
    # Insensitive for remote connection
    browselocal = browsewin.find("Browse Local")
    lib.utils.check(lambda: browselocal.sensitive is False)
    # Close the browser and reopen
    browsewin.find("Cancel").click()
    lib.utils.check(lambda: not browsewin.active)
    # Reopen, select storage
    newvm.find("install-import-browse").click()
    app.select_storagebrowser_volume("pool-dir", "bochs-vol")
    lib.utils.check(
            lambda: importtext.text == "/pool-dir/bochs-vol")

    _forward(newvm)
    _forward(newvm)

    newvm.find_fuzzy("Finish", "button").click()
    app.find_details_window("vm1")
    lib.utils.check(lambda: not newvm.showing)


def testNewVMSession(app):
    """
    Test with fake qemu session
    """
    app.uri = tests.utils.URIs.kvm_x86_session
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Import", "radio").click()
    _forward(newvm)
    newvm.find("import-entry").set_text("/pool-dir/testvol1.img")
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)
    newvm.combo_check_default("net-source", "Usermode")

    newvm.find_fuzzy("Finish", "button").click()
    details = app.find_details_window("vm1")
    lib.utils.check(lambda: not newvm.showing)
    details.window_close()

    # Ensure disconnecting will close the dialog
    newvm = _open_newvm(app)
    app.manager_test_conn_window_cleanup(".*session.*", newvm)


def testNewVMEmptyConn(app):
    """
    Test with an empty connection
    """
    app.uri = tests.utils.URIs.test_empty
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Import", "radio").click()
    _forward(newvm)
    newvm.find("import-entry").set_text(__file__)
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)
    newvm.combo_check_default("net-source", "Bridge")
    warnlabel = newvm.find_fuzzy("suitable default network", "label")
    warnlabel.check_onscreen()
    newvm.find("Device name:", "text").set_text("foobr0")

    # Select customize wizard, we will use this VM to hit specific
    # code paths
    newvm.find_fuzzy("Customize", "check").click()
    newvm.find_fuzzy("Finish", "button").click()
    vmname = "vm1"
    details = app.find_details_window(vmname)

    # Check that addhw hostdev drop down is empty
    details.find("add-hardware", "push button").click()
    addhw = app.find_window("Add New Virtual Hardware")
    addhw.find("USB Host Device", "table cell").click()
    tab = addhw.find("host-tab", None)
    lib.utils.check(lambda: tab.showing)
    cell = tab.find("No Devices", "table cell")
    lib.utils.check(lambda: cell.selected)
    addhw.find("Cancel", "push button").click()
    lib.utils.check(lambda: not addhw.active)
    lib.utils.check(lambda: details.active)

    # Finish
    details.find_fuzzy("Begin Installation", "button").click()
    lib.utils.check(lambda: details.dead)
    app.find_details_window(vmname)


def testNewVMInactiveNetwork(app):
    """
    Test with an inactive 'default' network
    """
    app.uri = tests.utils.URIs.test_default
    hostwin = app.manager_open_host("Virtual Networks",
            conn_label="test default")
    cell = hostwin.find("default", "table cell")
    cell.click()
    hostwin.find("net-stop").click()
    hostwin.keyCombo("<ctrl>w")

    newvm = _open_newvm(app)

    newvm.find_fuzzy("Import", "radio").click()
    _forward(newvm)
    newvm.find("import-entry").set_text(__file__)
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)

    newvm.find_fuzzy("Finish", "button").click()
    app.click_alert_button("start the network", "Yes")
    lib.utils.check(lambda: not newvm.showing)


@unittest.mock.patch.dict('os.environ', {"VIRTINST_TEST_SUITE": "1"})
def testNewVMDefaultBridge(app):
    """
    We actually set the unittest env variable here, which
    sets a fake bridge in interface.py
    """
    app.uri = tests.utils.URIs.test_empty
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Import", "radio").click()
    _forward(newvm)
    newvm.find("import-entry").set_text(__file__)
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)
    newvm.find("Network selection", "toggle button").click_expander()
    newvm.combo_check_default("net-source", "Bridge")
    devname = newvm.find("Device name:", "text")
    lib.utils.check(lambda: devname.text == "testsuitebr0")

    newvm.find_fuzzy("Finish", "button").click()
    app.find_details_window("vm1")
    lib.utils.check(lambda: not newvm.showing)


@unittest.mock.patch.dict('os.environ',
        {"VIRTINST_TEST_SUITE_FAKE_NO_SPICE": "1"})
def testCreateVMMissingSpice(app):
    newvm = _open_newvm(app)

    newvm.find_fuzzy("Import", "radio").click()
    _forward(newvm)
    newvm.find("import-entry").set_text("/pool-dir/testvol1.img")
    newvm.find("oslist-entry").set_text("generic")
    newvm.find("oslist-popover").find_fuzzy("generic").click()
    _forward(newvm)
    _forward(newvm)

    newvm.find_fuzzy("Finish", "button").click()
    details = app.find_details_window("vm1")
    lib.utils.check(lambda: not newvm.showing)

    details.find_fuzzy("test suite faking no spice")
    details.window_close()
