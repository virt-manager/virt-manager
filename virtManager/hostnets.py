# Copyright (C) 2007, 2013-2014 Red Hat, Inc.
# Copyright (C) 2007 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

from gi.repository import Gtk
from gi.repository import Pango

from virtinst import NodeDevice

from . import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .createnet import vmmCreateNetwork


EDIT_NET_IDS = (
EDIT_NET_NAME,
EDIT_NET_AUTOSTART,
EDIT_NET_QOS,
) = list(range(3))


ICON_RUNNING = "state_running"
ICON_SHUTOFF = "state_shutoff"


class vmmHostNets(vmmGObjectUI):
    def __init__(self, conn, builder, topwin):
        vmmGObjectUI.__init__(self, "hostnets.ui",
                              None, builder=builder, topwin=topwin)
        self.conn = conn

        self._addnet = None

        self._active_edits = set()
        self.top_box = self.widget("top-box")

        self.builder.connect_signals({
            "on_net_add_clicked": self._add_network_cb,
            "on_net_delete_clicked": self._delete_network_cb,
            "on_net_stop_clicked": self._stop_network_cb,
            "on_net_start_clicked": self._start_network_cb,
            "on_net_apply_clicked": (lambda *x: self._net_apply()),
            "on_net_list_changed": self._net_selected_cb,
            "on_net_autostart_toggled": (lambda *x:
                self._enable_net_apply(EDIT_NET_AUTOSTART)),
            "on_net_name_changed": (lambda *x:
                self._enable_net_apply(EDIT_NET_NAME)),

            "on_qos_inbound_average_changed":  (lambda *x:
                self._enable_net_apply(EDIT_NET_QOS)),
            "on_qos_inbound_peak_changed":  (lambda *x:
                self._enable_net_apply(EDIT_NET_QOS)),
            "on_qos_inbound_burst_changed":  (lambda *x:
                self._enable_net_apply(EDIT_NET_QOS)),
            "on_qos_outbound_average_changed":  (lambda *x:
                self._enable_net_apply(EDIT_NET_QOS)),
            "on_qos_outbound_peak_changed":  (lambda *x:
                self._enable_net_apply(EDIT_NET_QOS)),
            "on_qos_outbound_burst_changed":  (lambda *x:
                self._enable_net_apply(EDIT_NET_QOS)),

            "on_net_qos_inbound_enable_toggled": self._change_qos_cb,
            "on_net_qos_outbound_enable_toggled": self._change_qos_cb,
        })

        self._init_ui()
        self._populate_networks()
        self.conn.connect("net-added", self._conn_nets_changed_cb)
        self.conn.connect("net-removed", self._conn_nets_changed_cb)
        self.conn.connect("state-changed", self._conn_state_changed_cb)


    #######################
    # Standard UI methods #
    #######################

    def _cleanup(self):
        self.conn = None

        if self._addnet:
            self._addnet.cleanup()
            self._addnet = None

    def close(self, ignore1=None, ignore2=None):
        if self._addnet:
            self._addnet.close()


    ###########
    # UI init #
    ###########

    def _init_ui(self):
        self.widget("network-pages").set_show_tabs(False)

        # [ unique, label, icon name, icon size, is_active ]
        netListModel = Gtk.ListStore(str, str, str, int, bool)
        self.widget("net-list").set_model(netListModel)

        sel = self.widget("net-list").get_selection()
        sel.set_select_function((lambda *x: self._confirm_changes()), None)

        netCol = Gtk.TreeViewColumn(_("Networks"))
        netCol.set_spacing(6)
        net_txt = Gtk.CellRendererText()
        net_txt.set_property("ellipsize", Pango.EllipsizeMode.END)
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


    ##############
    # Public API #
    ##############

    def refresh_page(self):
        self._populate_networks()
        self.conn.schedule_priority_tick(pollnet=True)


    #################
    # UI populating #
    #################

    def _refresh_conn_state(self):
        conn_active = self.conn.is_active()
        self.widget("net-add").set_sensitive(conn_active and
            self.conn.is_network_capable())

        if conn_active and not self.conn.is_network_capable():
            self._set_error_page(
                _("Libvirt connection does not support virtual network "
                  "management."))

        if conn_active:
            uiutil.set_list_selection_by_number(self.widget("net-list"), 0)
            return

        self._set_error_page(_("Connection not active."))
        self._populate_networks()

    def _current_network(self):
        connkey = uiutil.get_list_selection(self.widget("net-list"))
        return connkey and self.conn.get_net(connkey)

    def _set_error_page(self, msg):
        self.widget("network-pages").set_current_page(1)
        self.widget("network-error-label").set_text(msg)

    def _refresh_current_network(self):
        net = self._current_network()
        if not net:
            self._set_error_page(_("No virtual network selected."))
            return

        self.widget("network-pages").set_current_page(0)

        try:
            self._populate_net_state(net)
        except Exception as e:
            logging.exception(e)
            self._set_error_page(_("Error selecting network: %s") % e)
        self._disable_net_apply()

    def _populate_networks(self):
        net_list = self.widget("net-list")
        curnet = self._current_network()

        model = net_list.get_model()
        # Prevent events while the model is modified
        net_list.set_model(None)
        try:
            net_list.get_selection().unselect_all()
            model.clear()
            for net in self.conn.list_nets():
                net.disconnect_by_obj(self)
                net.connect("state-changed", self._net_state_changed_cb)
                model.append([net.get_connkey(), net.get_name(), "network-idle",
                              Gtk.IconSize.LARGE_TOOLBAR,
                              bool(net.is_active())])
        finally:
            net_list.set_model(model)

        uiutil.set_list_selection(net_list,
            curnet and curnet.get_connkey() or None)

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

    def _update_qos_widgets(self):
        enabled = self.widget("net-qos-inbound-enable").get_active()
        self.widget("net-qos-inbound-grid").set_visible(enabled)

        enabled = self.widget("net-qos-outbound-enable").get_active()
        self.widget("net-qos-outbound-grid").set_visible(enabled)

    def _populate_qos_state(self, net):
        qos = net.get_qos()

        self.widget("net-qos-inbound-enable").set_active(qos.is_inbound())
        self.widget("net-qos-outbound-enable").set_active(qos.is_outbound())

        self._update_qos_widgets()

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

    def _populate_net_state(self, net):
        active = net.is_active()

        self.widget("net-details").set_sensitive(True)
        self.widget("net-name").set_text(net.get_name())
        self.widget("net-name").set_editable(not active)
        self.widget("net-device").set_text(net.get_bridge_device() or "")
        self.widget("net-name-domain").set_text(net.get_name_domain() or "")
        uiutil.set_grid_row_visible(self.widget("net-name-domain"),
                                       bool(net.get_name_domain()))

        state = active and _("Active") or _("Inactive")
        icon = (active and ICON_RUNNING or ICON_SHUTOFF)
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


    #############################
    # Network lifecycle actions #
    #############################

    def _delete_network_cb(self, src):
        net = self._current_network()
        if net is None:
            return

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the network %s?") % net.get_name())
        if not result:
            return

        logging.debug("Deleting network '%s'", net.get_name())
        vmmAsyncJob.simple_async_noshow(net.delete, [], self,
                            _("Error deleting network '%s'") % net.get_name())

    def _start_network_cb(self, src):
        net = self._current_network()
        if net is None:
            return

        logging.debug("Starting network '%s'", net.get_name())
        vmmAsyncJob.simple_async_noshow(net.start, [], self,
                            _("Error starting network '%s'") % net.get_name())

    def _stop_network_cb(self, src):
        net = self._current_network()
        if net is None:
            return

        logging.debug("Stopping network '%s'", net.get_name())
        self.widget("vf-list").get_model().clear()
        vmmAsyncJob.simple_async_noshow(net.stop, [], self,
                            _("Error stopping network '%s'") % net.get_name())

    def _add_network_cb(self, src):
        logging.debug("Launching 'Add Network'")
        try:
            if self._addnet is None:
                self._addnet = vmmCreateNetwork(self.conn)
            self._addnet.show(self.topwin)
        except Exception as e:
            self.err.show_err(_("Error launching network wizard: %s") % str(e))


    ############################
    # Net apply/config actions #
    ############################

    def _net_apply(self):
        net = self._current_network()
        if net is None:
            return

        logging.debug("Applying changes for network '%s'", net.get_name())
        try:
            if EDIT_NET_AUTOSTART in self._active_edits:
                auto = self.widget("net-autostart").get_active()
                net.set_autostart(auto)
            if EDIT_NET_NAME in self._active_edits:
                net.define_name(self.widget("net-name").get_text())
                self.idle_add(self._populate_networks)
            if EDIT_NET_QOS in self._active_edits:
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
            self._disable_net_apply()

    def _disable_net_apply(self):
        self._active_edits = set()
        self.widget("net-apply").set_sensitive(False)

    def _enable_net_apply(self, edittype):
        self.widget("net-apply").set_sensitive(True)
        self._active_edits.add(edittype)

    def _confirm_changes(self):
        if (self.is_visible() and
            self._active_edits and
            self.err.confirm_unapplied_changes()):
            self._net_apply()

        self._disable_net_apply()
        return True


    ################
    # UI listeners #
    ################

    def _conn_state_changed_cb(self, conn):
        self._refresh_conn_state()

    def _conn_nets_changed_cb(self, src, connkey):
        self._populate_networks()

    def _change_qos_cb(self, src):
        self._enable_net_apply(EDIT_NET_QOS)
        self._update_qos_widgets()

    def _net_state_changed_cb(self, net):
        # Update net state inline in the tree model
        for row in self.widget("net-list").get_model():
            if row[0] == net.get_connkey():
                row[4] = net.is_active()

        # If refreshed network is the current net, refresh the UI
        curnet = self._current_network()
        if curnet and curnet.get_connkey() == net.get_connkey():
            self._refresh_current_network()

    def _net_selected_cb(self, selection):
        self._refresh_current_network()
