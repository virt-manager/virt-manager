#
# Copyright (C) 2014 Red Hat, Inc.
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

# pylint: disable=E0611
from gi.repository import Gtk
from gi.repository import GObject
# pylint: enable=E0611

import virtinst
from virtManager import uiutil
from virtManager.baseclass import vmmGObjectUI


class vmmNetworkList(vmmGObjectUI):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, []),
        "changed-vport": (GObject.SignalFlags.RUN_FIRST, None, [])
    }

    def __init__(self, conn, builder, topwin):
        vmmGObjectUI.__init__(self, "netlist.ui",
                              None, builder=builder, topwin=topwin)
        self.conn = conn

        self.builder.connect_signals({
            "on_net_source_changed": self._on_net_source_changed,
            "on_net_source_mode_changed": self._emit_changed,
            "on_net_bridge_name_changed": self._emit_changed,

            "on_vport_type_changed": self._emit_vport_changed,
            "on_vport_managerid_changed": self._emit_vport_changed,
            "on_vport_typeid_changed": self._emit_vport_changed,
            "on_vport_typeidversion_changed": self._emit_vport_changed,
            "on_vport_instanceid_changed": self._emit_vport_changed,
        })

        self._init_ui()
        self.top_label = self.widget("net-source-label")
        self.top_box = self.widget("net-source-box")
        self.top_vport = self.widget("vport-expander")

    def _cleanup(self):
        try:
            self.conn.disconnect_by_func(self._repopulate_network_list)
        except:
            pass

        self.conn = None


    ##########################
    # Initialization methods #
    ##########################

    def _init_ui(self):
        # [ network type, source name, label, sensitive?, net is active,
        #   manual bridge, net instance]
        model = Gtk.ListStore(str, str, str, bool, bool, bool, object)
        combo = self.widget("net-source")
        combo.set_model(model)

        text = Gtk.CellRendererText()
        combo.pack_start(text, True)
        combo.add_attribute(text, 'text', 2)
        combo.add_attribute(text, 'sensitive', 3)

        combo = self.widget("net-source-mode")
        # [xml value, label]
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.set_combo_text_column(combo, 1)

        model.append(["bridge", "Bridge"])
        model.append(["vepa", "VEPA"])
        model.append(["private", "Private"])
        model.append(["passthrough", "Passthrough"])

        combo.set_active(0)

        self.conn.connect("net-added", self._repopulate_network_list)
        self.conn.connect("net-removed", self._repopulate_network_list)
        self.conn.connect("interface-added", self._repopulate_network_list)
        self.conn.connect("interface-removed", self._repopulate_network_list)

    def _pretty_network_desc(self, nettype, source=None, netobj=None):
        if nettype == virtinst.VirtualNetworkInterface.TYPE_USER:
            return _("Usermode networking")

        extra = None
        if nettype == virtinst.VirtualNetworkInterface.TYPE_BRIDGE:
            ret = _("Bridge")
        elif nettype == virtinst.VirtualNetworkInterface.TYPE_VIRTUAL:
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

    def _build_source_row(self, nettype, name,
        label, is_sensitive, is_running, manual_bridge=False, key=None):
        return [nettype, name, label,
                is_sensitive, is_running, manual_bridge,
                key]

    def _find_virtual_networks(self):
        vnet_dict = {}
        vnet_bridges = []
        hasNet = False
        netIdxLabel = None

        for uuid in self.conn.list_net_uuids():
            net = self.conn.get_net(uuid)
            nettype = virtinst.VirtualNetworkInterface.TYPE_VIRTUAL

            label = self._pretty_network_desc(nettype, net.get_name(), net)
            if not net.is_active():
                label += " (%s)" % _("Inactive")

            hasNet = True
            # FIXME: Should we use 'default' even if it's inactive?
            # FIXME: This preference should be configurable
            if net.get_name() == "default":
                netIdxLabel = label

            vnet_dict[label] = self._build_source_row(
                nettype, net.get_name(), label, True,
                net.is_active(), key=net.get_uuid())

            # Build a list of vnet bridges, so we know not to list them
            # in the physical interface list
            vnet_bridge = net.get_bridge_device()
            if vnet_bridge:
                vnet_bridges.append(vnet_bridge)

        if not hasNet:
            label = _("No virtual networks available")
            vnet_dict[label] = self._build_source_row(
                None, None, label, False, False)

        return vnet_dict, vnet_bridges, netIdxLabel

    def _find_physical_devices(self, vnet_bridges):
        vnet_taps = []
        for vm in self.conn.vms.values():
            for nic in vm.get_network_devices(refresh_if_nec=False):
                if nic.target_dev and nic.target_dev not in vnet_taps:
                    vnet_taps.append(nic.target_dev)

        bridge_dict = {}
        iface_dict = {}
        hasShared = False
        brIdxLabel = None
        skip_ifaces = ["lo"]

        for name in self.conn.list_net_device_paths():
            br = self.conn.get_net_device(name)
            bridge_name = br.get_bridge()
            nettype = virtinst.VirtualNetworkInterface.TYPE_BRIDGE

            if ((bridge_name in vnet_bridges) or
                (br.get_name() in vnet_bridges) or
                (br.get_name() in vnet_taps) or
                (br.get_name() in [v + "-nic" for v in vnet_bridges]) or
                (br.get_name() in skip_ifaces)):
                # Don't list this, as it is basically duplicating
                # virtual net info
                continue

            if br.is_shared():
                sensitive = True
                if br.get_bridge():
                    hasShared = True
                    brlabel = "(%s)" % self._pretty_network_desc(nettype,
                                                                 bridge_name)
                else:
                    bridge_name = name
                    brlabel = _("(Empty bridge)")
            else:
                if self.conn.check_support(
                    self.conn.SUPPORT_CONN_DIRECT_INTERFACE):
                    sensitive = True
                    nettype = virtinst.VirtualNetworkInterface.TYPE_DIRECT
                    bridge_name = name
                    brlabel = ": %s" % _("macvtap")
                else:
                    sensitive = False
                    brlabel = "(%s)" % _("Not bridged")

            label = _("Host device %s %s") % (br.get_name(), brlabel)
            if hasShared and not brIdxLabel:
                brIdxLabel = label

            row = self._build_source_row(
                nettype, bridge_name, label, sensitive, True,
                key=br.get_name())

            if sensitive:
                bridge_dict[label] = row
            else:
                iface_dict[label] = row

        return bridge_dict, iface_dict, brIdxLabel

    def _populate_network_list(self):
        net_list = self.widget("net-source")
        model = net_list.get_model()
        model.clear()

        # For qemu:///session
        if self.conn.is_qemu_session():
            nettype = virtinst.VirtualNetworkInterface.TYPE_USER
            r = self._build_source_row(
                nettype, None, self._pretty_network_desc(nettype), True, True)
            model.append(r)
            net_list.set_active(0)
            return

        (vnet_dict, vnet_bridges, netIdxLabel) = self._find_virtual_networks()
        (bridge_dict, iface_dict, brIdxLabel) = self._find_physical_devices(
            vnet_bridges)

        for indict in [bridge_dict, vnet_dict, iface_dict]:
            keylist = indict.keys()
            keylist.sort()
            rowlist = [indict[k] for k in keylist]
            for row in rowlist:
                model.append(row)

        # If there is a bridge device, default to that
        # If not, use 'default' network
        # If not present, use first list entry
        # If list empty, use no network devices
        label = brIdxLabel or netIdxLabel

        default = 0
        if not len(model):
            row = self._build_source_row(
                None, None, _("No networking"), True, False)
            model.insert(0, row)
            default = 0
        elif label:
            default = [idx for idx in range(len(model)) if
                       model[idx][2] == label][0]

        # After all is said and done, add a manual bridge option
        manual_row = self._build_source_row(
            None, None, _("Specify shared device name"),
            True, False, manual_bridge=True)
        model.append(manual_row)

        net_list.set_active(default)


    ###############
    # Public APIs #
    ###############

    def get_network_row(self):
        return uiutil.get_list_selection(self.widget("net-source"))

    def get_network_selection(self):
        net_list = self.widget("net-source")
        bridge_entry = self.widget("net-bridge-name")

        row = uiutil.get_list_selection(net_list)
        if not row:
            return None, None, None

        net_type = row[0]
        net_src = row[1]
        net_check_bridge = row[5]

        if net_check_bridge and bridge_entry:
            net_type = virtinst.VirtualNetworkInterface.TYPE_BRIDGE
            net_src = bridge_entry.get_text()

        mode = None
        if self.widget("net-source-mode").is_visible():
            mode = uiutil.get_list_selection(self.widget("net-source-mode"), 0)

        return net_type, net_src, mode

    def get_vport(self):
        vport_type = self.widget("vport-type").get_text()
        vport_managerid = self.widget("vport-managerid").get_text()
        vport_typeid = self.widget("vport-typeid").get_text()
        vport_idver = self.widget("vport-typeidversion").get_text()
        vport_instid = self.widget("vport-instanceid").get_text()

        return (vport_type, vport_managerid, vport_typeid,
         vport_idver, vport_instid)

    def validate_network(self, macaddr, model=None):
        nettype, devname, mode = self.get_network_selection()
        if nettype is None:
            return None

        net = None

        # Make sure VirtualNetwork is running
        netobj = None
        if nettype == virtinst.VirtualNetworkInterface.TYPE_VIRTUAL:
            for net in self.conn.nets.values():
                if net.get_name() == devname:
                    netobj = net
                    break

        if netobj and not netobj.is_active():
            res = self.err.yes_no(_("Virtual Network is not active."),
                _("Virtual Network '%s' is not active. "
                  "Would you like to start the network "
                  "now?") % devname)
            if not res:
                return False

            # Try to start the network
            try:
                netobj.start()
                netobj.tick()
                logging.info("Started network '%s'", devname)
            except Exception, e:
                return self.err.show_err(_("Could not start virtual network "
                                      "'%s': %s") % (devname, str(e)))

        # Create network device
        try:
            net = virtinst.VirtualNetworkInterface(self.conn.get_backend())
            net.type = nettype
            net.source = devname
            net.macaddr = macaddr
            net.model = model
            net.source_mode = mode
            if net.model == "spapr-vlan":
                net.address.set_addrstr("spapr-vio")

            if net.type == "direct":
                (vport_type, vport_managerid, vport_typeid,
                 vport_idver, vport_instid) = self.get_vport()

                net.virtualport.type = vport_type or None
                net.virtualport.managerid = vport_managerid or None
                net.virtualport.typeid = vport_typeid or None
                net.virtualport.typeidversion = vport_idver or None
                net.virtualport.instanceid = vport_instid or None
        except Exception, e:
            return self.err.val_err(_("Error with network parameters."), e)

        # Make sure there is no mac address collision
        isfatal, errmsg = net.is_conflict_net(net.conn, net.macaddr)
        if isfatal:
            return self.err.val_err(_("Mac address collision."), errmsg)
        elif errmsg is not None:
            retv = self.err.yes_no(_("Mac address collision."),
                _("%s Are you sure you want to use this address?") % errmsg)
            if not retv:
                return False

        return net

    def reset_state(self):
        self._populate_network_list()

        net_warn = self.widget("net-source-warn")
        net_err = self.conn.netdev_error
        net_warn.set_visible(bool(net_err))
        net_warn.set_tooltip_text(net_err or "")

        self.widget("net-bridge-name").set_text("")
        self.widget("net-source-mode").set_active(0)

        self.widget("vport-type").set_text("")
        self.widget("vport-managerid").set_text("")
        self.widget("vport-typeid").set_text("")
        self.widget("vport-typeidversion").set_text("")
        self.widget("vport-instanceid").set_text("")

    def set_dev(self, net):
        self.reset_state()

        nettype = net.type
        source = net.source
        source_mode = net.source_mode
        is_direct = (net.type == "direct")

        uiutil.set_combo_entry(self.widget("net-source-mode"), source_mode)

        # Virtualport config
        self.widget("vport-expander").set_visible(is_direct)

        vport = net.virtualport
        self.widget("vport-type").set_text(vport.type or "")
        self.widget("vport-managerid").set_text(str(vport.managerid or ""))
        self.widget("vport-typeid").set_text(str(vport.typeid or ""))
        self.widget("vport-typeidversion").set_text(
            str(vport.typeidversion or ""))
        self.widget("vport-instanceid").set_text(vport.instanceid or "")

        # Find the matching row in the net list
        combo = self.widget("net-source")
        rowiter = None
        for row in combo.get_model():
            if row[0] == nettype and row[1] == source:
                rowiter = row.iter
                break
        if not rowiter:
            if nettype == "bridge":
                rowiter = combo.get_model()[-1].iter
                self.widget("net-bridge-name").set_text(source)
        if not rowiter:
            desc = self._pretty_network_desc(nettype, source)
            combo.get_model().insert(0,
                self._build_source_row(nettype, source, desc, True, True))
            rowiter = combo.get_model()[0].iter

        combo.set_active_iter(rowiter)
        combo.emit("changed")


    #############
    # Listeners #
    #############

    def _emit_changed(self, *args, **kwargs):
        ignore = args
        ignore = kwargs
        self.emit("changed")

    def _emit_vport_changed(self, *args, **kwargs):
        ignore = args
        ignore = kwargs
        self.emit("changed-vport")

    def _repopulate_network_list(self, *args, **kwargs):
        ignore = args
        ignore = kwargs

        netlist = self.widget("net-source")
        label = uiutil.get_list_selection(netlist, 2)
        self._populate_network_list()

        for row in netlist.get_model():
            if label and row[2] == label:
                netlist.set_active_iter(row.iter)
                return

    def _on_net_source_changed(self, src):
        self._emit_changed()

        row = uiutil.get_list_selection(src)
        if not row:
            return

        is_direct = (row[0] == virtinst.VirtualNetworkInterface.TYPE_DIRECT)

        self.widget("vport-expander").set_visible(is_direct)
        uiutil.set_grid_row_visible(self.widget("net-source-mode"), is_direct)
        uiutil.set_grid_row_visible(
            self.widget("net-macvtap-warn-box"), is_direct)
        if is_direct and self.widget("net-source-mode").get_active() == -1:
            self.widget("net-source-mode").set_active(0)

        show_bridge = row[5]
        uiutil.set_grid_row_visible(
            self.widget("net-bridge-name"), show_bridge)
