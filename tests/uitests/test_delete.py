# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import shutil

import tests.utils
from . import lib


class _DeleteRow:
    """
    Helper class for interacting with the delete dialog rows
    """
    def __init__(self, cell1, cell2, cell3, cell4):
        ignore = cell4
        self.chkcell = cell1
        self.path = cell2.text
        self.target = cell3.text
        self.undeletable = not self.chkcell.sensitive
        self.default = self.chkcell.checked
        self.notdefault = not self.undeletable and not self.default


def _create_testdriver_path(fn):
    def wrapper(app, *args, **kwargs):
        # This special path is hardcoded in test-many-devices
        tmppath = "/tmp/virt-manager-uitests/tmp1"
        tmpdir = os.path.dirname(tmppath)
        try:
            if not os.path.exists(tmpdir):
                os.mkdir(tmpdir)
            open(tmppath, "w").write("foo")
            os.chmod(tmppath, 0o444)
            return fn(app, tmppath, *args, **kwargs)
        finally:
            if os.path.exists(tmpdir):
                os.chmod(tmpdir, 0o777)
                shutil.rmtree(tmpdir)
    return wrapper


def _open_storage_browser(app):
    app.root.find("New", "push button").click()
    newvm = app.find_window("New VM")
    newvm.find_fuzzy("Local install media", "radio").click()
    newvm.find_fuzzy("Forward", "button").click()
    newvm.find_fuzzy("install-iso-browse", "button").click()
    return app.root.find("vmm-storage-browser")


def _open_delete(app, vmname):
    app.manager_vm_action(vmname, delete=True)
    return app.find_window("Delete")


def _finish(app, delete, paths, expect_fail=False, click_no=False):
    delete.find_fuzzy("Delete", "button").click()
    if paths:
        alert = app.root.find("vmm dialog", "alert")
        alert.find_fuzzy("Are you sure")
        for path in paths:
            alert.find_fuzzy(path)
        if click_no:
            alert.find("No", "push button").click()
            return
        alert.find("Yes", "push button").click()
    if not expect_fail:
        lib.utils.check(lambda: not delete.showing)


def _get_all_rows(delete):
    slist = delete.find("storage-list")
    def pred(node):
        return node.roleName == "table cell"
    cells = slist.findChildren(pred, isLambda=True)

    idx = 0
    rows = []
    while idx < len(cells):
        rows.append(_DeleteRow(*cells[idx:idx + 4]))
        idx += 4
    return rows


################################################
# UI tests for virt-manager's VM delete window #
################################################

def _testDeleteManyDevices(app,
        nondefault_path=None, delete_nondefault=False,
        skip_finish=False):
    delete = _open_delete(app, "test-many-devices")

    rows = _get_all_rows(delete)
    selected_rows = [r.path for r in rows if r.default]
    undeletable_rows = [r.path for r in rows if r.undeletable]
    notdefault_rows = [r.path for r in rows if r.notdefault]

    defpath = "/dev/default-pool/overlay.img"
    nondefault_path2 = "/dev/default-pool/sharevol.img"

    assert selected_rows == [defpath]
    if nondefault_path:
        assert nondefault_path in notdefault_rows
    assert nondefault_path2 in notdefault_rows
    assert "/dev/fda" in undeletable_rows

    if delete_nondefault:
        # Click the selector for the nondefault path
        found = [r for r in rows if r.path == nondefault_path]
        assert len(found) == 1
        slist = delete.find("storage-list")
        slist.click()
        chkcell = found[0].chkcell
        chkcell.bring_on_screen()
        chkcell.click()
        chkcell.click()
        chkcell.click()
        lib.utils.check(lambda: chkcell.checked)

    paths = []
    if defpath:
        paths.append(defpath)
    if delete_nondefault:
        paths.append(nondefault_path)
    if skip_finish:
        return paths
    _finish(app, delete, paths)

    # Confirm
    browser = _open_storage_browser(app)
    browser.find_fuzzy("default-pool", "table cell").click()
    browser.find("vol-refresh", "push button").click()
    lib.utils.check(lambda: "overlay.img" not in browser.fmt_nodes())
    browser.find("sharevol.img", "table cell")


@_create_testdriver_path
def testDeleteManyDevices(app, tmppath):
    """
    Hit a specific case of a path not selected by default
    because the permissions are readonly
    """
    _testDeleteManyDevices(app, nondefault_path=tmppath)


@_create_testdriver_path
def testDeleteNondefaultOverride(app, tmppath):
    """
    Path not selected by default, but we select it,
    which will cause it to be manually unlinked
    """
    _testDeleteManyDevices(app,
            nondefault_path=tmppath,
            delete_nondefault=True)
    assert not os.path.exists(tmppath)


@_create_testdriver_path
def testDeleteFailure(app, tmppath):
    """
    After launching the wizard we change permissions to make
    file deletion fail
    """
    paths = _testDeleteManyDevices(app,
            nondefault_path=tmppath,
            delete_nondefault=True,
            skip_finish=True)
    os.chmod(os.path.dirname(tmppath), 0o555)
    delete = app.find_window("Delete")
    _finish(app, delete, paths, expect_fail=True, click_no=True)
    lib.utils.check(lambda: delete.active)
    _finish(app, delete, paths, expect_fail=True)
    assert os.path.exists(tmppath)
    app.click_alert_button("Errors encountered", "Close")

    # Ensure disconnecting will close the dialog
    win = _open_delete(app, "test-clone")
    app.manager_test_conn_window_cleanup("test testdriver.xml", win)


def testDeleteRemoteManyDevices(app):
    """
    Test with a remote VM to hit a certain code path
    """
    app.uri = tests.utils.URIs.kvm_remote
    _testDeleteManyDevices(app)


def testDeleteSkipStorage(app):
    """
    Test VM delete with all storage skipped
    """
    delete = _open_delete(app, "test-many-devices")
    chk = delete.find("Delete associated", "check box")
    slist = delete.find("storage-list")

    lib.utils.check(lambda: chk.checked)
    chk.click()
    lib.utils.check(lambda: not chk.checked)
    lib.utils.check(lambda: not slist.showing)

    _finish(app, delete, None)

    # Confirm nothing was deleted compare to the default selections
    browser = _open_storage_browser(app)
    browser.find_fuzzy("default-pool", "table cell").click()
    browser.find("vol-refresh", "push button").click()
    browser.find("overlay.img", "table cell")
    browser.find("sharevol.img", "table cell")


def testDeleteDeviceNoStorage(app):
    """
    Verify successful device remove with storage doesn't
    touch host storage
    """
    details = app.manager_open_details("test-many-devices",
            shutdown=True)

    hwlist = details.find("hw-list")
    hwlist.click()
    c = hwlist.find("USB Disk 1")
    c.bring_on_screen()
    c.click()
    tab = details.find("disk-tab")
    lib.utils.check(lambda: tab.showing)
    details.find("config-remove").click()

    delete = app.find_window("Remove Disk")
    chk = delete.find("Delete associated", "check box")
    lib.utils.check(lambda: not chk.checked)
    _finish(app, delete, [])
    details.window_close()

    browser = _open_storage_browser(app)
    browser.find_fuzzy("default-pool", "table cell").click()
    browser.find("vol-refresh", "push button").click()
    browser.find("overlay.img", "table cell")


def testDeleteDeviceWithStorage(app):
    """
    Verify successful device remove deletes storage
    """
    details = app.manager_open_details("test-many-devices",
            shutdown=True)

    hwlist = details.find("hw-list")
    hwlist.click()
    c = hwlist.find("USB Disk 1")
    c.bring_on_screen()
    c.click()
    tab = details.find("disk-tab")
    lib.utils.check(lambda: tab.showing)
    details.find("config-remove").click()

    delete = app.find_window("Remove Disk")
    chk = delete.find("Delete associated", "check box")
    lib.utils.check(lambda: not chk.checked)
    chk.click()
    lib.utils.check(lambda: chk.checked)
    path = "/dev/default-pool/overlay.img"
    delete.find_fuzzy(path)
    _finish(app, delete, [path])
    details.window_close()

    browser = _open_storage_browser(app)
    browser.find_fuzzy("default-pool", "table cell").click()
    browser.find("vol-refresh", "push button").click()
    lib.utils.check(lambda: "overlay.img" not in browser.fmt_nodes())


def testDeleteDeviceFail(app):
    """
    Verify failed device remove does not touch storage
    """
    details = app.manager_open_details("test-many-devices")

    hwlist = details.find("hw-list")
    hwlist.click()
    c = hwlist.find("USB Disk 1")
    c.bring_on_screen()
    c.click()
    tab = details.find("disk-tab")
    lib.utils.check(lambda: tab.showing)
    details.find("config-remove").click()

    delete = app.find_window("Remove Disk")
    chk = delete.find("Delete associated", "check box")
    lib.utils.check(lambda: not chk.checked)
    chk.click()
    lib.utils.check(lambda: chk.checked)
    path = "/dev/default-pool/overlay.img"
    delete.find_fuzzy(path)
    _finish(app, delete, [path], expect_fail=True)
    app.click_alert_button("Storage will not be.*deleted", "OK")
    details.window_close()

    # Verify file still exists
    browser = _open_storage_browser(app)
    browser.find_fuzzy("default-pool", "table cell").click()
    browser.find("vol-refresh", "push button").click()
    browser.find("overlay.img", "table cell")
