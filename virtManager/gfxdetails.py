#
# Copyright (C) 2006-2007, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
# Copyright (C) 2014 SUSE LINUX Products GmbH, Nuernberg, Germany.
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

from gi.repository import Gtk
from gi.repository import GObject

import virtinst
from . import uiutil
from .baseclass import vmmGObjectUI


class vmmGraphicsDetails(vmmGObjectUI):
    __gsignals__ = {
        "changed-password": (GObject.SignalFlags.RUN_FIRST, None, []),
        "changed-port": (GObject.SignalFlags.RUN_FIRST, None, []),
        "changed-tlsport": (GObject.SignalFlags.RUN_FIRST, None, []),
        "changed-type": (GObject.SignalFlags.RUN_FIRST, None, []),
        "changed-listen": (GObject.SignalFlags.RUN_FIRST, None, []),
        "changed-address": (GObject.SignalFlags.RUN_FIRST, None, []),
        "changed-keymap": (GObject.SignalFlags.RUN_FIRST, None, []),
        "changed-opengl": (GObject.SignalFlags.RUN_FIRST, None, []),
        "changed-rendernode": (GObject.SignalFlags.RUN_FIRST, None, []),
    }

    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, "gfxdetails.ui",
                              None, builder=builder, topwin=topwin)
        self.vm = vm
        self.conn = vm.conn

        self.builder.connect_signals({
            "on_graphics_type_changed": self._change_graphics_type,
            "on_graphics_port_auto_toggled": self._change_port_auto,
            "on_graphics_tlsport_auto_toggled": self._change_tlsport_auto,
            "on_graphics_use_password": self._change_password_chk,

            "on_graphics_listen_type_changed": self._change_graphics_listen,
            "on_graphics_password_changed": lambda ignore: self.emit("changed-password"),
            "on_graphics_address_changed": lambda ignore: self.emit("changed-address"),
            "on_graphics_tlsport_changed": lambda ignore: self.emit("changed-tlsport"),
            "on_graphics_port_changed": lambda ignore: self.emit("changed-port"),
            "on_graphics_keymap_changed": lambda ignore: self.emit("changed-keymap"),
            "on_graphics_opengl_toggled": self._change_opengl,
            "on_graphics_rendernode_changed": lambda ignore: self.emit("changed-rendernode")
        })

        self._init_ui()
        self.top_box = self.widget("graphics-box")

    def _cleanup(self):
        self.vm = None
        self.conn = None

    ##########################
    # Initialization methods #
    ##########################

    def _init_ui(self):
        graphics_list = self.widget("graphics-type")
        graphics_model = Gtk.ListStore(str, str)
        graphics_list.set_model(graphics_model)
        uiutil.init_combo_text_column(graphics_list, 1)
        graphics_model.clear()
        graphics_model.append(["spice", _("Spice server")])
        graphics_model.append(["vnc", _("VNC server")])

        graphics_listen_list = self.widget("graphics-listen-type")
        graphics_listen_model = Gtk.ListStore(str, str)
        graphics_listen_list.set_model(graphics_listen_model)
        uiutil.init_combo_text_column(graphics_listen_list, 1)
        graphics_listen_model.clear()
        graphics_listen_model.append(["address", _("Address")])
        graphics_listen_model.append(["none", _("None")])

        self.widget("graphics-address").set_model(Gtk.ListStore(str, str))
        uiutil.init_combo_text_column(self.widget("graphics-address"), 1)

        model = self.widget("graphics-address").get_model()
        model.clear()
        model.append([None, _("Hypervisor default")])
        model.append(["127.0.0.1", _("Localhost only")])
        model.append(["0.0.0.0", _("All interfaces")])

        # Keymap
        combo = self.widget("graphics-keymap")
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        model.append(["auto", _("Auto")])
        model.append([virtinst.VirtualGraphics.KEYMAP_LOCAL,
                      _("Copy local keymap")])
        for k in virtinst.VirtualGraphics.valid_keymaps():
            model.append([k, k])

        # Host GPU rendernode
        combo = self.widget("graphics-rendernode")
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        model.append([None, _("Auto")])
        devs = self.conn.filter_nodedevs("drm")
        for i in devs:
            drm = i.xmlobj
            if drm.drm_type != 'render':
                continue
            rendernode = drm.get_devnode().path

            model.append([rendernode, i.xmlobj.drm_pretty_name(self.conn.get_backend())])

    def _get_config_graphics_ports(self):
        port = uiutil.spin_get_helper(self.widget("graphics-port"))
        tlsport = uiutil.spin_get_helper(self.widget("graphics-tlsport"))
        gtype = uiutil.get_list_selection(self.widget("graphics-type"))

        if self.widget("graphics-port-auto").get_active():
            port = -1
        if self.widget("graphics-tlsport-auto").get_active():
            tlsport = -1

        if gtype != "spice":
            tlsport = None
        return port, tlsport


    ##############
    # Public API #
    ##############

    def reset_state(self):
        uiutil.set_grid_row_visible(self.widget("graphics-display"), False)
        uiutil.set_grid_row_visible(self.widget("graphics-xauth"), False)

        self.widget("graphics-type").set_active(0)
        self.widget("graphics-listen-type").set_active(0)
        self.widget("graphics-address").set_active(0)
        self.widget("graphics-keymap").set_active(0)
        self.widget("graphics-rendernode").set_active(0)

        self._change_ports()
        self.widget("graphics-port-auto").set_active(True)
        self.widget("graphics-tlsport-auto").set_active(True)
        self.widget("graphics-password").set_text("")
        self.widget("graphics-password").set_sensitive(False)
        self.widget("graphics-password-chk").set_active(False)

    def get_values(self):
        gtype = uiutil.get_list_selection(self.widget("graphics-type"))
        port, tlsport = self._get_config_graphics_ports()
        listen = uiutil.get_list_selection(self.widget("graphics-listen-type"))
        addr = uiutil.get_list_selection(self.widget("graphics-address"))
        keymap = uiutil.get_list_selection(self.widget("graphics-keymap"))
        if keymap == "auto":
            keymap = None

        passwd = self.widget("graphics-password").get_text()
        if not self.widget("graphics-password-chk").get_active():
            passwd = None

        gl = self.widget("graphics-opengl").get_active()
        rendernode = uiutil.get_list_selection(self.widget("graphics-rendernode"))

        return gtype, port, tlsport, listen, addr, passwd, keymap, gl, rendernode

    def set_dev(self, gfx):
        self.reset_state()

        def set_port(basename, val):
            auto = self.widget(basename + "-auto")
            widget = self.widget(basename)
            auto.set_inconsistent(False)
            label = auto.get_label().split(" (")[0]

            if val == -1 or gfx.autoport:
                auto.set_active(True)
                if val and val != -1:
                    label += " (%s %s)" % (_("Port"), val)
            elif val is None:
                auto.set_inconsistent(True)
            else:
                auto.set_active(False)
                widget.set_value(val)

            auto.set_label(label)

        gtype = gfx.type
        is_vnc = (gtype == "vnc")
        is_sdl = (gtype == "sdl")
        is_spice = (gtype == "spice")
        title = (_("%(graphicstype)s Server") %
                  {"graphicstype" : gfx.pretty_type_simple(gtype)})

        if is_vnc or is_spice:
            use_passwd = gfx.passwd is not None

            set_port("graphics-port", gfx.port)
            listentype = gfx.get_first_listen_type()
            if listentype and listentype == 'none':
                uiutil.set_list_selection(self.widget("graphics-listen-type"), 'none')
            else:
                uiutil.set_list_selection(self.widget("graphics-listen-type"), 'address')
                uiutil.set_list_selection(
                    self.widget("graphics-address"), gfx.listen)
            uiutil.set_list_selection(
                self.widget("graphics-keymap"), gfx.keymap or None)

            self.widget("graphics-password").set_text(gfx.passwd or "")
            self.widget("graphics-password-chk").set_active(use_passwd)
            self.widget("graphics-password").set_sensitive(use_passwd)

        if is_spice:
            set_port("graphics-tlsport", gfx.tlsPort)

            opengl_warning = ""
            rendernode_warning = ""
            opengl_supported = self.conn.check_support(
                    self.conn.SUPPORT_CONN_SPICE_GL)
            rendernode_supported = self.conn.check_support(
                    self.conn.SUPPORT_CONN_SPICE_RENDERNODE)

            # * If spicegl isn't supported, show a warning icon and
            #     and desensitive everything
            # * If qemu:///system and rendernode isn't supported,
            #     show a warning icon and desensitize everything, since
            #     rendernode support is needed for it to work out of the box.
            # * Otherwise, enable all UI, but show warning icons anyways
            #     for potential config issues

            glval = False
            renderval = None
            glsensitive = False
            if not opengl_supported:
                opengl_warning = (
                    _("Hypervisor/libvirt does not support spice GL"))
            elif not rendernode_supported:
                rendernode_warning = (
                    _("Hypervisor/libvirt does not support manual rendernode"))
                if self.conn.is_qemu_system():
                    opengl_warning = rendernode_warning

            if not opengl_warning:
                glval = bool(gfx.gl)
                glsensitive = True
            if not rendernode_warning:
                renderval = gfx.rendernode or None

            if opengl_warning:
                pass
            elif not [v for v in self.vm.xmlobj.get_devices("video") if
                    (v.model == "virtio" and v.accel3d)]:
                opengl_warning = _("Spice GL requires "
                    "virtio graphics configured with accel3d.")
            elif gfx.get_first_listen_type() not in ["none", "socket"]:
                opengl_warning = _("Graphics listen type does not support "
                    "spice GL.")

            self.widget("graphics-opengl").set_active(glval)
            uiutil.set_list_selection(
                    self.widget("graphics-rendernode"), renderval)

            self.widget("graphics-opengl").set_sensitive(glsensitive)
            self.widget("graphics-opengl-warn").set_tooltip_text(
                    opengl_warning or None)
            self.widget("graphics-opengl-warn").set_visible(
                    bool(opengl_warning))

            self.widget("graphics-rendernode").set_sensitive(
                    rendernode_supported)
            self.widget("graphics-rendernode-warn").set_tooltip_text(
                    rendernode_warning or None)
            self.widget("graphics-rendernode-warn").set_visible(
                    bool(rendernode_warning))

        if is_sdl:
            title = _("Local SDL Window")

            self.widget("graphics-display").set_text(
                gfx.display or _("Unknown"))
            self.widget("graphics-xauth").set_text(
                gfx.xauth or _("Unknown"))

        uiutil.set_list_selection(self.widget("graphics-type"), gtype)
        return title


    #############
    # Listeners #
    #############

    def _show_rows_from_type(self):
        hide_all = ["graphics-xauth", "graphics-display", "graphics-address",
            "graphics-password-box", "graphics-keymap", "graphics-port-box",
            "graphics-tlsport-box", "graphics-opengl-box"]

        gtype = uiutil.get_list_selection(self.widget("graphics-type"))
        listen = uiutil.get_list_selection(self.widget("graphics-listen-type"))

        sdl_rows = ["graphics-xauth", "graphics-display"]
        vnc_rows = ["graphics-password-box", "graphics-keymap"]
        if listen == 'address':
            vnc_rows.extend(["graphics-port-box", "graphics-address"])
        spice_rows = vnc_rows[:]
        if listen == 'address':
            spice_rows.extend(["graphics-tlsport-box"])
        spice_rows.extend(["graphics-opengl-box"])

        rows = []
        if gtype == "sdl":
            rows = sdl_rows
        elif gtype == "vnc":
            rows = vnc_rows
        elif gtype == "spice":
            rows = spice_rows

        for row in hide_all:
            uiutil.set_grid_row_visible(self.widget(row), row in rows)

    def _change_graphics_type(self, ignore):
        self._show_rows_from_type()
        self.emit("changed-type")

    def _change_graphics_listen(self, ignore):
        self._show_rows_from_type()
        self.emit("changed-listen")

    def _change_opengl(self, ignore):
        uiutil.set_grid_row_visible(
                self.widget("graphics-rendernode-box"),
                self.widget("graphics-opengl").get_active())
        self.emit("changed-opengl")

    def _change_port_auto(self, ignore):
        self.widget("graphics-port-auto").set_inconsistent(False)
        self._change_ports()
        self.emit("changed-port")

    def _change_tlsport_auto(self, ignore):
        self.widget("graphics-tlsport-auto").set_inconsistent(False)
        self._change_ports()
        self.emit("changed-tlsport")

    def _change_ports(self):
        is_auto = (self.widget("graphics-port-auto").get_active() or
            self.widget("graphics-port-auto").get_inconsistent())
        is_tlsauto = (self.widget("graphics-tlsport-auto").get_active() or
            self.widget("graphics-tlsport-auto").get_inconsistent())

        self.widget("graphics-port").set_visible(not is_auto)
        self.widget("graphics-tlsport").set_visible(not is_tlsauto)

    def _change_password_chk(self, ignore=None):
        if self.widget("graphics-password-chk").get_active():
            self.widget("graphics-password").set_sensitive(True)
        else:
            self.widget("graphics-password").set_text("")
            self.widget("graphics-password").set_sensitive(False)
        self.emit("changed-password")
