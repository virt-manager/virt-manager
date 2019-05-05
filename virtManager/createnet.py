# Copyright (C) 2006-2007, 2013 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import ipaddress
import logging

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Pango

from virtinst import Network

from . import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI

_green = Gdk.Color.parse("#c0ffc0")[1]
_red = Gdk.Color.parse("#ffc0c0")[1]
_black = Gdk.Color.parse("#000000")[1]
_white = Gdk.Color.parse("#f0f0f0")[1]


def _make_ipaddr(addrstr):
    if addrstr is None:
        return None
    try:
        return ipaddress.ip_network(str(addrstr), strict=False)
    except Exception:
        return None


class vmmCreateNetwork(vmmGObjectUI):
    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "createnet.ui", "vmm-create-net")
        self.conn = conn

        self.builder.connect_signals({
            "on_create_cancel_clicked": self.close,
            "on_vmm_create_delete_event": self.close,
            "on_create_finish_clicked": self.finish,

            "on_net_forward_mode_changed": self._net_forward_mode_changed_cb,
            "on_net_dns_use_toggled": self._net_dns_use_toggled_cb,

            "on_net-ipv4-enable_toggled":  self.change_ipv4_enable,
            "on_net-ipv4-network_changed":  self.change_ipv4_network,
            "on_net-dhcpv4-enable_toggled": self.change_dhcpv4_enable,
            "on_net-dhcpv4-start_changed":  self.change_dhcpv4_start,
            "on_net-dhcpv4-end_changed":    self.change_dhcpv4_end,

            "on_net-ipv6-enable_toggled":  self.change_ipv6_enable,
            "on_net-ipv6-network_changed":  self.change_ipv6_network,
            "on_net-dhcpv6-enable_toggled": self.change_dhcpv6_enable,
            "on_net-dhcpv6-start_changed":  self.change_dhcpv6_start,
            "on_net-dhcpv6-end_changed":    self.change_dhcpv6_end,
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
        blue = Gdk.Color.parse("#0072A8")[1]
        self.widget("header").modify_bg(Gtk.StateType.NORMAL, blue)

        # [ label, dev name ]
        pf_list = self.widget("net-hostdevs")
        pf_model = Gtk.ListStore(str, str)
        pf_list.set_model(pf_model)
        text = uiutil.init_combo_text_column(pf_list, 1)
        text.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)

        # [ label, dev name ]
        fw_list = self.widget("net-forward-device")
        fw_model = Gtk.ListStore(str, str)
        fw_list.set_model(fw_model)
        uiutil.init_combo_text_column(fw_list, 1)

        # [ label, mode ]
        mode_list = self.widget("net-forward-mode")
        mode_model = Gtk.ListStore(str, str)
        mode_list.set_model(mode_model)
        uiutil.init_combo_text_column(mode_list, 1)

        mode_model.append(["nat", _("NAT")])
        mode_model.append(["route", _("Routed")])
        mode_model.append(["open", _("Open")])
        mode_model.append(["isolated", _("Isolated")])
        mode_model.append(["hostdev", _("SR-IOV pool")])

    def reset_state(self):
        default_name = Network.find_free_name(
                self.conn.get_backend(), "network")
        self.widget("net-name").set_text(default_name)

        self.widget("net-dns-use-netname").set_active(True)

        self.widget("net-ipv4-expander").set_visible(True)
        self.widget("net-ipv4-expander").set_expanded(False)
        self.widget("net-ipv6-expander").set_visible(True)
        self.widget("net-ipv6-expander").set_expanded(False)
        self.widget("net-dns-expander").set_visible(True)
        self.widget("net-dns-expander").set_expanded(False)

        self.widget("net-ipv4-enable").set_active(True)
        self.widget("net-ipv4-network").set_text("192.168.100.0/24")
        self.widget("net-dhcpv4-enable").set_active(True)
        self.widget("net-dhcpv4-start").set_text("192.168.100.128")
        self.widget("net-dhcpv4-end").set_text("192.168.100.254")

        self.widget("net-ipv6-enable").set_active(False)
        self.widget("net-ipv6-network").set_text("")
        self.widget("net-dhcpv6-enable").set_active(False)
        self.widget("net-dhcpv6-start").set_text("")
        self.widget("net-dhcpv6-end").set_text("")


        # Populate physical forward devices
        devnames = []
        for nodedev in self.conn.filter_nodedevs("net"):
            devnames.append(nodedev.xmlobj.interface)
        for iface in self.conn.list_interfaces():
            if iface.get_name() not in devnames:
                devnames.append(iface.get_name())

        fw_model = self.widget("net-forward-device").get_model()
        fw_model.clear()
        fw_model.append([None, _("Any physical device")])

        for name in devnames:
            fw_model.append([name, _("Physical device %s") % name])
        self.widget("net-forward-device").set_active(0)

        self.widget("net-forward-mode").set_active(0)


        # Populate hostdev forward devices
        devprettynames = []
        ifnames = []
        for pcidev in self.conn.filter_nodedevs("pci"):
            if pcidev.xmlobj.capability_type != "virt_functions":
                continue
            devdesc = pcidev.xmlobj.pretty_name()
            for netdev in self.conn.filter_nodedevs("net"):
                if pcidev.xmlobj.name != netdev.xmlobj.parent:
                    continue
                ifname = netdev.xmlobj.interface
                devprettyname = "%s (%s)" % (ifname, devdesc)
                devprettynames.append(devprettyname)
                ifnames.append(ifname)
                break

        pf_model = self.widget("net-hostdevs").get_model()
        pf_model.clear()
        for devprettyname, ifname in zip(devprettynames, ifnames):
            pf_model.append([ifname, devprettyname])
        if len(pf_model) == 0:
            pf_model.append([None, _("No available device")])
        self.widget("net-hostdevs").set_active(0)



    ##################
    # UI get helpers #
    ##################

    def get_config_ipv4_enable(self):
        return (self.widget("net-ipv4-expander").is_visible() and
                self.widget("net-ipv4-enable").get_active())
    def get_config_ipv6_enable(self):
        return (self.widget("net-ipv6-expander").is_visible() and
                self.widget("net-ipv6-enable").get_active())
    def get_config_dhcpv4_enable(self):
        return self.widget("net-dhcpv4-enable").get_active()
    def get_config_dhcpv6_enable(self):
        return self.widget("net-dhcpv6-enable").get_active()

    def get_config_domain_name(self):
        widget = self.widget("net-domain-name")
        if not widget.is_visible():
            return None

        if self.widget("net-dns-use-netname").get_active():
            return self.widget("net-name").get_text()
        return widget.get_text()

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
        mode = uiutil.get_list_selection(self.widget("net-forward-mode"))
        if mode == "isolated":
            return [None, None]

        if mode == "hostdev":
            dev = uiutil.get_list_selection(self.widget("net-hostdevs"))
        else:
            dev = uiutil.get_list_selection(self.widget("net-forward-device"))
        return [dev, mode]


    ###################
    # Page validation #
    ###################

    def _validate_name(self):
        try:
            name = self.widget("net-name").get_text()
            Network.validate_name(self.conn.get_backend(), name)
        except Exception as e:
            return self.err.val_err(_("Invalid network name"), str(e))

        return True

    def _validate_ipv4(self):
        if not self.get_config_ipv4_enable():
            return True
        ip = self.get_config_ip4()
        if ip is None:
            return self.err.val_err(_("Invalid Network Address"),
                    _("The network address could not be understood"))

        if ip.version != 4:
            return self.err.val_err(_("Invalid Network Address"),
                    _("The network must be an IPv4 address"))

        if ip.num_addresses < 8:
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

        return True

    def _validate_ipv6(self):
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

        return True

    def _validate(self):
        return (self._validate_name() and
                self._validate_ipv4() and
                self._validate_ipv6())


    #############
    # Listeners #
    #############

    def _net_forward_mode_changed_cb(self, src):
        mode = uiutil.get_list_selection(self.widget("net-forward-mode"))

        fw_visible = mode not in ["open", "isolated", "hostdev"]
        is_hostdev = mode in ["hostdev"]

        uiutil.set_grid_row_visible(
            self.widget("net-forward-device"), fw_visible)
        uiutil.set_grid_row_visible(self.widget("net-hostdevs"), is_hostdev)

        self.widget("net-ipv4-expander").set_visible(not is_hostdev)
        self.widget("net-ipv6-expander").set_visible(not is_hostdev)
        self.widget("net-dns-expander").set_visible(not is_hostdev)

    def _net_dns_use_toggled_cb(self, src):
        custom = self.widget("net-dns-use-custom").get_active()
        self.widget("net-domain-name").set_sensitive(custom)

    def change_ipv4_enable(self, ignore):
        enabled = self.get_config_ipv4_enable()
        self.widget("net-ipv4-box").set_visible(enabled)
    def change_ipv6_enable(self, ignore):
        enabled = self.get_config_ipv6_enable()
        self.widget("net-ipv6-box").set_visible(enabled)

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

        valid_ip = (ip.num_addresses >= 8 and ip.is_private)
        start = int(ip.num_addresses // 2)
        end = int(ip.num_addresses - 2)

        src.modify_bg(Gtk.StateType.NORMAL, valid_ip and _green or _red)
        self.widget("net-dhcpv4-start").set_text(
            str(ip.network_address + start)
        )
        self.widget("net-dhcpv4-end").set_text(str(ip.network_address + end))

    def change_ipv6_network(self, src):
        ip = self.get_config_ip6()

        if ip is None or ip.version != 6:
            src.modify_bg(Gtk.StateType.NORMAL, _red)
            return

        valid_ip = (ip.num_addresses == 64 and ip.is_private)
        start = 256
        end = 512 - 1

        src.modify_bg(Gtk.StateType.NORMAL, valid_ip and _green or _red)
        self.widget("net-dhcpv6-start").set_text(
            str(ip.network_address + start)
        )
        self.widget("net-dhcpv6-end").set_text(str(ip.network_address + end))


    #########################
    # XML build and install #
    #########################


    def _build_xmlobj(self):
        net = Network(self.conn.get_backend())

        net.name = self.widget("net-name").get_text()
        net.domain_name = self.get_config_domain_name()

        dev, mode = self.get_config_forwarding()
        if mode:
            net.forward.mode = mode
            if mode == "open":
                net.forward.dev = None
            else:
                net.forward.dev = dev or None

        if net.forward.mode == "hostdev":
            net.forward.managed = "yes"
            pfobj = net.forward.pf.add_new()
            pfobj.dev = net.forward.dev
            net.forward.dev = None
            return net

        if self.get_config_ipv4_enable():
            ip = self.get_config_ip4()
            ipobj = net.ips.add_new()
            ipobj.address = str(ip.network_address + 1)
            ipobj.netmask = str(ip.netmask)

            if self.get_config_dhcpv4_enable():
                dhcpobj = ipobj.ranges.add_new()
                dhcpobj.start = str(
                    self.get_config_dhcpv4_start().network_address
                )
                dhcpobj.end = str(self.get_config_dhcpv4_end().network_address)

        if self.get_config_ipv6_enable():
            ip = self.get_config_ip6()
            ipobj = net.ips.add_new()
            ipobj.family = "ipv6"
            ipobj.address = str(ip.network_address + 1)
            ipobj.prefix = str(ip.prefixlen)

            if self.get_config_dhcpv6_enable():
                dhcpobj = ipobj.ranges.add_new()
                dhcpobj.start = str(
                    self.get_config_dhcpv6_start().network_address
                )
                dhcpobj.end = str(
                    self.get_config_dhcpv6_end().network_address
                )

        return net

    def _finish_cb(self, error, details):
        self.reset_finish_cursor()

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
        if not self._validate():
            return

        try:
            net = self._build_xmlobj()
        except Exception as e:
            self.err.show_err(_("Error generating network xml: %s") % str(e))
            return

        self.set_finish_cursor()
        progWin = vmmAsyncJob(self._async_net_create, [net],
                              self._finish_cb, [],
                              _("Creating virtual network..."),
                              _("Creating the virtual network may take a "
                                "while..."),
                              self.topwin)
        progWin.run()
