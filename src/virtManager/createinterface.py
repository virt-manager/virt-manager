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

import gobject
import gtk
import gtk.glade

import sys
import traceback
import logging

from virtinst import Interface

from virtManager import util
from virtManager import uihelpers
from virtManager.error import vmmErrorDialog
from virtManager.asyncjob import vmmAsyncJob
from virtManager.createmeter import vmmCreateMeter

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

class vmmCreateInterface(gobject.GObject):
    __gsignals__ = {
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                             gobject.TYPE_NONE, [str]),
    }

    def __init__(self, config, conn):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + \
                                    "/vmm-create-interface.glade",
                                    "vmm-create-interface",
                                    domain="virt-manager")
        self.config = config
        self.conn = conn
        self.interface = None

        self.topwin = self.window.get_widget("vmm-create-interface")
        self.err = vmmErrorDialog(self.topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))

        # Bridge configuration dialog
        self.bridge_config_win = gtk.glade.XML(self.config.get_glade_dir() + \
                                               "/vmm-create-interface.glade",
                                               "bridge-config",
                                               domain="virt-manager")
        self.bridge_config = self.bridge_config_win.get_widget(
                                                        "bridge-config")
        self.bridge_config_win.signal_autoconnect({
            "on_bridge_config_delete_event": self.bridge_config_finish,
            "on_bridge_ok_clicked" : self.bridge_config_finish,
        })

        # Bond configuration dialog
        self.bond_config_win = gtk.glade.XML(self.config.get_glade_dir() + \
                                             "/vmm-create-interface.glade",
                                             "bond-config",
                                             domain="virt-manager")
        self.bond_config = self.bond_config_win.get_widget("bond-config")
        self.bond_config_win.signal_autoconnect({
            "on_bond_config_delete_event": self.bond_config_finish,
            "on_bond_ok_clicked" : self.bond_config_finish,

            "on_bond_monitor_mode_changed": self.bond_monitor_mode_changed,
        })


        self.window.signal_autoconnect({
            "on_vmm_create_interface_delete_event" : self.close,

            "on_cancel_clicked": self.close,
            "on_back_clicked" : self.back,
            "on_forward_clicked" : self.forward,
            "on_finish_clicked" : self.finish,
            "on_help_clicked": self.show_help,
            "on_pages_switch_page": self.page_changed,

            "on_bridge_config_button_clicked": self.show_bridge_config,
            "on_bond_config_button_clicked": self.show_bond_config,
            "on_vlan_tag_changed": self.update_interface_name,
        })
        util.bind_escape_key_close(self)

        self.set_initial_state()

    def show(self):
        self.reset_state()
        self.topwin.show()
        self.topwin.present()

    def show_bond_config(self, src):
        self.bond_config.show_all()

    def show_bridge_config(self, src):
        self.bridge_config.show_all()

    def close(self, ignore1=None, ignore2=None):
        self.topwin.hide()

        return 1


    ###########################
    # Initialization routines #
    ###########################

    def set_initial_state(self):

        self.window.get_widget("pages").set_show_tabs(False)
        self.bond_config_win.get_widget("bond-pages").set_show_tabs(False)

        # FIXME: Unhide this when we make some documentation
        self.window.get_widget("help").hide()
        finish_img = gtk.image_new_from_stock(gtk.STOCK_QUIT,
                                              gtk.ICON_SIZE_BUTTON)
        self.window.get_widget("finish").set_image(finish_img)

        blue = gtk.gdk.color_parse("#0072A8")
        self.window.get_widget("header").modify_bg(gtk.STATE_NORMAL, blue)

        box = self.window.get_widget("header-icon-box")
        image = gtk.image_new_from_icon_name("network-idle",
                                             gtk.ICON_SIZE_DIALOG)
        image.show()
        box.pack_end(image, False)

        # Interface type
        type_list = self.window.get_widget("interface-type")
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
            self.window.get_widget("interface-startmode"))

        # Parent/slave Interface list
        slave_list = self.window.get_widget("interface-list")
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
        mode_list = self.bond_config_win.get_widget("bond-mode")
        mode_model = gtk.ListStore(str, str)
        mode_list.set_model(mode_model)
        txt = gtk.CellRendererText()
        mode_list.pack_start(txt, True)
        mode_list.add_attribute(txt, "text", 0)
        mode_model.append([_("System default"), None])
        for m in Interface.InterfaceBond.INTERFACE_BOND_MODES:
            mode_model.append([m, m])

        mon_list = self.bond_config_win.get_widget("bond-monitor-mode")
        mon_model = gtk.ListStore(str, str)
        mon_list.set_model(mon_model)
        txt = gtk.CellRendererText()
        mon_list.pack_start(txt, True)
        mon_list.add_attribute(txt, "text", 0)
        mon_model.append([_("System default"), None])
        for m in Interface.InterfaceBond.INTERFACE_BOND_MONITOR_MODES:
            mon_model.append([m, m])

        validate_list = self.bond_config_win.get_widget("arp-validate")
        validate_model = gtk.ListStore(str)
        validate_list.set_model(validate_model)
        txt = gtk.CellRendererText()
        validate_list.pack_start(txt, True)
        validate_list.add_attribute(txt, "text", 0)
        for m in Interface.InterfaceBond.INTERFACE_BOND_MONITOR_MODE_ARP_VALIDATE_MODES:
            validate_model.append([m])

        carrier_list = self.bond_config_win.get_widget("mii-carrier")
        carrier_model = gtk.ListStore(str)
        carrier_list.set_model(carrier_model)
        txt = gtk.CellRendererText()
        carrier_list.pack_start(txt, True)
        carrier_list.add_attribute(txt, "text", 0)
        for m in Interface.InterfaceBond.INTERFACE_BOND_MONITOR_MODE_MII_CARRIER_TYPES:
            carrier_model.append([m])


    def reset_state(self):

        self.window.get_widget("pages").set_current_page(PAGE_TYPE)
        self.page_changed(None, None, PAGE_TYPE)

        self.window.get_widget("interface-type").set_active(0)

        # General details
        self.window.get_widget("interface-name-entry").set_text("")
        self.window.get_widget("interface-name-label").set_text("")
        self.window.get_widget("interface-startmode").set_active(0)
        self.window.get_widget("interface-activate").set_active(False)

        # Bridge config
        self.bridge_config_win.get_widget("bridge-delay").set_value(0)
        self.bridge_config_win.get_widget("bridge-stp").set_active(True)

        # Bond config
        self.bond_config_win.get_widget("bond-mode").set_active(0)
        self.bond_config_win.get_widget("bond-monitor-mode").set_active(0)

        self.bond_config_win.get_widget("arp-interval").set_value(0)
        self.bond_config_win.get_widget("arp-target").set_text("")
        self.bond_config_win.get_widget("arp-validate").set_active(0)

        self.bond_config_win.get_widget("mii-frequency").set_value(0)
        self.bond_config_win.get_widget("mii-updelay").set_value(0)
        self.bond_config_win.get_widget("mii-downdelay").set_value(0)
        self.bond_config_win.get_widget("mii-carrier").set_active(0)

    def populate_details_page(self):
        itype = self.get_config_interface_type()

        # Set up default interface name
        self.window.get_widget("interface-name-entry").hide()
        self.window.get_widget("interface-name-label").hide()

        if itype in [ Interface.Interface.INTERFACE_TYPE_BRIDGE,
                      Interface.Interface.INTERFACE_TYPE_BOND ]:
            widget = "interface-name-entry"
        else:
            widget = "interface-name-label"

        self.window.get_widget(widget).show()
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
            self.window.get_widget("%s-label" % value).set_property("visible",
                                                                    do_show)
            self.window.get_widget("%s-box" % value).set_property("visible",
                                                                  do_show)

        if itype == Interface.Interface.INTERFACE_TYPE_BRIDGE:
            self.update_bridge_desc()

        elif itype == Interface.Interface.INTERFACE_TYPE_BOND:
            self.update_bond_desc()

        # Populate device list
        self.populate_interface_list(itype)

    def interface_item_toggled(self, src, index, slave_list):
        itype = self.get_config_interface_type()
        active = src.get_active()
        model = slave_list.get_model()

        if itype in [ Interface.Interface.INTERFACE_TYPE_ETHERNET,
                      Interface.Interface.INTERFACE_TYPE_VLAN ]:
            # Deselect any selected rows
            for row in model:
                if row == model[index]:
                    continue
                row[INTERFACE_ROW_SELECT] = False

        # Toggle the clicked row
        model[index][INTERFACE_ROW_SELECT] = not active

        self.update_interface_name()

    def populate_interface_list(self, itype):
        iface_list = self.window.get_widget("interface-list")
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

        self.window.get_widget("interface-list-text").set_text(msg)

        iface_list = []
        row_dict = {}

        for phys in self.conn.get_devices("net"):
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
                if row_dict.has_key(name):
                    del(row_dict[name])

                # We only want 'unconfigured' interfaces here
                continue

            if row_dict.has_key(name):
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
                    tag = self.window.get_widget("vlan-tag").get_value()
                    name = "%s.%s" % (iface, int(tag))

                elif itype == Interface.Interface.INTERFACE_TYPE_ETHERNET:
                    name = iface

        return name


    #########################
    # get_config_* routines #
    #########################

    def get_config_interface_type(self):
        type_list = self.window.get_widget("interface-type")
        return type_list.get_model()[type_list.get_active()][0]

    def set_interface_name(self, name):
        if self.window.get_widget("interface-name-entry").get_property("visible"):
            widget = "interface-name-entry"
        else:
            widget = "interface-name-label"

        self.window.get_widget(widget).set_text(name)

    def get_config_interface_name(self):
        if self.window.get_widget("interface-name-entry").get_property("visible"):
            return self.window.get_widget("interface-name-entry").get_text()
        else:
            return self.window.get_widget("interface-name-label").get_text()

    def get_config_interface_startmode(self):
        start_list = self.window.get_widget("interface-startmode")
        return start_list.get_model()[start_list.get_active()][0]

    def get_config_selected_interfaces(self):
        iface_list = self.window.get_widget("interface-list")
        model = iface_list.get_model()
        ret = []

        for row in model:
            active = row[INTERFACE_ROW_SELECT]
            iobj = row[INTERFACE_ROW_KEY]

            if active:
                ret.append(row)

        return ret

    def get_config_bridge_params(self):
        delay = self.bridge_config_win.get_widget("bridge-delay").get_value()
        stp = self.bridge_config_win.get_widget("bridge-stp").get_active()
        return [delay, stp]

    ################
    # UI Listeners #
    ################

    def update_interface_name(self, ignore1=None, ignore2=None):
        itype = self.get_config_interface_type()
        if itype not in [ Interface.Interface.INTERFACE_TYPE_VLAN,
                          Interface.Interface.INTERFACE_TYPE_ETHERNET ]:
            # The rest have editable name fields, so don't overwrite
            return

        name = self.get_default_name()
        self.set_interface_name(name)

    def bond_monitor_mode_changed(self, src):
        model = src.get_model()
        value = model[src.get_active()][1]
        bond_pages = self.bond_config_win.get_widget("bond-pages")

        if value == "arpmon":
            page = BOND_PAGE_ARP
        elif value == "miimon":
            page = BOND_PAGE_MII
        else:
            page = BOND_PAGE_DEFAULT

        bond_pages.set_current_page(page)

    def update_bridge_desc(self):
        delay, stp = self.get_config_bridge_params()
        txt  = "STP %s" % (stp and "on" or "off")
        txt += ", delay %d sec" % int(delay)

        self.window.get_widget("bridge-config-label").set_text(txt)

    def update_bond_desc(self):
        mode_list = self.bond_config_win.get_widget("bond-mode")
        model = mode_list.get_model()
        mode = model[mode_list.get_active()][0]

        mon_list = self.bond_config_win.get_widget("bond-monitor-mode")
        model = mon_list.get_model()
        mon = model[mon_list.get_active()][1]

        txt = mode
        if mon:
            txt += ", %s" % mon

        self.window.get_widget("bond-config-label").set_text(txt)

    #######################
    # Notebook navigation #
    #######################

    def back(self, src):
        notebook = self.window.get_widget("pages")
        curpage = notebook.get_current_page()
        notebook.set_current_page(curpage - 1)

    def forward(self, ignore):
        notebook = self.window.get_widget("pages")
        curpage = notebook.get_current_page()

        if self.validate(notebook.get_current_page()) != True:
            return

        self.window.get_widget("forward").grab_focus()
        notebook.set_current_page(curpage + 1)

    def page_changed(self, ignore1, ignore2, pagenum):
        next_page = pagenum + 1
        # Update page number
        page_lbl = ("<span color='#59B0E2'>%s</span>" %
                    _("Step %(current_page)d of %(max_page)d") %
                    {'current_page': next_page, 'max_page': PAGE_DETAILS+1})

        self.window.get_widget("header-pagenum").set_markup(page_lbl)

        if pagenum == 0:
            self.window.get_widget("back").set_sensitive(False)
        else:
            self.window.get_widget("back").set_sensitive(True)

        if pagenum == PAGE_DETAILS:
            self.populate_details_page()
            self.window.get_widget("forward").hide()
            self.window.get_widget("finish").show()
            self.window.get_widget("finish").grab_focus()

        else:
            self.window.get_widget("forward").show()
            self.window.get_widget("finish").hide()

    def validate(self, pagenum):
        try:
            if pagenum == PAGE_TYPE:
                # Nothing to validate
                return True
            elif pagenum == PAGE_DETAILS:
                return self.validate_details_page()

        except Exception, e:
            self.err.show_err(_("Uncaught error validating install "
                                "parameters: %s") % str(e),
                                "".join(traceback.format_exc()))
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
            return self.err.val_err(_("Error setting interface parameters."),
                                    str(e))

        return True

    def validate_bridge(self, iobj, ifaces):
        delay = self.bridge_config_win.get_widget("bridge-delay").get_value()
        stp = self.bridge_config_win.get_widget("bridge-stp").get_active()

        iobj.stp = stp
        iobj.delay = int(delay)

        return True


    def validate_bond(self, iobj, ifaces):
        mode_list = self.bond_config_win.get_widget("bond-mode")
        model = mode_list.get_model()
        mode = model[mode_list.get_active()][1]

        mon_list = self.bond_config_win.get_widget("bond-monitor-mode")
        model = mon_list.get_model()
        mon = model[mon_list.get_active()][1]

        val_list = self.bond_config_win.get_widget("arp-validate")
        val_model = val_list.get_model()
        arp_val = val_model[val_list.get_active()][0]

        car_list = self.bond_config_win.get_widget("mii-carrier")
        car_model = car_list.get_model()
        mii_car = car_model[car_list.get_active()][0]

        # ARP params
        arp_int = self.bond_config_win.get_widget("arp-interval").get_value()
        arp_tar = self.bond_config_win.get_widget("arp-target").get_text()

        # MII params
        mii_freq = self.bond_config_win.get_widget("mii-frequency").get_value()
        mii_up = self.bond_config_win.get_widget("mii-updelay").get_value()
        mii_down = self.bond_config_win.get_widget("mii-downdelay").get_value()

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
        idx = self.window.get_widget("vlan-tag").get_value()

        iobj.tag = int(idx)
        return True


    def validate_ethernet(self, iobj, ifaces):
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

    #####################
    # Creation routines #
    #####################

    def finish(self, src):

        # Validate the final page
        page = self.window.get_widget("pages").get_current_page()
        if self.validate(page) != True:
            return False

        activate = self.window.get_widget("interface-activate").get_active()

        # Start the install
        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        progWin = vmmAsyncJob(self.config, self.do_install, [activate],
                              title=_("Creating virtual interface"),
                              text=_("The virtual interface is now being "
                                     "created."))
        progWin.run()
        error, details = progWin.get_error()

        if error != None:
            self.err.show_err(error, details)

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        if error:
            return

        # FIXME: Hmm, shouldn't we emit a signal here rather than do this?
        self.conn.tick(noStatsUpdate=True)
        self.close()


    def do_install(self, activate, asyncjob):
        meter = vmmCreateMeter(asyncjob)
        error = None
        details = None
        try:
            self.interface.conn = util.dup_conn(self.config, self.conn)

            self.interface.install(meter, create=activate)
            logging.debug("Install completed")
        except:
            (_type, value, stacktrace) = sys.exc_info ()

            # Detailed error message, in English so it can be Googled.
            details = ("Error creating interface: '%s'" %
                       (str(_type) + " " + str(value) + "\n" +
                       traceback.format_exc (stacktrace)))
            error = (_("Error creating interface: '%s'") % str(value))

        if error:
            asyncjob.set_error(error, details)


    def show_help(self, ignore):
        # No help available yet.
        pass

gobject.type_register(vmmCreateInterface)
