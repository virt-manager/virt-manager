#
# Copyright (C) 2007 Red Hat, Inc.
# Copyright (C) 2007 Daniel P. Berrange <berrange@redhat.com>
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
import gtk
import gtk.glade
import libvirt
import sparkline
import logging
import os

from virtManager.createnet import vmmCreateNetwork
from virtManager.error import vmmErrorDialog

class vmmHost(gobject.GObject):
    __gsignals__ = {
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                               gobject.TYPE_NONE, [str]),
        }
    def __init__(self, config, conn):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-host.glade", "vmm-host", domain="virt-manager")
        self.config = config
        self.conn = conn

        topwin = self.window.get_widget("vmm-host")
        topwin.hide()

        self.err = vmmErrorDialog(topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))

        self.window.get_widget("overview-uri").set_text(self.conn.get_uri())
        self.window.get_widget("overview-hostname").set_text(self.conn.get_hostname(True))
        self.window.get_widget("overview-hypervisor").set_text(self.conn.get_driver())
        self.window.get_widget("overview-memory").set_text(self.conn.pretty_host_memory_size())
        self.window.get_widget("overview-cpus").set_text(str(self.conn.host_active_processor_count()))
        self.window.get_widget("overview-arch").set_text(self.conn.host_architecture())
        self.window.get_widget("config-autoconnect").set_active(conn.get_autoconnect())

        netListModel = gtk.ListStore(str, str, str)
        self.window.get_widget("net-list").set_model(netListModel)
        self.populate_networks(netListModel)

        self.window.get_widget("net-list").get_selection().connect("changed", self.net_selected)

        netCol = gtk.TreeViewColumn("Networks")
        net_txt = gtk.CellRendererText()
        net_img = gtk.CellRendererPixbuf()
        netCol.pack_start(net_txt, True)
        netCol.pack_start(net_img, False)
        netCol.add_attribute(net_txt, 'text', 1)
        netCol.add_attribute(net_img, 'stock-id', 2)

        self.window.get_widget("net-list").append_column(netCol)
        self.window.get_widget("net-details").set_sensitive(False)

        self.cpu_usage_graph = sparkline.Sparkline()
        self.cpu_usage_graph.show()
        self.window.get_widget("performance-table").attach(self.cpu_usage_graph, 1, 2, 0, 1)

        self.memory_usage_graph = sparkline.Sparkline()
        self.memory_usage_graph.show()
        self.window.get_widget("performance-table").attach(self.memory_usage_graph, 1, 2, 1, 2)

        self.add = None
        self.window.get_widget("details-tabs").get_nth_page(2).hide()

        self.conn.connect("net-added", self.repopulate_networks)
        self.conn.connect("net-removed", self.repopulate_networks)

        # XXX not technically correct once we enable remote management
        if (os.getuid() != 0 and not self.conn.is_remote()) \
           or self.conn.get_state() is self.conn.STATE_DISCONNECTED:
            self.window.get_widget("net-add").set_sensitive(False)


        self.window.signal_autoconnect({
            "on_menu_file_close_activate": self.close,
            "on_vmm_host_delete_event": self.close,
            "on_menu_help_about_activate": self.show_help,
            "on_net_add_clicked": self.add_network,
            "on_net_delete_clicked": self.delete_network,
            "on_net_stop_clicked": self.stop_network,
            "on_net_start_clicked": self.start_network,
            "on_config_autoconnect_toggled": self.toggle_autoconnect,
            })

        self.conn.connect("resources-sampled", self.refresh_resources)
        self.conn.connect("net-started", self.refresh_network)
        self.conn.connect("net-stopped", self.refresh_network)
        self.refresh_resources()

    def show(self):
        # Update autostart value
        self.window.get_widget("config-autoconnect").set_active(self.conn.get_autoconnect())
        dialog = self.window.get_widget("vmm-host")
        dialog.present()

    def is_visible(self):
        if self.window.get_widget("vmm-host").flags() & gtk.VISIBLE:
           return 1
        return 0

    def delete_network(self, src):
        net = self.current_network()
        if net is not None:
            net.delete()

    def start_network(self, src):
        net = self.current_network()
        if net is not None:
            net.start()

    def stop_network(self, src):
        net = self.current_network()
        if net is not None:
            net.stop()

    def add_network(self, src):
        if self.conn.is_remote():
            self.err.val_err(_("Creating new networks on remote connections is not yet supported"))
            return

        if self.add is None:
            self.add = vmmCreateNetwork(self.config, self.conn)
        self.add.show()

    def toggle_autoconnect(self, ignore=None):
        if self.conn.get_autoconnect() != \
           self.window.get_widget("config-autoconnect").get_active():
            self.conn.toggle_autoconnect()

    def show_help(self, src):
        # From the Details window, show the help document from the Details page
        self.emit("action-show-help", "virt-manager-host-window")

    def show_help(self, src):
        # From the Details window, show the help document from the Details page
        self.emit("action-show-help", "virt-manager-host-window")

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-host").hide()
        return 1

    def refresh_resources(self, ignore=None):
        self.window.get_widget("performance-cpu").set_text("%d %%" % self.conn.cpu_time_percentage())
        vm_memory = self.conn.pretty_current_memory()
        host_memory = self.conn.pretty_host_memory_size()
        self.window.get_widget("performance-memory").set_text("%s of %s" % (vm_memory, host_memory))

        cpu_vector = self.conn.cpu_time_vector()
        cpu_vector.reverse()
        self.cpu_usage_graph.set_property("data_array", cpu_vector)

        memory_vector = self.conn.current_memory_vector()
        memory_vector.reverse()
        self.memory_usage_graph.set_property("data_array", memory_vector)

    def current_network(self):
        sel = self.window.get_widget("net-list").get_selection()
        active = sel.get_selected()
        if active[1] != None:
            curruuid = active[0].get_value(active[1], 0)
            return self.conn.get_net(curruuid)
        return None

    def refresh_network(self, src, uri, uuid):
        sel = self.window.get_widget("net-list").get_selection()
        active = sel.get_selected()
        if active[1] != None:
            curruuid = active[0].get_value(active[1], 0)
            if curruuid == uuid:
                self.net_selected(sel)

    def net_selected(self, src):
        active = src.get_selected()
        if active[1] != None:
            uuid = active[0].get_value(active[1], 0)
            if uuid is None:
                self.window.get_widget("net-details").set_sensitive(False)
            else:
                self.window.get_widget("net-details").set_sensitive(True)
                net = self.conn.get_net(uuid)
                self.window.get_widget("net-name").set_text(net.get_name())
                self.window.get_widget("net-uuid").set_text(net.get_uuid())

                if net.is_active():
                    self.window.get_widget("net-device").set_text(net.get_bridge_device())
                    self.window.get_widget("net-device").set_sensitive(True)
                    self.window.get_widget("net-state").set_text(_("Active"))
                    self.window.get_widget("net-state-icon").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/state_running.png", 18, 18))
                    self.window.get_widget("net-start").set_sensitive(False)
                    self.window.get_widget("net-stop").set_sensitive(True)
                    self.window.get_widget("net-delete").set_sensitive(False)
                else:
                    self.window.get_widget("net-device").set_text("")
                    self.window.get_widget("net-device").set_sensitive(False)
                    self.window.get_widget("net-state").set_text(_("Inactive"))
                    self.window.get_widget("net-state-icon").set_from_pixbuf(gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/state_shutoff.png", 18, 18))
                    self.window.get_widget("net-start").set_sensitive(True)
                    self.window.get_widget("net-stop").set_sensitive(False)
                    self.window.get_widget("net-delete").set_sensitive(True)

                autostart = True
                try:
                    autostart = net.get_autostart()
                except:
                    # Hack, libvirt 0.2.1 is missing python binding for the autostart method
                    pass
                if autostart:
                    self.window.get_widget("net-autostart").set_text(_("On boot"))
                    self.window.get_widget("net-autostart-icon").set_from_stock(gtk.STOCK_YES, gtk.ICON_SIZE_MENU)
                else:
                    self.window.get_widget("net-autostart").set_text(_("Never"))
                    self.window.get_widget("net-autostart-icon").set_from_stock(gtk.STOCK_NO, gtk.ICON_SIZE_MENU)

                network = net.get_ipv4_network()
                self.window.get_widget("net-ip4-network").set_text(str(network))

                dhcp = net.get_ipv4_dhcp_range()
                self.window.get_widget("net-ip4-dhcp-start").set_text(str(dhcp[0]))
                self.window.get_widget("net-ip4-dhcp-end").set_text(str(dhcp[1]))

                (forward, forwardDev) = net.get_ipv4_forward()
                if forward:
                    self.window.get_widget("net-ip4-forwarding-icon").set_from_stock(gtk.STOCK_CONNECT, gtk.ICON_SIZE_MENU)
                    if forwardDev != None and forwardDev != "":
                        self.window.get_widget("net-ip4-forwarding").set_text(_("NAT to physical device %s") % (forwardDev))
                    else:
                        self.window.get_widget("net-ip4-forwarding").set_text(_("NAT to any physical device"))
                else:
                    self.window.get_widget("net-ip4-forwarding-icon").set_from_stock(gtk.STOCK_DISCONNECT, gtk.ICON_SIZE_MENU)
                    self.window.get_widget("net-ip4-forwarding").set_text(_("Isolated virtual network"))
        else:
            self.window.get_widget("net-details").set_sensitive(False)

    def repopulate_networks(self, src, uri, uuid):
        self.populate_networks(self.window.get_widget("net-list").get_model())

    def populate_networks(self, model):
        model.clear()
        for uuid in self.conn.list_net_uuids():
            net = self.conn.get_net(uuid)
            model.append([uuid, net.get_name(), gtk.STOCK_NETWORK])


gobject.type_register(vmmHost)
