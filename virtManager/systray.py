# Copyright (C) 2009, 2013 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

from gi.repository import Gtk

from . import vmmenu
from .baseclass import vmmGObject
from .connmanager import vmmConnectionManager


class vmmSystray(vmmGObject):
    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = vmmSystray()
        return cls._instance

    def __init__(self):
        vmmGObject.__init__(self)
        self._cleanup_on_app_close()

        self.topwin = None

        self.conn_menuitems = {}
        self.conn_vm_menuitems = {}
        self.vm_action_dict = {}

        self.systray_menu = None
        self.systray_icon = None
        self._init_ui()

        self.add_gsettings_handle(
            self.config.on_view_system_tray_changed(
                self._show_systray_changed_cb))
        self._show_systray_changed_cb()

        connmanager = vmmConnectionManager.get_instance()
        connmanager.connect("conn-added", self._conn_added)
        connmanager.connect("conn-removed", self._conn_removed)
        for conn in connmanager.conns.values():
            self._conn_added(connmanager, conn)

    def is_embedded(self):
        return (self.systray_icon and
                self.systray_icon.is_embedded())

    def _cleanup(self):
        if self.systray_menu:
            self.systray_menu.destroy()
            self.systray_menu = None

        self._hide()
        self.conn_menuitems = None
        self.conn_vm_menuitems = None
        self.vm_action_dict = None


    ###########################
    # Initialization routines #
    ###########################

    def _init_ui(self):
        self.systray_menu = Gtk.Menu()
        self.systray_menu.add(Gtk.SeparatorMenuItem())

        exit_item = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_QUIT, None)
        exit_item.connect("activate", self.exit_app)
        self.systray_menu.add(exit_item)
        self.systray_menu.show_all()

    def _show(self):
        if self.systray_icon:
            return
        self.systray_icon = Gtk.StatusIcon()
        self.systray_icon.set_visible(True)
        self.systray_icon.set_property("icon-name", "virt-manager")
        self.systray_icon.connect("activate", self.systray_activate)
        self.systray_icon.connect("popup-menu", self.systray_popup)
        self.systray_icon.set_tooltip_text(_("Virtual Machine Manager"))

    def _hide(self):
        if not self.systray_icon:
            return
        self.systray_icon.set_visible(False)
        self.systray_icon = None

    def _show_systray_changed_cb(self):
        do_show = self.config.get_view_system_tray()
        logging.debug("Showing systray: %s", do_show)

        if do_show:
            self._show()
        else:
            self._hide()

    # Helper functions
    def _get_vm_menu_item(self, vm):
        connkey = vm.get_connkey()
        uri = vm.conn.get_uri()

        if uri in self.conn_vm_menuitems:
            if connkey in self.conn_vm_menuitems[uri]:
                return self.conn_vm_menuitems[uri][connkey]
        return None

    def _set_vm_status_icon(self, vm, menu_item):
        image = Gtk.Image()
        image.set_from_icon_name(vm.run_status_icon_name(),
                                 Gtk.IconSize.MENU)
        image.set_sensitive(vm.is_active())
        menu_item.set_image(image)

    # Listeners

    def systray_activate(self, _src):
        from .manager import vmmManager
        manager = vmmManager.get_instance(self)
        if manager.is_visible():
            manager.close()
        else:
            manager.show()

    def systray_popup(self, widget_ignore, button, event_time):
        if button != 3:
            return

        self.systray_menu.popup(None, None, Gtk.StatusIcon.position_menu,
                                self.systray_icon, 0, event_time)

    def repopulate_menu_list(self):
        # Build sorted connection list
        connsort = list(self.conn_menuitems.keys())
        connsort.sort()
        connsort.reverse()

        # Empty conn list
        for child in self.systray_menu.get_children():
            if child in list(self.conn_menuitems.values()):
                self.systray_menu.remove(child)

        # Build sorted conn list
        for uri in connsort:
            self.systray_menu.insert(self.conn_menuitems[uri], 0)


    def _conn_added(self, _engine, conn):
        conn.connect("vm-added", self.vm_added)
        conn.connect("vm-removed", self.vm_removed)
        conn.connect("state-changed", self.conn_state_changed)

        if conn.get_uri() in self.conn_menuitems:
            return

        menu_item = Gtk.MenuItem.new_with_label(conn.get_pretty_desc())
        menu_item.show()
        vm_submenu = Gtk.Menu()
        vm_submenu.show()
        menu_item.set_submenu(vm_submenu)

        self.conn_menuitems[conn.get_uri()] = menu_item
        self.conn_vm_menuitems[conn.get_uri()] = {}

        self.repopulate_menu_list()

        self.conn_state_changed(conn)
        self.populate_vm_list(conn)

    def _conn_removed(self, _engine, uri):
        if uri not in self.conn_menuitems:
            return

        menu_item = self.conn_menuitems[uri]
        self.systray_menu.remove(menu_item)
        menu_item.destroy()
        del(self.conn_menuitems[uri])
        self.conn_vm_menuitems[uri] = {}

        self.repopulate_menu_list()

    def conn_state_changed(self, conn):
        sensitive = conn.is_active()
        menu_item = self.conn_menuitems[conn.get_uri()]
        menu_item.set_sensitive(sensitive)

    def populate_vm_list(self, conn):
        uri = conn.get_uri()
        conn_menu_item = self.conn_menuitems[uri]
        vm_submenu = conn_menu_item.get_submenu()

        # Empty conn menu
        for c in vm_submenu.get_children():
            vm_submenu.remove(c)

        vm_mappings = {}
        for vm in conn.list_vms():
            vm_mappings[vm.get_name()] = vm.get_connkey()

        vm_names = list(vm_mappings.keys())
        vm_names.sort()

        if len(vm_names) == 0:
            menu_item = Gtk.MenuItem.new_with_label(_("No virtual machines"))
            menu_item.set_sensitive(False)
            vm_submenu.insert(menu_item, 0)
            return

        for i, name in enumerate(vm_names):
            connkey = vm_mappings[name]
            if connkey in self.conn_vm_menuitems[uri]:
                vm_item = self.conn_vm_menuitems[uri][connkey]
                vm_submenu.insert(vm_item, i)

    def vm_added(self, conn, connkey):
        uri = conn.get_uri()
        vm = conn.get_vm(connkey)
        if not vm:
            return
        vm.connect("state-changed", self.vm_state_changed)

        vm_mappings = self.conn_vm_menuitems[uri]
        if connkey in vm_mappings:
            return

        # Build VM list entry
        menu_item = Gtk.ImageMenuItem.new_with_label(vm.get_name())
        menu_item.set_use_underline(False)

        vm_mappings[connkey] = menu_item
        vm_action_menu = vmmenu.VMActionMenu(self, lambda: vm)
        menu_item.set_submenu(vm_action_menu)
        self.vm_action_dict[connkey] = vm_action_menu

        # Add VM to menu list
        self.populate_vm_list(conn)

        # Update state
        self.vm_state_changed(vm)
        menu_item.show()

    def vm_removed(self, conn, connkey):
        uri = conn.get_uri()
        vm_mappings = self.conn_vm_menuitems[uri]
        if not vm_mappings:
            return

        if connkey not in vm_mappings:
            return

        conn_item = self.conn_menuitems[uri]
        vm_menu_item = vm_mappings[connkey]
        vm_menu = conn_item.get_submenu()
        vm_menu.remove(vm_menu_item)
        vm_menu_item.destroy()
        vm_mappings.pop(connkey)
        self.vm_action_dict.pop(connkey)

        if len(vm_menu.get_children()) == 0:
            placeholder = Gtk.MenuItem.new_with_label(
                _("No virtual machines"))
            placeholder.show()
            placeholder.set_sensitive(False)
            vm_menu.add(placeholder)

    def vm_state_changed(self, vm):
        menu_item = self._get_vm_menu_item(vm)
        if not menu_item:
            return

        self._set_vm_status_icon(vm, menu_item)

        # Update action widget states
        menu = self.vm_action_dict[vm.get_connkey()]
        menu.update_widget_states(vm)

    def exit_app(self, _src):
        from .engine import vmmEngine
        vmmEngine.get_instance().exit_app()
