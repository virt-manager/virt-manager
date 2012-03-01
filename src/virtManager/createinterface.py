#
# Copyright (C) 2008 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
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

import gtk

import logging

from virtinst import Interface

from virtManager import util
from virtManager import uihelpers
from virtManager.baseclass import vmmGObjectUI
from virtManager.asyncjob import vmmAsyncJob

PAGE_TYPE = 0
PAGE_DETAILS = 1

DETAILS_BOND = 0
DETAILS_BRIDGE = 1
DETAILS_VLAN = 2
DETAILS_ETHERNET = 3

INTERFACE_ROW_KEY = 0
INTERFACE_ROW_SELECT = 1
INTERFACE_ROW_CANT_SELECT = 2
INTERFACE_ROW_NAME = 3
INTERFACE_ROW_TYPE = 4
INTERFACE_ROW_IS_DEFINED = 5
INTERFACE_ROW_IS_ACTIVE = 6
INTERFACE_ROW_IN_USE_BY = 7
INTERFACE_ROW_MAC = 8

BOND_PAGE_ARP = 0
BOND_PAGE_MII = 1
BOND_PAGE_DEFAULT = 2

IP_DHCP = 0
IP_STATIC = 1
IP_NONE = 2

class vmmCreateInterface(vmmGObjectUI):
    def __init__(self, conn):
        vmmGObjectUI.__init__(self,
                              "vmm-create-interface.ui",
                              "vmm-create-interface")
        self.conn = conn
        self.interface = None

        self.bridge_config = self.widget("bridge-config")
        self.bridge_config.set_transient_for(self.topwin)

        self.bond_config = self.widget("bond-config")
        self.bond_config.set_transient_for(self.topwin)

        self.ip_config = self.widget("ip-config")
        self.ip_config.set_transient_for(self.topwin)

        self.ip_manually_changed = False

        self.window.connect_signals({
            "on_vmm_create_interface_delete_event" : self.close,

            "on_cancel_clicked": self.close,
            "on_back_clicked" : self.back,
            "on_forward_clicked" : self.forward,
            "on_finish_clicked" : self.finish,
            "on_help_clicked": self.show_help,
            "on_pages_switch_page": self.page_changed,

            "on_bridge_config_button_clicked": self.show_bridge_config,
            "on_bond_config_button_clicked": self.show_bond_config,
            "on_ip_config_button_clicked": self.show_ip_config,
            "on_vlan_tag_changed": self.update_interface_name,

            # Bridge config dialog
            "on_bridge_config_delete_event": self.bridge_config_finish,
            "on_bridge_ok_clicked" : self.bridge_config_finish,

            # IP config dialog
            "on_ip_config_delete_event": self.ip_config_finish,
            "on_ip_ok_clicked": self.ip_config_finish,

            "on_ip_copy_interface_toggled": self.ip_copy_interface_toggled,

            "on_ipv4_mode_changed": self.ipv4_mode_changed,
            "on_ipv6_mode_changed": self.ipv6_mode_changed,

            "on_ipv6_address_add_clicked": self.ipv6_address_add,
            "on_ipv6_address_remove_clicked": self.ipv6_address_remove,

            # Bond config dialog
            "on_bond_config_delete_event": self.bond_config_finish,
            "on_bond_ok_clicked" : self.bond_config_finish,

            "on_bond_monitor_mode_changed": self.bond_monitor_mode_changed,
        })
        self.bind_escape_key_close()

        self.set_initial_state()

    def show(self, parent):
        logging.debug("Showing new interface wizard")
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def show_bond_config(self, src):
        logging.debug("Showing new interface bond config")
        self.bond_config.show_all()

    def show_bridge_config(self, src):
        logging.debug("Showing new interface bridge config")
        self.bridge_config.show_all()

    def show_ip_config(self, src):
        logging.debug("Showing new interface ip config")
        self.ip_manually_changed = True
        self.ip_config.show_all()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing new interface wizard")
        self.ip_config.hide()
        self.bridge_config.hide()
        self.bond_config.hide()
        self.topwin.hide()

        return 1

    def _cleanup(self):
        self.close()

        self.conn = None
        self.interface = None

        self.ip_config.destroy()
        self.ip_config = None

        self.bridge_config.destroy()
        self.bridge_config = None

        self.bond_config.destroy()
        self.bond_config = None

    ###########################
    # Initialization routines #
    ###########################

    def set_initial_state(self):

        self.widget("pages").set_show_tabs(False)
        self.widget("bond-pages").set_show_tabs(False)

        # FIXME: Unhide this when we make some documentation
        self.widget("help").hide()
        finish_img = gtk.image_new_from_stock(gtk.STOCK_QUIT,
                                              gtk.ICON_SIZE_BUTTON)
        self.widget("finish").set_image(finish_img)

        blue = gtk.gdk.color_parse("#0072A8")
        self.widget("header").modify_bg(gtk.STATE_NORMAL, blue)

        box = self.widget("header-icon-box")
        image = gtk.image_new_from_icon_name("network-idle",
                                             gtk.ICON_SIZE_DIALOG)
        image.show()
        box.pack_end(image, False)

        # Interface type
        type_list = self.widget("interface-type")
        type_model = gtk.ListStore(str, str)
        type_list.set_model(type_model)
        text = gtk.CellRendererText()
        type_list.pack_start(text, True)
        type_list.add_attribute(text, 'text', 1)
        type_model.append([Interface.Interface.INTERFACE_TYPE_BRIDGE,
                           _("Bridge")])
        type_model.append([Interface.Interface.INTERFACE_TYPE_BOND,
                           _("Bond")])
        type_model.append([Interface.Interface.INTERFACE_TYPE_ETHERNET,
                           _("Ethernet")])
        type_model.append([Interface.Interface.INTERFACE_TYPE_VLAN,
                          _("VLAN")])

        # Start mode
        uihelpers.build_startmode_combo(
            self.widget("interface-startmode"))

        # Parent/slave Interface list
        slave_list = self.widget("interface-list")
        # [ vmmInterface, selected, selectabel, name, type, is defined,
        #   is active, in use by str, mac]
        slave_model = gtk.ListStore(object, bool, bool, str, str, bool, bool,
                                    str, str)
        slave_list.set_model(slave_model)

        selectCol = gtk.TreeViewColumn()
        nameCol = gtk.TreeViewColumn(_("Name"))
        typeCol = gtk.TreeViewColumn(_("Type"))
        useCol = gtk.TreeViewColumn(_("In use by"))

        slave_list.append_column(selectCol)
        slave_list.append_column(nameCol)
        slave_list.append_column(typeCol)
        slave_list.append_column(useCol)

        chk = gtk.CellRendererToggle()
        chk.connect("toggled", self.interface_item_toggled, slave_list)
        selectCol.pack_start(chk, False)
        selectCol.add_attribute(chk, "active", INTERFACE_ROW_SELECT)
        selectCol.add_attribute(chk, "inconsistent", INTERFACE_ROW_CANT_SELECT)
        selectCol.set_sort_column_id(INTERFACE_ROW_CANT_SELECT)

        txt = gtk.CellRendererText()
        nameCol.pack_start(txt, True)
        nameCol.add_attribute(txt, "text", INTERFACE_ROW_NAME)
        nameCol.set_sort_column_id(INTERFACE_ROW_NAME)

        txt = gtk.CellRendererText()
        typeCol.pack_start(txt, True)
        typeCol.add_attribute(txt, "text", INTERFACE_ROW_TYPE)
        typeCol.set_sort_column_id(INTERFACE_ROW_TYPE)
        slave_model.set_sort_column_id(INTERFACE_ROW_CANT_SELECT,
                                       gtk.SORT_ASCENDING)

        txt = gtk.CellRendererText()
        useCol.pack_start(txt, True)
        useCol.add_attribute(txt, "text", INTERFACE_ROW_IN_USE_BY)
        useCol.set_sort_column_id(INTERFACE_ROW_IN_USE_BY)

        # Bond config
        mode_list = self.widget("bond-mode")
        mode_model = gtk.ListStore(str, str)
        mode_list.set_model(mode_model)
        txt = gtk.CellRendererText()
        mode_list.pack_start(txt, True)
        mode_list.add_attribute(txt, "text", 0)
        mode_model.append([_("System default"), None])
        for m in Interface.InterfaceBond.INTERFACE_BOND_MODES:
            mode_model.append([m, m])

        mon_list = self.widget("bond-monitor-mode")
        mon_model = gtk.ListStore(str, str)
        mon_list.set_model(mon_model)
        txt = gtk.CellRendererText()
        mon_list.pack_start(txt, True)
        mon_list.add_attribute(txt, "text", 0)
        mon_model.append([_("System default"), None])
        for m in Interface.InterfaceBond.INTERFACE_BOND_MONITOR_MODES:
            mon_model.append([m, m])

        validate_list = self.widget("arp-validate")
        validate_model = gtk.ListStore(str)
        validate_list.set_model(validate_model)
        txt = gtk.CellRendererText()
        validate_list.pack_start(txt, True)
        validate_list.add_attribute(txt, "text", 0)
        for m in Interface.InterfaceBond.INTERFACE_BOND_MONITOR_MODE_ARP_VALIDATE_MODES:
            validate_model.append([m])

        carrier_list = self.widget("mii-carrier")
        carrier_model = gtk.ListStore(str)
        carrier_list.set_model(carrier_model)
        txt = gtk.CellRendererText()
        carrier_list.pack_start(txt, True)
        carrier_list.add_attribute(txt, "text", 0)
        for m in Interface.InterfaceBond.INTERFACE_BOND_MONITOR_MODE_MII_CARRIER_TYPES:
            carrier_model.append([m])

        # IP config
        copy_iface = self.widget("ip-copy-interface-combo")
        copy_model = gtk.ListStore(str, object, bool)
        copy_iface.set_model(copy_model)
        txt = gtk.CellRendererText()
        copy_iface.pack_start(txt, True)
        copy_iface.add_attribute(txt, "text", 0)
        copy_iface.add_attribute(txt, "sensitive", 2)

        ip_mode = self.widget("ipv4-mode")
        ip_model = gtk.ListStore(str)
        ip_mode.set_model(ip_model)
        txt = gtk.CellRendererText()
        ip_mode.pack_start(txt, True)
        ip_mode.add_attribute(txt, "text", 0)
        ip_model.insert(IP_DHCP, ["DHCP"])
        ip_model.insert(IP_STATIC, ["Static"])
        ip_model.insert(IP_NONE, ["No configuration"])

        ip_mode = self.widget("ipv6-mode")
        ip_model = gtk.ListStore(str)
        ip_mode.set_model(ip_model)
        txt = gtk.CellRendererText()
        ip_mode.pack_start(txt, True)
        ip_mode.add_attribute(txt, "text", 0)
        ip_model.insert(IP_DHCP, ["DHCP"])
        ip_model.insert(IP_STATIC, ["Static"])
        ip_model.insert(IP_NONE, ["No configuration"])

        v6_addr = self.widget("ipv6-address-list")
        addr_model = gtk.ListStore(str)
        v6_addr.set_model(addr_model)
        txt_col = gtk.TreeViewColumn("")
        v6_addr.append_column(txt_col)
        txt = gtk.CellRendererText()
        txt.set_property("editable", True)
        txt.connect("edited", self.ipv6_address_editted)
        txt_col.pack_start(txt, True)
        txt_col.add_attribute(txt, "text", 0)
        v6_addr.get_selection().connect("changed", self.ipv6_address_selected)

    def reset_state(self):

        self.widget("pages").set_current_page(PAGE_TYPE)
        self.page_changed(None, None, PAGE_TYPE)

        self.widget("interface-type").set_active(0)

        # General details
        self.widget("interface-name-entry").set_text("")
        self.widget("interface-name-label").set_text("")
        self.widget("interface-startmode").set_active(0)
        self.widget("interface-activate").set_active(False)

        # Bridge config
        self.widget("bridge-delay").set_value(0)
        self.widget("bridge-stp").set_active(True)

        # Bond config
        self.widget("bond-mode").set_active(0)
        self.widget("bond-monitor-mode").set_active(0)

        self.widget("arp-interval").set_value(0)
        self.widget("arp-target").set_text("")
        self.widget("arp-validate").set_active(0)

        self.widget("mii-frequency").set_value(0)
        self.widget("mii-updelay").set_value(0)
        self.widget("mii-downdelay").set_value(0)
        self.widget("mii-carrier").set_active(0)

        # IP config
        self.ip_manually_changed = False
        self.widget("ip-do-manual").set_active(True)
        self.widget("ip-do-manual-box").set_current_page(0)

        self.widget("ipv4-mode").set_active(IP_DHCP)
        self.widget("ipv4-address").set_text("")
        self.widget("ipv4-gateway").set_text("")

        self.widget("ipv6-mode").set_active(IP_NONE)
        self.widget("ipv6-autoconf").set_active(False)
        self.ipv6_address_selected()

    def populate_details_page(self):
        itype = self.get_config_interface_type()

        # Set up default interface name
        self.widget("interface-name-entry").hide()
        self.widget("interface-name-label").hide()

        if itype in [Interface.Interface.INTERFACE_TYPE_BRIDGE,
                     Interface.Interface.INTERFACE_TYPE_BOND]:
            widget = "interface-name-entry"
        else:
            widget = "interface-name-label"

        self.widget(widget).show()
        default_name = self.get_default_name()
        self.set_interface_name(default_name)

        # Make sure interface type specific fields are shown
        type_dict = {
            Interface.Interface.INTERFACE_TYPE_BRIDGE : "bridge",
            Interface.Interface.INTERFACE_TYPE_BOND : "bond",
            Interface.Interface.INTERFACE_TYPE_VLAN : "vlan",
        }

        for key, value in type_dict.items():
            do_show = (key == itype)
            self.widget("%s-label" % value).set_property("visible", do_show)
            self.widget("%s-box" % value).set_property("visible", do_show)

        if itype == Interface.Interface.INTERFACE_TYPE_BRIDGE:
            self.update_bridge_desc()

        elif itype == Interface.Interface.INTERFACE_TYPE_BOND:
            self.update_bond_desc()

        # Populate device list
        self.populate_interface_list(itype)

        self.update_ip_config()

    def update_ip_config(self):
        (is_manual, current_name,
         ignore, ignore, ignore) = self.get_config_ip_info()
        itype = self.get_config_interface_type()
        ifaces = self.get_config_selected_interfaces()

        copy_radio = self.widget("ip-copy-interface")
        copy_combo = self.widget("ip-copy-interface-combo")
        copy_model = copy_combo.get_model()

        # Only select 'copy from' option if using bridge/bond/vlan
        enable_copy = (itype in [Interface.Interface.INTERFACE_TYPE_BRIDGE,
                                 Interface.Interface.INTERFACE_TYPE_BOND,
                                 Interface.Interface.INTERFACE_TYPE_VLAN])

        # Set defaults if required
        copy_model.clear()
        active_rows = []
        inactive_rows = []
        for row in ifaces:
            is_defined = row[INTERFACE_ROW_IS_DEFINED]
            name = row[INTERFACE_ROW_NAME]
            label = name
            sensitive = False

            iface_obj = None
            if is_defined:
                iface_obj = self.conn.get_interface(name)

            # We only want configured (aka interface API) interfaces with
            # actually present <protocol> info
            if not is_defined or not iface_obj:
                label += " (Not configured)"
            elif not iface_obj.get_protocol_xml():
                label += " (No IP configuration)"
            else:
                sensitive = True

            row = [label, iface_obj, sensitive]
            if sensitive:
                active_rows.append(row)
            else:
                inactive_rows.append(row)

        # Make sure inactive rows are listed after active rows
        for row in active_rows + inactive_rows:
            copy_model.append(row)

        if len(copy_model) == 0:
            copy_model.append(["No child interfaces selected.", None, False])

        if not enable_copy:
            copy_model.clear()
            copy_model.append(["", None, False])

        # Find default model selection
        have_valid_copy = bool(active_rows)

        # Re select previous selection, 0 otherwise
        idx = 0
        if not is_manual and current_name:
            found_idx = 0
            for row in copy_model:
                if row[1] == current_name:
                    idx = found_idx
                    break
                found_idx += 1
        copy_combo.set_active(idx)

        copy_radio.set_sensitive(enable_copy)
        if not self.ip_manually_changed:
            if (enable_copy and have_valid_copy):
                copy_radio.set_active(True)
            else:
                self.widget("ip-do-manual").set_active(True)

        self.update_ip_desc()

    def populate_interface_list(self, itype):
        iface_list = self.widget("interface-list")
        model = iface_list.get_model()
        model.clear()

        ifilter = [Interface.Interface.INTERFACE_TYPE_ETHERNET]
        msg = None
        if itype == Interface.Interface.INTERFACE_TYPE_BRIDGE:
            ifilter.append(Interface.Interface.INTERFACE_TYPE_VLAN)
            ifilter.append(Interface.Interface.INTERFACE_TYPE_BOND)
            msg = _("Choose interface(s) to bridge:")

        elif itype == Interface.Interface.INTERFACE_TYPE_VLAN:
            msg = _("Choose parent interface:")
        elif itype == Interface.Interface.INTERFACE_TYPE_BOND:
            msg = _("Choose interfaces to bond:")
        elif itype == Interface.Interface.INTERFACE_TYPE_ETHERNET:
            msg = _("Choose an unconfigured interface:")

        self.widget("interface-list-text").set_text(msg)

        iface_list = []
        row_dict = {}

        for phys in self.conn.get_nodedevs("net"):
            row_dict[phys.interface] = [phys.interface,
                                        False, False, phys.interface,
                                        "ethernet", False, True, None,
                                        phys.address]

        for name in self.conn.list_interface_names():
            iface = self.conn.get_interface(name)
            key = iface.interface
            iface_type = iface.get_type()
            active = iface.is_active()
            name = iface.get_name()

            if iface_type not in ifilter:
                continue

            if itype == Interface.Interface.INTERFACE_TYPE_ETHERNET:
                if name in row_dict:
                    del(row_dict[name])

                # We only want 'unconfigured' interfaces here
                continue

            if name in row_dict:
                # Interface was listed via nodedev APIs
                row = row_dict[name]
                row[INTERFACE_ROW_KEY] = key
                row[INTERFACE_ROW_IS_DEFINED] = True
                row[INTERFACE_ROW_IS_ACTIVE] = True

            else:
                # Brand new row
                row = [key, False, False,
                       iface.get_name(), iface.get_type(), True,
                       active, None, iface.get_mac()]
                row_dict[name] = row

        for row in row_dict.values():
            name = row[INTERFACE_ROW_NAME]
            row[INTERFACE_ROW_IN_USE_BY] = util.iface_in_use_by(self.conn,
                                                                name)

        for row in row_dict.values():
            model.append(row)

    def get_default_name(self):
        itype = self.get_config_interface_type()

        name = _("No interface selected")
        if itype == Interface.Interface.INTERFACE_TYPE_BRIDGE:
            name = Interface.Interface.find_free_name(self.conn.vmm, "br")
        elif itype == Interface.Interface.INTERFACE_TYPE_BOND:
            name = Interface.Interface.find_free_name(self.conn.vmm, "bond")
        else:
            ifaces = self.get_config_selected_interfaces()
            if len(ifaces) > 0:
                iface = ifaces[0][INTERFACE_ROW_NAME]

                if itype == Interface.Interface.INTERFACE_TYPE_VLAN:
                    tag = uihelpers.spin_get_helper(self.widget("vlan-tag"))
                    name = "%s.%s" % (iface, int(tag))

                elif itype == Interface.Interface.INTERFACE_TYPE_ETHERNET:
                    name = iface

        return name


    #########################
    # get_config_* routines #
    #########################

    def get_config_interface_type(self):
        type_list = self.widget("interface-type")
        return type_list.get_model()[type_list.get_active()][0]

    def set_interface_name(self, name):
        if self.widget("interface-name-entry").get_property("visible"):
            widget = "interface-name-entry"
        else:
            widget = "interface-name-label"

        self.widget(widget).set_text(name)

    def get_config_interface_name(self):
        if self.widget("interface-name-entry").get_property("visible"):
            return self.widget("interface-name-entry").get_text()
        else:
            return self.widget("interface-name-label").get_text()

    def get_config_interface_startmode(self):
        start_list = self.widget("interface-startmode")
        return start_list.get_model()[start_list.get_active()][0]

    def get_config_selected_interfaces(self):
        iface_list = self.widget("interface-list")
        model = iface_list.get_model()
        ret = []

        for row in model:
            active = row[INTERFACE_ROW_SELECT]
            iobj = row[INTERFACE_ROW_KEY]

            if active:
                ret.append(row)

        return ret

    def get_config_bridge_params(self):
        delay = self.widget("bridge-delay").get_value()
        stp = self.widget("bridge-stp").get_active()
        return [delay, stp]

    def get_config_ipv6_address_selection(self):
        src = self.widget("ipv6-address-list")
        selection = src.get_selection()
        ignore, treepath = selection.get_selected()
        return treepath

    def get_config_ipv6_addresses(self):
        src = self.widget("ipv6-address-list")
        model = src.get_model()
        return map(lambda x: x[0], model)

    ################
    # UI Listeners #
    ################

    def interface_item_toggled(self, src, index, slave_list):
        itype = self.get_config_interface_type()
        active = src.get_active()
        model = slave_list.get_model()

        if itype in [Interface.Interface.INTERFACE_TYPE_ETHERNET,
                     Interface.Interface.INTERFACE_TYPE_VLAN]:
            # Deselect any selected rows
            for row in model:
                if row == model[index]:
                    continue
                row[INTERFACE_ROW_SELECT] = False

        # Toggle the clicked row
        model[index][INTERFACE_ROW_SELECT] = not active

        self.update_interface_name()
        self.update_ip_config()

    def update_interface_name(self, ignore1=None, ignore2=None):
        itype = self.get_config_interface_type()
        if itype not in [Interface.Interface.INTERFACE_TYPE_VLAN,
                         Interface.Interface.INTERFACE_TYPE_ETHERNET]:
            # The rest have editable name fields, so don't overwrite
            return

        name = self.get_default_name()
        self.set_interface_name(name)

    def bond_monitor_mode_changed(self, src):
        model = src.get_model()
        value = model[src.get_active()][1]
        bond_pages = self.widget("bond-pages")

        if value == "arpmon":
            page = BOND_PAGE_ARP
        elif value == "miimon":
            page = BOND_PAGE_MII
        else:
            page = BOND_PAGE_DEFAULT

        bond_pages.set_current_page(page)

    def ip_copy_interface_toggled(self, src):
        active = src.get_active()

        self.widget("ip-copy-interface-box").set_sensitive(active)
        self.widget("ip-do-manual-box").set_sensitive(not active)

    def ipv4_mode_changed(self, src):
        static = (src.get_active() == IP_STATIC)
        self.widget("ipv4-static-box").set_sensitive(static)

    def ipv6_mode_changed(self, src):
        static = (src.get_active() == IP_STATIC)
        self.widget("ipv6-static-box").set_sensitive(static)

    def update_bridge_desc(self):
        delay, stp = self.get_config_bridge_params()
        txt  = "STP %s" % (stp and "on" or "off")
        txt += ", delay %d sec" % int(delay)

        self.widget("bridge-config-label").set_text(txt)

    def update_bond_desc(self):
        mode_list = self.widget("bond-mode")
        model = mode_list.get_model()
        mode = model[mode_list.get_active()][0]

        mon_list = self.widget("bond-monitor-mode")
        model = mon_list.get_model()
        mon = model[mon_list.get_active()][1]

        txt = mode
        if mon:
            txt += ", %s" % mon

        self.widget("bond-config-label").set_text(txt)

    def update_ip_desc(self):
        is_manual, name, ipv4, ipv6, ignore = self.get_config_ip_info()
        label = ""

        if is_manual:
            if ipv4:
                label += "IPv4: %s" % (ipv4.dhcp and "DHCP" or "Static")

            if ipv6:
                if label:
                    label += ", "
                label += "IPv6: "

                mode_label = ""
                if ipv6.autoconf and ipv6.dhcp:
                    mode_label += "Autoconf "

                if ipv6.dhcp:
                    mode_label += "DHCP"

                if not mode_label:
                    mode_label = "Static"

                label += mode_label

        else:
            if name:
                label = "Copy configuration from '%s'" % name

        if not label:
            label = "No configuration"

        self.widget("ip-config-label").set_text(label)

    def get_config_ip_info(self):
        if not self.widget("ip-label").get_property("visible"):
            return [True, None, None, None, None]

        if not self.validate_ip_info():
            return [True, None, None, None, None]

        return self.build_ip_info()

    def build_ip_info(self):
        def get_row(widget):
            combo = widget.get_model()
            active = widget.get_active()
            if active == -1:
                return None
            return combo[active]

        def build_ip(addr_str):
            if not addr_str:
                return None

            ret = addr_str.rsplit("/", 1)
            ip = Interface.InterfaceProtocolIPAddress(ret[0])
            if len(ret) > 1:
                ip.prefix = ret[1]

            return ip

        is_manual = self.widget("ip-do-manual").get_active()

        copy_row = get_row(self.widget("ip-copy-interface-combo"))

        v4_mode = self.widget("ipv4-mode").get_active()
        v4_addr = self.widget("ipv4-address").get_text()
        v4_gate = self.widget("ipv4-gateway").get_text()

        v6_mode = self.widget("ipv6-mode").get_active()
        v6_auto = self.widget("ipv6-autoconf").get_active()
        v6_gate = self.widget("ipv6-gateway").get_text()
        v6_addrlist = self.get_config_ipv6_addresses()

        copy_name = None
        proto_xml = None
        ipv4 = None
        ipv6 = None

        if not is_manual:
            if copy_row[1] and copy_row[2]:
                copy_name = copy_row[1].get_name()
                proto_xml = copy_row[1].get_protocol_xml()

        else:
            # Build IPv4 Info
            if v4_mode != IP_NONE:
                ipv4 = Interface.InterfaceProtocolIPv4()
                ipv4.dhcp = bool(v4_mode == IP_DHCP)
                if not ipv4.dhcp:
                    if v4_addr:
                        ipv4.ips.append(build_ip(v4_addr))

                    if v4_gate:
                        ipv4.gateway = v4_gate

            # Build IPv6 Info
            if v6_mode != IP_NONE:
                ipv6 = Interface.InterfaceProtocolIPv6()
                ipv6.dhcp = bool(v6_mode == IP_DHCP)
                ipv6.autoconf = bool(v6_auto)
                if not ipv6.dhcp:
                    if v6_gate:
                        ipv6.gateway = v6_gate
                    if v6_addrlist:
                        ipv6.ips = map(build_ip, v6_addrlist)

        return [is_manual, copy_name, ipv4, ipv6, proto_xml]

    def ipv6_address_add(self, src):
        src = self.widget("ipv6-address-list")
        model = src.get_model()
        model.append(["Insert address/prefix"])

    def ipv6_address_remove(self, src):
        treepath = self.get_config_ipv6_address_selection()
        src = self.widget("ipv6-address-list")
        model = src.get_model()
        if treepath != None:
            del(model[treepath])

    def ipv6_address_editted(self, src, path, new_text):
        src = self.widget("ipv6-address-list")
        model = src.get_model()
        row = model[path]
        row[0] = new_text

    def ipv6_address_selected(self, src=None):
        treepath = self.get_config_ipv6_address_selection()
        has_selection = (treepath != None)

        self.widget("ipv6-address-remove").set_sensitive(has_selection)


    #######################
    # Notebook navigation #
    #######################

    def back(self, src):
        notebook = self.widget("pages")
        curpage = notebook.get_current_page()
        notebook.set_current_page(curpage - 1)

    def forward(self, ignore):
        notebook = self.widget("pages")
        curpage = notebook.get_current_page()

        if self.validate(notebook.get_current_page()) != True:
            return

        self.widget("forward").grab_focus()
        notebook.set_current_page(curpage + 1)

    def page_changed(self, ignore1, ignore2, pagenum):
        next_page = pagenum + 1
        # Update page number
        page_lbl = ("<span color='#59B0E2'>%s</span>" %
                    _("Step %(current_page)d of %(max_page)d") %
                    {'current_page': next_page, 'max_page': PAGE_DETAILS + 1})

        self.widget("header-pagenum").set_markup(page_lbl)

        if pagenum == 0:
            self.widget("back").set_sensitive(False)
        else:
            self.widget("back").set_sensitive(True)

        if pagenum == PAGE_DETAILS:
            self.populate_details_page()
            self.widget("forward").hide()
            self.widget("finish").show()
            self.widget("finish").grab_focus()

        else:
            self.widget("forward").show()
            self.widget("finish").hide()

    def validate(self, pagenum):
        try:
            if pagenum == PAGE_TYPE:
                # Nothing to validate
                return True
            elif pagenum == PAGE_DETAILS:
                return self.validate_details_page()

        except Exception, e:
            self.err.show_err(_("Uncaught error validating install "
                                "parameters: %s") % str(e))
            return

    def validate_details_page(self):
        itype = self.get_config_interface_type()
        name = self.get_config_interface_name()
        start = self.get_config_interface_startmode()
        ifaces = self.get_config_selected_interfaces()
        iclass = Interface.Interface.interface_class_for_type(itype)

        if not name:
            return self.err.val_err(_("An interface name is required."))

        if (itype != Interface.Interface.INTERFACE_TYPE_BRIDGE and
            len(ifaces) == 0):
            return self.err.val_err(_("An interface must be selected"))

        try:
            iobj = iclass(name, self.conn.vmm)
            iobj.start_mode = start
            check_conflict = False

            # Pull info from selected interfaces
            if hasattr(iobj, "interfaces"):
                iobj.interfaces = map(lambda x: x[INTERFACE_ROW_KEY], ifaces)
                check_conflict = True

            elif hasattr(iobj, "parent_interface"):
                iobj.parent_interface = ifaces[0][INTERFACE_ROW_KEY]

            elif itype == Interface.Interface.INTERFACE_TYPE_ETHERNET:
                iobj.macaddr = ifaces[0][INTERFACE_ROW_MAC]

            # Warn about defined interfaces
            defined_ifaces = ""
            if check_conflict:
                for row in ifaces:
                    if not row[INTERFACE_ROW_IS_DEFINED]:
                        continue

                    if defined_ifaces:
                        defined_ifaces += ", "
                    defined_ifaces += row[INTERFACE_ROW_NAME]

            if defined_ifaces:
                ret = self.err.yes_no(
                        _("The following interface(s) are already "
                          "configured:\n\n%s\n\nUsing these may overwrite "
                          "their existing configuration. Are you sure you "
                          "want to use the selected interface(s)?") %
                          defined_ifaces)
                if not ret:
                    return ret

            # Validate IP info (get_config validates for us)
            (is_manual, copy_name, ipv4,
             ipv6, proto_xml) = self.get_config_ip_info()

            if is_manual:
                protos = []
                if ipv4:
                    protos.append(ipv4)
                if ipv6:
                    protos.append(ipv6)
                iobj.protocols = protos
            else:
                iobj.protocol_xml = proto_xml

            if itype == Interface.Interface.INTERFACE_TYPE_BRIDGE:
                ret = self.validate_bridge(iobj, ifaces)
            elif itype == Interface.Interface.INTERFACE_TYPE_BOND:
                ret = self.validate_bond(iobj, ifaces)
            elif itype == Interface.Interface.INTERFACE_TYPE_VLAN:
                ret = self.validate_vlan(iobj, ifaces)
            elif itype == Interface.Interface.INTERFACE_TYPE_ETHERNET:
                ret = self.validate_ethernet(iobj, ifaces)

            if not ret:
                return ret

            iobj.get_xml_config()

            self.interface = iobj
        except Exception, e:
            return self.err.val_err(
                            _("Error setting interface parameters."), e)

        return True

    def validate_bridge(self, iobj, ifaces):
        delay = self.widget("bridge-delay").get_value()
        stp = self.widget("bridge-stp").get_active()

        iobj.stp = stp
        iobj.delay = int(delay)

        return True


    def validate_bond(self, iobj, ifaces):
        mode_list = self.widget("bond-mode")
        model = mode_list.get_model()
        mode = model[mode_list.get_active()][1]

        mon_list = self.widget("bond-monitor-mode")
        model = mon_list.get_model()
        mon = model[mon_list.get_active()][1]

        val_list = self.widget("arp-validate")
        val_model = val_list.get_model()
        arp_val = val_model[val_list.get_active()][0]

        car_list = self.widget("mii-carrier")
        car_model = car_list.get_model()
        mii_car = car_model[car_list.get_active()][0]

        # ARP params
        arp_int = self.widget("arp-interval").get_value()
        arp_tar = self.widget("arp-target").get_text()

        # MII params
        mii_freq = self.widget("mii-frequency").get_value()
        mii_up = self.widget("mii-updelay").get_value()
        mii_down = self.widget("mii-downdelay").get_value()

        iobj.bond_mode = mode
        iobj.monitor_mode = mon

        if not mon:
            # No monitor params, just return
            return True

        if mon == "arpmon":
            iobj.arp_validate_mode = arp_val
            iobj.arp_interval = int(arp_int)
            iobj.arp_target = arp_tar or None

        elif mon == "miimon":
            iobj.mii_carrier_mode = mii_car
            iobj.mii_frequency = int(mii_freq)
            iobj.mii_updelay = int(mii_up)
            iobj.mii_downdelay = int(mii_down)

        return True


    def validate_vlan(self, iobj, ifaces):
        idx = uihelpers.spin_get_helper(self.widget("vlan-tag"))

        iobj.tag = int(idx)
        return True


    def validate_ethernet(self, iobj, ifaces):
        return True


    def validate_ip_info(self):
        try:
            self.build_ip_info()
        except Exception, e:
            self.err.show_err(_("Error validating IP configuration: %s") %
                              str(e))
            return False

        return True

    ####################
    # Dialog callbacks #
    ####################

    def bridge_config_finish(self, ignore1=None, ignore2=None):
        self.update_bridge_desc()
        self.bridge_config.hide()
        return 1

    def bond_config_finish(self, ignore1=None, ignore2=None):
        self.update_bond_desc()
        self.bond_config.hide()
        return 1

    def ip_config_finish(self, ignore1=None, ignore2=None):
        if not self.validate_ip_info():
            return
        self.update_ip_desc()
        self.ip_config.hide()
        return 1

    #####################
    # Creation routines #
    #####################

    def finish(self, src):

        # Validate the final page
        page = self.widget("pages").get_current_page()
        if self.validate(page) != True:
            return False

        activate = self.widget("interface-activate").get_active()

        # Start the install
        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        progWin = vmmAsyncJob(self.do_install, [activate],
                              _("Creating virtual interface"),
                              _("The virtual interface is now being created."),
                              self.topwin)
        error, details = progWin.run()

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        if error:
            error = _("Error creating interface: '%s'") % error
            self.err.show_err(error,
                              details=details)
        else:
            # FIXME: Hmm, shouldn't we emit a signal here rather than do this?
            self.conn.tick(noStatsUpdate=True)
            self.close()

    def do_install(self, asyncjob, activate):
        meter = asyncjob.get_meter()
        error = None
        details = None

        self.interface.conn = util.dup_conn(self.conn).vmm

        self.interface.install(meter, create=activate)
        logging.debug("Install completed")

    def show_help(self, ignore):
        # No help available yet.
        pass

vmmGObjectUI.type_register(vmmCreateInterface)
vmmCreateInterface.signal_new(vmmCreateInterface, "action-show-help", [str])
