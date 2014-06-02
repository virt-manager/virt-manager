#
# Copyright (C) 2007, 2013 Red Hat, Inc.
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

import logging

from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk

from virtinst import VirtualDisk
from virtinst import StoragePool
from virtinst import Interface

from virtManager import uiutil
from virtManager.asyncjob import vmmAsyncJob
from virtManager.connection import vmmConnection
from virtManager.createnet import vmmCreateNetwork
from virtManager.createpool import vmmCreatePool
from virtManager.createvol import vmmCreateVolume
from virtManager.createinterface import vmmCreateInterface
from virtManager.baseclass import vmmGObjectUI
from virtManager.graphwidgets import Sparkline

INTERFACE_PAGE_INFO = 0
INTERFACE_PAGE_ERROR = 1

(EDIT_NET_NAME,
EDIT_NET_AUTOSTART,

EDIT_POOL_NAME,
EDIT_POOL_AUTOSTART,
) = range(4)


class vmmHost(vmmGObjectUI):
    __gsignals__ = {
        "action-exit-app": (GObject.SignalFlags.RUN_FIRST, None, []),
        "action-view-manager": (GObject.SignalFlags.RUN_FIRST, None, []),
        "action-restore-domain": (GObject.SignalFlags.RUN_FIRST, None, [str]),
        "host-closed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "host-opened": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "host.ui", "vmm-host")
        self.conn = conn

        self.title = conn.get_short_hostname() + " " + self.topwin.get_title()
        self.topwin.set_title(self.title)

        self.ICON_RUNNING = "state_running"
        self.ICON_SHUTOFF = "state_shutoff"

        self.addnet = None
        self.addpool = None
        self.addvol = None
        self.addinterface = None
        self.volmenu = None
        self._in_refresh = False

        self.active_edits = []

        self.cpu_usage_graph = None
        self.memory_usage_graph = None
        self.init_conn_state()

        self.init_net_state()
        self.init_storage_state()
        self.init_interface_state()

        self.builder.connect_signals({
            "on_menu_file_view_manager_activate" : self.view_manager,
            "on_menu_file_quit_activate" : self.exit_app,
            "on_menu_file_close_activate": self.close,
            "on_vmm_host_delete_event": self.close,
            "on_host_page_switch": self.page_changed,

            "on_menu_restore_saved_activate": self.restore_domain,

            "on_net_add_clicked": self.add_network,
            "on_net_delete_clicked": self.delete_network,
            "on_net_stop_clicked": self.stop_network,
            "on_net_start_clicked": self.start_network,
            "on_net_apply_clicked": self.net_apply,
            "on_net_list_changed": self.net_selected,
            "on_net_autostart_toggled": self.net_autostart_changed,
            "on_net_name_changed": (lambda *x:
                self.enable_net_apply(x, EDIT_NET_NAME)),

            "on_pool_add_clicked" : self.add_pool,
            "on_vol_add_clicked" : self.add_vol,
            "on_pool_stop_clicked": self.stop_pool,
            "on_pool_start_clicked": self.start_pool,
            "on_pool_delete_clicked": self.delete_pool,
            "on_pool_refresh_clicked": self.pool_refresh,
            "on_pool_autostart_toggled": self.pool_autostart_changed,
            "on_vol_delete_clicked": self.delete_vol,
            "on_vol_list_button_press_event": self.popup_vol_menu,
            "on_pool_apply_clicked": self.pool_apply,
            "on_vol_list_changed": self.vol_selected,
            "on_pool_name_changed": (lambda *x:
                self.enable_pool_apply(x, EDIT_POOL_NAME)),

            "on_interface_add_clicked" : self.add_interface,
            "on_interface_start_clicked" : self.start_interface,
            "on_interface_stop_clicked" : self.stop_interface,
            "on_interface_delete_clicked" : self.delete_interface,
            "on_interface_startmode_changed": self.interface_startmode_changed,
            "on_interface_apply_clicked" : self.interface_apply,
            "on_interface_list_changed": self.interface_selected,

            "on_config_autoconnect_toggled": self.toggle_autoconnect,
        })

        self.repopulate_networks()
        self.repopulate_storage_pools()
        self.repopulate_interfaces()

        self.conn.connect("net-added", self.repopulate_networks)
        self.conn.connect("net-removed", self.repopulate_networks)
        self.conn.connect("net-started", self.refresh_network)
        self.conn.connect("net-stopped", self.refresh_network)

        self.conn.connect("pool-added", self.repopulate_storage_pools)
        self.conn.connect("pool-removed", self.repopulate_storage_pools)
        self.conn.connect("pool-started", self.refresh_storage_pool)
        self.conn.connect("pool-stopped", self.refresh_storage_pool)

        self.conn.connect("interface-added", self.repopulate_interfaces)
        self.conn.connect("interface-removed", self.repopulate_interfaces)
        self.conn.connect("interface-started", self.refresh_interface)
        self.conn.connect("interface-stopped", self.refresh_interface)

        self.conn.connect("state-changed", self.conn_state_changed)
        self.conn.connect("resources-sampled", self.refresh_resources)
        self.reset_state()


    def init_net_state(self):
        self.widget("network-pages").set_show_tabs(False)

        # [ unique, label, icon name, icon size, is_active ]
        netListModel = Gtk.ListStore(str, str, str, int, bool)
        self.widget("net-list").set_model(netListModel)

        netCol = Gtk.TreeViewColumn("Networks")
        netCol.set_spacing(6)
        net_txt = Gtk.CellRendererText()
        net_img = Gtk.CellRendererPixbuf()
        netCol.pack_start(net_img, False)
        netCol.pack_start(net_txt, True)
        netCol.add_attribute(net_txt, 'text', 1)
        netCol.add_attribute(net_txt, 'sensitive', 4)
        netCol.add_attribute(net_img, 'icon-name', 2)
        netCol.add_attribute(net_img, 'stock-size', 3)
        self.widget("net-list").append_column(netCol)
        netListModel.set_sort_column_id(1, Gtk.SortType.ASCENDING)

    def init_storage_state(self):
        self.widget("storage-pages").set_show_tabs(False)

        self.volmenu = Gtk.Menu()
        volCopyPath = Gtk.ImageMenuItem.new_with_label(_("Copy Volume Path"))
        volCopyImage = Gtk.Image()
        volCopyImage.set_from_stock(Gtk.STOCK_COPY, Gtk.IconSize.MENU)
        volCopyPath.set_image(volCopyImage)
        volCopyPath.show()
        volCopyPath.connect("activate", self.copy_vol_path)
        self.volmenu.add(volCopyPath)

        volListModel = Gtk.ListStore(str, str, str, str, str)
        self.widget("vol-list").set_model(volListModel)

        volCol = Gtk.TreeViewColumn("Volumes")
        vol_txt1 = Gtk.CellRendererText()
        volCol.pack_start(vol_txt1, True)
        volCol.add_attribute(vol_txt1, 'text', 1)
        volCol.set_sort_column_id(1)
        self.widget("vol-list").append_column(volCol)

        volSizeCol = Gtk.TreeViewColumn("Size")
        vol_txt2 = Gtk.CellRendererText()
        volSizeCol.pack_start(vol_txt2, False)
        volSizeCol.add_attribute(vol_txt2, 'text', 2)
        volSizeCol.set_sort_column_id(2)
        self.widget("vol-list").append_column(volSizeCol)

        volFormatCol = Gtk.TreeViewColumn("Format")
        vol_txt3 = Gtk.CellRendererText()
        volFormatCol.pack_start(vol_txt3, False)
        volFormatCol.add_attribute(vol_txt3, 'text', 3)
        volFormatCol.set_sort_column_id(3)
        self.widget("vol-list").append_column(volFormatCol)

        volUseCol = Gtk.TreeViewColumn("Used By")
        vol_txt4 = Gtk.CellRendererText()
        volUseCol.pack_start(vol_txt4, False)
        volUseCol.add_attribute(vol_txt4, 'text', 4)
        volUseCol.set_sort_column_id(4)
        self.widget("vol-list").append_column(volUseCol)

        volListModel.set_sort_column_id(1, Gtk.SortType.ASCENDING)

        init_pool_list(self.widget("pool-list"), self.pool_selected)

    def init_interface_state(self):
        self.widget("interface-pages").set_show_tabs(False)

        # [ unique, label, icon name, icon size, is_active ]
        interfaceListModel = Gtk.ListStore(str, str, str, int, bool)
        self.widget("interface-list").set_model(interfaceListModel)

        interfaceCol = Gtk.TreeViewColumn("Interfaces")
        interfaceCol.set_spacing(6)
        interface_txt = Gtk.CellRendererText()
        interface_img = Gtk.CellRendererPixbuf()
        interfaceCol.pack_start(interface_img, False)
        interfaceCol.pack_start(interface_txt, True)
        interfaceCol.add_attribute(interface_txt, 'text', 1)
        interfaceCol.add_attribute(interface_txt, 'sensitive', 4)
        interfaceCol.add_attribute(interface_img, 'icon-name', 2)
        interfaceCol.add_attribute(interface_img, 'stock-size', 3)
        self.widget("interface-list").append_column(interfaceCol)
        interfaceListModel.set_sort_column_id(1, Gtk.SortType.ASCENDING)

        # Startmode combo
        vmmCreateInterface.build_interface_startmode_combo(
            self.widget("interface-startmode"))

        # [ name, type ]
        childListModel = Gtk.ListStore(str, str)
        childList = self.widget("interface-child-list")
        childList.set_model(childListModel)

        childNameCol = Gtk.TreeViewColumn("Name")
        child_txt1 = Gtk.CellRendererText()
        childNameCol.pack_start(child_txt1, True)
        childNameCol.add_attribute(child_txt1, 'text', 0)
        childNameCol.set_sort_column_id(0)
        childList.append_column(childNameCol)

        childTypeCol = Gtk.TreeViewColumn("Interface Type")
        child_txt2 = Gtk.CellRendererText()
        childTypeCol.pack_start(child_txt2, True)
        childTypeCol.add_attribute(child_txt2, 'text', 1)
        childTypeCol.set_sort_column_id(1)
        childList.append_column(childTypeCol)
        childListModel.set_sort_column_id(0, Gtk.SortType.ASCENDING)

    def init_conn_state(self):
        uri = self.conn.get_uri()
        host = self.conn.get_hostname()
        drv = self.conn.get_driver()
        memory = self.conn.pretty_host_memory_size()
        proc = self.conn.host_active_processor_count()
        arch = self.conn.host_architecture()
        auto = self.conn.get_autoconnect()

        self.widget("overview-uri").set_text(uri)
        self.widget("overview-hostname").set_text(host)
        self.widget("overview-hypervisor").set_text(drv)
        self.widget("overview-memory").set_text(memory)
        self.widget("overview-cpus").set_text(str(proc))
        self.widget("overview-arch").set_text(arch)
        self.widget("config-autoconnect").set_active(auto)

        self.cpu_usage_graph = Sparkline()
        self.cpu_usage_graph.show()
        self.widget("performance-cpu-align").add(self.cpu_usage_graph)

        self.memory_usage_graph = Sparkline()
        self.memory_usage_graph.show()
        self.widget("performance-memory-align").add(self.memory_usage_graph)


    def show(self):
        logging.debug("Showing host details: %s", self.conn)
        vis = self.is_visible()
        self.topwin.present()
        if vis:
            return

        self.emit("host-opened")

    def is_visible(self):
        return self.topwin.get_visible()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing host details: %s", self.conn)
        if not self.is_visible():
            return

        self.topwin.hide()
        self.emit("host-closed")

        return 1

    def _cleanup(self):
        self.conn = None

        if self.addnet:
            self.addnet.cleanup()
            self.addnet = None

        if self.addpool:
            self.addpool.cleanup()
            self.addpool = None

        if self.addvol:
            self.addvol.cleanup()
            self.addvol = None

        if self.addinterface:
            self.addinterface.cleanup()
            self.addinterface = None

        self.volmenu.destroy()
        self.volmenu = None

        self.cpu_usage_graph.destroy()
        self.cpu_usage_graph = None

        self.memory_usage_graph.destroy()
        self.memory_usage_graph = None

    def view_manager(self, src_ignore):
        self.emit("action-view-manager")

    def restore_domain(self, src_ignore):
        self.emit("action-restore-domain", self.conn.get_uri())

    def exit_app(self, src_ignore):
        self.emit("action-exit-app")

    def reset_state(self):
        self.refresh_resources()
        self.conn_state_changed()

        # Update autostart value
        auto = self.conn.get_autoconnect()
        self.widget("config-autoconnect").set_active(auto)

    def page_changed(self, src, child, pagenum):
        ignore = src
        ignore = child
        if pagenum == 1:
            self.conn.schedule_priority_tick(pollnet=True)
        elif pagenum == 2:
            self.conn.schedule_priority_tick(pollpool=True)
        elif pagenum == 3:
            self.conn.schedule_priority_tick(polliface=True)

    def refresh_resources(self, ignore=None):
        vm_memory = self.conn.pretty_stats_memory()
        host_memory = self.conn.pretty_host_memory_size()
        cpu_vector = self.conn.host_cpu_time_vector()
        memory_vector = self.conn.stats_memory_vector()

        cpu_vector.reverse()
        memory_vector.reverse()

        self.widget("performance-cpu").set_text("%d %%" %
                                        self.conn.host_cpu_time_percentage())
        self.widget("performance-memory").set_text(
                            _("%(currentmem)s of %(maxmem)s") %
                            {'currentmem': vm_memory, 'maxmem': host_memory})

        self.cpu_usage_graph.set_property("data_array", cpu_vector)
        self.memory_usage_graph.set_property("data_array", memory_vector)

    def conn_state_changed(self, ignore1=None):
        conn_active = (self.conn.get_state() == vmmConnection.STATE_ACTIVE)
        self.widget("menu_file_restore_saved").set_sensitive(conn_active)
        self.widget("net-add").set_sensitive(conn_active and
            self.conn.is_network_capable())
        self.widget("pool-add").set_sensitive(conn_active and
            self.conn.is_storage_capable())
        self.widget("interface-add").set_sensitive(conn_active and
            self.conn.is_interface_capable())

        if not conn_active:
            self.set_net_error_page(_("Connection not active."))
            self.set_storage_error_page(_("Connection not active."))
            self.set_interface_error_page(_("Connection not active."))

            self.repopulate_networks()
            self.repopulate_storage_pools()
            self.repopulate_interfaces()
            return

        if not self.conn.is_network_capable():
            self.set_net_error_page(
                _("Libvirt connection does not support virtual network "
                  "management."))

        if not self.conn.is_storage_capable():
            self.set_storage_error_page(
                _("Libvirt connection does not support storage management."))

        if not self.conn.is_interface_capable():
            self.set_interface_error_page(
                _("Libvirt connection does not support interface management."))


    def toggle_autoconnect(self, src):
        self.conn.set_autoconnect(src.get_active())


    # -------------------------
    # Virtual Network functions
    # -------------------------

    def delete_network(self, src_ignore):
        net = self.current_network()
        if net is None:
            return

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the network %s?") % net.get_name())
        if not result:
            return

        logging.debug("Deleting network '%s'", net.get_name())
        vmmAsyncJob.simple_async_noshow(net.delete, [], self,
                            _("Error deleting network '%s'") % net.get_name())

    def start_network(self, src_ignore):
        net = self.current_network()
        if net is None:
            return

        logging.debug("Starting network '%s'", net.get_name())
        vmmAsyncJob.simple_async_noshow(net.start, [], self,
                            _("Error starting network '%s'") % net.get_name())

    def stop_network(self, src_ignore):
        net = self.current_network()
        if net is None:
            return

        logging.debug("Stopping network '%s'", net.get_name())
        vmmAsyncJob.simple_async_noshow(net.stop, [], self,
                            _("Error stopping network '%s'") % net.get_name())

    def add_network(self, src_ignore):
        logging.debug("Launching 'Add Network'")
        try:
            if self.addnet is None:
                self.addnet = vmmCreateNetwork(self.conn)
            self.addnet.show(self.topwin)
        except Exception, e:
            self.err.show_err(_("Error launching network wizard: %s") % str(e))

    def net_apply(self, src_ignore):
        net = self.current_network()
        if net is None:
            return

        logging.debug("Applying changes for network '%s'", net.get_name())
        try:
            if EDIT_NET_AUTOSTART in self.active_edits:
                auto = self.widget("net-autostart").get_active()
                net.set_autostart(auto)
            if EDIT_NET_NAME in self.active_edits:
                net.define_name(self.widget("net-name").get_text())
                self.repopulate_networks()
        except Exception, e:
            self.err.show_err(_("Error changing network settings: %s") % str(e))
            return
        finally:
            self.disable_net_apply()

    def disable_net_apply(self):
        self.active_edits = []
        self.widget("net-apply").set_sensitive(False)

    def enable_net_apply(self, *arglist):
        edittype = arglist[-1]
        self.widget("net-apply").set_sensitive(True)
        if edittype not in self.active_edits:
            self.active_edits.append(edittype)

    def net_autostart_changed(self, src_ignore):
        auto = self.widget("net-autostart").get_active()
        self.widget("net-autostart").set_label(auto and
                                               _("On Boot") or
                                               _("Never"))
        self.enable_net_apply(EDIT_NET_AUTOSTART)

    def current_network(self):
        connkey = uiutil.get_list_selection(self.widget("net-list"), 0)
        try:
            return connkey and self.conn.get_net(connkey)
        except KeyError:
            return None

    def refresh_network(self, src_ignore, connkey):
        uilist = self.widget("net-list")
        sel = uilist.get_selection()
        model, treeiter = sel.get_selected()
        net = self.conn.get_net(connkey)
        net.tick()

        for row in uilist.get_model():
            if row[0] == connkey:
                row[4] = net.is_active()

        if treeiter is not None:
            if model[treeiter][0] == connkey:
                self.net_selected(sel)

    def set_net_error_page(self, msg):
        self.reset_net_state()
        self.widget("network-pages").set_current_page(1)
        self.widget("network-error-label").set_text(msg)

    def net_selected(self, src):
        model, treeiter = src.get_selected()
        if treeiter is None:
            self.set_net_error_page(_("No virtual network selected."))
            return

        self.widget("network-pages").set_current_page(0)
        connkey = model[treeiter][0]

        try:
            net = self.conn.get_net(connkey)
        except KeyError:
            self.disable_net_apply()
            return
        except Exception, e:
            logging.exception(e)
            self.set_net_error_page(_("Error selecting network: %s") % e)

        try:
            self.populate_net_state(net)
        except Exception, e:
            logging.exception(e)
            self.set_net_error_page(_("Error selecting network: %s") % e)
        finally:
            self.disable_net_apply()

    def _populate_net_ipv4_state(self, net):
        (netstr,
         (dhcpstart, dhcpend),
         (routeaddr, routevia)) = net.get_ipv4_network()

        self.widget("net-ipv4-expander").set_visible(bool(netstr))
        if not netstr:
            return

        forward = net.get_ipv4_forward_mode()
        self.widget("net-ipv4-forwarding-icon").set_from_stock(
            forward and Gtk.STOCK_CONNECT or Gtk.STOCK_DISCONNECT,
            Gtk.IconSize.MENU)
        self.widget("net-ipv4-forwarding").set_text(net.pretty_forward_mode())

        dhcpstr = _("Disabled")
        if dhcpstart:
            dhcpstr = dhcpstart + " - " + dhcpend
        self.widget("net-ipv4-dhcp-range").set_text(dhcpstr)
        self.widget("net-ipv4-network").set_text(netstr)

        uiutil.set_grid_row_visible(
            self.widget("net-ipv4-route"), bool(routevia))
        if routevia:
            routevia = routeaddr + ", gateway=" + routevia
            self.widget("net-ipv4-route").set_text(routevia or "")


    def _populate_net_ipv6_state(self, net):
        (netstr,
         (dhcpstart, dhcpend),
         (routeaddr, routevia)) = net.get_ipv6_network()

        self.widget("net-ipv6-expander").set_visible(bool(netstr))
        self.widget("net-ipv6-forwarding-icon").set_from_stock(
            netstr and Gtk.STOCK_CONNECT or Gtk.STOCK_DISCONNECT,
            Gtk.IconSize.MENU)

        if netstr:
            prettymode = _("Routed network")
        elif net.get_ipv6_enabled():
            prettymode = _("Isolated network, internal routing only")
        else:
            prettymode = _("Isolated network, routing disabled")
        self.widget("net-ipv6-forwarding").set_text(prettymode)

        dhcpstr = _("Disabled")
        if dhcpstart:
            dhcpstr = dhcpstart + " - " + dhcpend
        self.widget("net-ipv6-dhcp-range").set_text(dhcpstr)
        self.widget("net-ipv6-network").set_text(netstr or "")

        uiutil.set_grid_row_visible(
            self.widget("net-ipv6-route"), bool(routevia))
        if routevia:
            routevia = routeaddr + ", gateway=" + routevia
            self.widget("net-ipv6-route").set_text(routevia or "")

    def populate_net_state(self, net):
        active = net.is_active()

        self.widget("net-details").set_sensitive(True)
        self.widget("net-name").set_text(net.get_name())
        self.widget("net-name").set_editable(not active)
        self.widget("net-device").set_text(net.get_bridge_device() or "")
        self.widget("net-name-domain").set_text(net.get_name_domain() or "")
        uiutil.set_grid_row_visible(self.widget("net-name-domain"),
                                       bool(net.get_name_domain()))

        state = active and _("Active") or _("Inactive")
        icon = (active and self.ICON_RUNNING or
                           self.ICON_SHUTOFF)
        self.widget("net-state").set_text(state)
        self.widget("net-state-icon").set_from_icon_name(icon,
                                                         Gtk.IconSize.BUTTON)

        self.widget("net-start").set_sensitive(not active)
        self.widget("net-stop").set_sensitive(active)
        self.widget("net-delete").set_sensitive(not active)

        autostart = net.get_autostart()
        autolabel = autostart and _("On Boot") or _("Never")
        self.widget("net-autostart").set_active(autostart)
        self.widget("net-autostart").set_label(autolabel)

        self._populate_net_ipv4_state(net)
        self._populate_net_ipv6_state(net)


    def reset_net_state(self):
        self.widget("net-details").set_sensitive(False)
        self.widget("net-name").set_text("")
        self.widget("net-device").set_text("")
        self.widget("net-state").set_text(_("Inactive"))
        self.widget("net-state-icon").set_from_icon_name(self.ICON_SHUTOFF,
                                                         Gtk.IconSize.BUTTON)
        self.widget("net-start").set_sensitive(False)
        self.widget("net-stop").set_sensitive(False)
        self.widget("net-delete").set_sensitive(False)
        self.widget("net-autostart").set_label(_("Never"))
        self.widget("net-autostart").set_active(False)
        self.widget("net-ipv4-network").set_text("")
        self.widget("net-ipv4-dhcp-range").set_text("")
        self.widget("net-ipv4-route").set_text("")
        self.widget("net-ipv4-forwarding-icon").set_from_stock(
                                    Gtk.STOCK_DISCONNECT, Gtk.IconSize.MENU)
        self.widget("net-ipv4-forwarding").set_text(
                                    _("Isolated network"))
        self.widget("net-ipv6-network").set_text("")
        self.widget("net-ipv6-dhcp-range").set_text("")
        self.widget("net-ipv6-route").set_text("")
        self.widget("net-ipv6-forwarding").set_text(
                                    _("Isolated network"))
        self.disable_net_apply()

    def repopulate_networks(self, src=None, connkey=None):
        ignore = src
        ignore = connkey
        self.populate_networks(self.widget("net-list").get_model())

    def populate_networks(self, model):
        curnet = self.current_network()

        net_list = self.widget("net-list")
        net_list.get_selection().unselect_all()
        model.clear()
        for net in self.conn.list_nets():
            model.append([net.get_connkey(), net.get_name(), "network-idle",
                          Gtk.IconSize.LARGE_TOOLBAR,
                          bool(net.is_active())])

        uiutil.set_row_selection(net_list,
            curnet and curnet.get_connkey() or None)


    # ------------------------------
    # Storage Manager methods
    # ------------------------------


    def stop_pool(self, src_ignore):
        pool = self.current_pool()
        if pool is None:
            return

        logging.debug("Stopping pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.stop, [], self,
                            _("Error stopping pool '%s'") % pool.get_name())

    def start_pool(self, src_ignore):
        pool = self.current_pool()
        if pool is None:
            return

        logging.debug("Starting pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.start, [], self,
                            _("Error starting pool '%s'") % pool.get_name())

    def delete_pool(self, src_ignore):
        pool = self.current_pool()
        if pool is None:
            return

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the pool %s?") % pool.get_name())
        if not result:
            return

        logging.debug("Deleting pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(pool.delete, [], self,
                            _("Error deleting pool '%s'") % pool.get_name())

    def pool_refresh(self, src_ignore):
        if self._in_refresh:
            logging.debug("Already refreshing the pool, skipping")
            return

        pool = self.current_pool()
        if pool is None:
            return

        self._in_refresh = True

        def cb():
            try:
                pool.refresh()
                self.idle_add(self.refresh_current_pool)
            finally:
                self._in_refresh = False

        logging.debug("Refresh pool '%s'", pool.get_name())
        vmmAsyncJob.simple_async_noshow(cb, [], self,
                            _("Error refreshing pool '%s'") % pool.get_name())

    def delete_vol(self, src_ignore):
        vol = self.current_vol()
        if vol is None:
            return

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the volume %s?") % vol.get_name())
        if not result:
            return

        def cb():
            vol.delete()
            def idlecb():
                self.refresh_current_pool()
                self.repopulate_storage_volumes()
            self.idle_add(idlecb)

        logging.debug("Deleting volume '%s'", vol.get_name())
        vmmAsyncJob.simple_async_noshow(cb, [], self,
                        _("Error refreshing volume '%s'") % vol.get_name())

    def add_pool(self, src_ignore):
        logging.debug("Launching 'Add Pool' wizard")
        try:
            if self.addpool is None:
                self.addpool = vmmCreatePool(self.conn)
            self.addpool.show(self.topwin)
        except Exception, e:
            self.err.show_err(_("Error launching pool wizard: %s") % str(e))

    def add_vol(self, src_ignore):
        pool = self.current_pool()
        if pool is None:
            return

        logging.debug("Launching 'Add Volume' wizard for pool '%s'",
                      pool.get_name())
        try:
            if self.addvol is None:
                self.addvol = vmmCreateVolume(self.conn, pool)
                self.addvol.connect("vol-created", self.refresh_current_pool)
            else:
                self.addvol.set_parent_pool(self.conn, pool)
            self.addvol.show(self.topwin)
        except Exception, e:
            self.err.show_err(_("Error launching volume wizard: %s") % str(e))

    def refresh_current_pool(self, ignore1=None):
        cp = self.current_pool()
        if cp is None:
            return
        cp.refresh()
        self.refresh_storage_pool(None, cp.get_connkey())

    def current_pool(self):
        connkey = uiutil.get_list_selection(self.widget("pool-list"), 0)
        try:
            return connkey and self.conn.get_pool(connkey)
        except KeyError:
            return None

    def current_vol(self):
        pool = self.current_pool()
        if not pool:
            return None

        connkey = uiutil.get_list_selection(self.widget("vol-list"), 0)
        try:
            return connkey and pool.get_volume(connkey)
        except KeyError:
            return None

    def pool_apply(self, src_ignore):
        pool = self.current_pool()
        if pool is None:
            return

        logging.debug("Applying changes for pool '%s'", pool.get_name())
        try:
            if EDIT_POOL_AUTOSTART in self.active_edits:
                auto = self.widget("pool-autostart").get_active()
                pool.set_autostart(auto)
            if EDIT_POOL_NAME in self.active_edits:
                pool.define_name(self.widget("pool-name-entry").get_text())
                self.repopulate_storage_pools()
        except Exception, e:
            self.err.show_err(_("Error changing pool settings: %s") % str(e))
            return
        self.disable_pool_apply()

    def disable_pool_apply(self):
        self.active_edits = []
        self.widget("pool-apply").set_sensitive(False)

    def enable_pool_apply(self, *arglist):
        edittype = arglist[-1]
        self.widget("pool-apply").set_sensitive(True)
        if edittype not in self.active_edits:
            self.active_edits.append(edittype)

    def pool_autostart_changed(self, src_ignore):
        auto = self.widget("pool-autostart").get_active()
        self.widget("pool-autostart").set_label(auto and
                                                _("On Boot") or
                                                _("Never"))
        self.enable_pool_apply(EDIT_POOL_AUTOSTART)

    def set_storage_error_page(self, msg):
        self.reset_pool_state()
        self.widget("storage-pages").set_current_page(1)
        self.widget("storage-error-label").set_text(msg)

    def pool_selected(self, src):
        model, treeiter = src.get_selected()
        if treeiter is None:
            self.set_storage_error_page(_("No storage pool selected."))
            return

        self.widget("storage-pages").set_current_page(0)
        connkey = model[treeiter][0]

        try:
            self.populate_pool_state(connkey)
        except Exception, e:
            logging.exception(e)
            self.set_storage_error_page(_("Error selecting pool: %s") % e)
        self.disable_pool_apply()

    def populate_pool_state(self, connkey):
        pool = self.conn.get_pool(connkey)
        pool.tick()
        auto = pool.get_autostart()
        active = pool.is_active()

        # Set pool details state
        self.widget("pool-details").set_sensitive(True)
        self.widget("pool-name").set_markup("<b>%s:</b>" %
                                            pool.get_name())
        self.widget("pool-name-entry").set_text(pool.get_name())
        self.widget("pool-name-entry").set_editable(not active)
        self.widget("pool-sizes").set_markup(
                """<span size="large">%s Free</span> / <i>%s In Use</i>""" %
                (pool.get_pretty_available(), pool.get_pretty_allocation()))
        self.widget("pool-type").set_text(
                StoragePool.get_pool_type_desc(pool.get_type()))
        self.widget("pool-location").set_text(
                pool.get_target_path())
        self.widget("pool-state-icon").set_from_icon_name(
                ((active and self.ICON_RUNNING) or self.ICON_SHUTOFF),
                Gtk.IconSize.BUTTON)
        self.widget("pool-state").set_text(
                (active and _("Active")) or _("Inactive"))
        self.widget("pool-autostart").set_label(
                (auto and _("On Boot")) or _("Never"))
        self.widget("pool-autostart").set_active(auto)

        self.widget("vol-list").set_sensitive(active)
        self.repopulate_storage_volumes()

        self.widget("pool-delete").set_sensitive(not active)
        self.widget("pool-stop").set_sensitive(active)
        self.widget("pool-start").set_sensitive(not active)
        self.widget("vol-add").set_sensitive(active)
        self.widget("vol-add").set_tooltip_text(_("Create new volume"))
        self.widget("vol-delete").set_sensitive(False)

        if active and not pool.supports_volume_creation():
            self.widget("vol-add").set_sensitive(False)
            self.widget("vol-add").set_tooltip_text(
                _("Pool does not support volume creation"))

    def refresh_storage_pool(self, src, connkey):
        ignore = src
        refresh_pool_in_list(self.widget("pool-list"), self.conn, connkey)
        curpool = self.current_pool()
        if curpool.get_connkey() != connkey:
            return

        # Currently selected pool changed state: force a 'pool_selected' to
        # update vol list
        self.pool_selected(self.widget("pool-list").get_selection())

    def reset_pool_state(self):
        self.widget("pool-details").set_sensitive(False)
        self.widget("pool-name").set_text("")
        self.widget("pool-name-entry").set_text("")
        self.widget("pool-sizes").set_markup("""<span size="large"> </span>""")
        self.widget("pool-type").set_text("")
        self.widget("pool-location").set_text("")
        self.widget("pool-state-icon").set_from_icon_name(self.ICON_SHUTOFF,
                                                          Gtk.IconSize.BUTTON)
        self.widget("pool-state").set_text(_("Inactive"))
        self.widget("vol-list").get_model().clear()
        self.widget("pool-autostart").set_label(_("Never"))
        self.widget("pool-autostart").set_active(False)

        self.widget("pool-delete").set_sensitive(False)
        self.widget("pool-stop").set_sensitive(False)
        self.widget("pool-start").set_sensitive(False)
        self.widget("vol-add").set_sensitive(False)
        self.widget("vol-delete").set_sensitive(False)
        self.widget("vol-list").set_sensitive(False)
        self.disable_pool_apply()

    def vol_selected(self, src):
        model, treeiter = src.get_selected()
        ignore = model
        if treeiter is None:
            self.widget("vol-delete").set_sensitive(False)
            return

        self.widget("vol-delete").set_sensitive(True)

    def popup_vol_menu(self, widget_ignore, event):
        if event.button != 3:
            return

        self.volmenu.popup(None, None, None, None, 0, event.time)

    def copy_vol_path(self, ignore=None):
        vol = self.current_vol()
        if not vol:
            return
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        target_path = vol.get_target_path()
        if target_path:
            clipboard.set_text(target_path, -1)


    def repopulate_storage_pools(self, src=None, connkey=None):
        ignore = src
        ignore = connkey
        pool_list = self.widget("pool-list")
        populate_storage_pools(pool_list, self.conn, self.current_pool())

    def repopulate_storage_volumes(self):
        list_widget = self.widget("vol-list")
        pool = self.current_pool()
        populate_storage_volumes(list_widget, pool, None)


    #############################
    # Interface manager methods #
    #############################

    def stop_interface(self, src_ignore):
        interface = self.current_interface()
        if interface is None:
            return

        if not self.err.chkbox_helper(self.config.get_confirm_interface,
            self.config.set_confirm_interface,
            text1=_("Are you sure you want to stop the interface "
                    "'%s'?" % interface.get_name())):
            return

        logging.debug("Stopping interface '%s'", interface.get_name())
        vmmAsyncJob.simple_async_noshow(interface.stop, [], self,
                    _("Error stopping interface '%s'") % interface.get_name())

    def start_interface(self, src_ignore):
        interface = self.current_interface()
        if interface is None:
            return

        if not self.err.chkbox_helper(self.config.get_confirm_interface,
            self.config.set_confirm_interface,
            text1=_("Are you sure you want to start the interface "
                    "'%s'?" % interface.get_name())):
            return

        logging.debug("Starting interface '%s'", interface.get_name())
        vmmAsyncJob.simple_async_noshow(interface.start, [], self,
                    _("Error starting interface '%s'") % interface.get_name())

    def delete_interface(self, src_ignore):
        interface = self.current_interface()
        if interface is None:
            return

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the interface %s?")
                                   % interface.get_name())
        if not result:
            return

        logging.debug("Deleting interface '%s'", interface.get_name())
        vmmAsyncJob.simple_async_noshow(interface.delete, [], self,
                    _("Error deleting interface '%s'") % interface.get_name())

    def add_interface(self, src_ignore):
        logging.debug("Launching 'Add Interface' wizard")
        try:
            if self.addinterface is None:
                self.addinterface = vmmCreateInterface(self.conn)
            self.addinterface.show(self.topwin)
        except Exception, e:
            self.err.show_err(_("Error launching interface wizard: %s") %
                              str(e))

    def refresh_current_interface(self, ignore1=None):
        cp = self.current_interface()
        if cp is None:
            return

        self.refresh_interface(None, cp.get_name())

    def current_interface(self):
        connkey = uiutil.get_list_selection(self.widget("interface-list"), 0)
        try:
            return connkey and self.conn.get_interface(connkey)
        except KeyError:
            return None

    def interface_apply(self, src_ignore):
        interface = self.current_interface()
        if interface is None:
            return

        newmode = uiutil.get_list_selection(
            self.widget("interface-startmode"), 0)

        logging.debug("Applying changes for interface '%s'",
                      interface.get_name())
        try:
            interface.set_startmode(newmode)
        except Exception, e:
            self.err.show_err(_("Error setting interface startmode: %s") %
                              str(e))
            return

        # XXX: This will require an interface restart
        self.widget("interface-apply").set_sensitive(False)

    def interface_startmode_changed(self, src_ignore):
        self.widget("interface-apply").set_sensitive(True)

    def set_interface_error_page(self, msg):
        self.reset_interface_state()
        self.widget("interface-pages").set_current_page(INTERFACE_PAGE_ERROR)
        self.widget("interface-error-label").set_text(msg)

    def interface_selected(self, src):
        model, treeiter = src.get_selected()
        if treeiter is None:
            self.set_interface_error_page(_("No interface selected."))
            return

        self.widget("interface-pages").set_current_page(INTERFACE_PAGE_INFO)
        connkey = model[treeiter][0]

        try:
            self.populate_interface_state(connkey)
        except Exception, e:
            logging.exception(e)
            self.set_interface_error_page(_("Error selecting interface: %s") %
                                          e)

        self.widget("interface-apply").set_sensitive(False)

    def populate_interface_state(self, connkey):
        interface = self.conn.get_interface(connkey)
        name = interface.get_name()
        children = interface.get_slaves()
        itype = interface.get_type()
        mac = interface.get_mac()
        active = interface.is_active()
        startmode = interface.get_startmode()
        ipv4 = interface.get_ipv4()
        ipv6 = interface.get_ipv6()

        self.widget("interface-details").set_sensitive(True)
        self.widget("interface-name").set_markup(
            "<b>%s %s:</b>" % (interface.get_pretty_type(),
                               interface.get_name()))
        self.widget("interface-mac").set_text(mac or _("Unknown"))

        self.widget("interface-state-icon").set_from_icon_name(
            ((active and self.ICON_RUNNING) or self.ICON_SHUTOFF),
            Gtk.IconSize.BUTTON)
        self.widget("interface-state").set_text(
                                    (active and _("Active")) or _("Inactive"))

        # Set start mode
        start_list = self.widget("interface-startmode")
        start_model = start_list.get_model()
        start_label = self.widget("interface-startmode-label")
        start_list.hide()
        start_label.show()
        start_label.set_text(startmode)

        idx = 0
        for row in start_model:
            if row[0] == startmode:
                start_list.set_active(idx)
                start_list.show()
                start_label.hide()
                break
            idx += 1

        # This can fail if other interfaces are busted, so ignore errors
        used_by = None
        try:
            used_by = vmmCreateInterface.iface_in_use_by(self.conn, name)
        except Exception, e:
            logging.debug("Error looking up iface usage: %s", e)
        self.widget("interface-inuseby").set_text(used_by or "-")

        # IP info
        self.widget("interface-ipv4-expander").set_visible(bool(ipv4))
        self.widget("interface-ipv6-expander").set_visible(bool(ipv6))

        if ipv4:
            mode = ipv4[0] and "DHCP" or "Static"
            addr = ipv4[1] or "-"
            self.widget("interface-ipv4-mode").set_text(mode)
            self.widget("interface-ipv4-address").set_text(addr)

        if ipv6:
            mode = ""
            if ipv6[1]:
                mode = "Autoconf "

            if ipv6[0]:
                mode += "DHCP"
            else:
                mode = "Static"

            addrstr = "-"
            if ipv6[2]:
                addrstr = reduce(lambda x, y: x + "\n" + y, ipv6[2])

            self.widget("interface-ipv6-mode").set_text(mode)
            self.widget("interface-ipv6-address").set_text(addrstr)

        self.widget("interface-delete").set_sensitive(not active)
        self.widget("interface-stop").set_sensitive(active)
        self.widget("interface-start").set_sensitive(not active)

        show_child = (children or
                      itype in [Interface.INTERFACE_TYPE_BRIDGE,
                                Interface.INTERFACE_TYPE_BOND])
        self.widget("interface-child-box").set_visible(show_child)
        self.populate_interface_children()

    def refresh_interface(self, src, connkey):
        ignore = src

        iface_list = self.widget("interface-list")
        sel = iface_list.get_selection()
        model, treeiter = sel.get_selected()
        iface = self.conn.get_interface(connkey)
        name = iface.get_name()
        iface.tick()

        for row in iface_list.get_model():
            if row[0] == name:
                row[4] = iface.is_active()

        if treeiter is not None:
            if model[treeiter][0] == name:
                self.interface_selected(sel)


    def reset_interface_state(self):
        self.widget("interface-delete").set_sensitive(False)
        self.widget("interface-stop").set_sensitive(False)
        self.widget("interface-start").set_sensitive(False)
        self.widget("interface-apply").set_sensitive(False)

    def repopulate_interfaces(self, src=None, connkey=None):
        ignore = src
        ignore = connkey
        interface_list = self.widget("interface-list")
        self.populate_interfaces(interface_list.get_model())

    def populate_interfaces(self, model):
        curiface = self.current_interface()

        iface_list = self.widget("interface-list")
        iface_list.get_selection().unselect_all()
        model.clear()
        for iface in self.conn.list_interfaces():
            model.append([iface.get_connkey(), iface.get_name(),
                          "network-idle", Gtk.IconSize.LARGE_TOOLBAR,
                          bool(iface.is_active())])

        uiutil.set_row_selection(iface_list,
            curiface and curiface.get_connkey() or None)

    def populate_interface_children(self):
        interface = self.current_interface()
        child_list = self.widget("interface-child-list")
        model = child_list.get_model()
        child_list.get_selection().unselect_all()
        model.clear()

        if not interface:
            return

        for name, itype in interface.get_slaves():
            row = [name, itype]
            model.append(row)


# These functions are broken out, since they are used by storage browser
# dialog.

def init_pool_list(pool_list, changed_func):
    poolListModel = Gtk.ListStore(str, str, bool, str)
    pool_list.set_model(poolListModel)

    pool_list.get_selection().connect("changed", changed_func)

    poolCol = Gtk.TreeViewColumn("Storage Pools")
    pool_txt = Gtk.CellRendererText()
    pool_per = Gtk.CellRendererText()
    poolCol.pack_start(pool_per, False)
    poolCol.pack_start(pool_txt, True)
    poolCol.add_attribute(pool_txt, 'markup', 1)
    poolCol.add_attribute(pool_txt, 'sensitive', 2)
    poolCol.add_attribute(pool_per, 'markup', 3)
    pool_list.append_column(poolCol)
    poolListModel.set_sort_column_id(1, Gtk.SortType.ASCENDING)


def refresh_pool_in_list(pool_list, conn, connkey):
    for row in pool_list.get_model():
        if row[0] != connkey:
            continue

        # Update active sensitivity and percent available for passed key
        row[3] = get_pool_size_percent(conn, connkey)
        row[2] = conn.get_pool(connkey).is_active()
        return


def populate_storage_pools(pool_list, conn, curpool):
    model = pool_list.get_model()
    # Prevent events while the model is modified
    pool_list.set_model(None)
    pool_list.get_selection().unselect_all()
    model.clear()
    for pool in conn.list_pools():
        connkey = pool.get_connkey()
        per = get_pool_size_percent(conn, connkey)
        pool = conn.get_pool(connkey)

        name = pool.get_name()
        typ = StoragePool.get_pool_type_desc(pool.get_type())
        label = "%s\n<span size='small'>%s</span>" % (name, typ)

        model.append([connkey, label, pool.is_active(), per])

    pool_list.set_model(model)
    uiutil.set_row_selection(pool_list,
        curpool and curpool.get_connkey() or None)


def populate_storage_volumes(list_widget, pool, sensitive_cb):
    vols = pool and pool.get_volumes() or {}
    model = list_widget.get_model()
    list_widget.get_selection().unselect_all()
    model.clear()

    for key in vols.keys():
        vol = vols[key]

        try:
            path = vol.get_target_path()
            name = vol.get_pretty_name(pool.get_type())
            cap = vol.get_pretty_capacity()
            fmt = vol.get_format() or ""
        except:
            logging.debug("Error getting volume info for '%s', "
                          "hiding it", key, exc_info=True)
            continue

        namestr = None
        try:
            if path:
                names = VirtualDisk.path_in_use_by(vol.conn.get_backend(),
                                                   path)
                namestr = ", ".join(names)
                if not namestr:
                    namestr = None
        except:
            logging.exception("Failed to determine if storage volume in "
                              "use.")

        row = [key, name, cap, fmt, namestr]
        if sensitive_cb:
            row.append(sensitive_cb(fmt))
        model.append(row)


def get_pool_size_percent(conn, connkey):
    pool = conn.get_pool(connkey)
    cap = pool.get_capacity()
    alloc = pool.get_allocation()
    if not cap or alloc is None:
        per = 0
    else:
        per = int(((float(alloc) / float(cap)) * 100))
    return "<span size='small' color='#484848'>%s%%</span>" % int(per)
