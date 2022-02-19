# Copyright (C) 2007, 2013-2014 Red Hat, Inc.
# Copyright (C) 2007 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk
from gi.repository import Pango

from virtinst import log

from .lib import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .createnet import vmmCreateNetwork
from .xmleditor import vmmXMLEditor


EDIT_NET_IDS = (
EDIT_NET_NAME,
EDIT_NET_AUTOSTART,
EDIT_NET_XML,
) = list(range(3))


ICON_RUNNING = "state_running"
ICON_SHUTOFF = "state_shutoff"


class vmmHostNets(vmmGObjectUI):
    def __init__(self, conn, builder, topwin):
        vmmGObjectUI.__init__(self, "hostnets.ui",
                              None, builder=builder, topwin=topwin)
        self.conn = conn

        self._addnet = None
        self._xmleditor = None

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
        })

        self._init_ui()
        self._populate_networks()
        self._refresh_conn_state()
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

        self._xmleditor.cleanup()
        self._xmleditor = None

    def close(self, ignore1=None, ignore2=None):
        if self._addnet:
            self._addnet.close()


    ###########
    # UI init #
    ###########

    def _init_ui(self):
        self.widget("network-pages").set_show_tabs(False)

        self._xmleditor = vmmXMLEditor(self.builder, self.topwin,
                self.widget("net-details-align"),
                self.widget("net-details"))
        self._xmleditor.connect("changed",
                lambda s: self._enable_net_apply(EDIT_NET_XML))
        self._xmleditor.connect("xml-requested",
                self._xmleditor_xml_requested_cb)
        self._xmleditor.connect("xml-reset",
                self._xmleditor_xml_reset_cb)

        # [ netobj, label, icon name, icon size, is_active ]
        netListModel = Gtk.ListStore(object, str, str, int, bool)
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


    ##############
    # Public API #
    ##############

    def refresh_page(self):
        self.conn.schedule_priority_tick(pollnet=True)


    #################
    # UI populating #
    #################

    def _refresh_conn_state(self):
        conn_active = self.conn.is_active()
        self.widget("net-add").set_sensitive(conn_active and
            self.conn.support.conn_network())

        if conn_active and not self.conn.support.conn_network():
            self._set_error_page(  # pragma: no cover
                _("Libvirt connection does not support virtual network "
                  "management."))

        if conn_active:
            uiutil.set_list_selection_by_number(self.widget("net-list"), 0)
            return

        self._populate_networks()
        self._set_error_page(_("Connection not active."))

    def _current_network(self):
        return uiutil.get_list_selection(self.widget("net-list"))

    def _set_error_page(self, msg):
        self.widget("network-pages").set_current_page(1)
        self.widget("network-error-label").set_text(msg)
        self.widget("net-start").set_sensitive(False)
        self.widget("net-stop").set_sensitive(False)
        self.widget("net-delete").set_sensitive(False)
        self._disable_net_apply()

    def _refresh_current_network(self):
        net = self._current_network()
        if not net:
            self._set_error_page(_("No virtual network selected."))
            return

        self.widget("network-pages").set_current_page(0)

        try:
            self._populate_net_state(net)
        except Exception as e:  # pragma: no cover
            log.exception(e)
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
                model.append([net, net.get_name(), "network-idle",
                              Gtk.IconSize.LARGE_TOOLBAR,
                              bool(net.is_active())])
        finally:
            net_list.set_model(model)

        uiutil.set_list_selection(net_list, curnet)

    def _populate_net_ipv4_state(self, net):
        (netstr, (dhcpstart, dhcpend)) = net.get_ipv4_network()

        self.widget("net-ipv4-expander").set_visible(bool(netstr))
        if not netstr:
            return

        self.widget("net-ipv4-forwarding").set_text(net.pretty_forward_mode())

        dhcpstr = _("Disabled")
        if dhcpstart:
            dhcpstr = dhcpstart + " - " + dhcpend
        self.widget("net-ipv4-dhcp-range").set_text(dhcpstr)
        self.widget("net-ipv4-network").set_text(netstr)

    def _populate_net_ipv6_state(self, net):
        (netstr, (dhcpstart, dhcpend)) = net.get_ipv6_network()

        self.widget("net-ipv6-expander").set_visible(bool(netstr))

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

    def _populate_net_state(self, net):
        active = net.is_active()

        self.widget("net-details").set_sensitive(True)
        self.widget("net-name").set_text(net.get_name())
        self.widget("net-name").set_editable(not active)
        self.widget("net-device").set_text(net.get_bridge_device() or "")
        self.widget("net-name-domain").set_text(net.get_name_domain() or "")
        uiutil.set_grid_row_visible(self.widget("net-name-domain"),
                                       bool(net.get_name_domain()))

        icon = (active and ICON_RUNNING or ICON_SHUTOFF)
        self.widget("net-state").set_text(net.run_status())
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

        self._xmleditor.set_xml_from_libvirtobject(net)


    #############################
    # Network lifecycle actions #
    #############################

    def _delete_network_cb(self, src):
        net = self._current_network()
        if net is None:
            return  # pragma: no cover

        result = self.err.yes_no(_("Are you sure you want to permanently "
                                   "delete the network %s?") % net.get_name())
        if not result:
            return

        log.debug("Deleting network '%s'", net.get_name())
        vmmAsyncJob.simple_async_noshow(net.delete, [], self,
                            _("Error deleting network '%s'") % net.get_name())

    def _start_network_cb(self, src):
        net = self._current_network()
        if net is None:
            return  # pragma: no cover

        log.debug("Starting network '%s'", net.get_name())
        vmmAsyncJob.simple_async_noshow(net.start, [], self,
                            _("Error starting network '%s'") % net.get_name())

    def _stop_network_cb(self, src):
        net = self._current_network()
        if net is None:
            return  # pragma: no cover

        log.debug("Stopping network '%s'", net.get_name())
        vmmAsyncJob.simple_async_noshow(net.stop, [], self,
                            _("Error stopping network '%s'") % net.get_name())

    def _add_network_cb(self, src):
        log.debug("Launching 'Add Network'")
        try:
            if self._addnet is None:
                self._addnet = vmmCreateNetwork(self.conn)
            self._addnet.show(self.topwin)
        except Exception as e:  # pragma: no cover
            self.err.show_err(_("Error launching network wizard: %s") % str(e))


    ############################
    # Net apply/config actions #
    ############################

    def _net_apply(self):
        net = self._current_network()
        if net is None:
            return  # pragma: no cover

        log.debug("Applying changes for network '%s'", net.get_name())
        try:
            if EDIT_NET_AUTOSTART in self._active_edits:
                auto = self.widget("net-autostart").get_active()
                net.set_autostart(auto)
            if EDIT_NET_NAME in self._active_edits:
                net.define_name(self.widget("net-name").get_text())
                self.idle_add(self._populate_networks)
            if EDIT_NET_XML in self._active_edits:
                net.define_xml(self._xmleditor.get_xml())

        except Exception as e:
            self.err.show_err(_("Error changing network settings: %s") % str(e))
            return
        finally:
            self._disable_net_apply()

    def _disable_net_apply(self):
        self._active_edits = set()
        self.widget("net-apply").set_sensitive(False)
        self._xmleditor.details_changed = False

    def _enable_net_apply(self, edittype):
        self.widget("net-apply").set_sensitive(True)
        self._active_edits.add(edittype)
        self._xmleditor.details_changed = True

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

    def _conn_nets_changed_cb(self, src, net):
        self._populate_networks()

    def _net_state_changed_cb(self, net):
        # Update net state inline in the tree model
        for row in self.widget("net-list").get_model():
            if row[0] == net:
                row[4] = net.is_active()

        # If refreshed network is the current net, refresh the UI
        curnet = self._current_network()
        if curnet == net:
            self._refresh_current_network()

    def _net_selected_cb(self, selection):
        self._refresh_current_network()

    def _xmleditor_xml_requested_cb(self, src):
        self._refresh_current_network()

    def _xmleditor_xml_reset_cb(self, src):
        self._refresh_current_network()
