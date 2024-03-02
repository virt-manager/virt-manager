# Copyright (C) 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk

import virtinst
from virtinst import log

from ..lib import uiutil
from ..baseclass import vmmGObjectUI


NET_ROW_LABEL = 0
NET_ROW_SENSITIVE = 1
NET_ROW_DATA = 2


class _NetRowData:
    @staticmethod
    def build_row(*args, **kwargs):
        rowdata = _NetRowData(*args, **kwargs)
        return [rowdata.label, rowdata.is_sensitive, rowdata]

    def __init__(self, nettype, source, label, is_sensitive, manual=False):
        self.nettype = nettype
        self.source = source
        self.label = label
        self.is_sensitive = is_sensitive
        self.manual = manual


def _build_manual_row(nettype, label):
    return _NetRowData.build_row(nettype, None, label, True, manual=True)


def _pretty_network_desc(nettype, source=None, netobj=None):
    if nettype == virtinst.DeviceInterface.TYPE_USER:
        return _("Usermode networking")

    extra = None
    if nettype == virtinst.DeviceInterface.TYPE_VIRTUAL:
        ret = _("Virtual network")
        if netobj:
            extra = ": %s" % netobj.pretty_forward_mode()
    else:
        ret = nettype.capitalize()

    if source:
        ret += " '%s'" % source
    if extra:
        ret += " %s" % extra

    return ret


class vmmNetworkList(vmmGObjectUI):
    __gsignals__ = {
        "changed": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    def __init__(self, conn, builder, topwin):
        vmmGObjectUI.__init__(self, "netlist.ui",
                              None, builder=builder, topwin=topwin)
        self.conn = conn

        self.builder.connect_signals({
            "on_net_source_changed": self._on_net_source_changed,
            "on_net_portgroup_changed": self._emit_changed,
            "on_net_bridge_name_changed": self._emit_changed,
        })

        self._init_ui()
        self.top_label = self.widget("net-source-label")
        self.top_box = self.widget("net-source-box")

    def _cleanup(self):
        self.conn.disconnect_by_obj(self)
        self.conn = None

        self.top_label.destroy()
        self.top_box.destroy()


    ##########################
    # Initialization methods #
    ##########################

    def _init_ui(self):
        fields = []
        fields.insert(NET_ROW_LABEL, str)
        fields.insert(NET_ROW_SENSITIVE, bool)
        fields.insert(NET_ROW_DATA, object)

        model = Gtk.ListStore(*fields)
        combo = self.widget("net-source")
        combo.set_model(model)

        text = Gtk.CellRendererText()
        combo.pack_start(text, True)
        combo.add_attribute(text, 'text', NET_ROW_LABEL)
        combo.add_attribute(text, 'sensitive', NET_ROW_SENSITIVE)

        combo = self.widget("net-portgroup")
        model = Gtk.ListStore(str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 0)

        self.conn.connect("net-added", self._repopulate_network_list)
        self.conn.connect("net-removed", self._repopulate_network_list)

    def _find_virtual_networks(self):
        rows = []

        for net in self.conn.list_nets():
            nettype = virtinst.DeviceInterface.TYPE_VIRTUAL

            label = _pretty_network_desc(nettype, net.get_name(), net)
            if not net.is_active():
                label += " (%s)" % _("Inactive")

            if net.get_xmlobj().virtualport_type == "openvswitch":
                label += " (OpenVSwitch)"

            row = _NetRowData.build_row(nettype, net.get_name(), label, True)
            rows.append(row)

        return rows

    def _populate_network_model(self, model):
        model.clear()

        def _add_manual_bridge_row():
            _nettype = virtinst.DeviceInterface.TYPE_BRIDGE
            _label = _("Bridge device...")
            model.append(_build_manual_row(_nettype, _label))
            return len(model) - 1

        def _add_manual_macvtap_row():
            _label = _("Macvtap device...")
            _nettype = virtinst.DeviceInterface.TYPE_DIRECT
            model.append(_build_manual_row(_nettype, _label))

        vnets = self._find_virtual_networks()
        default_bridge = virtinst.DeviceInterface.default_bridge(
                self.conn.get_backend())

        add_usermode = False
        if self.conn.is_qemu_unprivileged():
            log.debug("Using unprivileged qemu, adding usermode net")
            vnets = []
            default_bridge = None
            add_usermode = True

        if add_usermode:
            nettype = virtinst.DeviceInterface.TYPE_USER
            label = _pretty_network_desc(nettype)
            model.append(_NetRowData.build_row(nettype, None, label, True))

        defaultnetidx = None
        for row in sorted(vnets, key=lambda r: r[NET_ROW_LABEL]):
            model.append(row)
            if row[NET_ROW_DATA].source == "default":
                defaultnetidx = len(model) - 1

        bridgeidx = _add_manual_bridge_row()
        _add_manual_macvtap_row()

        # If there is a bridge device, default to that
        if default_bridge:
            self.widget("net-manual-source").set_text(default_bridge)
            return bridgeidx

        # If not, use 'default' network
        if defaultnetidx is not None:
            return defaultnetidx

        # If not present, use first list entry
        if bridgeidx == 0:
            # This means we are defaulting to something that
            # requires manual intervention. Raise the warning
            self.widget("net-default-warn-box").show()
        return 0

    def _check_network_is_running(self, net):
        # Make sure VirtualNetwork is running
        if not net.type == virtinst.DeviceInterface.TYPE_VIRTUAL:
            return
        devname = net.source

        netobj = None
        if net.type == virtinst.DeviceInterface.TYPE_VIRTUAL:
            netobj = self.conn.get_net_by_name(devname)

        if not netobj or netobj.is_active():
            return

        res = self.err.yes_no(_("Virtual Network is not active."),
            _("Virtual Network '%s' is not active. "
              "Would you like to start the network "
              "now?") % devname)
        if not res:
            return  # pragma: no cover

        # Try to start the network
        try:
            netobj.start()
            log.debug("Started network '%s'", devname)
        except Exception as e:  # pragma: no cover
            return self.err.show_err(
                _("Could not start virtual network '%(device)s': %(error)s") % {
                    "device": devname,
                    "error": str(e),
                })

    def _find_rowiter_for_dev(self, net):
        """
        Find the row in our current model that matches the passed in
        net device (like populating the details UI for an existing VM).
        If we don't find a match, we fake it a bit
        """
        nettype = net.type
        source = net.source
        if net.network:
            # If using type=network with a forward mode=bridge network,
            # on domain startup the runtime XML will be changed to
            # type=bridge and both source/@bridge and source/@network will
            # be filled in. For our purposes, treat this as a type=network
            source = net.network
            nettype = "network"

        combo = self.widget("net-source")
        def _find_row(_nettype, _source, _manual):
            for row in combo.get_model():
                rowdata = row[NET_ROW_DATA]
                if _nettype and rowdata.nettype != _nettype:
                    continue
                if _source and rowdata.source != _source:
                    continue
                if _manual and rowdata.manual != _manual:
                    continue  # pragma: no cover
                return row.iter

        # Find the matching row in the net list
        rowiter = _find_row(nettype, source, None)
        if rowiter:
            return rowiter

        # If this is a bridge or macvtap device, show the
        # manual source mode
        if nettype in [virtinst.DeviceInterface.TYPE_BRIDGE,
                       virtinst.DeviceInterface.TYPE_DIRECT]:
            rowiter = _find_row(nettype, None, True)
            self.widget("net-manual-source").set_text(source or "")
            if rowiter:
                return rowiter

        # This is some network type we don't know about. Generate
        # a label for it and stuff it in the list
        desc = _pretty_network_desc(nettype, source)
        combo.get_model().insert(0,
            _NetRowData.build_row(nettype, source, desc, True))
        return combo.get_model()[0].iter


    ###############
    # Public APIs #
    ###############

    def _get_network_row_data(self):
        return uiutil.get_list_selection(
                self.widget("net-source"), column=NET_ROW_DATA)

    def get_network_selection(self):
        rowdata = self._get_network_row_data()
        net_type = rowdata.nettype
        net_src = rowdata.source
        net_check_manual = rowdata.manual

        if net_check_manual:
            net_src = self.widget("net-manual-source").get_text() or None

        mode = None
        is_direct = (net_type == virtinst.DeviceInterface.TYPE_DIRECT)
        if is_direct:
            # This is generally the safest and most featureful default
            mode = "bridge"

        portgroup = None
        if self.widget("net-portgroup").is_visible():
            portgroup = uiutil.get_list_selection(self.widget("net-portgroup"))

        return net_type, net_src, mode, portgroup

    def build_device(self, macaddr, model=None):
        nettype, devname, mode, portgroup = self.get_network_selection()

        net = virtinst.DeviceInterface(self.conn.get_backend())
        net.type = nettype
        net.source = devname
        net.macaddr = macaddr
        net.model = model
        net.source_mode = mode
        net.portgroup = portgroup

        return net

    def validate_device(self, net):
        self._check_network_is_running(net)
        virtinst.DeviceInterface.check_mac_in_use(net.conn, net.macaddr)
        net.validate()

    def reset_state(self):
        self.widget("net-default-warn-box").set_visible(False)
        self.widget("net-manual-source").set_text("")
        self.widget("net-portgroup").get_child().set_text("")
        self._repopulate_network_list()

    def set_dev(self, net):
        self.reset_state()
        rowiter = self._find_rowiter_for_dev(net)

        combo = self.widget("net-source")
        combo.set_active_iter(rowiter)
        combo.emit("changed")

        if net.portgroup:
            uiutil.set_list_selection(
                    self.widget("net-portgroup"), net.portgroup)


    #############
    # Listeners #
    #############

    def _emit_changed(self, *args, **kwargs):
        ignore1 = args
        ignore2 = kwargs
        self.emit("changed")

    def _repopulate_network_list(self, *args, **kwargs):
        ignore1 = args
        ignore2 = kwargs

        netlist = self.widget("net-source")
        current_label = uiutil.get_list_selection(
                netlist, column=NET_ROW_LABEL)

        model = netlist.get_model()
        if not model:
            return  # pragma: no cover

        try:
            if model:
                netlist.set_model(None)
                default_idx = self._populate_network_model(model)
        finally:
            netlist.set_model(model)

        for row in netlist.get_model():
            if current_label and row[NET_ROW_LABEL] == current_label:
                netlist.set_active_iter(row.iter)
                return

        netlist.set_active(default_idx)


    def _populate_portgroups(self, portgroups):
        combo = self.widget("net-portgroup")
        model = combo.get_model()
        model.clear()

        default = None
        for p in portgroups:
            model.append([p.name])
            if p.default:
                default = p.name

        uiutil.set_list_selection(combo, default)

    def _on_net_source_changed(self, src):
        ignore = src
        self._emit_changed()
        rowdata = self._get_network_row_data()
        if not rowdata:
            return  # pragma: no cover

        nettype = rowdata.nettype
        is_direct = (nettype == virtinst.DeviceInterface.TYPE_DIRECT)
        is_virtual = (nettype == virtinst.DeviceInterface.TYPE_VIRTUAL)

        uiutil.set_grid_row_visible(
            self.widget("net-macvtap-warn-box"), is_direct)

        show_bridge = rowdata.manual
        uiutil.set_grid_row_visible(
            self.widget("net-manual-source"), show_bridge)

        net = None
        if is_virtual:
            net = self.conn.get_net_by_name(rowdata.source)

        portgroups = []
        if net:
            portgroups = net.get_xmlobj().portgroups

        uiutil.set_grid_row_visible(
            self.widget("net-portgroup"), bool(portgroups))
        self._populate_portgroups(portgroups)
