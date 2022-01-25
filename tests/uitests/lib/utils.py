# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import time


def check(func, timeout=2):
    """
    Run the passed func in a loop every .1 seconds until timeout is hit or
    the func returns True.
    """
    start_time = time.time()
    interval = 0.1
    while True:
        if func() is True:
            return
        if (time.time() - start_time) > timeout:
            raise RuntimeError("Loop condition wasn't met")
        time.sleep(interval)


def walkUIList(app, win, lst, error_cb, reverse=False):
    """
    Toggle down through a UI list like addhardware, net/storage/iface
    lists, and ensure an error isn't raised.
    """
    # Walk the lst UI and find all labelled table cells, these are
    # the actual list entries
    all_cells = lst.findChildren(lambda w: w.roleName == "table cell")
    if reverse:
        all_cells.reverse()
    all_cells[0].click()
    cells_per_selection = len([c for c in all_cells if c.focused])

    idx = 0
    while idx < len(all_cells):
        cell = all_cells[idx]
        if not cell.state_selected:
            # Could be a separator table cell. Try to figure it out
            if not any([c.name for c in
                        all_cells[idx:(idx + cells_per_selection)]]):
                idx += cells_per_selection
                continue

        check(lambda: cell.state_selected)
        app.rawinput.pressKey(reverse and "Up" or "Down")

        if not win.active:
            # Should mean an error dialog popped up
            app.root.find("Error", "alert")
            raise AssertionError("Error dialog raised?")
        if error_cb():
            raise AssertionError("Error found on a page")

        idx += cells_per_selection
        if idx >= len(all_cells):
            # Last cell, selection shouldn't have changed
            check(lambda: cell.state_selected)
        else:
            check(lambda: not cell.state_selected)


def test_xmleditor_interactions(app, win, finish):
    """
    Helper to test some common XML editor interactions
    """
    # Click the tab, make a bogus XML edit
    win.find("XML", "page tab").click()
    xmleditor = win.find("XML editor")
    xmleditor.set_text(xmleditor.text.replace("<", "<FOO", 1))

    # Trying to click away should warn that there's unapplied changes
    win.find("Details", "page tab").click()
    # Select 'No', meaning don't abandon changes
    app.click_alert_button("changes will be lost", "No")
    check(lambda: xmleditor.showing)

    # Click the finish button, but our bogus change should trigger error
    finish.click()
    app.click_alert_button("(xmlParseDoc|tag.mismatch)", "Close")

    # Try unapplied changes again, this time abandon our changes
    win.find("Details", "page tab").click()
    app.click_alert_button("changes will be lost", "Yes")
    check(lambda: not xmleditor.showing)


def get_xmleditor_xml(_app, win):
    win.find("XML", "page tab").click()
    xmleditor = win.find("XML editor")
    xml = xmleditor.get_text()
    win.find("Details", "page tab").click()
    check(lambda: not xmleditor.showing)
    return xml
