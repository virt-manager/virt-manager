# Copyright (C) 2006-2007, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
# Copyright (C) 2014 SUSE LINUX Products GmbH, Nuernberg, Germany.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk

import virtinst

from ..lib import uiutil
from ..baseclass import vmmGObjectUI


class vmmGraphicsDetails(vmmGObjectUI):
    __gsignals__ = {
        "changed-password": (vmmGObjectUI.RUN_FIRST, None, []),
        "changed-port": (vmmGObjectUI.RUN_FIRST, None, []),
        "changed-type": (vmmGObjectUI.RUN_FIRST, None, []),
        "changed-listen": (vmmGObjectUI.RUN_FIRST, None, []),
        "changed-address": (vmmGObjectUI.RUN_FIRST, None, []),
        "changed-opengl": (vmmGObjectUI.RUN_FIRST, None, []),
        "changed-rendernode": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, "gfxdetails.ui",
                              None, builder=builder, topwin=topwin)
        self.vm = vm
        self.conn = vm.conn

        self.builder.connect_signals({
            "on_graphics_type_changed": self._change_graphics_type,
            "on_graphics_port_auto_toggled": self._change_port_auto,
            "on_graphics_use_password": self._change_password_cb,
            "on_graphics_show_password": self._show_password_cb,

            "on_graphics_listen_type_changed": self._change_graphics_listen,
            "on_graphics_password_changed": lambda ignore: self.emit("changed-password"),
            "on_graphics_address_changed": lambda ignore: self.emit("changed-address"),
            "on_graphics_port_changed": lambda ignore: self.emit("changed-port"),
            "on_graphics_opengl_toggled": self._change_opengl,
            "on_graphics_rendernode_changed": lambda ignore: self.emit("changed-rendernode")
        })

        self._init_ui()
        self.top_box = self.widget("graphics-box")

    def _cleanup(self):
        self.vm = None
        self.conn = None


    #####################
    # Pretty UI helpers #
    #####################

    @staticmethod
    def graphics_pretty_type_simple(gtype):
        if (gtype in [virtinst.DeviceGraphics.TYPE_VNC,
                      virtinst.DeviceGraphics.TYPE_SDL,
                      virtinst.DeviceGraphics.TYPE_RDP]):
            return str(gtype).upper()
        return str(gtype).capitalize()


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

        # Host GPU rendernode
        combo = self.widget("graphics-rendernode")
        model = Gtk.ListStore(str, str)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)
        model.append([None, _("Auto")])
        devs = self.conn.filter_nodedevs("drm")
        for i in devs:
            drm = i.xmlobj
            if drm.is_drm_render():
                rendernode = drm.get_devnode().path
                model.append([rendernode, i.pretty_name()])

    def _get_config_graphics_ports(self):
        port = uiutil.spin_get_helper(self.widget("graphics-port"))
        if self.widget("graphics-port-auto").get_active():
            port = -1
        return port

    ##############
    # UI syncing #
    ##############

    def _sync_ui(self):
        gtype = uiutil.get_list_selection(self.widget("graphics-type"))
        is_vnc = gtype == "vnc"
        is_spice = gtype == "spice"

        listen = uiutil.get_list_selection(self.widget("graphics-listen-type"))
        has_listen_none = (listen in ["none", "socket"])

        has_virtio_3d = bool([
            v for v in self.vm.xmlobj.devices.video if
            (v.model == "virtio" and v.accel3d)])

        uiutil.set_grid_row_visible(
                self.widget("graphics-warn-virtio"),
                not has_virtio_3d)
        uiutil.set_grid_row_visible(
                self.widget("graphics-warn-listen"),
                not has_listen_none)

        passwd_enabled = self.widget("graphics-password-chk").get_active()
        self.widget("graphics-password").set_sensitive(passwd_enabled)
        if not passwd_enabled:
            self.widget("graphics-password").set_text("")
        passwd_visible = self.widget("graphics-visiblity-chk").get_active()
        self.widget("graphics-password").set_visibility(passwd_visible)

        glval = self.widget("graphics-opengl").get_active()
        uiutil.set_grid_row_visible(
                self.widget("graphics-opengl-subopts-box"),
                glval and is_spice)

        all_rows = [
            "graphics-listen-type",
            "graphics-address",
            "graphics-password-box",
            "graphics-port-box",
            "graphics-opengl",
            "graphics-opengl-subopts-box",
        ]

        is_auto = (self.widget("graphics-port-auto").get_active() or
            self.widget("graphics-port-auto").get_inconsistent())
        self.widget("graphics-port").set_visible(not is_auto)

        rows = ["graphics-password-box", "graphics-listen-type"]
        if listen == 'address':
            rows.extend(["graphics-port-box", "graphics-address"])
        if is_spice:
            rows.append("graphics-opengl")
            if glval:
                rows.append("graphics-opengl-subopts-box")

        if not is_vnc and not is_spice:
            rows = []

        for row in all_rows:
            uiutil.set_grid_row_visible(self.widget(row), row in rows)



    ##############
    # Public API #
    ##############

    def reset_state(self):
        self.widget("graphics-type").set_active(0)
        self.widget("graphics-listen-type").set_active(0)
        self.widget("graphics-address").set_active(0)

        # Select last entry in the list, which should be a rendernode path
        rendermodel = self.widget("graphics-rendernode").get_model()
        self.widget("graphics-rendernode").set_active_iter(rendermodel[-1].iter)

        self.widget("graphics-port-auto").set_active(True)
        self.widget("graphics-password").set_text("")
        self.widget("graphics-password").set_sensitive(False)
        self.widget("graphics-password-chk").set_active(False)
        self.widget("graphics-opengl").set_active(False)
        self._sync_ui()

    def get_values(self):
        gtype = uiutil.get_list_selection(self.widget("graphics-type"))
        port = self._get_config_graphics_ports()
        listen = uiutil.get_list_selection(self.widget("graphics-listen-type"))
        addr = uiutil.get_list_selection(self.widget("graphics-address"))

        passwd = self.widget("graphics-password").get_text()
        if not self.widget("graphics-password-chk").get_active():
            passwd = None

        glval = self.widget("graphics-opengl").get_active()
        if not self.widget("graphics-opengl").is_visible():
            glval = None

        rendernode = uiutil.get_list_selection(self.widget("graphics-rendernode"))
        if not self.widget("graphics-rendernode").is_visible():
            rendernode = None

        return gtype, port, listen, addr, passwd, glval, rendernode

    def set_dev(self, gfx):
        self.reset_state()

        portval = gfx.port
        portautolabel = _("A_uto")

        if portval == -1 or gfx.autoport:
            portauto = True
            if portval and portval != -1:  # pragma: no cover
                # Triggering this with the test driver is tough
                # because it doesn't fill in runtime port values
                portautolabel = _("A_uto (Port %(port)d)") % {"port": portval}
        elif portval is None:
            portauto = None
        else:
            portauto = False

        self.widget("graphics-port").set_value(portval or 0)
        self.widget("graphics-port-auto").set_label(portautolabel)
        self.widget("graphics-port-auto").set_active(bool(portauto))
        self.widget("graphics-port-auto").set_inconsistent(portauto is None)

        gtype = gfx.type
        uiutil.set_list_selection(self.widget("graphics-type"), gtype)

        use_passwd = gfx.passwd is not None
        self.widget("graphics-password").set_text(gfx.passwd or "")
        self.widget("graphics-password-chk").set_active(use_passwd)

        listentype = gfx.get_first_listen_type()
        uiutil.set_list_selection(
                self.widget("graphics-listen-type"), listentype)
        uiutil.set_list_selection(
                self.widget("graphics-address"), gfx.listen)

        glval = bool(gfx.gl)
        renderval = gfx.rendernode or None
        self.widget("graphics-opengl").set_active(glval)

        if glval:
            # Only sync rendernode UI with XML, if gl=on, otherwise
            # we want to preserve the suggested rendernode already
            # selected in the UI
            uiutil.set_list_selection(
                   self.widget("graphics-rendernode"), renderval)


    #############
    # Listeners #
    #############

    def _change_graphics_type(self, ignore):
        self._sync_ui()
        self.emit("changed-type")

    def _change_graphics_listen(self, ignore):
        self._sync_ui()
        self.emit("changed-listen")

    def _change_opengl(self, ignore):
        self._sync_ui()
        self.emit("changed-opengl")
        self.emit("changed-rendernode")

    def _change_port_auto(self, ignore):
        self.widget("graphics-port-auto").set_inconsistent(False)
        self._sync_ui()
        self.emit("changed-port")

    def _change_password_cb(self, src):
        self._sync_ui()
        self.emit("changed-password")

    def _show_password_cb(self, src):
        self._sync_ui()
