#
# Copyright (C) 2012 Red Hat, Inc.
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

import gtk

import dbus

import logging
import time
import traceback

from virtManager.asyncjob import vmmAsyncJob

#############################
# PackageKit lookup helpers #
#############################

def check_packagekit(errbox, packages, ishv):
    """
    Returns None when we determine nothing useful.
    Returns (success, did we just install libvirt) otherwise.
    """
    if not packages:
        logging.debug("No PackageKit packages to search for.")
        return

    logging.debug("Asking PackageKit what's installed locally.")
    try:
        session = dbus.SystemBus()

        pk_control = dbus.Interface(
                        session.get_object("org.freedesktop.PackageKit",
                                           "/org/freedesktop/PackageKit"),
                        "org.freedesktop.PackageKit")
    except Exception:
        logging.exception("Couldn't connect to packagekit")
        return

    if ishv:
        msg = _("Searching for available hypervisors...")
    else:
        msg = _("Checking for installed package '%s'") % packages[0]

    found = []
    progWin = vmmAsyncJob(_do_async_search,
                          [session, pk_control, packages], msg, msg,
                          None, async=False)
    error, ignore = progWin.run()
    if error:
        return

    found = progWin.get_data()

    not_found = filter(lambda x: x not in found, packages)
    logging.debug("Missing packages: %s", not_found)

    do_install = not_found
    if not do_install:
        if not not_found:
            # Got everything we wanted, try to connect
            logging.debug("All packages found locally.")
            return []

        else:
            logging.debug("No packages are available for install.")
            return

    missing = reduce(lambda x, y: x + "\n" + y, do_install, "")
    if ishv:
        msg = (_("The following packages are not installed:\n%s\n\n"
                 "These are required to create KVM guests locally.\n"
                 "Would you like to install them now?") % missing)
        title = _("Packages required for KVM usage")
    else:
        msg = _("The following packages are not installed:\n%s\n\n"
                "Would you like to install them now?" % missing)
        title = _("Recommended package installs")

    ret = errbox.yes_no(title, msg)

    if not ret:
        logging.debug("Package install declined.")
        return

    try:
        packagekit_install(do_install)
    except Exception, e:
        errbox.show_err(_("Error talking to PackageKit: %s") % str(e))
        return

    return do_install

def _do_async_search(asyncjob, session, pk_control, packages):
    found = []
    try:
        for name in packages:
            ret_found = packagekit_search(session, pk_control, name, packages)
            found += ret_found

    except Exception, e:
        logging.exception("Error searching for installed packages")
        asyncjob.set_error(str(e), "".join(traceback.format_exc()))

    asyncjob.set_data(found)

def packagekit_install(package_list):
    session = dbus.SessionBus()

    pk_control = dbus.Interface(
                    session.get_object("org.freedesktop.PackageKit",
                                       "/org/freedesktop/PackageKit"),
                        "org.freedesktop.PackageKit.Modify")

    # Set 2 hour timeout
    timeout = 60 * 60 * 2
    logging.debug("Installing packages: %s", package_list)
    pk_control.InstallPackageNames(0, package_list, "hide-confirm-search",
                                   timeout=timeout)

def packagekit_search(session, pk_control, package_name, packages):
    tid = pk_control.GetTid()
    pk_trans = dbus.Interface(
                    session.get_object("org.freedesktop.PackageKit", tid),
                    "org.freedesktop.PackageKit.Transaction")

    found = []
    def package(info, package_id, summary):
        ignore = info
        ignore = summary

        found_name = str(package_id.split(";")[0])
        if found_name in packages:
            found.append(found_name)

    def error(code, details):
        raise RuntimeError("PackageKit search failure: %s %s" %
                            (code, details))

    def finished(ignore, runtime_ignore):
        gtk.main_quit()

    pk_trans.connect_to_signal('Finished', finished)
    pk_trans.connect_to_signal('ErrorCode', error)
    pk_trans.connect_to_signal('Package', package)
    try:
        pk_trans.SearchNames("installed", [package_name])
    except dbus.exceptions.DBusException, e:
        if e.get_dbus_name() != "org.freedesktop.DBus.Error.UnknownMethod":
            raise

        # Try older search API
        pk_trans.SearchName("installed", package_name)

    # Call main() so this function is synchronous
    gtk.main()

    return found

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
        bus = dbus.SystemBus()
    except:
        logging.exception("Error getting system bus handle")
        return

    try:
        systemd = dbus.Interface(bus.get_object(
                                 "org.freedesktop.systemd1",
                                 "/org/freedesktop/systemd1"),
                                 "org.freedesktop.systemd1.Manager")
    except:
        logging.exception("Couldn't connect to systemd")
        return

    try:
        unitpath = systemd.GetUnit(unitname)
        proxy = bus.get_object("org.freedesktop.systemd1", unitpath)
        props = dbus.Interface(proxy, "org.freedesktop.DBus.Properties")
        state = props.Get("org.freedesktop.systemd1.Unit", "ActiveState")

        logging.debug("libvirtd state=%s", state)
        if state == "Active":
            logging.debug("libvirtd already active, not starting")
            return True
    except:
        logging.exception("Failed to lookup libvirtd status")
        return

    # Connect to system-config-services and offer to start
    try:
        scs = dbus.Interface(bus.get_object(
                             "org.fedoraproject.Config.Services",
                             "/org/fedoraproject/Config/Services/systemd1"),
                             "org.freedesktop.systemd1.Manager")
        scs.StartUnit(unitname, "replace")
        time.sleep(2)
        return True
    except:
        logging.exception("Failed to talk to system-config-services")
