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

import logging
import os
import time

import dbus
import libvirt

def do_we_have_session():
    pid = os.getpid()
    try:
        bus = dbus.SystemBus()
    except:
        logging.exception("Error getting system bus handle")
        return

    # Check systemd
    try:
        manager = dbus.Interface(bus.get_object(
                                 "org.freedesktop.login1",
                                 "/org/freedesktop/login1"),
                                 "org.freedesktop.login1.Manager")
        ret = manager.GetSessionByPID(pid)
        logging.debug("Found login1 session=%s", ret)
        return True
    except:
        logging.exception("Couldn't connect to logind")

    # Check ConsoleKit
    try:
        manager = dbus.Interface(bus.get_object(
                                 "org.freedesktop.ConsoleKit",
                                 "/org/freedesktop/ConsoleKit/Manager"),
                                 "org.freedesktop.ConsoleKit.Manager")
        ret = manager.GetSessionForUnixProcess(pid)
        logging.debug("Found ConsoleKit session=%s", ret)
        return True
    except:
        logging.exception("Couldn't connect to ConsoleKit")

    return False


def creds_polkit(action):
    """
    Libvirt openAuth callback for PolicyKit < 1.0
    """
    if os.getuid() == 0:
        logging.debug("Skipping policykit check as root")
        return 0

    logging.debug("Doing policykit for %s", action)

    try:
        # First try to use org.freedesktop.PolicyKit.AuthenticationAgent
        # which is introduced with PolicyKit-0.7
        bus = dbus.SessionBus()

        obj = bus.get_object("org.freedesktop.PolicyKit.AuthenticationAgent",
                             "/")
        pkit = dbus.Interface(obj,
                              "org.freedesktop.PolicyKit.AuthenticationAgent")

        pkit.ObtainAuthorization(action, 0, os.getpid())
    except dbus.exceptions.DBusException, e:
        if (e.get_dbus_name() != "org.freedesktop.DBus.Error.ServiceUnknown"):
            raise

        # If PolicyKit < 0.7, fallback to org.gnome.PolicyKit
        logging.debug("Falling back to org.gnome.PolicyKit")
        obj = bus.get_object("org.gnome.PolicyKit",
                             "/org/gnome/PolicyKit/Manager")
        pkit = dbus.Interface(obj, "org.gnome.PolicyKit.Manager")
        pkit.ShowDialog(action, 0)

    return 0


def creds_dialog(creds):
    """
    Thread safe wrapper for libvirt openAuth user/pass callback
    """
    import gobject

    retipc = []

    def wrapper(fn, creds):
        try:
            ret = fn(creds)
        except:
            logging.exception("Error from creds dialog")
            ret = -1
        retipc.append(ret)

    gobject.idle_add(wrapper, creds_dialog_main, creds)

    while not retipc:
        time.sleep(.1)

    return retipc[0]


def creds_dialog_main(creds):
    """
    Libvirt openAuth callback for username/password credentials
    """
    import gtk

    dialog = gtk.Dialog("Authentication required", None, 0,
                        (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                         gtk.STOCK_OK, gtk.RESPONSE_OK))
    label = []
    entry = []

    box = gtk.Table(2, len(creds))
    box.set_border_width(6)
    box.set_row_spacings(6)
    box.set_col_spacings(12)

    def _on_ent_activate(ent):
        idx = entry.index(ent)

        if idx < len(entry) - 1:
            entry[idx + 1].grab_focus()
        else:
            dialog.response(gtk.RESPONSE_OK)

    row = 0
    for cred in creds:
        if (cred[0] == libvirt.VIR_CRED_AUTHNAME or
            cred[0] == libvirt.VIR_CRED_PASSPHRASE):
            prompt = cred[1]
            if not prompt.endswith(":"):
                prompt += ":"

            text_label = gtk.Label(prompt)
            text_label.set_alignment(0.0, 0.5)

            label.append(text_label)
        else:
            return -1

        ent = gtk.Entry()
        if cred[0] == libvirt.VIR_CRED_PASSPHRASE:
            ent.set_visibility(False)
        ent.connect("activate", _on_ent_activate)
        entry.append(ent)

        box.attach(label[row], 0, 1, row, row + 1, gtk.FILL, 0, 0, 0)
        box.attach(entry[row], 1, 2, row, row + 1, gtk.FILL, 0, 0, 0)
        row = row + 1

    vbox = dialog.get_child()
    vbox.add(box)

    dialog.show_all()
    res = dialog.run()
    dialog.hide()

    if res == gtk.RESPONSE_OK:
        row = 0
        for cred in creds:
            cred[4] = entry[row].get_text()
            row = row + 1
        ret = 0
    else:
        ret = -1

    dialog.destroy()
    return ret


def acquire_tgt():
    """
    Try to get kerberos ticket if openAuth seems to require it
    """
    logging.debug("In acquire tgt.")
    try:
        bus = dbus.SessionBus()
        ka = bus.get_object('org.gnome.KrbAuthDialog',
                            '/org/gnome/KrbAuthDialog')
        ret = ka.acquireTgt("", dbus_interface='org.gnome.KrbAuthDialog')
    except Exception, e:
        logging.info("Cannot acquire tgt" + str(e))
        ret = False
    return ret
