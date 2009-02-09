#
# Copyright (C) 2006 Red Hat, Inc.
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

import gobject
import gtk.glade
import virtinst
import logging
import dbus

HV_XEN = 0
HV_QEMU = 1

CONN_LOCAL = 0
CONN_TCP = 1
CONN_TLS = 2
CONN_SSH = 3

class vmmConnect(gobject.GObject):
    __gsignals__ = {
        "completed": (gobject.SIGNAL_RUN_FIRST,
                      gobject.TYPE_NONE, (str,object,object)),
        "cancelled": (gobject.SIGNAL_RUN_FIRST,
                      gobject.TYPE_NONE, ())
        }

    def __init__(self, config, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-open-connection.glade", "vmm-open-connection", domain="virt-manager")
        self.engine = engine
        self.window.get_widget("vmm-open-connection").hide()

        self.window.signal_autoconnect({
            "on_connection_changed": self.update_widget_states,
            "on_cancel_clicked": self.cancel,
            "on_connect_clicked": self.open_connection,
            "on_vmm_open_connection_delete_event": self.cancel,
            })

        self.browser = None
        self.can_browse = False

        default = virtinst.util.default_connection()
        if default is None:
            self.window.get_widget("hypervisor").set_active(-1)
        elif default[0:3] == "xen":
            self.window.get_widget("hypervisor").set_active(0)
        elif default[0:4] == "qemu":
            self.window.get_widget("hypervisor").set_active(1)

        self.window.get_widget("connection").set_active(0)
        self.window.get_widget("connect").grab_default()
        self.window.get_widget("autoconnect").set_active(True)

        connListModel = gtk.ListStore(str, str, str)
        self.window.get_widget("conn-list").set_model(connListModel)

        nameCol = gtk.TreeViewColumn(_("Name"))
        name_txt = gtk.CellRendererText()
        nameCol.pack_start(name_txt, True)
        nameCol.add_attribute(name_txt, "text", 2)
        nameCol.set_sort_column_id(2)
        self.window.get_widget("conn-list").append_column(nameCol)
        connListModel.set_sort_column_id(2, gtk.SORT_ASCENDING)

        self.window.get_widget("conn-list").get_selection().connect("changed", self.conn_selected)

        self.bus = dbus.SystemBus()
        try:
            self.server = dbus.Interface(self.bus.get_object("org.freedesktop.Avahi", "/"), "org.freedesktop.Avahi.Server")
            self.can_browse = True
        except Exception, e:
            logging.debug("Couldn't contact avahi: %s" % str(e))
            self.server = None
            self.can_browse = False

        self.reset_state()


    def cancel(self,ignore1=None,ignore2=None):
        self.close()
        self.emit("cancelled")
        return 1

    def close(self):
        self.window.get_widget("vmm-open-connection").hide()
        self.stop_browse()

    def show(self):
        win = self.window.get_widget("vmm-open-connection")
        win.show_all()
        win.present()
        self.reset_state()

    def reset_state(self):
        self.window.get_widget("hypervisor").set_active(0)
        self.window.get_widget("autoconnect").set_sensitive(True)
        self.window.get_widget("autoconnect").set_active(True)
        self.window.get_widget("conn-list").set_sensitive(False)
        self.window.get_widget("conn-list").get_model().clear()
        self.window.get_widget("hostname").set_text("")
        self.stop_browse()

    def update_widget_states(self, src):
        if src.get_active() > 0:
            self.window.get_widget("hostname").set_sensitive(True)
            self.window.get_widget("autoconnect").set_active(False)
            self.window.get_widget("autoconnect").set_sensitive(True)
            if self.can_browse:
                self.window.get_widget("conn-list").set_sensitive(True)
                self.start_browse()
        else:
            self.window.get_widget("conn-list").set_sensitive(False)
            self.window.get_widget("hostname").set_sensitive(False)
            self.window.get_widget("hostname").set_text("")
            self.window.get_widget("autoconnect").set_sensitive(True)
            self.window.get_widget("autoconnect").set_active(True)
            self.stop_browse()

    def add_service(self, interface, protocol, name, type, domain, flags):
        try:
            # Async service resolving
            res = self.server.ServiceResolverNew(interface, protocol, name,
                                                 type, domain, -1, 0)
            resint = dbus.Interface(self.bus.get_object("org.freedesktop.Avahi",
                                                        res),
                                    "org.freedesktop.Avahi.ServiceResolver")
            resint.connect_to_signal("Found", self.add_conn_to_list)
            # Synchronous service resolving
            #self.server.ResolveService(interface, protocol, name, type,
            #                           domain, -1, 0)
        except Exception, e:
            logging.exception(e)

    def remove_service(self, interface, protocol, name, type, domain, flags):
        try:
            model = self.window.get_widget("conn-list").get_model()
            name = str(name)
            for row in model:
                if row[0] == name:
                    model.remove(row.iter)
        except Exception, e:
            logging.exception(e)

    def add_conn_to_list(self, interface, protocol, name, type, domain,
                         host, aprotocol, address, port, text, flags):
        try:
            model = self.window.get_widget("conn-list").get_model()
            for row in model:
                if row[2] == str(name):
                    return
            model.append([str(address), self.sanitize_hostname(str(host)),
                          str(name)])
        except Exception, e:
            logging.exception(e)

    def start_browse(self):
        if self.browser or not self.can_browse:
            return
        # Call method to create new browser, and get back an object path for it.
        interface = -1              # physical interface to use? -1 is unspec
        protocol  = 0               # 0 = IPv4, 1 = IPv6, -1 = Unspecified
        service   = '_libvirt._tcp' # Service name to poll for
        flags     = 0               # Extra option flags
        domain    = ""              # Domain to browse in. NULL uses default
        bpath = self.server.ServiceBrowserNew(interface, protocol, service,
                                              domain, flags)

        # Create browser interface for the new object
        self.browser = dbus.Interface(self.bus.get_object("org.freedesktop.Avahi",
                                                          bpath),
                                      "org.freedesktop.Avahi.ServiceBrowser")

        self.browser.connect_to_signal("ItemNew", self.add_service)
        self.browser.connect_to_signal("ItemRemove", self.remove_service)

    def stop_browse(self):
        if self.browser:
            del(self.browser)
            self.browser = None

    def conn_selected(self, src):
        active = src.get_selected()
        if active[1] == None:
            return
        ip = active[0].get_value(active[1], 0)
        host = active[0].get_value(active[1], 1)
        host = self.sanitize_hostname(host)
        entry = host
        if not entry:
            entry = ip
        self.window.get_widget("hostname").set_text(entry)

    def open_connection(self, src):
        hv = self.window.get_widget("hypervisor").get_active()
        conn = self.window.get_widget("connection").get_active()
        host = self.window.get_widget("hostname").get_text()
        auto = False
        if self.window.get_widget("autoconnect").get_property("sensitive"):
            auto = self.window.get_widget("autoconnect").get_active()
        uri = None

        if conn == CONN_SSH and '@' in host:
            user, host = host.split('@',1)
        else:
            user = "root"

        readOnly = None
        if hv == -1:
            pass
        elif hv == HV_XEN:
            if conn == CONN_LOCAL:
                uri = "xen:///"
            elif conn == CONN_TLS:
                uri = "xen+tls://" + host + "/"
            elif conn == CONN_SSH:

                uri = "xen+ssh://" + user + "@" + host + "/"
            elif conn == CONN_TCP:
                uri = "xen+tcp://" + host + "/"
        else:
            if conn == CONN_LOCAL:
                uri = "qemu:///system"
            elif conn == CONN_TLS:
                uri = "qemu+tls://" + host + "/system"
            elif conn == CONN_SSH:
                uri = "qemu+ssh://" + user + "@" + host + "/system"
            elif conn == CONN_TCP:
                uri = "qemu+tcp://" + host + "/system"

        logging.debug("Connection to open is %s" % uri)
        self.close()
        self.emit("completed", uri, readOnly, auto)

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
        return host

gobject.type_register(vmmConnect)
