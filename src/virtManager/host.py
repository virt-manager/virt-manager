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
import traceback

from virtinst import Storage

from virtManager.createnet import vmmCreateNetwork
from virtManager.createpool import vmmCreatePool
from virtManager.createvol import vmmCreateVolume
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

        self.PIXBUF_STATE_RUNNING = gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/state_running.png", 18, 18)
        self.PIXBUF_STATE_SHUTOFF = gtk.gdk.pixbuf_new_from_file_at_size(self.config.get_icon_dir() + "/state_shutoff.png", 18, 18)

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

        poolListModel = gtk.ListStore(str, str, float)
        self.window.get_widget("pool-list").set_model(poolListModel)
        self.populate_storage_pools(poolListModel)

        volListModel = gtk.ListStore(str, str, str, str, str)
        self.window.get_widget("vol-list").set_model(volListModel)

        self.window.get_widget("net-list").get_selection().connect("changed", self.net_selected)
        self.window.get_widget("pool-list").get_selection().connect("changed", self.pool_selected)
        self.window.get_widget("vol-list").get_selection().connect("changed", self.vol_selected)

        netCol = gtk.TreeViewColumn("Networks")
        net_txt = gtk.CellRendererText()
        net_img = gtk.CellRendererPixbuf()
        netCol.pack_start(net_txt, True)
        netCol.pack_start(net_img, False)
        netCol.add_attribute(net_txt, 'text', 1)
        netCol.add_attribute(net_img, 'stock-id', 2)
        self.window.get_widget("net-list").append_column(netCol)
        netListModel.set_sort_column_id(1, gtk.SORT_ASCENDING)

        poolCol = gtk.TreeViewColumn("Pools")
        pool_txt = gtk.CellRendererText()
        pool_prg = gtk.CellRendererProgress()
        poolCol.pack_start(pool_txt, True)
        poolCol.pack_start(pool_prg, False)
        poolCol.add_attribute(pool_txt, 'text', 1)
        poolCol.add_attribute(pool_prg, 'value', 2)
        self.window.get_widget("pool-list").append_column(poolCol)
        poolListModel.set_sort_column_id(1, gtk.SORT_ASCENDING)

        volCol = gtk.TreeViewColumn("Volumes")
        vol_txt1 = gtk.CellRendererText()
        volCol.pack_start(vol_txt1, True)
        volCol.add_attribute(vol_txt1, 'text', 1)
        volCol.set_sort_column_id(1)
        self.window.get_widget("net-details").set_sensitive(False)
        self.window.get_widget("vol-list").append_column(volCol)

        volSizeCol = gtk.TreeViewColumn("Size")
        vol_txt2 = gtk.CellRendererText()
        volSizeCol.pack_start(vol_txt2, False)
        volSizeCol.add_attribute(vol_txt2, 'text', 2)
        volSizeCol.set_sort_column_id(2)
        self.window.get_widget("vol-list").append_column(volSizeCol)

        volFormatCol = gtk.TreeViewColumn("Format")
        vol_txt3 = gtk.CellRendererText()
        volFormatCol.pack_start(vol_txt3, False)
        volFormatCol.add_attribute(vol_txt3, 'text', 3)
        volFormatCol.set_sort_column_id(3)
        self.window.get_widget("vol-list").append_column(volFormatCol)

        volPathCol = gtk.TreeViewColumn("Path")
        vol_txt4 = gtk.CellRendererText()
        volPathCol.pack_start(vol_txt4, False)
        volPathCol.add_attribute(vol_txt4, 'text', 4)
        volPathCol.set_sort_column_id(4)
        self.window.get_widget("vol-list").append_column(volPathCol)

        volListModel.set_sort_column_id(1, gtk.SORT_ASCENDING)

        self.cpu_usage_graph = sparkline.Sparkline()
        self.cpu_usage_graph.show()
        self.window.get_widget("performance-table").attach(self.cpu_usage_graph, 1, 2, 0, 1)

        self.memory_usage_graph = sparkline.Sparkline()
        self.memory_usage_graph.show()
        self.window.get_widget("performance-table").attach(self.memory_usage_graph, 1, 2, 1, 2)

        self.addnet = None
        self.addpool = None
        self.addvol = None

        self.conn.connect("net-added", self.repopulate_networks)
        self.conn.connect("net-removed", self.repopulate_networks)
        self.conn.connect("net-started", self.refresh_network)
        self.conn.connect("net-stopped", self.refresh_network)

        self.conn.connect("pool-added", self.repopulate_storage_pools)
        self.conn.connect("pool-removed", self.repopulate_storage_pools)
        self.conn.connect("pool-started", self.refresh_storage_pool)
        self.conn.connect("pool-stopped", self.refresh_storage_pool)

        self.window.signal_autoconnect({
            "on_menu_file_close_activate": self.close,
            "on_vmm_host_delete_event": self.close,
            "on_menu_help_contents_activate": self.show_help,
            "on_net_add_clicked": self.add_network,
            "on_net_delete_clicked": self.delete_network,
            "on_net_stop_clicked": self.stop_network,
            "on_net_start_clicked": self.start_network,
            "on_net_autostart_toggled": self.net_autostart_changed,
            "on_net_apply_clicked": self.net_apply,
            "on_pool_add_clicked" : self.add_pool,
            "on_vol_add_clicked" : self.add_vol,
            "on_pool_stop_clicked": self.stop_pool,
            "on_pool_start_clicked": self.start_pool,
            "on_pool_delete_clicked": self.delete_pool,
            "on_pool_autostart_toggled": self.pool_autostart_changed,
            "on_vol_delete_clicked": self.delete_vol,
            "on_pool_apply_clicked": self.pool_apply,
            "on_config_autoconnect_toggled": self.toggle_autoconnect,
            })

        self.conn.connect("resources-sampled", self.refresh_resources)
        self.refresh_resources()
        self.reset_pool_state()
        self.reset_net_state()

    def show(self):
        # Update autostart value
        self.window.get_widget("config-autoconnect").set_active(self.conn.get_autoconnect())
        dialog = self.window.get_widget("vmm-host")
        dialog.present()

    def is_visible(self):
        if self.window.get_widget("vmm-host").flags() & gtk.VISIBLE:
           return 1
        return 0

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-host").hide()
        return 1

    def show_help(self, src):
        self.emit("action-show-help", "virt-manager-host-window")

    def toggle_autoconnect(self, ignore=None):
        if self.conn.get_autoconnect() != \
           self.window.get_widget("config-autoconnect").get_active():
            self.conn.toggle_autoconnect()

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

    # -------------------------
    # Virtual Network functions
    # -------------------------

    def delete_network(self, src):
        net = self.current_network()
        if net is None:
            return

        result = self.err.yes_no(_("This will permanently delete the network "
                                   "'%s,' are you sure?") % net.get_name())
        if not result:
            return
        try:
            net.delete()
        except Exception, e:
            self.err.show_err(_("Error deleting network: %s") % str(e),
                              "".join(traceback.format_exc()))

    def start_network(self, src):
        net = self.current_network()
        if net is None:
            return

        try:
            net.start()
        except Exception, e:
            self.err.show_err(_("Error starting network: %s") % str(e),
                              "".join(traceback.format_exc()))

    def stop_network(self, src):
        net = self.current_network()
        if net is None:
            return

        try:
            net.stop()
        except Exception, e:
            self.err.show_err(_("Error stopping network: %s") % str(e),
                              "".join(traceback.format_exc()))

    def add_network(self, src):
        try:
            if self.addnet is None:
                self.addnet = vmmCreateNetwork(self.config, self.conn)
            self.addnet.show()
        except Exception, e:
            self.err.show_err(_("Error launching network wizard: %s") % str(e),
                              "".join(traceback.format_exc()))

    def net_apply(self, src):
        net = self.current_network()
        if net is None:
            return

        try:
            net.set_autostart(self.window.get_widget("net-autostart").get_active())
        except Exception, e:
            self.err.show_err(_("Error setting net autostart: %s") % str(e),
                              "".join(traceback.format_exc()))
            return
        self.window.get_widget("net-apply").set_sensitive(False)

    def net_autostart_changed(self, src):
        auto = self.window.get_widget("net-autostart").get_active()
        self.window.get_widget("net-autostart").set_label(auto and \
                                                          _("On Boot") or \
                                                          _("Never"))
        self.window.get_widget("net-apply").set_sensitive(True)

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
        selected = src.get_selected()
        if selected[1] == None or \
           selected[0].get_value(selected[1], 0) == None:
            self.reset_net_state()
            return
        net = self.conn.get_net(selected[0].get_value(selected[1], 0))
        active = net.is_active()

        self.window.get_widget("net-details").set_sensitive(True)
        self.window.get_widget("net-name").set_text(net.get_name())

        if active:
            self.window.get_widget("net-device").set_text(net.get_bridge_device())
            self.window.get_widget("net-device").set_sensitive(True)
            self.window.get_widget("net-state").set_text(_("Active"))
            self.window.get_widget("net-state-icon").set_from_pixbuf(self.PIXBUF_STATE_RUNNING)
        else:
            self.window.get_widget("net-device").set_text("")
            self.window.get_widget("net-device").set_sensitive(False)
            self.window.get_widget("net-state").set_text(_("Inactive"))
            self.window.get_widget("net-state-icon").set_from_pixbuf(self.PIXBUF_STATE_SHUTOFF)

        self.window.get_widget("net-start").set_sensitive(not active)
        self.window.get_widget("net-stop").set_sensitive(active)
        self.window.get_widget("net-delete").set_sensitive(not active)

        autostart = net.get_autostart()
        self.window.get_widget("net-autostart").set_active(autostart)
        if autostart:
            self.window.get_widget("net-autostart").set_label(_("On Boot"))
        else:
            self.window.get_widget("net-autostart").set_label(_("Never"))

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

        self.window.get_widget("net-apply").set_sensitive(False)

    def reset_net_state(self):
        self.window.get_widget("net-details").set_sensitive(False)
        self.window.get_widget("net-name").set_text("")
        self.window.get_widget("net-device").set_text("")
        self.window.get_widget("net-device").set_sensitive(False)
        self.window.get_widget("net-state").set_text(_("Inactive"))
        self.window.get_widget("net-state-icon").set_from_pixbuf(self.PIXBUF_STATE_SHUTOFF)
        self.window.get_widget("net-start").set_sensitive(False)
        self.window.get_widget("net-stop").set_sensitive(False)
        self.window.get_widget("net-delete").set_sensitive(False)
        self.window.get_widget("net-autostart").set_label(_("Never"))
        self.window.get_widget("net-autostart").set_active(False)
        self.window.get_widget("net-ip4-network").set_text("")
        self.window.get_widget("net-ip4-dhcp-start").set_text("")
        self.window.get_widget("net-ip4-dhcp-end").set_text("")
        self.window.get_widget("net-ip4-forwarding-icon").set_from_stock(gtk.STOCK_DISCONNECT, gtk.ICON_SIZE_MENU)
        self.window.get_widget("net-ip4-forwarding").set_text(_("Isolated virtual network"))
        self.window.get_widget("net-apply").set_sensitive(False)

    def repopulate_networks(self, src, uri, uuid):
        self.populate_networks(self.window.get_widget("net-list").get_model())

    def populate_networks(self, model):
        model.clear()
        for uuid in self.conn.list_net_uuids():
            net = self.conn.get_net(uuid)
            model.append([uuid, net.get_name(), gtk.STOCK_NETWORK])


    # ------------------------------
    # Storage Manager methods
    # ------------------------------


    def stop_pool(self, src):
        pool = self.current_pool()
        if pool is not None:
            try:
                pool.stop()
            except Exception, e:
                self.err.show_err(_("Error starting pool '%s': %s") % \
                                    (pool.get_name(), str(e)),
                                  "".join(traceback.format_exc()))

    def start_pool(self, src):
        pool = self.current_pool()
        if pool is not None:
            try:
                pool.start()
            except Exception, e:
                self.err.show_err(_("Error starting pool '%s': %s") % \
                                    (pool.get_name(), str(e)),
                                  "".join(traceback.format_exc()))

    def delete_pool(self, src):
        pool = self.current_pool()
        if pool is None:
            return

        result = self.err.yes_no(_("This will permanently delete the pool "
                                   "'%s,' are you sure?") % pool.get_name())
        if not result:
            return
        try:
            pool.delete()
        except Exception, e:
            self.err.show_err(_("Error deleting pool: %s") % str(e),
                              "".join(traceback.format_exc()))

    def delete_vol(self, src):
        vol = self.current_vol()
        if vol is None:
            return

        result = self.err.yes_no(_("This will permanently delete the volume "
                                   "'%s,' are you sure?") % vol.get_name())
        if not result:
            return

        try:
            vol.delete()
            self.refresh_current_pool()
        except Exception, e:
            self.err.show_err(_("Error deleting volume: %s") % str(e),
                              "".join(traceback.format_exc()))
            return
        self.populate_storage_volumes()

    def add_pool(self, src):
        try:
            if self.addpool is None:
                self.addpool = vmmCreatePool(self.config, self.conn)
            self.addpool.show()
        except Exception, e:
            self.err.show_err(_("Error launching pool wizard: %s") % str(e),
                              "".join(traceback.format_exc()))

    def add_vol(self, src):
        pool = self.current_pool()
        if pool is None:
            return
        try:
            if self.addvol is None:
                self.addvol = vmmCreateVolume(self.config, self.conn, pool)
                self.addvol.connect("vol-created", self.refresh_current_pool)
            else:
                self.addvol.set_parent_pool(pool)
            self.addvol.show()
        except Exception, e:
            self.err.show_err(_("Error launching volume wizard: %s") % str(e),
                              "".join(traceback.format_exc()))

    def refresh_current_pool(self, ignore1=None):
        cp = self.current_pool()
        if cp is None:
            return
        cp.refresh()
        self.refresh_storage_pool(None, None, cp.get_uuid())

    def current_pool(self):
        sel = self.window.get_widget("pool-list").get_selection()
        active = sel.get_selected()
        if active[1] != None:
            curruuid = active[0].get_value(active[1], 0)
            return self.conn.get_pool(curruuid)
        return None

    def current_vol(self):
        pool = self.current_pool()
        if not pool:
            return None
        sel = self.window.get_widget("vol-list").get_selection()
        active = sel.get_selected()
        if active[1] != None:
            curruuid = active[0].get_value(active[1], 0)
            return pool.get_volume(curruuid)
        return None

    def pool_apply(self, src):
        pool = self.current_pool()
        if pool is None:
            return

        try:
            pool.set_autostart(self.window.get_widget("pool-autostart").get_active())
        except Exception, e:
            self.err.show_err(_("Error setting pool autostart: %s") % str(e),
                              "".join(traceback.format_exc()))
            return
        self.window.get_widget("pool-apply").set_sensitive(False)

    def pool_autostart_changed(self, src):
        auto = self.window.get_widget("pool-autostart").get_active()
        self.window.get_widget("pool-autostart").set_label(auto and \
                                                           _("On Boot") or \
                                                           _("Never"))
        self.window.get_widget("pool-apply").set_sensitive(True)

    def pool_selected(self, src):
        selected = src.get_selected()
        if selected[1] is None or \
           selected[0].get_value(selected[1], 0) is None:
            self.reset_pool_state()
            return

        uuid = selected[0].get_value(selected[1], 0)
        pool = self.conn.get_pool(uuid)
        auto = pool.get_autostart()
        active = pool.is_active()

        # Set pool details state
        self.window.get_widget("pool-details").set_sensitive(True)
        self.window.get_widget("pool-name").set_markup("<b>%s:</b>" % \
                                                       pool.get_name())
        self.window.get_widget("pool-sizes").set_markup("""<span size="large">%s Free</span> / <i>%s In Use</i>""" % (pool.get_pretty_available(), pool.get_pretty_allocation()))
        self.window.get_widget("pool-type").set_text(Storage.StoragePool.get_pool_type_desc(pool.get_type()))
        self.window.get_widget("pool-location").set_text(pool.get_target_path())
        self.window.get_widget("pool-state-icon").set_from_pixbuf((active and self.PIXBUF_STATE_RUNNING) or self.PIXBUF_STATE_SHUTOFF)
        self.window.get_widget("pool-state").set_text((active and _("Active")) or _("Inactive"))
        self.window.get_widget("pool-autostart").set_label((auto and _("On Boot")) or _("Never"))
        self.window.get_widget("pool-autostart").set_active(auto)

        self.window.get_widget("vol-list").set_sensitive(active)
        self.populate_storage_volumes()

        self.window.get_widget("pool-delete").set_sensitive(not active)
        self.window.get_widget("pool-stop").set_sensitive(active)
        self.window.get_widget("pool-start").set_sensitive(not active)
        self.window.get_widget("pool-apply").set_sensitive(False)
        self.window.get_widget("vol-add").set_sensitive(active)
        self.window.get_widget("vol-delete").set_sensitive(False)

    def refresh_storage_pool(self, src, uri, uuid):
        sel = self.window.get_widget("pool-list").get_selection()
        model = self.window.get_widget("pool-list").get_model()
        active = sel.get_selected()
        if active[1] == None:
            return
        curruuid = active[0].get_value(active[1], 0)
        if curruuid != uuid:
            return
        self.pool_selected(sel)
        for row in model:
            if row[0] == curruuid:
                row[2] = self.get_pool_size_percent(uuid)
                break

    def reset_pool_state(self):
        self.window.get_widget("pool-details").set_sensitive(False)
        self.window.get_widget("pool-name").set_text("")
        self.window.get_widget("pool-sizes").set_markup("""<span size="large"> </span>""")
        self.window.get_widget("pool-type").set_text("")
        self.window.get_widget("pool-location").set_text("")
        self.window.get_widget("pool-state-icon").set_from_pixbuf(self.PIXBUF_STATE_SHUTOFF)
        self.window.get_widget("pool-state").set_text(_("Inactive"))
        self.window.get_widget("vol-list").get_model().clear()
        self.window.get_widget("pool-autostart").set_label(_("Never"))
        self.window.get_widget("pool-autostart").set_active(False)

        self.window.get_widget("pool-delete").set_sensitive(False)
        self.window.get_widget("pool-stop").set_sensitive(False)
        self.window.get_widget("pool-start").set_sensitive(False)
        self.window.get_widget("pool-apply").set_sensitive(False)
        self.window.get_widget("vol-add").set_sensitive(False)
        self.window.get_widget("vol-delete").set_sensitive(False)
        self.window.get_widget("vol-list").set_sensitive(False)

    def vol_selected(self, src):
        selected = src.get_selected()
        if selected[1] is None or \
           selected[0].get_value(selected[1], 0) is None:
            self.window.get_widget("vol-delete").set_sensitive(False)
            return

        self.window.get_widget("vol-delete").set_sensitive(True)

    def repopulate_storage_pools(self, src, uri, uuid):
        self.populate_storage_pools(self.window.get_widget("pool-list").get_model())

    def get_pool_size_percent(self, uuid):
        pool = self.conn.get_pool(uuid)
        cap = pool.get_capacity()
        all = pool.get_allocation()
        if not cap or all is None:
            per = 0
        else:
            per = int(((float(all) / float(cap)) * 100))
        return per

    def populate_storage_pools(self, model):
        model.clear()
        for uuid in self.conn.list_pool_uuids():
            per = self.get_pool_size_percent(uuid)
            pool = self.conn.get_pool(uuid)
            model.append([uuid, pool.get_name(), per])

    def populate_storage_volumes(self):
        pool = self.current_pool()
        model = self.window.get_widget("vol-list").get_model()
        model.clear()
        vols = pool.get_volumes()
        for key in vols.keys():
            vol = vols[key]
            model.append([key, vol.get_name(), vol.get_pretty_capacity(),
                          vol.get_format() or "", vol.get_target_path() or ""])

gobject.type_register(vmmHost)
