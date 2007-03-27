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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import gobject
import gtk
import gtk.glade
import libvirt
import sparkline
import logging

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

        self.window.get_widget("overview-hostname").set_text(self.conn.get_hostname())
        self.window.get_widget("overview-hypervisor").set_text(self.conn.get_type())
        self.window.get_widget("overview-memory").set_text(self.conn.pretty_host_memory_size())
        self.window.get_widget("overview-cpus").set_text(str(self.conn.host_active_processor_count()))
        self.window.get_widget("overview-arch").set_text(self.conn.host_architecture())

        netListModel = gtk.ListStore(str, str, gtk.gdk.Pixbuf)
        self.window.get_widget("net-list").set_model(netListModel)
        self.populate_networks(netListModel)

        self.window.get_widget("net-list").get_selection().connect("changed", self.net_selected)

        netCol = gtk.TreeViewColumn("Networks")
        net_txt = gtk.CellRendererText()
        net_img = gtk.CellRendererPixbuf()
        netCol.pack_start(net_txt, True)
        netCol.pack_start(net_img, False)
        netCol.add_attribute(net_txt, 'text', 1)
        netCol.add_attribute(net_img, 'pixbuf', 2)

        self.window.get_widget("net-list").append_column(netCol)
        self.window.get_widget("net-details").set_sensitive(False)

        self.cpu_usage_graph = sparkline.Sparkline()
        self.cpu_usage_graph.show()
        self.window.get_widget("performance-table").attach(self.cpu_usage_graph, 1, 2, 0, 1)

        self.memory_usage_graph = sparkline.Sparkline()
        self.memory_usage_graph.show()
        self.window.get_widget("performance-table").attach(self.memory_usage_graph, 1, 2, 1, 2)


        self.window.get_widget("details-tabs").get_nth_page(2).hide()

        self.window.signal_autoconnect({
            "on_menu_file_close_activate": self.close,
            "on_vmm_host_delete_event": self.close,
            "on_menu_help_about_activate": self.show_help,
            })

        self.conn.connect("resources-sampled", self.refresh_resources)

    def show(self):
        dialog = self.window.get_widget("vmm-host")
        dialog.present()

    def is_visible(self):
        if self.window.get_widget("vmm-host").flags() & gtk.VISIBLE:
           return 1
        return 0

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
                self.window.get_widget("net-device").set_text(net.get_bridge_device())

                ip4 = net.get_ip4_config()
                self.window.get_widget("net-ip4-address").set_text(ip4[0])
                self.window.get_widget("net-ip4-netmask").set_text(ip4[1])
                self.window.get_widget("net-ip4-dhcp-start").set_text(ip4[2])
                self.window.get_widget("net-ip4-dhcp-end").set_text(ip4[3])

                if ip4[4] != None and ip4[4] != "":
                    self.window.get_widget("net-ip4-forwarding").set_text(_("NAT to physical device ") + ip4[4])
                else:
                    self.window.get_widget("net-ip4-forwarding").set_text(_("Masquerade to default route"))
        else:
            self.window.get_widget("net-details").set_sensitive(False)

    def populate_networks(self, model):
        model.clear()
        for uuid in self.conn.list_net_uuids():
            net = self.conn.get_net(uuid)
            model.append([uuid, net.get_name(), gtk.gdk.pixbuf_new_from_file(self.config.get_icon_dir() + "/icon_ethernet.png")])

        #model.append([None, "Add network", gtk.gdk.pixbuf_new_from_file(self.config.get_icon_dir() + "/icon_addnew.png")])


gobject.type_register(vmmHost)
