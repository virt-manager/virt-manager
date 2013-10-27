#
# Copyright (C) 2012-2013 Red Hat, Inc.
# Copyright (C) 2012 Cole Robinson <crobinso@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#

# pylint: disable=E0611
from gi.repository import Gio
# pylint: enable=E0611

import logging
import time


#############################
# PackageKit lookup helpers #
#############################

def check_packagekit(parent, errbox, packages):
    """
    Returns None when we determine nothing useful.
    Returns (success, did we just install libvirt) otherwise.
    """
    if not packages:
        logging.debug("No PackageKit packages to search for.")
        return

    logging.debug("Asking PackageKit what's installed locally.")
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        Gio.DBusProxy.new_sync(bus, 0, None,
                               "org.freedesktop.PackageKit",
                               "/org/freedesktop/PackageKit",
                               "org.freedesktop.PackageKit", None)
    except Exception:
        logging.exception("Couldn't connect to packagekit")
        return

    try:
        packagekit_install(parent, packages)
    except Exception, e:
        if "Modify.transactionCancelled" in str(e):
            logging.debug("PackageKit transaction cancelled.")
            return
        errbox.show_err(_("Error talking to PackageKit: %s") % str(e))
        return

    return True


def packagekit_install(parent, package_list):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    pk_control = Gio.DBusProxy.new_sync(bus, 0, None,
                            "org.freedesktop.PackageKit",
                            "/org/freedesktop/PackageKit",
                            "org.freedesktop.PackageKit.Modify", None)

    xid = 0
    try:
        # Need to import GdkX11 just to get access to get_xid function
        # This will likely fail on wayland in the future, so ignore errors
        from gi.repository import GdkX11  # pylint: disable=E0611
        ignore = GdkX11

        if parent and parent.topwin.get_window():
            xid = parent.topwin.get_window().get_xid()
    except:
        pass

    # Set 2 hour timeout
    timeout = 1000 * 60 * 60 * 2
    logging.debug("Installing packages: %s", package_list)
    pk_control.InstallPackageNames("(uass)", xid, package_list, "",
                                   timeout=timeout)


###################
# Service helpers #
###################


def start_libvirtd():
    """
    Connect to systemd and start libvirtd if required
    """
    logging.debug("Trying to start libvirtd through systemd")
    unitname = "libvirtd.service"

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except:
        logging.exception("Error getting system bus handle")
        return

    try:
        systemd = Gio.DBusProxy.new_sync(bus, 0, None,
                                 "org.freedesktop.systemd1",
                                 "/org/freedesktop/systemd1",
                                 "org.freedesktop.systemd1.Manager", None)
    except:
        logging.exception("Couldn't connect to systemd")
        return

    try:
        unitpath = systemd.GetUnit("(s)", unitname)
        unit = Gio.DBusProxy.new_sync(bus, 0, None,
                                 "org.freedesktop.systemd1", unitpath,
                                 "org.freedesktop.systemd1.Unit", None)
        state = unit.get_cached_property("ActiveState")

        logging.debug("libvirtd state=%s", state)
        if str(state).lower().strip("'") == "active":
            logging.debug("libvirtd already active, not starting")
            return True
    except:
        logging.exception("Failed to lookup libvirtd status")
        return

    # Connect to system-config-services and offer to start
    try:
        logging.debug("libvirtd not running, asking system-config-services "
                      "to start it")
        scs = Gio.DBusProxy.new_sync(bus, 0, None,
                             "org.fedoraproject.Config.Services",
                             "/org/fedoraproject/Config/Services/systemd1",
                             "org.freedesktop.systemd1.Manager", None)
        scs.StartUnit("(ss)", unitname, "replace")
        time.sleep(2)
        logging.debug("Starting libvirtd appeared to succeed")
        return True
    except:
        logging.exception("Failed to talk to system-config-services")
