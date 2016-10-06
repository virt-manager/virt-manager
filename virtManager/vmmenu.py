#
# Copyright (C) 2009, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
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


####################################################################
# Build toolbar shutdown button menu (manager and details toolbar) #
####################################################################

class _VMMenu(Gtk.Menu):
    def __init__(self, src, current_vm_cb, show_open=True):
        Gtk.Menu.__init__(self)
        self._parent = src
        self._current_vm_cb = current_vm_cb
        self._show_open = show_open

        self._init_state()

    def _add_action(self, label, signal,
                    iconname="system-shutdown", addcb=True):
        if label.startswith("gtk-"):
            item = Gtk.ImageMenuItem.new_from_stock(label, None)
        else:
            item = Gtk.ImageMenuItem.new_with_mnemonic(label)

        if iconname:
            if iconname.startswith("gtk-"):
                icon = Gtk.Image.new_from_stock(iconname, Gtk.IconSize.MENU)
            else:
                icon = Gtk.Image.new_from_icon_name(iconname,
                                                    Gtk.IconSize.MENU)
            item.set_image(icon)

        item.vmm_widget_name = signal
        if addcb:
            item.connect("activate", self._action_cb)
        self.add(item)
        return item

    def _action_cb(self, src):
        vm = self._current_vm_cb()
        if not vm:
            return
        self._parent.emit("action-%s-domain" % src.vmm_widget_name,
                          vm.conn.get_uri(), vm.get_connkey())

    def _init_state(self):
        raise NotImplementedError()
    def update_widget_states(self, vm):
        raise NotImplementedError()


class VMShutdownMenu(_VMMenu):
    def _init_state(self):
        self._add_action(_("_Reboot"), "reboot")
        self._add_action(_("_Shut Down"), "shutdown")
        self._add_action(_("F_orce Reset"), "reset")
        self._add_action(_("_Force Off"), "destroy")
        self.add(Gtk.SeparatorMenuItem())
        self._add_action(_("Sa_ve"), "save", iconname=Gtk.STOCK_SAVE)

        self.show_all()

    def update_widget_states(self, vm):
        statemap = {
            "reboot": bool(vm and vm.is_stoppable()),
            "shutdown": bool(vm and vm.is_stoppable()),
            "reset": bool(vm and vm.is_stoppable()),
            "save": bool(vm and vm.is_destroyable()),
            "destroy": bool(vm and vm.is_destroyable()),
        }

        for child in self.get_children():
            name = getattr(child, "vmm_widget_name", None)
            if name in statemap:
                child.set_sensitive(statemap[name])

            if name == "reset":
                child.set_tooltip_text(None)
                if vm and not vm.conn.check_support(
                    vm.conn.SUPPORT_CONN_DOMAIN_RESET):
                    child.set_tooltip_text(_("Hypervisor does not support "
                        "domain reset."))
                    child.set_sensitive(False)


class VMActionMenu(_VMMenu):
    def _init_state(self):
        self._add_action(_("_Run"), "run", Gtk.STOCK_MEDIA_PLAY)
        self._add_action(_("_Pause"), "suspend", Gtk.STOCK_MEDIA_PAUSE)
        self._add_action(_("R_esume"), "resume", Gtk.STOCK_MEDIA_PAUSE)
        s = self._add_action(_("_Shut Down"), "shutdown", addcb=False)
        s.set_submenu(VMShutdownMenu(self._parent, self._current_vm_cb))

        self.add(Gtk.SeparatorMenuItem())
        self._add_action(_("Clone..."), "clone", None)
        self._add_action(_("Migrate..."), "migrate", None)
        self._add_action(_("_Delete"), "delete", Gtk.STOCK_DELETE)

        if self._show_open:
            self.add(Gtk.SeparatorMenuItem())
            self._add_action(Gtk.STOCK_OPEN, "show", None)

        self.show_all()

    def update_widget_states(self, vm):
        statemap = {
            "run": bool(vm and vm.is_runable()),
            "shutdown": bool(vm and vm.is_stoppable()),
            "suspend": bool(vm and vm.is_stoppable()),
            "resume": bool(vm and vm.is_paused()),
            "migrate": bool(vm and vm.is_stoppable()),
            "clone": bool(vm and vm.is_clonable()),
        }
        vismap = {
            "suspend": bool(vm and not vm.is_paused()),
            "resume": bool(vm and vm.is_paused()),
        }

        for child in self.get_children():
            name = getattr(child, "vmm_widget_name", None)
            if child.get_submenu():
                child.get_submenu().update_widget_states(vm)
            if name in statemap:
                child.set_sensitive(statemap[name])
            if name in vismap:
                child.set_visible(vismap[name])

    def change_run_text(self, text):
        for child in self.get_children():
            if getattr(child, "vmm_widget_name", None) == "run":
                child.get_child().set_label(text)
