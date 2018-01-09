#
# Copyright (C) 2006, 2013 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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

import glob
import os
import logging
import socket
import urllib

from gi.repository import Gio
from gi.repository import GObject
from gi.repository import Gtk

from . import uiutil
from .baseclass import vmmGObjectUI

(HV_QEMU,
HV_XEN,
HV_LXC,
HV_QEMU_SESSION,
HV_BHYVE,
HV_VZ,
HV_CUSTOM) = range(7)

(CONN_SSH,
CONN_TCP,
CONN_TLS) = range(3)


def current_user():
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return ""


def default_conn_user(conn):
    if conn == CONN_SSH:
        return "root"
    return current_user()


class vmmConnect(vmmGObjectUI):
    __gsignals__ = {
        "completed": (GObject.SignalFlags.RUN_FIRST, None, [str, bool]),
        "cancelled": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self):
        vmmGObjectUI.__init__(self, "connect.ui", "vmm-open-connection")

        self.builder.connect_signals({
            "on_hypervisor_changed": self.hypervisor_changed,
            "on_transport_changed": self.transport_changed,
            "on_hostname_combo_changed": self.hostname_combo_changed,
            "on_connect_remote_toggled": self.connect_remote_toggled,
            "on_username_entry_changed": self.username_changed,
            "on_hostname_changed": self.hostname_changed,

            "on_cancel_clicked": self.cancel,
            "on_connect_clicked": self.open_conn,
            "on_vmm_open_connection_delete_event": self.cancel,
        })

        self.browser = None
        self.browser_sigs = []

        # Set this if we can't resolve 'hostname.local': means avahi
        # prob isn't configured correctly, and we should strip .local
        self.can_resolve_local = None

        # Plain hostname resolve failed, means we should just use IP addr
        self.can_resolve_hostname = None

        self.set_initial_state()

        try:
            self.dbus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self.avahiserver = Gio.DBusProxy.new_sync(self.dbus, 0, None,
                                    "org.freedesktop.Avahi", "/",
                                    "org.freedesktop.Avahi.Server", None)

            # Call any API, so we detect if avahi is even available or not
            self.avahiserver.GetAPIVersion()
            logging.debug("Connected to avahi")
        except Exception as e:
            self.dbus = None
            self.avahiserver = None
            logging.debug("Couldn't contact avahi: %s", str(e))

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
        self.emit("cancelled")
        return 1

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing open connection")
        self.topwin.hide()

        if self.browser:
            for obj, sig in self.browser_sigs:
                obj.disconnect(sig)
            self.browser_sigs = []
            self.browser = None


    def show(self, parent, reset_state=True):
        logging.debug("Showing open connection")
        if reset_state:
            self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()
        self.start_browse()

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

        combo = self.widget("transport")
        model = Gtk.ListStore(str)
        model.append(["SSH"])
        model.append(["TCP (SASL, Kerberos)"])
        model.append(["SSL/TLS " + _("with certificates")])
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 0)

        # Hostname combo box entry
        hostListModel = Gtk.ListStore(str, str, str)
        host = self.widget("hostname")
        host.set_model(hostListModel)
        host.set_entry_text_column(2)
        hostListModel.set_sort_column_id(2, Gtk.SortType.ASCENDING)

    def reset_state(self):
        self.set_default_hypervisor()
        self.widget("transport").set_active(0)
        self.widget("autoconnect").set_sensitive(True)
        self.widget("autoconnect").set_active(True)
        self.widget("hostname").get_model().clear()
        self.widget("hostname").get_child().set_text("")
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

    def add_service(self, interface, protocol, name, typ, domain, flags):
        ignore = flags
        try:
            # Async service resolving
            res = self.avahiserver.ServiceResolverNew("(iisssiu)",
                                                 interface, protocol,
                                                 name, typ, domain, -1, 0)
            resint = Gio.DBusProxy.new_sync(self.dbus, 0, None,
                                    "org.freedesktop.Avahi", res,
                                    "org.freedesktop.Avahi.ServiceResolver",
                                    None)

            def cb(proxy, sender, signal, args):
                ignore = proxy
                ignore = sender
                if signal == "Found":
                    self.add_conn_to_list(*args)

            sig = resint.connect("g-signal", cb)
            self.browser_sigs.append((resint, sig))
        except Exception as e:
            logging.exception(e)

    def remove_service(self, interface, protocol, name, typ, domain, flags):
        ignore = domain
        ignore = protocol
        ignore = flags
        ignore = interface
        ignore = typ

        try:
            model = self.widget("hostname").get_model()
            name = str(name)
            for row in model:
                if row[0] == name:
                    model.remove(row.iter)
        except Exception as e:
            logging.exception(e)

    def add_conn_to_list(self, interface, protocol, name, typ, domain,
                         host, aprotocol, address, port, text, flags):
        ignore = domain
        ignore = protocol
        ignore = flags
        ignore = interface
        ignore = typ
        ignore = text
        ignore = aprotocol
        ignore = port

        try:
            model = self.widget("hostname").get_model()
            for row in model:
                if row[2] == str(name):
                    # Already present in list
                    return

            host = self.sanitize_hostname(str(host))
            model.append([str(address), str(host), str(name)])
        except Exception as e:
            logging.exception(e)

    def start_browse(self):
        if self.browser or not self.avahiserver:
            return
        # Call method to create new browser, and get back an object path for it.
        interface = -1              # physical interface to use? -1 is unspec
        protocol  = 0               # 0 = IPv4, 1 = IPv6, -1 = Unspecified
        service   = '_libvirt._tcp'  # Service name to poll for
        flags     = 0               # Extra option flags
        domain    = ""              # Domain to browse in. NULL uses default
        bpath = self.avahiserver.ServiceBrowserNew("(iissu)",
                                                   interface, protocol,
                                                   service, domain, flags)

        # Create browser interface for the new object
        self.browser = Gio.DBusProxy.new_sync(self.dbus, 0, None,
                                    "org.freedesktop.Avahi", bpath,
                                    "org.freedesktop.Avahi.ServiceBrowser",
                                    None)

        def cb(proxy, sender, signal, args):
            ignore = proxy
            ignore = sender
            if signal == "ItemNew":
                self.add_service(*args)
            elif signal == "ItemRemove":
                self.remove_service(*args)

        self.browser_sigs.append((self.browser,
                                  self.browser.connect("g-signal", cb)))

    def hostname_combo_changed(self, src):
        model = src.get_model()
        txt = src.get_child().get_text()
        row = None

        for currow in model:
            if currow[2] == txt:
                row = currow
                break

        if not row:
            return

        ip = row[0]
        host = row[1]
        entry = host
        if not entry:
            entry = ip

        self.widget("hostname").get_child().set_text(entry)

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
        uiutil.set_grid_row_visible(
            self.widget("transport"), show_remote)
        if not show_remote:
            self.widget("connect-remote").set_active(False)

        uiutil.set_grid_row_visible(self.widget("uri-label"), not is_custom)
        uiutil.set_grid_row_visible(self.widget("uri-entry"), is_custom)
        if is_custom:
            self.widget("uri-entry").grab_focus()
        self.populate_uri()

    def username_changed(self, src_ignore):
        self.populate_uri()

    def connect_remote_toggled(self, src_ignore):
        is_remote = self.is_remote()
        self.widget("hostname").set_sensitive(is_remote)
        self.widget("transport").set_sensitive(is_remote)
        self.widget("autoconnect").set_active(not is_remote)
        self.widget("username-entry").set_sensitive(is_remote)

        self.populate_default_user()
        self.populate_uri()

    def transport_changed(self, src_ignore):
        self.populate_default_user()
        self.populate_uri()

    def populate_uri(self):
        uri = self.generate_uri()
        self.widget("uri-label").set_text(uri)

    def populate_default_user(self):
        conn = self.widget("transport").get_active()
        default_user = default_conn_user(conn)
        self.widget("username-entry").set_text(default_user)

    def generate_uri(self):
        hv = uiutil.get_list_selection(self.widget("hypervisor"))
        conn = self.widget("transport").get_active()
        host = self.widget("hostname").get_child().get_text().strip()
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
            addrstr += urllib.quote(user) + "@"

        if host.count(":") > 1:
            host = "[%s]" % host
        addrstr += host

        hoststr = ""
        if not is_remote:
            hoststr = ":///"
        else:
            if conn == CONN_TLS:
                hoststr = "+tls://"
            if conn == CONN_SSH:
                hoststr = "+ssh://"
            if conn == CONN_TCP:
                hoststr = "+tcp://"
            hoststr += addrstr + "/"

        uri = hvstr + hoststr
        if hv in (HV_QEMU, HV_BHYVE, HV_VZ):
            uri += "system"
        elif hv == HV_QEMU_SESSION:
            uri += "session"

        return uri

    def validate(self):
        is_remote = self.is_remote()
        host = self.widget("hostname").get_child().get_text()

        if is_remote and not host:
            return self.err.val_err(_("A hostname is required for "
                                      "remote connections."))

        return True

    def open_conn(self, ignore):
        if not self.validate():
            return

        auto = False
        if self.widget("autoconnect").get_sensitive():
            auto = self.widget("autoconnect").get_active()
        if self.widget("uri-label").is_visible():
            uri = self.generate_uri()
        else:
            uri = self.widget("uri-entry").get_text()

        logging.debug("Generate URI=%s, auto=%s", uri, auto)
        self.close()
        self.emit("completed", uri, auto)

    def sanitize_hostname(self, host):
        if host == "linux" or host == "localhost":
            host = ""
        if host.startswith("linux-"):
            tmphost = host[6:]
            try:
                long(tmphost)
                host = ""
            except ValueError:
                pass

        if host:
            host = self.check_resolve_host(host)
        return host

    def check_resolve_host(self, host):
        # Try to resolve hostname
        #
        # Avahi always uses 'hostname.local', but for some reason
        # fedora 12 out of the box can't resolve '.local' names
        # Attempt to resolve the name. If it fails, remove .local
        # if present, and try again
        if host.endswith(".local"):
            if self.can_resolve_local is False:
                host = host[:-6]

            elif self.can_resolve_local is None:
                try:
                    socket.getaddrinfo(host, None)
                except Exception:
                    logging.debug("Couldn't resolve host '%s'. Stripping "
                                  "'.local' and retrying.", host)
                    self.can_resolve_local = False
                    host = self.check_resolve_host(host[:-6])
                else:
                    self.can_resolve_local = True

        else:
            if self.can_resolve_hostname is False:
                host = ""
            elif self.can_resolve_hostname is None:
                try:
                    socket.getaddrinfo(host, None)
                except Exception:
                    logging.debug("Couldn't resolve host '%s'. Disabling "
                                  "host name resolution, only using IP addr",
                                  host)
                    self.can_resolve_hostname = False
                else:
                    self.can_resolve_hostname = True

        return host
