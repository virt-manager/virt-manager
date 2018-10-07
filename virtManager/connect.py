# Copyright (C) 2006, 2013 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import glob
import os
import logging
import urllib.parse

from gi.repository import Gtk

from . import uiutil
from .baseclass import vmmGObjectUI
from .connmanager import vmmConnectionManager

(HV_QEMU,
HV_XEN,
HV_LXC,
HV_QEMU_SESSION,
HV_BHYVE,
HV_VZ,
HV_CUSTOM) = range(7)


class vmmConnect(vmmGObjectUI):
    @classmethod
    def get_instance(cls, parentobj):
        try:
            if not cls._instance:
                cls._instance = vmmConnect()
            return cls._instance
        except Exception as e:
            parentobj.err.show_err(
                    _("Error launching connect dialog: %s") % str(e))

    @classmethod
    def is_initialized(cls):
        return bool(cls._instance)

    def __init__(self):
        vmmGObjectUI.__init__(self, "connect.ui", "vmm-open-connection")
        self._cleanup_on_app_close()

        self.builder.connect_signals({
            "on_hypervisor_changed": self.hypervisor_changed,
            "on_connect_remote_toggled": self.connect_remote_toggled,
            "on_username_entry_changed": self.username_changed,
            "on_hostname_changed": self.hostname_changed,

            "on_cancel_clicked": self.cancel,
            "on_connect_clicked": self.open_conn,
            "on_vmm_open_connection_delete_event": self.cancel,
        })

        self.set_initial_state()
        self.reset_state()

    @staticmethod
    def default_uri():
        if os.path.exists('/var/lib/xen'):
            if (os.path.exists('/dev/xen/evtchn') or
                os.path.exists("/proc/xen")):
                return 'xen:///'

        if (os.path.exists("/usr/bin/qemu") or
            os.path.exists("/usr/bin/qemu-kvm") or
            os.path.exists("/usr/bin/kvm") or
            os.path.exists("/usr/libexec/qemu-kvm") or
            glob.glob("/usr/bin/qemu-system-*")):
            return "qemu:///system"

        if (os.path.exists("/usr/lib/libvirt/libvirt_lxc") or
            os.path.exists("/usr/lib64/libvirt/libvirt_lxc")):
            return "lxc:///"
        return None

    def cancel(self, ignore1=None, ignore2=None):
        logging.debug("Cancelling open connection")
        self.close()
        return 1

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing open connection")
        self.topwin.hide()


    def show(self, parent):
        logging.debug("Showing open connection")
        if self.topwin.is_visible():
            self.topwin.present()
            return

        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def _cleanup(self):
        pass

    def set_initial_state(self):
        self.widget("connect").grab_default()

        combo = self.widget("hypervisor")
        # [connection ID, label]
        model = Gtk.ListStore(int, str)

        def _add_hv_row(rowid, config_name, label):
            if (not self.config.default_hvs or
                not config_name or
                config_name in self.config.default_hvs):
                model.append([rowid, label])

        _add_hv_row(HV_QEMU, "qemu", "QEMU/KVM")
        _add_hv_row(HV_QEMU_SESSION, "qemu", "QEMU/KVM " + _("user session"))
        _add_hv_row(HV_XEN, "xen", "Xen")
        _add_hv_row(HV_LXC, "lxc", "LXC (" + _("Linux Containers") + ")")
        _add_hv_row(HV_BHYVE, "bhyve", "Bhyve")
        _add_hv_row(HV_VZ, "vz", "Virtuozzo")
        _add_hv_row(-1, None, "")
        _add_hv_row(HV_CUSTOM, None, "Custom URI...")
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        def sepfunc(model, it):
            return model[it][0] == -1
        combo.set_row_separator_func(sepfunc)

    def reset_state(self):
        self.set_default_hypervisor()
        self.widget("autoconnect").set_sensitive(True)
        self.widget("autoconnect").set_active(True)
        self.widget("hostname").set_text("")
        self.widget("connect-remote").set_active(False)
        self.widget("username-entry").set_text("")
        self.widget("uri-entry").set_text("")
        self.connect_remote_toggled(self.widget("connect-remote"))
        self.populate_uri()

    def is_remote(self):
        # Whether user is requesting a remote connection
        return self.widget("connect-remote").get_active()

    def set_default_hypervisor(self):
        default = self.default_uri()
        if not default or default.startswith("qemu"):
            uiutil.set_list_selection(self.widget("hypervisor"), HV_QEMU)
        elif default.startswith("xen"):
            uiutil.set_list_selection(self.widget("hypervisor"), HV_XEN)

    def hostname_changed(self, src_ignore):
        self.populate_uri()

    def hypervisor_changed(self, src):
        ignore = src
        hv = uiutil.get_list_selection(self.widget("hypervisor"))
        is_session = hv == HV_QEMU_SESSION
        is_custom = hv == HV_CUSTOM
        show_remote = not is_session and not is_custom
        uiutil.set_grid_row_visible(
            self.widget("session-warning-box"), is_session)
        uiutil.set_grid_row_visible(
            self.widget("connect-remote"), show_remote)
        uiutil.set_grid_row_visible(
            self.widget("username-entry"), show_remote)
        uiutil.set_grid_row_visible(
            self.widget("hostname"), show_remote)
        if not show_remote:
            self.widget("connect-remote").set_active(False)

        uiutil.set_grid_row_visible(self.widget("uri-label"), not is_custom)
        uiutil.set_grid_row_visible(self.widget("uri-entry"), is_custom)
        if is_custom:
            label = self.widget("uri-label").get_text()
            self.widget("uri-entry").set_text(label)
            self.widget("uri-entry").grab_focus()
        self.populate_uri()

    def username_changed(self, src_ignore):
        self.populate_uri()

    def connect_remote_toggled(self, src_ignore):
        is_remote = self.is_remote()
        self.widget("hostname").set_sensitive(is_remote)
        self.widget("autoconnect").set_active(not is_remote)
        self.widget("username-entry").set_sensitive(is_remote)

        if is_remote and not self.widget("username-entry").get_text():
            self.widget("username-entry").set_text("root")
        self.populate_uri()

    def populate_uri(self):
        uri = self.generate_uri()
        self.widget("uri-label").set_text(uri)

    def generate_uri(self):
        hv = uiutil.get_list_selection(self.widget("hypervisor"))
        host = self.widget("hostname").get_text().strip()
        user = self.widget("username-entry").get_text()
        is_remote = self.is_remote()

        hvstr = ""
        if hv == HV_XEN:
            hvstr = "xen"
        elif hv == HV_QEMU or hv == HV_QEMU_SESSION:
            hvstr = "qemu"
        elif hv == HV_BHYVE:
            hvstr = "bhyve"
        elif hv == HV_VZ:
            hvstr = "vz"
        else:
            hvstr = "lxc"

        addrstr = ""
        if user:
            addrstr += urllib.parse.quote(user) + "@"

        if host.count(":") > 1:
            host = "[%s]" % host
        addrstr += host

        if is_remote:
            hoststr = "+ssh://" + addrstr + "/"
        else:
            hoststr = ":///"

        uri = hvstr + hoststr
        if hv in (HV_QEMU, HV_BHYVE, HV_VZ):
            uri += "system"
        elif hv == HV_QEMU_SESSION:
            uri += "session"

        return uri

    def validate(self):
        is_remote = self.is_remote()
        host = self.widget("hostname").get_text()

        if is_remote and not host:
            return self.err.val_err(_("A hostname is required for "
                                      "remote connections."))

        return True

    def _conn_open_completed(self, conn, ConnectError):
        if not ConnectError:
            self.close()
            self.reset_finish_cursor()
            return

        msg, details, title = ConnectError
        msg += "\n\n"
        msg += _("Would you still like to remember this connection?")

        remember = self.err.show_err(msg, details, title,
                buttons=Gtk.ButtonsType.YES_NO,
                dialog_type=Gtk.MessageType.QUESTION, modal=True)
        self.reset_finish_cursor()
        if remember:
            self.close()
        else:
            vmmConnectionManager.get_instance().remove_conn(conn.get_uri())

    def open_conn(self, ignore):
        if not self.validate():
            return

        auto = False
        if self.widget("autoconnect").get_sensitive():
            auto = bool(self.widget("autoconnect").get_active())
        if self.widget("uri-label").is_visible():
            uri = self.generate_uri()
        else:
            uri = self.widget("uri-entry").get_text()

        logging.debug("Generate URI=%s, auto=%s", uri, auto)

        conn = vmmConnectionManager.get_instance().add_conn(uri)
        conn.set_autoconnect(auto)
        if conn.is_active():
            return

        conn.connect_once("open-completed", self._conn_open_completed)
        self.set_finish_cursor()
        conn.open()
