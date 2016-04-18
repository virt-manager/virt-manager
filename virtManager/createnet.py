#
# Copyright (C) 2006-2007, 2013 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
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

from gi.repository import Gtk
from gi.repository import Gdk

import ipaddr

from virtinst import Network

from . import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI

(PAGE_NAME,
PAGE_IPV4,
PAGE_IPV6,
PAGE_MISC) = range(4)

PAGE_MAX = PAGE_MISC

_green = Gdk.Color.parse("#c0ffc0")[1]
_red = Gdk.Color.parse("#ffc0c0")[1]
_black = Gdk.Color.parse("#000000")[1]
_white = Gdk.Color.parse("#f0f0f0")[1]


def _make_ipaddr(addrstr):
    if addrstr is None:
        return None
    try:
        return ipaddr.IPNetwork(addrstr)
    except:
        return None


class vmmCreateNetwork(vmmGObjectUI):
    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "createnet.ui", "vmm-create-net")
        self.conn = conn

        self.builder.connect_signals({
            "on_create_pages_switch_page" : self.page_changed,
            "on_create_cancel_clicked" : self.close,
            "on_vmm_create_delete_event" : self.close,
            "on_create_forward_clicked" : self.forward,
            "on_create_back_clicked" : self.back,
            "on_create_finish_clicked" : self.finish,

            "on_net_name_activate": self.forward,
            "on_net_forward_toggled" : self.change_forward_type,

            "on_net-ipv4-enable_toggled" :  self.change_ipv4_enable,
            "on_net-ipv4-network_changed":  self.change_ipv4_network,
            "on_net-dhcpv4-enable_toggled": self.change_dhcpv4_enable,
            "on_net-dhcpv4-start_changed":  self.change_dhcpv4_start,
            "on_net-dhcpv4-end_changed":    self.change_dhcpv4_end,

            "on_net-ipv6-enable_toggled" :  self.change_ipv6_enable,
            "on_net-ipv6-network_changed":  self.change_ipv6_network,
            "on_net-dhcpv6-enable_toggled": self.change_dhcpv6_enable,
            "on_net-dhcpv6-start_changed":  self.change_dhcpv6_start,
            "on_net-dhcpv6-end_changed":    self.change_dhcpv6_end,

            "on_net-routev4-enable_toggled":  self.change_routev4_enable,
            "on_net-routev4-network_changed": self.change_routev4_network,
            "on_net-routev4-gateway_changed": self.change_routev4_gateway,

            "on_net-routev6-enable_toggled":  self.change_routev6_enable,
            "on_net-routev6-network_changed": self.change_routev6_network,
            "on_net-routev6-gateway_changed": self.change_routev6_gateway,
        })
        self.bind_escape_key_close()

        self.set_initial_state()


    ####################
    # Standard methods #
    ####################

    def show(self, parent):
        logging.debug("Showing new network wizard")
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing new network wizard")
        self.topwin.hide()
        return 1

    def _cleanup(self):
        self.conn = None

    def set_initial_state(self):
        notebook = self.widget("create-pages")
        notebook.set_show_tabs(False)

        blue = Gdk.Color.parse("#0072A8")[1]
        self.widget("header").modify_bg(Gtk.StateType.NORMAL, blue)

        # [ label, dev name ]
        fw_list = self.widget("net-forward")
        fw_model = Gtk.ListStore(str, str)
        fw_list.set_model(fw_model)
        uiutil.init_combo_text_column(fw_list, 0)

        # [ label, mode ]
        mode_list = self.widget("net-forward-mode")
        mode_model = Gtk.ListStore(str, str)
        mode_list.set_model(mode_model)
        uiutil.init_combo_text_column(mode_list, 0)

        mode_model.append([_("NAT"), "nat"])
        mode_model.append([_("Routed"), "route"])

    def reset_state(self):
        notebook = self.widget("create-pages")
        notebook.set_current_page(0)

        self.page_changed(None, None, 0)

        self.widget("net-name").set_text("")
        self.widget("net-domain-name").set_text("")

        self.widget("net-ipv4-enable").set_active(True)
        self.widget("net-ipv4-network").set_text("192.168.100.0/24")
        self.widget("net-dhcpv4-enable").set_active(True)
        self.widget("net-dhcpv4-start").set_text("192.168.100.128")
        self.widget("net-dhcpv4-end").set_text("192.168.100.254")
        self.widget("net-routev4-enable").set_active(False)
        self.widget("net-routev4-enable").toggled()
        self.widget("net-routev4-network").set_text("")
        self.widget("net-routev4-gateway").set_text("")

        self.widget("net-ipv6-enable").set_active(False)
        self.widget("net-ipv6-enable").toggled()
        self.widget("net-ipv6-network").set_text("")
        self.widget("net-dhcpv6-enable").set_active(False)
        self.widget("net-dhcpv6-enable").toggled()
        self.widget("net-dhcpv6-start").set_text("")
        self.widget("net-dhcpv6-end").set_text("")
        self.widget("net-routev6-enable").set_active(False)
        self.widget("net-routev6-enable").toggled()
        self.widget("net-routev6-network").set_text("")
        self.widget("net-routev6-gateway").set_text("")

        self.widget("net-enable-ipv6-networking").set_active(False)

        fw_model = self.widget("net-forward").get_model()
        fw_model.clear()
        fw_model.append([_("Any physical device"), None])

        devnames = []
        for nodedev in self.conn.filter_nodedevs("net"):
            devnames.append(nodedev.xmlobj.interface)
        for iface in self.conn.list_interfaces():
            if iface.get_name() not in devnames:
                devnames.append(iface.get_name())

        for name in devnames:
            fw_model.append([_("Physical device %s") % name, name])

        self.widget("net-forward").set_active(0)
        self.widget("net-forward-mode").set_active(0)
        self.widget("net-forward-none").set_active(True)


    ##################
    # UI get helpers #
    ##################

    def get_config_ipv4_enable(self):
        return self.widget("net-ipv4-enable").get_active()
    def get_config_ipv6_enable(self):
        return self.widget("net-ipv6-enable").get_active()
    def get_config_dhcpv4_enable(self):
        return self.widget("net-dhcpv4-enable").get_active()
    def get_config_dhcpv6_enable(self):
        return self.widget("net-dhcpv6-enable").get_active()
    def get_config_routev4_enable(self):
        return self.widget("net-routev4-enable").get_active()
    def get_config_routev6_enable(self):
        return self.widget("net-routev6-enable").get_active()

    def _get_network_helper(self, widgetname):
        widget = self.widget(widgetname)
        if not widget.is_visible() or not widget.is_sensitive():
            return None
        return _make_ipaddr(widget.get_text())

    def get_config_ip4(self):
        return self._get_network_helper("net-ipv4-network")
    def get_config_dhcpv4_start(self):
        return self._get_network_helper("net-dhcpv4-start")
    def get_config_dhcpv4_end(self):
        return self._get_network_helper("net-dhcpv4-end")
    def get_config_ip6(self):
        return self._get_network_helper("net-ipv6-network")
    def get_config_dhcpv6_start(self):
        return self._get_network_helper("net-dhcpv6-start")
    def get_config_dhcpv6_end(self):
        return self._get_network_helper("net-dhcpv6-end")

    def get_config_forwarding(self):
        if self.widget("net-forward-none").get_active():
            return [None, None]

        name = uiutil.get_list_selection(self.widget("net-forward"), column=1)
        mode = uiutil.get_list_selection(
            self.widget("net-forward-mode"), column=1)
        return [name, mode]

    def get_config_routev4_network(self):
        if not self.get_config_routev4_enable():
            return None
        return self.widget("net-routev4-network").get_text()
    def get_config_routev4_gateway(self):
        if not self.get_config_routev4_enable():
            return None
        return self.widget("net-routev4-gateway").get_text()
    def get_config_routev6_network(self):
        if not self.get_config_routev6_enable():
            return None
        return self.widget("net-routev6-network").get_text()
    def get_config_routev6_gateway(self):
        if not self.get_config_routev6_enable():
            return None
        return self.widget("net-routev6-gateway").get_text()


    ###################
    # Page validation #
    ###################

    def validate_name(self):
        try:
            net = self._build_xmlstub()
            net.name = self.widget("net-name").get_text()
        except Exception, e:
            return self.err.val_err(_("Invalid network name"), str(e))

        return True

    def validate_ipv4(self):
        if not self.get_config_ipv4_enable():
            return True
        ip = self.get_config_ip4()
        if ip is None:
            return self.err.val_err(_("Invalid Network Address"),
                    _("The network address could not be understood"))

        if ip.version != 4:
            return self.err.val_err(_("Invalid Network Address"),
                    _("The network must be an IPv4 address"))

        if ip.numhosts < 8:
            return self.err.val_err(_("Invalid Network Address"),
                    _("The network must address at least 8 addresses."))

        if ip.prefixlen < 15:
            return self.err.val_err(_("Invalid Network Address"),
                    _("The network prefix must be >= 15"))

        if not ip.is_private:
            res = self.err.yes_no(_("Check Network Address"),
                    _("The network should normally use a private IPv4 "
                      "address. Use this non-private address anyway?"))
            if not res:
                return False

        enabled = self.get_config_dhcpv4_enable()
        if enabled:
            start = self.get_config_dhcpv4_start()
            end = self.get_config_dhcpv4_end()
            if start is None:
                return self.err.val_err(_("Invalid DHCP Address"),
                    _("The DHCP start address could not be understood"))
            if end is None:
                return self.err.val_err(_("Invalid DHCP Address"),
                    _("The DHCP end address could not be understood"))
            if not ip.overlaps(start):
                return self.err.val_err(_("Invalid DHCP Address"),
                    (_("The DHCP start address is not with the network %s") %
                     (str(ip))))
            if not ip.overlaps(end):
                return self.err.val_err(_("Invalid DHCP Address"),
                    (_("The DHCP end address is not with the network %s") %
                     (str(ip))))

        enabled = self.get_config_routev4_enable()
        if enabled:
            ntwk = self.get_config_routev4_network()
            ntwkbad = False
            gway = self.get_config_routev4_gateway()
            gwaybad = False
            if ntwk is None or gway is None:
                return True
            if ntwk == "" and gway == "":
                return True
            naddr = _make_ipaddr(ntwk)
            if naddr is None:
                ntwkbad = True
            else:
                if naddr.version != 4:
                    ntwkbad = True
                if naddr.prefixlen > 28:
                    ntwkbad = True
            gaddr = _make_ipaddr(gway)
            if gaddr is None:
                gwaybad = True
            else:
                if gaddr.version != 4:
                    gwaybad = True
                if gaddr.prefixlen != 32:
                    gwaybad = True
                if not ip.overlaps(gaddr):
                    gwaybad = True
            if ntwkbad:
                return self.err.val_err(_("Invalid static route"),
                            _("The network address is incorrect."))
            if gwaybad:
                return self.err.val_err(_("Invalid static route"),
                            _("The gateway address is incorrect."))

        return True

    def validate_ipv6(self):
        if not self.get_config_ipv6_enable():
            return True
        ip = self.get_config_ip6()
        if ip is None:
            return self.err.val_err(_("Invalid Network Address"),
                    _("The network address could not be understood"))

        if ip.version != 6:
            return self.err.val_err(_("Invalid Network Address"),
                    _("The network must be an IPv6 address"))

        if ip.prefixlen != 64:
            return self.err.val_err(_("Invalid Network Address"),
                    _("For libvirt, the IPv6 network prefix must be /64"))

        if not ip.is_private:
            res = self.err.yes_no(_("Check Network Address"),
                    _("The network should normally use a private IPv6 "
                      "address. Use this non-private address anyway?"))
            if not res:
                return False

        enabled = self.get_config_dhcpv6_enable()
        if enabled:
            start = self.get_config_dhcpv6_start()
            end = self.get_config_dhcpv6_end()
            if start is None:
                return self.err.val_err(_("Invalid DHCPv6 Address"),
                    _("The DHCPv6 start address could not be understood"))
            if end is None:
                return self.err.val_err(_("Invalid DHCPv6 Address"),
                    _("The DHCPv6 end address could not be understood"))
            if not ip.overlaps(start):
                return self.err.val_err(_("Invalid DHCPv6 Address"),
                    (_("The DHCPv6 start address is not with the network %s") %
                    (str(ip))))
            if not ip.overlaps(end):
                return self.err.val_err(_("Invalid DHCPv6 Address"),
                    (_("The DHCPv6 end address is not with the network %s") %
                    (str(ip))))

        enabled = self.get_config_routev6_enable()
        if enabled:
            ntwk = self.get_config_routev6_network()
            ntwkbad = False
            gway = self.get_config_routev6_gateway()
            gwaybad = False
            if ntwk is None or gway is None:
                return True
            if ntwk == "" and gway == "":
                return True
            naddr = _make_ipaddr(ntwk)
            if naddr is None:
                ntwkbad = True
            else:
                if naddr.version != 6:
                    ntwkbad = True
                if naddr.prefixlen > 64:
                    ntwkbad = True
            gaddr = _make_ipaddr(gway)
            if gaddr is None:
                gwaybad = True
            else:
                if gaddr.version != 6:
                    gwaybad = True
                if gaddr.prefixlen != 128:
                    gwaybad = True
                if not ip.overlaps(gaddr):
                    gwaybad = True
            if ntwkbad:
                return self.err.val_err(_("Invalid static route"),
                            _("The network address is incorrect."))
            if gwaybad:
                return self.err.val_err(_("Invalid static route"),
                            _("The gateway address is incorrect."))

        return True

    def validate_miscellaneous(self):
        return True

    def validate(self, page_num):
        if page_num == PAGE_NAME:
            return self.validate_name()
        elif page_num == PAGE_IPV4:
            return self.validate_ipv4()
        elif page_num == PAGE_IPV6:
            return self.validate_ipv6()
        elif page_num == PAGE_MISC:
            return self.validate_miscellaneous()
        return True


    #############
    # Listeners #
    #############

    def forward(self, ignore=None):
        notebook = self.widget("create-pages")
        if self.validate(notebook.get_current_page()) is not True:
            return

        self.widget("create-forward").grab_focus()
        notebook.next_page()

    def back(self, ignore=None):
        notebook = self.widget("create-pages")
        notebook.prev_page()

    def page_changed(self, ignore1, ignore2, page_number):
        page_lbl = ("<span color='#59B0E2'>%s</span>" %
                    _("Step %(current_page)d of %(max_page)d") %
                    {'current_page': page_number + 1,
                     'max_page': PAGE_MISC + 1})
        self.widget("header-pagenum").set_markup(page_lbl)

        if page_number == PAGE_NAME:
            name_widget = self.widget("net-name")
            name_widget.set_sensitive(True)
            name_widget.grab_focus()
        elif page_number == PAGE_MISC:
            name = self.widget("net-name").get_text()
            if self.widget("net-domain-name").get_text() == "":
                self.widget("net-domain-name").set_text(name)

        self.widget("create-back").set_sensitive(page_number != 0)

        is_last_page = (
            page_number == (self.widget("create-pages").get_n_pages() - 1))
        self.widget("create-forward").set_visible(not is_last_page)
        self.widget("create-finish").set_visible(is_last_page)
        if is_last_page:
            self.widget("create-finish").grab_focus()

    def change_forward_type(self, ignore):
        skip_fwd = self.widget("net-forward-none").get_active()

        self.widget("net-forward-mode").set_sensitive(not skip_fwd)
        self.widget("net-forward").set_sensitive(not skip_fwd)

    def change_ipv4_enable(self, ignore):
        enabled = self.get_config_ipv4_enable()
        self.widget("net-ipv4-box").set_visible(enabled)
    def change_ipv6_enable(self, ignore):
        enabled = self.get_config_ipv6_enable()
        self.widget("net-ipv6-box").set_visible(enabled)

    def change_routev4_enable(self, ignore):
        enabled = self.get_config_routev4_enable()
        ntwk = self.widget("net-routev4-network")
        gway = self.widget("net-routev4-gateway")
        uiutil.set_grid_row_visible(ntwk, enabled)
        uiutil.set_grid_row_visible(gway, enabled)
    def change_routev6_enable(self, ignore):
        enabled = self.get_config_routev6_enable()
        ntwk = self.widget("net-routev6-network")
        gway = self.widget("net-routev6-gateway")
        uiutil.set_grid_row_visible(ntwk, enabled)
        uiutil.set_grid_row_visible(gway, enabled)

    def change_dhcpv4_enable(self, ignore):
        enabled = self.get_config_dhcpv4_enable()
        start = self.widget("net-dhcpv4-start")
        end = self.widget("net-dhcpv4-end")
        uiutil.set_grid_row_visible(start, enabled)
        uiutil.set_grid_row_visible(end, enabled)
    def change_dhcpv6_enable(self, ignore):
        enabled = self.get_config_dhcpv6_enable()
        start = self.widget("net-dhcpv6-start")
        end = self.widget("net-dhcpv6-end")
        uiutil.set_grid_row_visible(start, enabled)
        uiutil.set_grid_row_visible(end, enabled)

    def change_dhcpv4_start(self, src):
        start = self.get_config_dhcpv4_start()
        self.change_dhcpv4(src, start)
    def change_dhcpv4_end(self, src):
        end = self.get_config_dhcpv4_end()
        self.change_dhcpv4(src, end)
    def change_dhcpv4(self, src, addr):
        ip = self.get_config_ip4()
        if ip is None or addr is None:
            src.modify_bg(Gtk.StateType.NORMAL, _white)
            return

        if addr.version != 4 or not ip.overlaps(addr):
            src.modify_bg(Gtk.StateType.NORMAL, _red)
        else:
            src.modify_bg(Gtk.StateType.NORMAL, _green)

    def change_dhcpv6_start(self, src):
        start = self.get_config_dhcpv6_start()
        self.change_dhcpv6(src, start)
    def change_dhcpv6_end(self, src):
        end = self.get_config_dhcpv6_end()
        self.change_dhcpv6(src, end)
    def change_dhcpv6(self, src, addr):
        ip = self.get_config_ip6()
        if ip is None or addr is None:
            src.modify_bg(Gtk.StateType.NORMAL, _white)
            return

        if addr.version != 6 or not ip.overlaps(addr):
            src.modify_bg(Gtk.StateType.NORMAL, _red)
        else:
            src.modify_bg(Gtk.StateType.NORMAL, _green)


    def change_ipv4_network(self, src):
        ip = self.get_config_ip4()

        # No IP specified or invalid IP
        if ip is None or ip.version != 4:
            src.modify_bg(Gtk.StateType.NORMAL, _red)
            return

        valid_ip = (ip.numhosts >= 8 and ip.is_private)
        gateway = (ip.prefixlen != 32 and str(ip.network + 1) or "")
        info = (ip.is_private and _("Private") or _("Other/Public"))
        start = int(ip.numhosts / 2)
        end = int(ip.numhosts - 2)

        src.modify_bg(Gtk.StateType.NORMAL, valid_ip and _green or _red)
        self.widget("net-info-gateway").set_text(gateway)
        self.widget("net-info-type").set_text(info)
        self.widget("net-dhcpv4-start").set_text(str(ip.network + start))
        self.widget("net-dhcpv4-end").set_text(str(ip.network + end))

    def change_routev4_network(self, src):
        ntwk = self.get_config_routev4_network()
        ipAddr = self.get_config_ip4()
        if ipAddr is None or ntwk is None:
            src.modify_bg(Gtk.StateType.NORMAL, _white)
            return

        addr = _make_ipaddr(ntwk)
        color = _green
        if (addr is None or
            addr.version != 4 or
            addr.prefixlen > 28):
            color = _red
        src.modify_bg(Gtk.StateType.NORMAL, color)

    def change_routev4_gateway(self, src):
        gway = self.get_config_routev4_gateway()
        ipAddr = self.get_config_ip4()
        if ipAddr is None or gway is None:
            src.modify_bg(Gtk.StateType.NORMAL, _white)
            return

        addr = _make_ipaddr(gway)
        color = _green
        if (addr is None or
            addr.version != 4 or
            not ipAddr.overlaps(addr) or
            addr.prefixlen != 32):
            color = _red
        src.modify_bg(Gtk.StateType.NORMAL, color)


    def change_ipv6_network(self, src):
        ip = self.get_config_ip6()

        if ip is None or ip.version != 6:
            src.modify_bg(Gtk.StateType.NORMAL, _red)
            return

        valid_ip = (ip.numhosts == 64 and ip.is_private)
        gateway = (ip.prefixlen != 64 and str(ip.network + 1) or "")
        start = 256
        end = 512 - 1
        if ip.is_private:
            info = _("Private")
        elif ip.is_reserved:
            info = _("Reserved")
        elif ip.is_unspecified:
            info = _("Unspecified")
        else:
            info = _("Other/Public")

        src.modify_bg(Gtk.StateType.NORMAL, valid_ip and _green or _red)
        self.widget("net-info-gateway-ip6").set_text(gateway)
        self.widget("net-info-type-ip6").set_text(info)
        self.widget("net-dhcpv6-start").set_text(str(ip.network + start))
        self.widget("net-dhcpv6-end").set_text(str(ip.network + end))

    def change_routev6_network(self, src):
        ntwk = self.get_config_routev6_network()
        ip = self.get_config_ip6()
        if ip is None or ntwk is None:
            src.modify_bg(Gtk.StateType.NORMAL, _white)
            return

        addr = _make_ipaddr(ntwk)
        color = _green
        if (addr is None or
            addr.version != 6 or
            addr.prefixlen > 64):
            color = _red
        src.modify_bg(Gtk.StateType.NORMAL, color)

    def change_routev6_gateway(self, src):
        gway = self.get_config_routev6_gateway()
        ip = self.get_config_ip6()
        if ip is None or gway is None:
            src.modify_bg(Gtk.StateType.NORMAL, _white)
            return

        addr = _make_ipaddr(gway)
        color = _green
        if (addr is None or
            addr.version != 6 or
            ip.overlaps(addr) or
            addr.prefixlen != 128):
            color = _red
        src.modify_bg(Gtk.StateType.NORMAL, color)



    #########################
    # XML build and install #
    #########################

    def _build_xmlstub(self):
        return Network(self.conn.get_backend())

    def _build_xmlobj(self):
        net = self._build_xmlstub()

        net.name = self.widget("net-name").get_text()
        net.domain_name = self.widget("net-domain-name").get_text() or None

        if self.widget("net-enable-ipv6-networking").get_active():
            net.ipv6 = True

        dev, mode = self.get_config_forwarding()
        if mode:
            net.forward.mode = mode
            net.forward.dev = dev or None

        if self.get_config_ipv4_enable():
            ip = self.get_config_ip4()
            ipobj = net.add_ip()
            ipobj.address = str(ip.network + 1)
            ipobj.netmask = str(ip.netmask)

            if self.get_config_dhcpv4_enable():
                dhcpobj = ipobj.add_range()
                dhcpobj.start = str(self.get_config_dhcpv4_start().network)
                dhcpobj.end = str(self.get_config_dhcpv4_end().network)

        if self.get_config_ipv6_enable():
            ip = self.get_config_ip6()
            ipobj = net.add_ip()
            ipobj.family = "ipv6"
            ipobj.address = str(ip.network + 1)
            ipobj.prefix = str(ip.prefixlen)

            if self.get_config_dhcpv6_enable():
                dhcpobj = ipobj.add_range()
                dhcpobj.start = str(self.get_config_dhcpv6_start().network)
                dhcpobj.end = str(self.get_config_dhcpv6_end().network)

        netaddr = _make_ipaddr(self.get_config_routev4_network())
        gwaddr = _make_ipaddr(self.get_config_routev4_gateway())
        if netaddr and gwaddr:
            route = net.add_route()
            route.family = "ipv4"
            route.address = netaddr.network
            route.prefix = netaddr.prefixlen
            route.gateway = gwaddr.network

        netaddr = _make_ipaddr(self.get_config_routev6_network())
        gwaddr = _make_ipaddr(self.get_config_routev6_gateway())
        if netaddr and gwaddr:
            route = net.add_route()
            route.family = "ipv6"
            route.address = netaddr.network
            route.prefix = netaddr.prefixlen
            route.gateway = gwaddr.network

        return net

    def _finish_cb(self, error, details):
        self.topwin.set_sensitive(True)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.TOP_LEFT_ARROW))

        if error:
            error = _("Error creating virtual network: %s") % str(error)
            self.err.show_err(error, details=details)
        else:
            self.conn.schedule_priority_tick(pollnet=True)
            self.close()

    def _async_net_create(self, asyncjob, net):
        ignore = asyncjob
        net.install()

    def finish(self, ignore):
        if not self.validate(PAGE_MAX):
            return

        try:
            net = self._build_xmlobj()
        except Exception, e:
            self.err.show_err(_("Error generating network xml: %s") % str(e))
            return

        self.topwin.set_sensitive(False)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.WATCH))

        progWin = vmmAsyncJob(self._async_net_create, [net],
                              self._finish_cb, [],
                              _("Creating virtual network..."),
                              _("Creating the virtual network may take a "
                                "while..."),
                              self.topwin)
        progWin.run()
