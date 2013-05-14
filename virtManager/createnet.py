#
# Copyright (C) 2006-2007 Red Hat, Inc.
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
import re

import ipaddr

# pylint: disable=E0611
from gi.repository import Gtk
from gi.repository import Gdk
# pylint: enable=E0611

from virtManager.network import vmmNetwork
from virtManager.baseclass import vmmGObjectUI

PAGE_INTRO = 0
PAGE_NAME = 1
PAGE_IPV4 = 2
PAGE_IPV6 = 3
PAGE_MISC = 4
PAGE_SUMMARY = 5


class vmmCreateNetwork(vmmGObjectUI):
    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "vmm-create-net.ui", "vmm-create-net")
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

        finish_img = Gtk.Image.new_from_stock(Gtk.STOCK_QUIT,
                                              Gtk.IconSize.BUTTON)
        self.widget("create-finish").set_image(finish_img)

        self.set_initial_state()

    def show(self, parent):
        logging.debug("Showing new network wizard")
        self.reset_state()
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def is_visible(self):
        return self.topwin.get_visible()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing new network wizard")
        self.topwin.hide()
        return 1

    def _cleanup(self):
        self.conn = None

    def set_initial_state(self):
        notebook = self.widget("create-pages")
        notebook.set_show_tabs(False)

        black  = Gdk.Color.parse("#000")[1]
        for num in range(PAGE_SUMMARY + 1):
            name = "page" + str(num) + "-title"
            self.widget(name).modify_bg(Gtk.StateType.NORMAL, black)

        fw_list = self.widget("net-forward")
        # [ label, dev name ]
        fw_model = Gtk.ListStore(str, str)
        fw_list.set_model(fw_model)
        text = Gtk.CellRendererText()
        fw_list.pack_start(text, True)
        fw_list.add_attribute(text, 'text', 0)

        fw_model.append([_("Any physical device"), None])
        for path in self.conn.list_net_device_paths():
            net = self.conn.get_net_device(path)
            fw_model.append([_("Physical device %s") % (net.get_name()),
                             net.get_name()])

        mode_list = self.widget("net-forward-mode")
        # [ label, mode ]
        mode_model = Gtk.ListStore(str, str)
        mode_list.set_model(mode_model)
        text = Gtk.CellRendererText()
        mode_list.pack_start(text, True)
        mode_list.add_attribute(text, 'text', 0)

        mode_model.append([_("NAT"), "nat"])
        mode_model.append([_("Routed"), "route"])

    def reset_state(self):
        notebook = self.widget("create-pages")
        notebook.set_current_page(0)

        self.page_changed(None, None, 0)

        self.widget("net-name").set_text("")
        self.widget("net-name").set_sensitive(True)
        self.widget("net-domain-name").set_text("")
        self.widget("net-domain-name").set_sensitive(True)
        self.widget("net-ipv4-enable").set_active(True)
        self.widget("net-ipv4-network").set_text("192.168.100.0/24")
        self.widget("net-ipv4-network").set_sensitive(True)
        self.widget("net-dhcpv4-enable").set_active(True)
        self.widget("net-dhcpv4-start").set_text("192.168.100.128")
        self.widget("net-dhcpv4-end").set_text("192.168.100.254")
        self.widget("net-dhcpv4-start").set_sensitive(True)
        self.widget("net-dhcpv4-end").set_sensitive(True)
        self.widget("net-ipv6-enable").set_active(False)
        self.widget("net-ipv6-network").set_text("")
        self.widget("net-ipv6-network").set_sensitive(True)
        self.widget("net-dhcpv6-enable").set_active(False)
        self.widget("net-dhcpv6-start").set_text("")
        self.widget("net-dhcpv6-end").set_text("")
        self.widget("net-forward-none").set_active(True)

        self.widget("net-forward").set_active(0)
        self.widget("net-forward-mode").set_active(0)
        self.widget("net-enable-ipv6-networking").set_active(False)


    def forward(self, ignore=None):
        notebook = self.widget("create-pages")
        if self.validate(notebook.get_current_page()) is not True:
            return

        self.widget("create-forward").grab_focus()
        notebook.next_page()

    def back(self, ignore=None):
        notebook = self.widget("create-pages")
        notebook.prev_page()

    def change_ipv4_enable(self, src):
        ignore = src

        white = Gdk.Color.parse("#f0f0f0")[1]
        net = self.widget("net-ipv4-network")
        start = self.widget("net-dhcpv4-start")
        end = self.widget("net-dhcpv4-end")
        network = self.widget("net-routev4-network")
        gateway = self.widget("net-routev4-gateway")
        if self.get_config_ipv4_enable():
            net.set_sensitive(True)
            net.set_text("")
            net.modify_bg(Gtk.StateType.NORMAL, white)
            if self.get_config_dhcpv4_enable():
                start.set_sensitive(True)
                end.set_sensitive(True)
            if self.get_config_routev4_enable():
                network.set_sensitive(True)
                gateway.set_sensitive(True)
        else:
            net.set_text("")
            start.set_text("")
            end.set_text("")
            network.set_text("")
            gateway.set_text("")
            net.set_sensitive(False)
            start.set_sensitive(False)
            end.set_sensitive(False)
            network.set_sensitive(False)
            gateway.set_sensitive(False)
            net.modify_bg(Gtk.StateType.NORMAL, white)
            start.modify_bg(Gtk.StateType.NORMAL, white)
            end.modify_bg(Gtk.StateType.NORMAL, white)
            network.modify_bg(Gtk.StateType.NORMAL, white)
            gateway.modify_bg(Gtk.StateType.NORMAL, white)

    def change_ipv6_enable(self, src):
        ignore = src

        white = Gdk.Color.parse("#f0f0f0")[1]
        net = self.widget("net-ipv6-network")
        start = self.widget("net-dhcpv6-start")
        end = self.widget("net-dhcpv6-end")
        network = self.widget("net-routev6-network")
        gateway = self.widget("net-routev6-gateway")
        if self.get_config_ipv6_enable():
            net.set_sensitive(True)
            net.set_text("")
            net.modify_bg(Gtk.StateType.NORMAL, white)
            if self.get_config_dhcpv6_enable():
                start.set_sensitive(True)
                end.set_sensitive(True)
            if self.get_config_routev6_enable():
                network.set_sensitive(True)
                gateway.set_sensitive(True)
        else:
            net.set_text("")
            start.set_text("")
            end.set_text("")
            network.set_text("")
            gateway.set_text("")
            net.set_sensitive(False)
            start.set_sensitive(False)
            end.set_sensitive(False)
            network.set_sensitive(False)
            gateway.set_sensitive(False)
            net.modify_bg(Gtk.StateType.NORMAL, white)
            start.modify_bg(Gtk.StateType.NORMAL, white)
            end.modify_bg(Gtk.StateType.NORMAL, white)
            network.modify_bg(Gtk.StateType.NORMAL, white)
            gateway.modify_bg(Gtk.StateType.NORMAL, white)

    def change_ipv4_network(self, src):
        ignore = src

        ip = self.get_config_ip4()
        green = Gdk.Color.parse("#c0ffc0")[1]
        red = Gdk.Color.parse("#ffc0c0")[1]
        black = Gdk.Color.parse("#000000")[1]
        src.modify_text(Gtk.StateType.NORMAL, black)

        # No IP specified or invalid IP
        if ip is None or ip.version != 4:
            src.modify_bg(Gtk.StateType.NORMAL, red)
            self.widget("net-info-gateway").set_text("")
            self.widget("net-info-type").set_text("")
            self.widget("net-dhcpv4-start").set_text("")
            self.widget("net-dhcpv4-end").set_text("")
            self.widget("net-routev4-network").set_text("")
            self.widget("net-routev4-gateway").set_text("")
            return

        # We've got a valid IP
        if ip.numhosts < 16 or not ip.is_private:
            src.modify_bg(Gtk.StateType.NORMAL, red)
        else:
            src.modify_bg(Gtk.StateType.NORMAL, green)

        if ip.prefixlen == 32:
            self.widget("net-info-gateway").set_text("")
        else:
            self.widget("net-info-gateway").set_text(str(ip.network + 1))

        if ip.is_private:
            self.widget("net-info-type").set_text(_("Private"))
        else:
            self.widget("net-info-type").set_text(_("Other/Public"))

        if self.get_config_dhcpv4_enable():
            self.widget("net-dhcpv4-start").set_sensitive(True)
            self.widget("net-dhcpv4-end").set_sensitive(True)
            start = int(ip.numhosts / 2)
            end   = int(ip.numhosts - 2)
            self.widget("net-dhcpv4-start").set_text(str(ip.network + start))
            self.widget("net-dhcpv4-end").set_text(str(ip.network + end))
        else:
            self.widget("net-dhcpv4-start").set_sensitive(False)
            self.widget("net-dhcpv4-end").set_sensitive(False)

        if self.get_config_routev4_enable():
            self.widget("net-routev4-network").set_sensitive(True)
            self.widget("net-routev4-gateway").set_sensitive(True)
        else:
            self.widget("net-routev4-network").set_sensitive(False)
            self.widget("net-routev4-gateway").set_sensitive(False)

    def change_ipv6_network(self, src):
        ignore = src

        ip = self.get_config_ip6()
        green = Gdk.Color.parse("#c0ffc0")[1]
        red = Gdk.Color.parse("#ffc0c0")[1]
        black = Gdk.Color.parse("#000000")[1]
        src.modify_text(Gtk.StateType.NORMAL, black)

        # No IP specified or invalid IP
        if ip is None or ip.version != 6:
            src.modify_bg(Gtk.StateType.NORMAL, red)
            self.widget("net-info-gateway-ip6").set_text("")
            self.widget("net-info-type-ip6").set_text("")
            self.widget("net-dhcpv6-start").set_text("")
            self.widget("net-dhcpv6-end").set_text("")
            self.widget("net-routev6-network").set_text("")
            self.widget("net-routev6-gateway").set_text("")
            return

        color = green
        if not ip.is_private:
            color = red
        if ip.prefixlen != 64:
            color = red
        src.modify_bg(Gtk.StateType.NORMAL, color)

        if ip.prefixlen != 64:
            self.widget("net-info-gateway-ip6").set_text("")
        else:
            self.widget("net-info-gateway-ip6").set_text(str(ip.network + 1))

        if ip.is_private:
            self.widget("net-info-type-ip6").set_text(_("Private"))
        elif ip.is_reserved:
            self.widget("net-info-type-ip6").set_text(_("Reserved"))
        elif ip.is_unspecified:
            self.widget("net-info-type-ip6").set_text(_("Unspecified"))
        else:
            self.widget("net-info-type-ip6").set_text(_("Other/Public"))

        if self.get_config_dhcpv6_enable():
            self.widget("net-dhcpv6-start").set_sensitive(True)
            self.widget("net-dhcpv6-end").set_sensitive(True)
            start = 256
            end   = 512 - 1
            self.widget("net-dhcpv6-start").set_text(str(ip.network + start))
            self.widget("net-dhcpv6-end").set_text(str(ip.network + end))
        else:
            self.widget("net-dhcpv6-start").set_sensitive(False)
            self.widget("net-dhcpv6-end").set_sensitive(False)

        if self.get_config_routev6_enable():
            self.widget("net-routev6-network").set_sensitive(True)
            self.widget("net-routev6-gateway").set_sensitive(True)
        else:
            self.widget("net-routev6-network").set_sensitive(False)
            self.widget("net-routev6-gateway").set_sensitive(False)


    def change_routev4_enable(self, src):
        ignore = src

        white = Gdk.Color.parse("#f0f0f0")[1]
        ntwk = self.widget("net-routev4-network")
        gway = self.widget("net-routev4-gateway")
        ntwk.modify_bg(Gtk.StateType.NORMAL, white)
        gway.modify_bg(Gtk.StateType.NORMAL, white)
        ntwk.set_text("")
        gway.set_text("")

        if self.get_config_routev4_enable():
            ntwk.set_sensitive(True)
            gway.set_sensitive(True)
        else:
            ntwk.set_sensitive(False)
            gway.set_sensitive(False)

    def get_config_routev4_network(self):
        if not self.get_config_routev4_enable():
            return None
        return self.widget("net-routev4-network").get_text()

    def get_config_routev4_gateway(self):
        if not self.get_config_routev4_enable():
            return None
        return self.widget("net-routev4-gateway").get_text()

    def get_route_addr(self, addrStr):
        if addrStr is None:
            return None
        try:
            addr = ipaddr.IPNetwork(addrStr)
        except:
            addr = None
        return addr

    def change_routev4_network(self, src):
        ignore = src

        ntwk = self.get_config_routev4_network()
        ipAddr = self.get_config_ip4()
        black = Gdk.Color.parse("#000000")[1]
        src.modify_text(Gtk.StateType.NORMAL, black)

        if ipAddr is None or ntwk is None:
            white = Gdk.Color.parse("#f0f0f0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, white)
            return
        addr = self.get_route_addr(ntwk)
        red = Gdk.Color.parse("#ffc0c0")[1]
        green = Gdk.Color.parse("#c0ffc0")[1]
        color = green
        if addr is None:
            color = red
        else:
            if addr.version != 4:
                color = red
            if addr.prefixlen > 28:
                color = red
        src.modify_bg(Gtk.StateType.NORMAL, color)

    def change_routev4_gateway(self, src):
        ignore = src

        gway = self.get_config_routev4_gateway()
        ipAddr = self.get_config_ip4()
        black = Gdk.Color.parse("#000000")[1]
        src.modify_text(Gtk.StateType.NORMAL, black)

        if ipAddr is None or gway is None:
            white = Gdk.Color.parse("#f0f0f0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, white)
            return
        addr = self.get_route_addr(gway)
        red = Gdk.Color.parse("#ffc0c0")[1]
        green = Gdk.Color.parse("#c0ffc0")[1]
        color = green
        if addr is None:
            color = red
        else:
            if addr.version != 4:
                color = red
            if not ipAddr.overlaps(addr):
                color = red
            if addr.prefixlen != 32:
                color = red
        src.modify_bg(Gtk.StateType.NORMAL, color)

    def change_dhcpv4_enable(self, src):
        ignore = src

        white = Gdk.Color.parse("#f0f0f0")[1]
        start = self.widget("net-dhcpv4-start")
        end = self.widget("net-dhcpv4-end")
        start.modify_bg(Gtk.StateType.NORMAL, white)
        end.modify_bg(Gtk.StateType.NORMAL, white)
        start.set_text("")
        end.set_text("")

        if not self.get_config_dhcpv4_enable():
            start.set_sensitive(False)
            end.set_sensitive(False)
        else:
            start.set_sensitive(True)
            end.set_sensitive(True)

            ip = self.get_config_ip4()
            if ip:
                start.set_text(str(ip.network + int(ip.numhosts / 2)))
                end.set_text(str(ip.network + int(ip.numhosts - 2)))

    def change_dhcpv4_start(self, src):
        ignore = src

        start = self.get_config_dhcpv4_start()
        self.change_dhcpv4(src, start)

    def change_dhcpv4_end(self, src):
        ignore = src

        end = self.get_config_dhcpv4_end()
        self.change_dhcpv4(src, end)

    def change_dhcpv4(self, src, addr):
        ip = self.get_config_ip4()
        black = Gdk.Color.parse("#000000")[1]
        src.modify_text(Gtk.StateType.NORMAL, black)

        if ip is None or addr is None:
            white = Gdk.Color.parse("#f0f0f0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, white)
            return
        if addr.version != 4 or not ip.overlaps(addr):
            red = Gdk.Color.parse("#ffc0c0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, red)
        else:
            green = Gdk.Color.parse("#c0ffc0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, green)

    def change_routev6_enable(self, src):
        white = Gdk.Color.parse("#f0f0f0")[1]
        ntwk = self.widget("net-routev6-network")
        gway = self.widget("net-routev6-gateway")
        ntwk.modify_bg(Gtk.StateType.NORMAL, white)
        gway.modify_bg(Gtk.StateType.NORMAL, white)
        ntwk.set_text("")
        gway.set_text("")

        if self.get_config_routev6_enable():
            ntwk.set_sensitive(True)
            gway.set_sensitive(True)
        else:
            ntwk.set_sensitive(False)
            gway.set_sensitive(False)

    def get_config_routev6_network(self):
        if not self.get_config_routev6_enable():
            return None
        return self.widget("net-routev6-network").get_text()

    def get_config_routev6_gateway(self):
        if not self.get_config_routev6_enable():
            return None
        return self.widget("net-routev6-gateway").get_text()

    def change_routev6_network(self, src):
        ntwk = self.get_config_routev6_network()
        ip = self.get_config_ip6()
        black = Gdk.Color.parse("#000000")[1]
        src.modify_text(Gtk.StateType.NORMAL, black)

        if ip is None or ntwk is None:
            white = Gdk.Color.parse("#f0f0f0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, white)
            return
        addr = self.get_route_addr(ntwk)
        red = Gdk.Color.parse("#ffc0c0")[1]
        green = Gdk.Color.parse("#c0ffc0")[1]
        color = green
        if addr is None:
            color = red
        else:
            if addr.version != 6:
                color = red
            if  addr.prefixlen > 64:
                color = red
        src.modify_bg(Gtk.StateType.NORMAL, color)

    def change_routev6_gateway(self, src):
        gway = self.get_config_routev6_gateway()
        ip = self.get_config_ip6()
        black = Gdk.Color.parse("#000000")[1]
        src.modify_text(Gtk.StateType.NORMAL, black)

        if ip is None or gway is None:
            white = Gdk.Color.parse("#f0f0f0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, white)
            return
        addr = self.get_route_addr(gway)
        red = Gdk.Color.parse("#ffc0c0")[1]
        green = Gdk.Color.parse("#c0ffc0")[1]
        color = green
        if addr is None:
            color = red
        else:
            if addr.version != 6:
                color = red
            if not ip.overlaps(addr):
                color = red
            if addr.prefixlen != 128:
                color = red
        src.modify_bg(Gtk.StateType.NORMAL, color)

    def change_dhcpv6_enable(self, src):
        white = Gdk.Color.parse("#f0f0f0")[1]
        start = self.widget("net-dhcpv6-start")
        end = self.widget("net-dhcpv6-end")
        start.modify_bg(Gtk.StateType.NORMAL, white)
        end.modify_bg(Gtk.StateType.NORMAL, white)
        start.set_text("")
        end.set_text("")
        if not self.get_config_dhcpv6_enable():
            start.set_sensitive(False)
            end.set_sensitive(False)

        else:
            start.set_sensitive(True)
            end.set_sensitive(True)

            ip = self.get_config_ip6()
            if ip:
                start.set_text(str(ip.network + 256))
                end.set_text(str(ip.network + 511))

    def change_dhcpv6_start(self, src):
        start = self.get_config_dhcpv6_start()
        self.change_dhcpv6(src, start)

    def change_dhcpv6_end(self, src):
        end = self.get_config_dhcpv6_end()
        self.change_dhcpv6(src, end)

    def change_dhcpv6(self, src, addr):
        ip = self.get_config_ip6()
        black = Gdk.Color.parse("#000000")[1]
        src.modify_text(Gtk.StateType.NORMAL, black)

        if ip is None or addr is None:
            white = Gdk.Color.parse("#f0f0f0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, white)
            return
        if addr.version != 6 or not ip.overlaps(addr):
            red = Gdk.Color.parse("#ffc0c0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, red)
        else:
            green = Gdk.Color.parse("#c0ffc0")[1]
            src.modify_bg(Gtk.StateType.NORMAL, green)

    def change_forward_type(self, src_ignore):
        skip_fwd = self.widget("net-forward-none").get_active()

        self.widget("net-forward-mode").set_sensitive(not skip_fwd)
        self.widget("net-forward").set_sensitive(not skip_fwd)

    def get_config_name(self):
        return self.widget("net-name").get_text()

    def get_config_domain_name(self):
        return self.widget("net-domain-name").get_text()

    def get_config_ip4(self):
        if not self.get_config_ipv4_enable():
            return None
        try:
            return ipaddr.IPNetwork(self.widget("net-ipv4-network").get_text())
        except:
            return None

    def get_config_dhcpv4_start(self):
        try:
            return ipaddr.IPNetwork(self.widget("net-dhcpv4-start").get_text())
        except:
            return None
    def get_config_dhcpv4_end(self):
        try:
            return ipaddr.IPNetwork(self.widget("net-dhcpv4-end").get_text())
        except:
            return None

    def get_config_ip6(self):
        if not self.get_config_ipv6_enable():
            return None
        try:
            return ipaddr.IPNetwork(self.widget("net-ipv6-network").get_text())
        except:
            return None

    def get_config_dhcpv6_start(self):
        try:
            return ipaddr.IPNetwork(self.widget("net-dhcpv6-start").get_text())
        except:
            return None

    def get_config_dhcpv6_end(self):
        try:
            return ipaddr.IPNetwork(self.widget("net-dhcpv6-end").get_text())
        except:
            return None

    def get_config_forwarding(self):
        if self.widget("net-forward-none").get_active():
            return [None, None]
        else:
            dev = self.widget("net-forward")
            model = dev.get_model()
            active = dev.get_active()
            name = model[active][1]

            mode_w = self.widget("net-forward-mode")
            mode = mode_w.get_model()[mode_w.get_active()][1]
            return [name, mode]

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

    def populate_summary(self):
        self.widget("summary-name").set_text(self.get_config_name())
        self.widget("summary-domain").set_text(self.get_config_domain_name())
        self.widget("summary-ip4-network").set_text("")
        self.widget("summary-ip4-gateway").set_text("")
        self.widget("summary-ip6-network").set_text("")
        self.widget("summary-ip6-gateway").set_text("")

        ip = self.get_config_ip4()
        if ip:
            self.widget("label-ip4-gateway").show()
            self.widget("summary-ip4-gateway").show()
            self.widget("label-ip4-network").set_text(_("Network Address / prefix:"))
            self.widget("summary-ip4-network").set_text(str(ip))
            self.widget("summary-ip4-gateway").set_text(str(ip.network + 1))
        else:
            self.widget("label-ip4-gateway").hide()
            self.widget("summary-ip4-gateway").hide()
            self.widget("label-ip4-network").set_text("IPv4 Network:")
            self.widget("summary-ip4-network").set_text("Not Defined")

        if ip and self.get_config_dhcpv4_enable():
            self.widget("label-dhcp-end").show()
            self.widget("summary-dhcp-end").show()
            start = self.get_config_dhcpv4_start()
            end = self.get_config_dhcpv4_end()
            self.widget("label-dhcp-start").set_text("DHCPv4 Start Address:")
            if start and end:
                self.widget("summary-dhcp-start").set_text(str(start.network))
                self.widget("summary-dhcp-end").set_text(str(end.network))
            else:
                self.widget("summary-dhcp-start").set_text("?")
                self.widget("summary-dhcp-end").set_text("?")
        else:
            self.widget("label-dhcp-end").hide()
            self.widget("summary-dhcp-end").hide()
            self.widget("label-dhcp-start").set_text(_("DHCPv4 Status:"))
            self.widget("summary-dhcp-start").set_text(_("Disabled"))

        if ip and self.get_config_routev4_enable():
            self.widget("label-routev4-network").show()
            self.widget("label-routev4-gateway").show()
            self.widget("summary-routev4-network").show()
            self.widget("summary-routev4-gateway").show()
            self.widget("summary-routev4-network").set_text("")
            self.widget("summary-routev4-gateway").set_text("")
            ntwk = self.get_config_routev4_network()
            try:
                naddr = ipaddr.IPNetwork(ntwk)
            except:
                naddr = None
            gway = self.get_config_routev4_gateway()
            try:
                gaddr = ipaddr.IPNetwork(gway)
            except:
                gaddr = None
            if naddr and gaddr:
                self.widget("summary-routev4-network").set_text(str(naddr))
                self.widget("summary-routev4-gateway").set_text(str(gaddr.network))
        else:
            self.widget("label-routev4-network").hide()
            self.widget("label-routev4-gateway").hide()
            self.widget("summary-routev4-network").hide()
            self.widget("summary-routev4-gateway").hide()

        forward_txt = ""
        dev, mode = self.get_config_forwarding()
        forward_txt = vmmNetwork.pretty_desc(mode, dev)
        self.widget("summary-ipv4-forwarding").set_text(forward_txt)

        ip = self.get_config_ip6()
        if ip:
            self.widget("label-ip6-gateway").show()
            self.widget("summary-ip6-gateway").show()
            self.widget("label-ip6-network").set_text(_("Network Address / prefix:"))
            self.widget("summary-ip6-network").set_text(str(ip))
            self.widget("summary-ip6-gateway").set_text(str(ip.network + 1))
        else:
            self.widget("label-ip6-gateway").hide()
            self.widget("summary-ip6-gateway").hide()
            self.widget("label-ip6-network").set_text(_("IPV6 Network:"))
            self.widget("summary-ip6-network").set_text(_("Not Defined"))


        if ip and self.get_config_dhcpv6_enable():
            self.widget("label-dhcpv6-end").show()
            self.widget("summary-dhcpv6-end").show()
            start = self.get_config_dhcpv6_start()
            end = self.get_config_dhcpv6_end()
            self.widget("label-dhcpv6-start").set_text("DHCPv6 Start Address:")
            if start and end:
                self.widget("summary-dhcpv6-start").set_text(str(start.network))
                self.widget("summary-dhcpv6-end").set_text(str(end.network))
            else:
                self.widget("summary-dhcpv6-start").set_text("?")
                self.widget("summary-dhcpv6-end").set_text("?")
        else:
            self.widget("label-dhcpv6-end").hide()
            self.widget("summary-dhcpv6-end").hide()
            self.widget("label-dhcpv6-start").set_text(_("DHCPv6 Status:"))
            self.widget("summary-dhcpv6-start").set_text(_("Disabled"))

        if ip and self.get_config_routev6_enable():
            self.widget("label-routev6-network").show()
            self.widget("label-routev6-gateway").show()
            self.widget("summary-routev6-network").show()
            self.widget("summary-routev6-gateway").show()
            self.widget("summary-routev6-network").set_text("")
            self.widget("summary-routev6-gateway").set_text("")
            ntwk = self.get_config_routev6_network()
            try:
                naddr = ipaddr.IPNetwork(ntwk)
            except:
                naddr = None
            gway = self.get_config_routev6_gateway()
            try:
                gaddr = ipaddr.IPNetwork(gway)
            except:
                gaddr = None
            if naddr and gaddr:
                self.widget("summary-routev6-network").set_text(str(naddr))
                self.widget("summary-routev6-gateway").set_text(str(gaddr.network))
        else:
            self.widget("label-routev6-network").hide()
            self.widget("label-routev6-gateway").hide()
            self.widget("summary-routev6-network").hide()
            self.widget("summary-routev6-gateway").hide()


        if ip:
            self.widget("summary-ipv6-forwarding").set_text("Routed network")
        else:
            if self.widget("net-enable-ipv6-networking").get_active():
                self.widget("summary-ipv6-forwarding").set_text("Isolated network, internal routing only")
            else:
                self.widget("summary-ipv6-forwarding").set_text("Isolated network")

    def populate_ipv4(self):
        if not self.get_config_ipv4_enable():
            self.widget("net-ipv4-network").set_text("")
            self.widget("net-dhcpv4-end").set_text("")
            self.widget("net-dhcpv4-start").set_text("")
            self.widget("net-ipv4-network").set_sensitive(False)
            self.widget("net-dhcpv4-start").set_sensitive(False)
            self.widget("net-dhcpv4-end").set_sensitive(False)
        else:
            self.widget("net-ipv4-network").set_sensitive(True)

        if not self.get_config_dhcpv4_enable():
            self.widget("net-dhcpv4-end").set_text("")
            self.widget("net-dhcpv4-start").set_text("")
            self.widget("net-dhcpv4-start").set_sensitive(False)
            self.widget("net-dhcpv4-end").set_sensitive(False)
        else:
            ip = self.get_config_ip4()
            if ip:
                start = int(ip.numhosts / 2)
                end   = int(ip.numhosts - 2)
                if self.widget("net-dhcpv4-start").get_text() == "":
                    self.widget("net-dhcpv4-start").set_text(str(ip.network + start))
                    self.widget("net-dhcpv4-end").set_text(str(ip.network + end))
            self.widget("net-dhcpv4-start").set_sensitive(True)
            self.widget("net-dhcpv4-end").set_sensitive(True)


    def populate_ipv6(self):
        if not self.get_config_ipv6_enable():
            self.widget("net-ipv6-network").set_text("")
            self.widget("net-dhcpv6-end").set_text("")
            self.widget("net-dhcpv6-start").set_text("")
            self.widget("net-ipv6-network").set_sensitive(False)
            self.widget("net-dhcpv6-start").set_sensitive(False)
            self.widget("net-dhcpv6-end").set_sensitive(False)
            self.widget("net-routev6-network").set_sensitive(False)
            self.widget("net-routev6-gateway").set_sensitive(False)
        else:
            self.widget("net-ipv6-network").set_sensitive(True)

        if not self.get_config_dhcpv6_enable():
            self.widget("net-dhcpv6-end").set_text("")
            self.widget("net-dhcpv6-start").set_text("")
            self.widget("net-dhcpv6-start").set_sensitive(False)
            self.widget("net-dhcpv6-end").set_sensitive(False)
        else:
            ip = self.get_config_ip6()
            if ip:
                start = 256
                end   = 512 - 1
                if self.widget("net-dhcpv6-start").get_text() == "":
                    self.widget("net-dhcpv6-start").set_text(str(ip.network + start))
                    self.widget("net-dhcpv6-end").set_text(str(ip.network + end))
            self.widget("net-dhcpv6-start").set_sensitive(True)
            self.widget("net-dhcpv6-end").set_sensitive(True)
        if not self.get_config_routev6_enable():
            self.widget("net-routev6-network").set_text("")
            self.widget("net-routev6-gateway").set_text("")
            self.widget("net-routev6-network").set_sensitive(False)
            self.widget("net-routev6-gateway").set_sensitive(False)
        else:
            self.widget("net-routev6-network").set_text("")
            self.widget("net-routev6-gateway").set_text("")
            self.widget("net-routev6-network").set_sensitive(True)
            self.widget("net-routev6-gateway").set_sensitive(True)

    def populate_misc(self):
        name = self.widget("net-name").get_text()
        if self.widget("net-domain-name").get_text() == "":
            self.widget("net-domain-name").set_text(name)

    def page_changed(self, ignore1, ignore2, page_number):
        if page_number == PAGE_NAME:
            name_widget = self.widget("net-name")
            name_widget.set_sensitive(True)
            name_widget.grab_focus()
        elif page_number == PAGE_IPV4:
            self.populate_ipv4()
        elif page_number == PAGE_IPV6:
            self.populate_ipv6()
        elif page_number == PAGE_MISC:
            self.populate_misc()
        elif page_number == PAGE_SUMMARY:
            self.populate_summary()

        if page_number == PAGE_INTRO:
            self.widget("create-back").set_sensitive(False)
        else:
            self.widget("create-back").set_sensitive(True)

        if page_number == PAGE_SUMMARY:
            self.widget("create-forward").hide()
            self.widget("create-finish").show()
            self.widget("create-finish").grab_focus()
        else:
            self.widget("create-forward").show()
            self.widget("create-finish").hide()


    def finish(self, ignore=None):
        name = self.get_config_name()
        dev, mode = self.get_config_forwarding()

        if self.widget("net-enable-ipv6-networking").get_active():
            xml = "<network ipv6='yes'>\n"
        else:
            xml = "<network>\n"

        xml += "  <name>%s</name>\n" % name

        domain_name = self.get_config_domain_name()
        if len(domain_name) != 0:
            xml += "  <domain name='%s' />\n" % domain_name

        if mode:
            if dev is not None:
                xml += "  <forward mode='%s' dev='%s'/>\n" % (mode, dev)
            else:
                xml += "  <forward mode='%s'/>\n" % mode

        if self.get_config_ipv4_enable():
            ip = self.get_config_ip4()
            xml += "  <ip address='%s' netmask='%s'>\n" % (str(ip.network + 1),
                                                       str(ip.netmask))

            if self.get_config_dhcpv4_enable():
                start = self.get_config_dhcpv4_start()
                end = self.get_config_dhcpv4_end()
                xml += "    <dhcp>\n"
                xml += "      <range start='%s' end='%s'/>\n" % (str(start.network),
                                                       str(end.network))
                xml += "    </dhcp>\n"
            xml += "  </ip>\n"

        if self.get_config_ipv6_enable():
            ip = self.get_config_ip6()
            xml += "  <ip family='ipv6' address='%s' prefix='%s'>\n" % (str(ip.network + 1),
                                                       str(ip.prefixlen))

            if self.get_config_dhcpv6_enable():
                start = self.get_config_dhcpv6_start()
                end = self.get_config_dhcpv6_end()
                xml += "    <dhcp>\n"
                xml += "      <range start='%s' end='%s'/>\n" % (str(start.network),
                                                                str(end.network))
                xml += "    </dhcp>\n"
            xml += "  </ip>\n"

        ntwk = self.get_config_routev4_network()
        try:
            netaddr = ipaddr.IPNetwork(ntwk)
        except:
            netaddr = None
        gway = self.get_config_routev4_gateway()
        try:
            gwaddr = ipaddr.IPNetwork(gway)
        except:
            gwaddr = None
        if netaddr and gwaddr:
            xml += "<route family='ipv4'"
            xml += " address='%s'" % netaddr.network
            xml += " prefix='%s'" % netaddr.prefixlen
            xml += " gateway='%s' />" % gwaddr.network

        ntwk = self.get_config_routev6_network()
        try:
            netaddr = ipaddr.IPNetwork(ntwk)
        except:
            netaddr = None
        gway = self.get_config_routev6_gateway()
        try:
            gwaddr = ipaddr.IPNetwork(gway)
        except:
            gwaddr = None
        if netaddr and gwaddr:
            xml += "<route family='ipv6'"
            xml += " address='%s'" % netaddr.network
            xml += " prefix='%s'" % netaddr.prefixlen
            xml += " gateway='%s' />" % gwaddr.network


        xml += "</network>\n"

        logging.debug("Generated network XML:\n" + xml)

        try:
            self.conn.create_network(xml)
        except Exception, e:
            self.err.show_err(_("Error creating virtual network: %s" % str(e)))
            return

        self.conn.tick(noStatsUpdate=True)
        self.close()

    def validate_name(self):
        name_widget = self.widget("net-name")
        name = name_widget.get_text()
        if len(name) > 50 or len(name) == 0:
            retcode = self.err.val_err(_("Invalid Network Name"),
                        _("Network name must be non-blank and less than "
                          "50 characters"))
            name_widget.grab_focus()
            return retcode
        if re.match("^[a-zA-Z0-9_]*$", name) is None:
            return self.err.val_err(_("Invalid Network Name"),
                        _("Network name may contain alphanumeric and '_' "
                          "characters only"))
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

        if ip.numhosts < 16:
            return self.err.val_err(_("Invalid Network Address"),
                    _("The network prefix must be at least /28 (16 addresses)"))

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
            naddr = self.get_route_addr(ntwk)
            if naddr is None:
                ntwkbad = True
            else:
                if naddr.version != 4:
                    ntwkbad = True
                if naddr.prefixlen > 28:
                    ntwkbad = True
            gaddr = self.get_route_addr(gway)
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
                    _("For libvirt, the IPv6 network prefix must be 64"))

        if not ip.is_private:
            res = self.err.yes_no(_("Check Network Address"),
                    _("The network should normally use a private IPv4 "
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
            naddr = self.get_route_addr(ntwk)
            if naddr is None:
                ntwkbad = True
            else:
                if naddr.version != 6:
                    ntwkbad = True
                if naddr.prefixlen > 64:
                    ntwkbad = True
            gaddr = self.get_route_addr(gway)
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
        domain_name = self.widget("net-domain-name").get_text()
        if len(domain_name) > 0:
            if len(domain_name) > 16:
                return self.err.val_err(_("Invalid Domain Name"),
                            _("Domain name must be less than 17 characters"))
            if re.match("^[a-zA-Z0-9_]*$", domain_name) is None:
                return self.err.val_err(_("Invalid Domain Name"),
                            _("Domain name may contain alphanumeric and '_' "
                              "characters only"))

        if not self.widget("net-forward-dev").get_active():
            return True

        dev = self.widget("net-forward")
        if dev.get_active() == -1:
            return self.err.val_err(_("Invalid forwarding mode"),
                    _("Please select where the traffic should be forwarded"))
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
