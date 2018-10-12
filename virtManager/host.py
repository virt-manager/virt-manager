# Copyright (C) 2007, 2013-2014 Red Hat, Inc.
# Copyright (C) 2007 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

from gi.repository import Gtk

from virtinst import NodeDevice
from virtinst import util

from . import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .createnet import vmmCreateNetwork
from .engine import vmmEngine
from .graphwidgets import Sparkline
from .storagelist import vmmStorageList

EDIT_NET_IDS = (
EDIT_NET_NAME,
EDIT_NET_AUTOSTART,
EDIT_NET_QOS,
) = list(range(3))


class vmmHost(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj, conn):
        try:
            # Maintain one dialog per connection
            uri = conn.get_uri()
            if cls._instances is None:
                cls._instances = {}
            if uri not in cls._instances:
                cls._instances[uri] = vmmHost(conn)
            cls._instances[uri].show()
        except Exception as e:
            if not parentobj:
                raise
            parentobj.err.show_err(
                    _("Error launching host dialog: %s") % str(e))

    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "host.ui", "vmm-host")
        self.conn = conn

        self._orig_title = self.topwin.get_title()
        self.ICON_RUNNING = "state_running"
        self.ICON_SHUTOFF = "state_shutoff"

        self.addnet = None

        self.active_edits = []

        self.cpu_usage_graph = None
        self.memory_usage_graph = None
        self.init_conn_state()

        self.storagelist = None
        self.init_storage_state()
        self.init_net_state()

        self.builder.connect_signals({
            "on_menu_file_view_manager_activate": self.view_manager,
            "on_menu_file_quit_activate": self.exit_app,
            "on_menu_file_close_activate": self.close,
            "on_vmm_host_delete_event": self.close,
            "on_host_page_switch": self.page_changed,

            "on_net_add_clicked": self.add_network,
            "on_net_delete_clicked": self.delete_network,
            "on_net_stop_clicked": self.stop_network,
            "on_net_start_clicked": self.start_network,
            "on_net_apply_clicked": (lambda *x: self.net_apply()),
            "on_net_list_changed": self.net_selected,
            "on_net_autostart_toggled": self.net_autostart_changed,
            "on_net_name_changed": (lambda *x:
                self.enable_net_apply(x, EDIT_NET_NAME)),

            "on_overview_name_changed": self._overview_name_changed,
            "on_config_autoconnect_toggled": self.toggle_autoconnect,

            "on_qos_inbound_average_changed":  (lambda *x:
                self.enable_net_apply(x, EDIT_NET_QOS)),
            "on_qos_inbound_peak_changed":  (lambda *x:
                self.enable_net_apply(x, EDIT_NET_QOS)),
            "on_qos_inbound_burst_changed":  (lambda *x:
                self.enable_net_apply(x, EDIT_NET_QOS)),
            "on_qos_outbound_average_changed":  (lambda *x:
                self.enable_net_apply(x, EDIT_NET_QOS)),
            "on_qos_outbound_peak_changed":  (lambda *x:
                self.enable_net_apply(x, EDIT_NET_QOS)),
            "on_qos_outbound_burst_changed":  (lambda *x:
                self.enable_net_apply(x, EDIT_NET_QOS)),

            "on_net_qos_inbound_enable_toggled": self.change_qos_in_enable,
            "on_net_qos_outbound_enable_toggled": self.change_qos_out_enable,
        })

        self.populate_networks()

        self.conn.connect("net-added", self.populate_networks)
        self.conn.connect("net-removed", self.populate_networks)

        self.conn.connect("state-changed", self.conn_state_changed)
        self.conn.connect("resources-sampled", self.refresh_resources)

        self.refresh_resources()
        self.conn_state_changed()
        self.widget("config-autoconnect").set_active(
            self.conn.get_autoconnect())

        self._cleanup_on_conn_removed()


    def init_net_state(self):
        self.widget("network-pages").set_show_tabs(False)

        # [ unique, label, icon name, icon size, is_active ]
        netListModel = Gtk.ListStore(str, str, str, int, bool)
        self.widget("net-list").set_model(netListModel)

        sel = self.widget("net-list").get_selection()
        sel.set_select_function((lambda *x: self.confirm_changes()), None)

        netCol = Gtk.TreeViewColumn(_("Networks"))
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

        # Virtual Function list
        # [vf-name]
        vf_list = self.widget("vf-list")
        vf_list_model = Gtk.ListStore(str)
        vf_list.set_model(vf_list_model)
        vf_list.set_headers_visible(False)

        vfTextCol = Gtk.TreeViewColumn()
        vf_txt = Gtk.CellRendererText()
        vfTextCol.pack_start(vf_txt, True)
        vfTextCol.add_attribute(vf_txt, 'text', 0)
        vf_list.append_column(vfTextCol)


    def init_storage_state(self):
        self.storagelist = vmmStorageList(self.conn, self.builder, self.topwin)
        self.widget("storage-align").add(self.storagelist.top_box)


    def init_conn_state(self):
        uri = self.conn.get_uri()
        auto = self.conn.get_autoconnect()

        self.widget("overview-uri").set_text(uri)
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

        vmmEngine.get_instance().increment_window_counter()

    def is_visible(self):
        return self.topwin.get_visible()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing host window for %s", self.conn)
        if not self.is_visible():
            return

        self.confirm_changes()

        self.topwin.hide()
        vmmEngine.get_instance().decrement_window_counter()

        return 1

    def _cleanup(self):
        self.conn = None

        self.storagelist.cleanup()
        self.storagelist = None

        if self.addnet:
            self.addnet.cleanup()
            self.addnet = None

        self.cpu_usage_graph.destroy()
        self.cpu_usage_graph = None

        self.memory_usage_graph.destroy()
        self.memory_usage_graph = None

    def view_manager(self, _src):
        from .manager import vmmManager
        vmmManager.get_instance(self).show()

    def exit_app(self, _src):
        vmmEngine.get_instance().exit_app()


    def page_changed(self, src, child, pagenum):
        ignore = src
        ignore = child
        self.confirm_changes()
        if pagenum == 1:
            self.populate_networks()
            self.conn.schedule_priority_tick(pollnet=True)
        elif pagenum == 2:
            self.storagelist.refresh_page()

    def refresh_resources(self, ignore=None):
        vm_memory = util.pretty_mem(self.conn.stats_memory())
        host_memory = util.pretty_mem(self.conn.host_memory_size())

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
        conn_active = self.conn.is_active()

        self.topwin.set_title(
            self.conn.get_pretty_desc() + " " + self._orig_title)
        if not self.widget("overview-name").has_focus():
            self.widget("overview-name").set_text(self.conn.get_pretty_desc())

        self.widget("net-add").set_sensitive(conn_active and
            self.conn.is_network_capable())

        if conn_active and not self.conn.is_network_capable():
            self.set_net_error_page(
                _("Libvirt connection does not support virtual network "
                  "management."))

        if conn_active:
            uiutil.set_list_selection_by_number(self.widget("net-list"), 0)
            return

        self.set_net_error_page(_("Connection not active."))

        self.populate_networks()

        self.storagelist.close()
        if self.addnet:
            self.addnet.close()

    def _overview_name_changed(self, src):
        src = self.widget("overview-name")
        self.conn.set_config_pretty_name(src.get_text())

    def toggle_autoconnect(self, src):
        self.conn.set_autoconnect(src.get_active())


    #############################
    # Virtual Network functions #
    #############################

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
        self.widget("vf-list").get_model().clear()
        vmmAsyncJob.simple_async_noshow(net.stop, [], self,
                            _("Error stopping network '%s'") % net.get_name())

    def add_network(self, src_ignore):
        logging.debug("Launching 'Add Network'")
        try:
            if self.addnet is None:
                self.addnet = vmmCreateNetwork(self.conn)
            self.addnet.show(self.topwin)
        except Exception as e:
            self.err.show_err(_("Error launching network wizard: %s") % str(e))

    def net_apply(self):
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
                self.idle_add(self.populate_networks)
            if EDIT_NET_QOS in self.active_edits:
                in_qos = self.widget("net-qos-inbound-enable").get_active()
                out_qos = self.widget("net-qos-outbound-enable").get_active()

                def get_value(name, enabled):
                    if not enabled:
                        return None
                    return self.widget(name).get_text() or None

                args = {}
                args['inbound_average'] = get_value("qos-inbound-average", in_qos)
                args['inbound_peak'] = get_value("qos-inbound-peak", in_qos)
                args['inbound_burst'] = get_value("qos-inbound-burst", in_qos)

                args['outbound_average'] = get_value("qos-outbound-average", out_qos)
                args['outbound_peak'] = get_value("qos-outbound-peak", out_qos)
                args['outbound_burst'] = get_value("qos-outbound-burst", out_qos)

                if net.set_qos(**args):
                    self.err.show_err(
                        _("Network could not be updated"),
                        text2=_("This change will take effect when the "
                                "network is restarted"),
                        buttons=Gtk.ButtonsType.OK,
                        dialog_type=Gtk.MessageType.INFO)


        except Exception as e:
            self.err.show_err(_("Error changing network settings: %s") % str(e))
            return
        finally:
            self.disable_net_apply()

    def disable_net_apply(self):
        for i in EDIT_NET_IDS:
            if i in self.active_edits:
                self.active_edits.remove(i)
        self.widget("net-apply").set_sensitive(False)

    def enable_net_apply(self, *arglist):
        edittype = arglist[-1]
        self.widget("net-apply").set_sensitive(True)
        if edittype not in self.active_edits:
            self.active_edits.append(edittype)

    def net_autostart_changed(self, src_ignore):
        self.enable_net_apply(EDIT_NET_AUTOSTART)

    def current_network(self):
        connkey = uiutil.get_list_selection(self.widget("net-list"))
        return connkey and self.conn.get_net(connkey)

    def refresh_network(self, net):
        connkey = net.get_connkey()
        uilist = self.widget("net-list")
        sel = uilist.get_selection()
        model, treeiter = sel.get_selected()

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
            self.populate_net_state(net)
        except Exception as e:
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

    def update_qos_widgets(self):
        enabled = self.widget("net-qos-inbound-enable").get_active()
        self.widget("net-qos-inbound-grid").set_visible(enabled)

        enabled = self.widget("net-qos-outbound-enable").get_active()
        self.widget("net-qos-outbound-grid").set_visible(enabled)

    def change_qos_in_enable(self, ignore):
        self.enable_net_apply(EDIT_NET_QOS)
        self.update_qos_widgets()

    def change_qos_out_enable(self, ignore):
        self.enable_net_apply(EDIT_NET_QOS)
        self.update_qos_widgets()

    def _populate_qos_state(self, net):
        qos = net.get_qos()

        self.widget("net-qos-inbound-enable").set_active(qos.is_inbound())
        self.widget("net-qos-outbound-enable").set_active(qos.is_outbound())

        self.update_qos_widgets()

        self.widget("qos-inbound-average").set_text(qos.inbound_average or "")
        self.widget("qos-inbound-peak").set_text(qos.inbound_peak or "")
        self.widget("qos-inbound-burst").set_text(qos.inbound_burst or "")

        self.widget("qos-outbound-average").set_text(qos.outbound_average or "")
        self.widget("qos-outbound-peak").set_text(qos.outbound_peak or "")
        self.widget("qos-outbound-burst").set_text(qos.outbound_burst or "")

    def _populate_sriov_state(self, net):
        (is_vf_pool, pf_name, vfs) = net.get_sriov_vf_networks()

        self.widget("net-sriov-expander").set_visible(is_vf_pool)
        if not pf_name:
            self.widget("pf-name").set_text("N/A")
            return

        self.widget("pf-name").set_text(pf_name)

        vf_list_model = self.widget("vf-list").get_model()
        vf_list_model.clear()
        for vf in vfs:
            addrStr = "%x:%x:%x.%x" % (vf.domain, vf.bus, vf.slot, vf.function)
            pcidev = NodeDevice.lookupNodedevFromString(self.conn.get_backend(),
                                                        addrStr)

            vf_name = None

            netdevs = self.conn.filter_nodedevs("net")
            for netdev in netdevs:
                logging.debug(netdev.xmlobj.parent)
                if pcidev.name == netdev.xmlobj.parent:
                    vf_name = netdev.xmlobj.interface
                    break

            vf_list_model.append([vf_name or addrStr])


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
        self.widget("net-autostart").set_active(autostart)
        self.widget("net-autostart").set_label(_("On Boot"))

        self._populate_net_ipv4_state(net)
        self._populate_net_ipv6_state(net)
        self._populate_qos_state(net)
        self._populate_sriov_state(net)


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
        self.widget("net-autostart").set_label(_("On Boot"))
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

    def populate_networks(self, src=None, connkey=None):
        ignore = src
        ignore = connkey

        net_list = self.widget("net-list")
        curnet = self.current_network()

        model = net_list.get_model()
        # Prevent events while the model is modified
        net_list.set_model(None)
        try:
            net_list.get_selection().unselect_all()
            model.clear()
            for net in self.conn.list_nets():
                net.disconnect_by_obj(self)
                net.connect("state-changed", self.refresh_network)
                model.append([net.get_connkey(), net.get_name(), "network-idle",
                              Gtk.IconSize.LARGE_TOOLBAR,
                              bool(net.is_active())])
        finally:
            net_list.set_model(model)

        uiutil.set_list_selection(net_list,
            curnet and curnet.get_connkey() or None)


    def confirm_changes(self):
        if not self.active_edits:
            return True

        if self.err.chkbox_helper(
                self.config.get_confirm_unapplied,
                self.config.set_confirm_unapplied,
                text1=(_("There are unapplied changes. "
                         "Would you like to apply them now?")),
                chktext=_("Don't warn me again."),
                default=False):

            if all([edit in EDIT_NET_IDS for edit in self.active_edits]):
                self.net_apply()

        self.active_edits = []
        return True
