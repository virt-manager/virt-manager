# Copyright (C) 2012-2013 Red Hat, Inc.
# Copyright (C) 2012 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import collections
import os
import re
import time

from gi.repository import GLib
from gi.repository import Gio
from gi.repository import Gtk

import libvirt

from virtinst import log

from ..baseclass import vmmGObjectUI
from . import uiutil


def do_we_have_session():
    pid = os.getpid()

    ret = False
    try:  # pragma: no cover
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        manager = Gio.DBusProxy.new_sync(bus, 0, None,
                        "org.freedesktop.login1",
                        "/org/freedesktop/login1",
                        "org.freedesktop.login1.Manager", None)

        # This raises an error exception
        out = manager.GetSessionByPID("(u)", pid)
        log.debug("Found login1 session=%s", out)
        ret = True
    except Exception:  # pragma: no cover
        log.exception("Failure talking to logind")

    return ret


class _vmmConnectAuth(vmmGObjectUI):
    def __init__(self, creds):
        vmmGObjectUI.__init__(self, "connectauth.ui", "connectauth")
        self.creds = creds
        self.topwin.set_title(_("Authentication required"))

        self.builder.connect_signals({
            "on_connectauth_cancel_clicked": self._cancel_cb,
            "on_connectauth_ok_clicked": self._ok_cb,
            "on_entry1_activate": self._entry_cb,
            "on_entry2_activate": self._entry_cb,
        })

        self.entry1 = self.widget("entry1")
        self.entry2 = self.widget("entry2")
        self._init_ui()

    def _cleanup(self):
        pass

    def _init_ui(self):
        uiutil.set_grid_row_visible(self.entry1, False)
        uiutil.set_grid_row_visible(self.entry2, False)

        for idx, cred in enumerate(self.creds):
            # Libvirt virConnectCredential
            credtype, prompt, _challenge, _defresult, _result = cred
            noecho = credtype in [
                    libvirt.VIR_CRED_PASSPHRASE,
                    libvirt.VIR_CRED_NOECHOPROMPT]
            if not prompt:  # pragma: no cover
                raise RuntimeError("No prompt for auth credtype=%s" % credtype)

            prompt += ": "
            label = self.widget("label%s" % (idx + 1))
            entry = self.widget("entry%s" % (idx + 1))
            uiutil.set_grid_row_visible(label, True)
            label.set_text(prompt)
            entry.set_visibility(not noecho)
            entry.get_accessible().set_name(prompt + " entry")

    def run(self):
        self.topwin.show()
        res = self.topwin.run()
        self.topwin.hide()

        if res != Gtk.ResponseType.OK:
            return -1

        self.creds[0][4] = self.entry1.get_text()
        if self.entry2.get_visible():
            self.creds[1][4] = self.entry2.get_text()
        return 0

    def _ok_cb(self, src):
        self.topwin.response(Gtk.ResponseType.OK)
    def _cancel_cb(self, src):
        self.topwin.response(Gtk.ResponseType.CANCEL)

    def _entry_cb(self, src):
        """
        If entry 1 activated and entry2 visible, jump to entry 2.
        Otherwise, click OK
        """
        if src == self.entry1 and self.entry2.is_visible():
            self.entry2.grab_focus()
            return
        self.topwin.response(Gtk.ResponseType.OK)


def creds_dialog(creds, cbdata):
    """
    Thread safe wrapper for libvirt openAuth user/pass callback
    """
    retipc = []

    def wrapper(creds, cbdata):
        try:
            _conn = cbdata
            dialogobj = _vmmConnectAuth(creds)
            ret = dialogobj.run()
            dialogobj.cleanup()
        except Exception:  # pragma: no cover
            log.exception("Error from creds dialog")
            ret = -1
        retipc.append(ret)

    GLib.idle_add(wrapper, creds, cbdata)

    while not retipc:
        time.sleep(.1)

    return retipc[0]


def connect_error(conn, errmsg, tb, warnconsole):
    """
    Format connection error message
    """
    errmsg = errmsg.strip(" \n")
    tb = tb.strip(" \n")
    hint = ""
    show_errmsg = True

    if conn.is_remote():
        log.debug("connect_error: conn transport=%s",
            conn.get_uri_transport())
        if re.search(r"nc: .* -- 'U'", tb):  # pragma: no cover
            hint += _("The remote host requires a version of netcat/nc "
                      "which supports the -U option.")
            show_errmsg = False
        elif (conn.get_uri_transport() == "ssh" and
                re.search(r"askpass", tb)):  # pragma: no cover

            hint += _("Configure SSH key access for the remote host, "
                      "or install an SSH askpass package locally.")
            show_errmsg = False
        else:
            hint += _("Verify that the 'libvirtd' daemon is running "
                      "on the remote host.")

    elif conn.is_xen():  # pragma: no cover
        hint += _("Verify that:\n"
                  " - A Xen host kernel was booted\n"
                  " - The Xen service has been started")

    else:
        if warnconsole:
            hint += _("Could not detect a local session: if you are "
                      "running virt-manager over ssh -X or VNC, you "
                      "may not be able to connect to libvirt as a "
                      "regular user. Try running as root.")
            show_errmsg = False
        elif re.search(r"libvirt-sock", tb):  # pragma: no cover
            hint += _("Verify that the 'libvirtd' daemon is running.")
            show_errmsg = False

    msg = _("Unable to connect to libvirt %s." % conn.get_uri())
    if show_errmsg:
        msg += "\n\n%s" % errmsg
    if hint:
        msg += "\n\n%s" % hint

    msg = msg.strip("\n")
    details = msg
    details += "\n\n"
    details += "Libvirt URI is: %s\n\n" % conn.get_uri()
    details += tb

    title = _("Virtual Machine Manager Connection Failure")

    ConnectError = collections.namedtuple("ConnectError",
            ["msg", "details", "title"])
    return ConnectError(msg, details, title)


##################################
# App first run connection setup #
##################################

def _start_libvirtd(config):
    log.debug("Trying to start libvirtd through systemd")

    unitname = "libvirtd.service"
    libvirtd_installed = False
    libvirtd_active = False
    unitpath = None

    # Fetch all units from systemd
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        systemd = Gio.DBusProxy.new_sync(bus, 0, None,
                                 "org.freedesktop.systemd1",
                                 "/org/freedesktop/systemd1",
                                 "org.freedesktop.systemd1.Manager", None)
        units = systemd.ListUnits()
        log.debug("Successfully listed units via systemd")
    except Exception:  # pragma: no cover
        units = []
        log.exception("Couldn't connect to systemd")
        libvirtd_installed = os.path.exists("/var/run/libvirt")
        libvirtd_active = os.path.exists("/var/run/libvirt/libvirt-sock")

    # Check if libvirtd is installed and running
    for unitinfo in units:
        if unitinfo[0] != unitname:
            continue
        libvirtd_installed = True
        libvirtd_active = unitinfo[3] == "active"
        unitpath = unitinfo[6]
        break

    log.debug("libvirtd_installed=%s libvirtd_active=%s unitpath=%s",
            libvirtd_installed, libvirtd_active, unitpath)

    # If it's not running, try to start it
    try:
        if unitpath and libvirtd_installed and not libvirtd_active:  # pragma: no cover
            unit = Gio.DBusProxy.new_sync(
                    bus, 0, None,
                    "org.freedesktop.systemd1", unitpath,
                    "org.freedesktop.systemd1.Unit", None)
            if config.CLITestOptions.fake_systemd_success:
                unit.Start("(s)", "fail")
                time.sleep(2)
                libvirtd_active = True
    except Exception:  # pragma: no cover
        log.exception("Error starting libvirtd")

    return libvirtd_installed, libvirtd_active


def setup_first_uri(config, tryuri):
    libvirtd_installed, libvirtd_active = _start_libvirtd(config)
    if config.CLITestOptions.fake_systemd_success:
        libvirtd_installed = True
        libvirtd_active = True

    if tryuri and libvirtd_installed and libvirtd_active:
        return

    # Manager fail message
    msg = ""
    if not libvirtd_installed:  # pragma: no cover
        msg += _("The libvirtd service does not appear to be installed. "
                 "Install and run the libvirtd service to manage "
                 "virtualization on this host.")
    elif not libvirtd_active:  # pragma: no cover
        msg += _("libvirtd is installed but not running. Start the "
                 "libvirtd service to manage virtualization on this host.")

    if not tryuri or "qemu" not in tryuri:
        if msg:
            msg += "\n\n"  # pragma: no cover
        msg += _("Could not detect a default hypervisor. Make "
                "sure the appropriate QEMU/KVM virtualization "
                "packages are installed to manage virtualization "
                "on this host.")

    if msg:
        msg += "\n\n"
        msg += _("A virtualization connection can be manually "
                 "added via File->Add Connection")

    if (tryuri is None or
        not libvirtd_installed or
        not libvirtd_active):
        return msg
