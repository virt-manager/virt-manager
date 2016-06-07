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

import logging
import os
import time

from gi.repository import GLib
from gi.repository import Gio

import libvirt


def do_we_have_session():
    pid = os.getpid()
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except:
        logging.exception("Error getting system bus handle")
        return

    # Check systemd
    try:
        manager = Gio.DBusProxy.new_sync(bus, 0, None,
                        "org.freedesktop.login1",
                        "/org/freedesktop/login1",
                        "org.freedesktop.login1.Manager", None)

        ret = manager.GetSessionByPID("(u)", pid)
        logging.debug("Found login1 session=%s", ret)
        return True
    except:
        logging.exception("Couldn't connect to logind")

    return False


def creds_dialog(conn, creds):
    """
    Thread safe wrapper for libvirt openAuth user/pass callback
    """

    retipc = []

    def wrapper(fn, conn, creds):
        try:
            ret = fn(conn, creds)
        except:
            logging.exception("Error from creds dialog")
            ret = -1
        retipc.append(ret)

    GLib.idle_add(wrapper, _creds_dialog_main, conn, creds)

    while not retipc:
        time.sleep(.1)

    return retipc[0]


def _creds_dialog_main(conn, creds):
    """
    Libvirt openAuth callback for username/password credentials
    """
    from gi.repository import Gtk

    dialog = Gtk.Dialog(_("Authentication required"), None, 0,
                        (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         Gtk.STOCK_OK, Gtk.ResponseType.OK))
    label = []
    entry = []

    box = Gtk.Table(2, len(creds))
    box.set_border_width(6)
    box.set_row_spacings(6)
    box.set_col_spacings(12)

    def _on_ent_activate(ent):
        idx = entry.index(ent)

        if idx < len(entry) - 1:
            entry[idx + 1].grab_focus()
        else:
            dialog.response(Gtk.ResponseType.OK)

    row = 0
    for cred in creds:
        if (cred[0] == libvirt.VIR_CRED_AUTHNAME or
            cred[0] == libvirt.VIR_CRED_PASSPHRASE):
            prompt = cred[1]
            if not prompt.endswith(":"):
                prompt += ":"

            text_label = Gtk.Label(label=prompt)
            text_label.set_alignment(0.0, 0.5)

            label.append(text_label)
        else:
            return -1

        ent = Gtk.Entry()
        if cred[0] == libvirt.VIR_CRED_PASSPHRASE:
            ent.set_visibility(False)
        elif conn.get_uri_username():
            ent.set_text(conn.get_uri_username())
        ent.connect("activate", _on_ent_activate)
        entry.append(ent)

        box.attach(label[row], 0, 1, row, row + 1,
            Gtk.AttachOptions.FILL, 0, 0, 0)
        box.attach(entry[row], 1, 2, row, row + 1,
            Gtk.AttachOptions.FILL, 0, 0, 0)
        row = row + 1

    vbox = dialog.get_child()
    vbox.add(box)

    dialog.show_all()
    res = dialog.run()
    dialog.hide()

    if res == Gtk.ResponseType.OK:
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
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        ka = Gio.DBusProxy.new_sync(bus, 0, None,
                                "org.gnome.KrbAuthDialog",
                                "/org/gnome/KrbAuthDialog",
                                "org.freedesktop.KrbAuthDialog", None)
        ret = ka.acquireTgt("(s)", "")
    except Exception, e:
        logging.info("Cannot acquire tgt" + str(e))
        ret = False
    return ret
