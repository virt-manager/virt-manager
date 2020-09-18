# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from . import lib


#####################################
# UI tests for the createnet wizard #
#####################################

def _open_netadd(app, hostwin):
    hostwin.find("net-add", "push button").click()
    win = app.find_window("Create a new virtual network")
    return win


def testCreateNet(app):
    """
    Basic test with object state management afterwards
    """
    hostwin = app.manager_open_host("Virtual Networks")
    win = _open_netadd(app, hostwin)

    # Create a simple default network
    name = win.find("Name:", "text")
    finish = win.find("Finish", "push button")
    lib.utils.check(lambda: name.text == "network")
    newname = "a-test-new-net"
    name.set_text(newname)
    finish.click()

    # Select the new network in the host window, then do
    # stop->start->stop->delete, for lifecycle testing
    lib.utils.check(lambda: hostwin.active)
    cell = hostwin.find(newname, "table cell")
    delete = hostwin.find("net-delete", "push button")
    start = hostwin.find("net-start", "push button")
    stop = hostwin.find("net-stop", "push button")

    cell.click()
    stop.click()
    lib.utils.check(lambda: start.sensitive)
    start.click()
    lib.utils.check(lambda: stop.sensitive)
    stop.click()
    lib.utils.check(lambda: delete.sensitive)

    # Delete it, clicking No first
    delete.click()
    app.click_alert_button("permanently delete the network", "No")
    lib.utils.check(lambda: not cell.dead)
    delete.click()
    app.click_alert_button("permanently delete the network", "Yes")
    # Ensure it's gone
    lib.utils.check(lambda: cell.dead)



def testCreateNetXMLEditor(app):
    """
    Test the XML editor
    """
    app.open(xmleditor_enabled=True)
    hostwin = app.manager_open_host("Virtual Networks")
    win = _open_netadd(app, hostwin)
    name = win.find("Name:", "text")
    finish = win.find("Finish", "push button")

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
    win = _open_netadd(app, hostwin)
    lib.utils.test_xmleditor_interactions(app, win, finish)
    win.find("Cancel", "push button").click()
    lib.utils.check(lambda: not win.visible)

    # Ensure host window closes fine
    hostwin.click()
    hostwin.keyCombo("<ctrl>w")
    lib.utils.check(lambda: not hostwin.showing and
            not hostwin.active)


def testCreateNetMulti(app):
    """
    Test remaining create options
    """
    app.uri = "test:///default"
    hostwin = app.manager_open_host(
            "Virtual Networks", conn_label="test default")
    win = _open_netadd(app, hostwin)
    finish = win.find("Finish", "push button")

    # Create a network with a bunch of options
    win.find("Name:", "text").set_text("default")
    win.find("net-mode").click()
    win.find("Isolated", "menu item").click()
    win.find("IPv4 configuration").click_expander()
    win.find("ipv4-network").set_text("192.168.100.0/25")
    ipv4start = win.find("ipv4-start")
    ipv4end = win.find("ipv4-end")
    lib.utils.check(lambda: ipv4start.text == "192.168.100.64")
    lib.utils.check(lambda: ipv4end.text == "192.168.100.126")
    win.find("Enable DHCPv4").click()
    win.find("Enable IPv4").click()
    win.find("IPv6 configuration").click_expander()
    win.find("Enable IPv6").click()
    win.find("Enable DHCPv6").click()
    win.find("ipv6-network").set_text("fd00:beef:10:6::1/64")
    win.find("ipv6-start").set_text("fd00:beef:10:6::1:1")
    win.find("ipv6-end").set_text("bad")
    win.find("DNS domain name").click_expander()
    win.find("Custom").click()
    win.find("domain-custom").set_text("mydomain")
    finish.click()
    # Name collision validation
    app.click_alert_button("in use by another network", "Close")
    win.find("Name:", "text").set_text("newnet1")
    finish.click()
    # XML define error
    app.click_alert_button("Error creating virtual network", "Close")
    win.find("ipv6-end").set_text("fd00:beef:10:6::1:f1")
    finish.click()
    lib.utils.check(lambda: hostwin.active)

    # More option work
    win = _open_netadd(app, hostwin)
    win.find("Name:", "text").set_text("newnet2")
    devicelist = win.find("net-devicelist")
    lib.utils.check(lambda: not devicelist.visible)
    win.find("net-mode").click()
    win.find("SR-IOV", "menu item").click()
    lib.utils.check(lambda: devicelist.visible)
    # Just confirm this is here
    win.find("No available device", "menu item")
    win.find("net-mode").click()
    win.find("Routed", "menu item").click()
    win.find("net-forward").click()
    win.find("Physical device", "menu item").click()
    win.find("net-device").set_text("fakedev0")
    finish.click()
    lib.utils.check(lambda: hostwin.active)


def testCreateNetSRIOV(app):
    """
    We need the full URI to test the SRIOV method
    """
    app.open(xmleditor_enabled=True)
    hostwin = app.manager_open_host("Virtual Networks")
    win = _open_netadd(app, hostwin)
    finish = win.find("Finish", "push button")

    win.find("net-mode").click()
    win.find("SR-IOV", "menu item").click()
    win.find("net-devicelist").click()
    win.find_fuzzy("eth3", "menu item").click()
    finish.click()
