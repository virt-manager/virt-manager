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

import os
import logging
import socket

# pylint: disable=E0611
from gi.repository import Gio
from gi.repository import GObject
from gi.repository import Gtk
# pylint: enable=E0611

from virtManager.baseclass import vmmGObjectUI

HV_XEN = 0
HV_QEMU = 1
HV_LXC = 2

CONN_SSH = 0
CONN_TCP = 1
CONN_TLS = 2


def current_user():
    try:
        import getpass
        return getpass.getuser()
    except:
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
            "on_connection_changed": self.conn_changed,
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

        self.dbus = None
        self.avahiserver = None
        try:
            self.dbus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self.avahiserver = Gio.DBusProxy.new_sync(self.dbus, 0, None,
                                    "org.freedesktop.Avahi", "/",
                                    "org.freedesktop.Avahi.Server", None)
        except Exception, e:
            logging.debug("Couldn't contact avahi: %s", str(e))

        self.reset_state()

    @staticmethod
    def default_uri(always_system=False):
        if os.path.exists('/var/lib/xen'):
            if (os.path.exists('/dev/xen/evtchn') or
                os.path.exists("/proc/xen")):
                return 'xen:///'

        if (os.path.exists("/usr/bin/qemu") or
            os.path.exists("/usr/bin/qemu-kvm") or
            os.path.exists("/usr/bin/kvm") or
            os.path.exists("/usr/libexec/qemu-kvm")):
            if always_system or os.geteuid() == 0:
                return "qemu:///system"
            else:
                return "qemu:///session"
        return None

    def cancel(self, ignore1=None, ignore2=None):
        logging.debug("Cancelling open connection")
        self.close()
        self.emit("cancelled")
        return 1

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing open connection")
        self.topwin.hide()
        self.stop_browse()

    def show(self, parent, reset_state=True):
        logging.debug("Showing open connection")
        if reset_state:
            self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def _cleanup(self):
        pass

    def set_initial_state(self):
        self.widget("connect").grab_default()

        # Hostname combo box entry
        hostListModel = Gtk.ListStore(str, str, str)
        host = self.widget("hostname")
        host.set_model(hostListModel)
        host.set_entry_text_column(2)
        hostListModel.set_sort_column_id(2, Gtk.SortType.ASCENDING)

    def reset_state(self):
        self.set_default_hypervisor()
        self.widget("connection").set_active(0)
        self.widget("autoconnect").set_sensitive(True)
        self.widget("autoconnect").set_active(True)
        self.widget("hostname").get_model().clear()
        self.widget("hostname").get_child().set_text("")
        self.widget("connect-remote").set_active(False)
        self.widget("username-entry").set_text("")
        self.stop_browse()
        self.connect_remote_toggled(self.widget("connect-remote"))
        self.populate_uri()

    def is_remote(self):
        # Whether user is requesting a remote connection
        return self.widget("connect-remote").get_active()

    def set_default_hypervisor(self):
        default = self.default_uri(always_system=True)
        if not default or default.startswith("qemu"):
            self.widget("hypervisor").set_active(1)
        elif default.startswith("xen"):
            self.widget("hypervisor").set_active(0)

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
        except Exception, e:
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
        except Exception, e:
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
        except Exception, e:
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

    def stop_browse(self):
        if self.browser:
            for obj, sig in self.browser_sigs:
                obj.disconnect(sig)
            self.browser_sigs = []
            self.browser = None

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

    def hypervisor_changed(self, src_ignore):
        self.populate_uri()

    def username_changed(self, src_ignore):
        self.populate_uri()

    def connect_remote_toggled(self, src_ignore):
        is_remote = self.is_remote()
        self.widget("hostname").set_sensitive(is_remote)
        self.widget("connection").set_sensitive(is_remote)
        self.widget("autoconnect").set_active(not is_remote)
        self.widget("username-entry").set_sensitive(is_remote)
        if is_remote and self.avahiserver:
            self.start_browse()
        else:
            self.stop_browse()

        self.populate_default_user()
        self.populate_uri()

    def conn_changed(self, src_ignore):
        self.populate_default_user()
        self.populate_uri()

    def populate_uri(self):
        uri = self.generate_uri()
        self.widget("uri-entry").set_text(uri)

    def populate_default_user(self):
        conn = self.widget("connection").get_active()
        default_user = default_conn_user(conn)
        self.widget("username-entry").set_text(default_user)

    def generate_uri(self):
        hv = self.widget("hypervisor").get_active()
        conn = self.widget("connection").get_active()
        host = self.widget("hostname").get_child().get_text().strip()
        user = self.widget("username-entry").get_text()
        is_remote = self.is_remote()

        hvstr = ""
        if hv == HV_XEN:
            hvstr = "xen"
        elif hv == HV_QEMU:
            hvstr = "qemu"
        else:
            hvstr = "lxc"

        addrstr = ""
        if user:
            addrstr += user + "@"
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
        if hv == HV_QEMU:
            uri += "system"

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
        uri = self.generate_uri()

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
                except:
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
                except:
                    logging.debug("Couldn't resolve host '%s'. Disabling "
                                  "host name resolution, only using IP addr",
                                  host)
                    self.can_resolve_hostname = False
                else:
                    self.can_resolve_hostname = True

        return host
