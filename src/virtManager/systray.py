#
# Copyright (C) 2009 Red Hat, Inc.
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

import logging

import gtk

from virtManager.baseclass import vmmGObject
from virtManager.error import vmmErrorDialog

try:
    import appindicator
except:
    appindicator = None

def build_image_menu_item(label):
    hasfunc = hasattr(gtk.ImageMenuItem, "set_use_underline")
    if hasfunc:
        label.replace("_", "__")

    menu_item = gtk.ImageMenuItem(label)
    if hasfunc:
        menu_item.set_use_underline(False)

    return menu_item

class vmmSystray(vmmGObject):
    def __init__(self, engine):
        vmmGObject.__init__(self)

        self.topwin = None
        self.err = vmmErrorDialog()

        self.conn_menuitems = {}
        self.conn_vm_menuitems = {}
        self.vm_action_dict = {}
        self.systray_menu = None
        self.systray_icon = None
        self.systray_indicator = False

        engine.connect("conn-added", self.conn_added)
        engine.connect("conn-removed", self.conn_removed)

        # Are we using Application Indicators?
        if appindicator is not None:
            self.systray_indicator = True

        self.init_systray_menu()

        self.add_gconf_handle(
            self.config.on_view_system_tray_changed(self.show_systray))

        self.show_systray()

    def is_visible(self):
        if self.systray_indicator:
            return (self.config.get_view_system_tray() and
                    self.systray_icon)
        else:
            return (self.config.get_view_system_tray() and
                    self.systray_icon and
                    self.systray_icon.is_embedded())

    def _cleanup(self):
        self.err = None

        if self.systray_menu:
            self.systray_menu.destroy()
            self.systray_menu = None

        self.systray_icon = None

    # Initialization routines

    def init_systray_menu(self):
        """
        Do we want notifications?

        Close App
        Hide app? As in, only have systray active? is that possible?
            Have one of those 'minimize to tray' notifications?

        """
        self.systray_menu = gtk.Menu()

        self.systray_menu.add(gtk.SeparatorMenuItem())

        if self.systray_indicator:
            hide_item = gtk.MenuItem("_Show Virtual Machine Manager")
            hide_item.connect("activate", self.systray_activate)
            self.systray_menu.add(hide_item)

        exit_item = gtk.ImageMenuItem(gtk.STOCK_QUIT)
        exit_item.connect("activate", self.exit_app)
        self.systray_menu.add(exit_item)
        self.systray_menu.show_all()

    def init_systray(self):
        # Build the systray icon
        if self.systray_icon:
            return

        if self.systray_indicator:
            self.systray_icon = appindicator.Indicator("virt-manager",
                                "virt-manager-icon",
                                appindicator.CATEGORY_OTHER)
            self.systray_icon.set_status(appindicator.STATUS_ACTIVE)
            self.systray_icon.set_menu(self.systray_menu)

        else:
            self.systray_icon = gtk.StatusIcon()
            self.systray_icon.set_visible(True)
            self.systray_icon.set_property("icon-name", "virt-manager")
            self.systray_icon.connect("activate", self.systray_activate)
            self.systray_icon.connect("popup-menu", self.systray_popup)
            self.systray_icon.set_tooltip(_("Virtual Machine Manager"))

    def show_systray(self, ignore1=None, ignore2=None, ignore3=None,
                     ignore4=None):
        do_show = self.config.get_view_system_tray()
        logging.debug("Showing systray: %s", do_show)

        if not self.systray_icon:
            if do_show:
                self.init_systray()
        else:
            if self.systray_indicator:
                if do_show:
                    self.systray_icon.set_status(appindicator.STATUS_ACTIVE)
                else:
                    self.systray_icon.set_status(appindicator.STATUS_PASSIVE)
            else:
                self.systray_icon.set_visible(do_show)

    def build_vm_menu(self, vm):
        icon_size = gtk.ICON_SIZE_MENU
        stop_icon = self.config.get_shutdown_icon_name()

        pause_item = gtk.ImageMenuItem(_("_Pause"))
        pause_img  = gtk.image_new_from_stock(gtk.STOCK_MEDIA_PAUSE, icon_size)
        pause_item.set_image(pause_img)
        pause_item.connect("activate", self.run_vm_action,
                           "action-suspend-domain", vm.get_uuid())

        resume_item = gtk.ImageMenuItem(_("_Resume"))
        resume_img  = gtk.image_new_from_stock(gtk.STOCK_MEDIA_PAUSE,
                                               icon_size)
        resume_item.set_image(resume_img)
        resume_item.connect("activate", self.run_vm_action,
                            "action-resume-domain", vm.get_uuid())

        run_item = gtk.ImageMenuItem(_("_Run"))
        run_img  = gtk.image_new_from_stock(gtk.STOCK_MEDIA_PLAY, icon_size)
        run_item.set_image(run_img)
        run_item.connect("activate", self.run_vm_action,
                         "action-run-domain", vm.get_uuid())

        # Shutdown menu
        reboot_item = gtk.ImageMenuItem(_("_Reboot"))
        reboot_img = gtk.image_new_from_icon_name(stop_icon, icon_size)
        reboot_item.set_image(reboot_img)
        reboot_item.connect("activate", self.run_vm_action,
                            "action-reboot-domain", vm.get_uuid())
        reboot_item.show()

        shutdown_item = gtk.ImageMenuItem(_("_Shut Down"))
        shutdown_img = gtk.image_new_from_icon_name(stop_icon, icon_size)
        shutdown_item.set_image(shutdown_img)
        shutdown_item.connect("activate", self.run_vm_action,
                              "action-shutdown-domain", vm.get_uuid())
        shutdown_item.show()

        destroy_item = gtk.ImageMenuItem(_("_Force Off"))
        destroy_img = gtk.image_new_from_icon_name(stop_icon, icon_size)
        destroy_item.set_image(destroy_img)
        destroy_item.show()
        destroy_item.connect("activate", self.run_vm_action,
                             "action-destroy-domain", vm.get_uuid())

        shutdown_menu = gtk.Menu()
        shutdown_menu.add(reboot_item)
        shutdown_menu.add(shutdown_item)
        shutdown_menu.add(destroy_item)
        shutdown_menu_item = gtk.ImageMenuItem(_("_Shut Down"))
        shutdown_menu_img = gtk.image_new_from_icon_name(stop_icon, icon_size)
        shutdown_menu_item.set_image(shutdown_menu_img)
        shutdown_menu_item.set_submenu(shutdown_menu)

        sep = gtk.SeparatorMenuItem()

        open_item = gtk.ImageMenuItem("gtk-open")
        open_item.show()
        open_item.connect("activate", self.run_vm_action,
                          "action-show-vm", vm.get_uuid())

        vm_action_dict = {}
        vm_action_dict["run"] = run_item
        vm_action_dict["pause"] = pause_item
        vm_action_dict["resume"] = resume_item
        vm_action_dict["shutdown_menu"] = shutdown_menu_item
        vm_action_dict["reboot"] = reboot_item
        vm_action_dict["shutdown"] = shutdown_item
        vm_action_dict["destroy"] = destroy_item
        vm_action_dict["sep"] = sep
        vm_action_dict["open"] = open_item

        menu = gtk.Menu()

        for key in ["run", "pause", "resume", "shutdown_menu", "sep", "open"]:
            item = vm_action_dict[key]
            item.show_all()
            menu.add(vm_action_dict[key])

        return menu, vm_action_dict

    # Helper functions
    def _get_vm_menu_item(self, vm):
        uuid = vm.get_uuid()
        uri = vm.conn.get_uri()

        if uri in self.conn_vm_menuitems:
            if uuid in self.conn_vm_menuitems[uri]:
                return self.conn_vm_menuitems[uri][uuid]
        return None

    def _set_vm_status_icon(self, vm, menu_item):
        image = gtk.Image()
        image.set_from_icon_name(vm.run_status_icon_name(),
                                 gtk.ICON_SIZE_MENU)
        image.set_sensitive(vm.is_active())
        menu_item.set_image(image)

    # Listeners

    def systray_activate(self, widget_ignore):
        self.emit("action-toggle-manager")

    def systray_popup(self, widget_ignore, button, event_time):
        if button != 3:
            return

        self.systray_menu.popup(None, None, gtk.status_icon_position_menu,
                                0, event_time, self.systray_icon)

    def repopulate_menu_list(self):
        # Build sorted connection list
        connsort = self.conn_menuitems.keys()
        connsort.sort()
        connsort.reverse()

        # Empty conn list
        for child in self.systray_menu.get_children():
            if child in self.conn_menuitems.values():
                self.systray_menu.remove(child)

        # Build sorted conn list
        for uri in connsort:
            self.systray_menu.insert(self.conn_menuitems[uri], 0)


    def conn_added(self, engine_ignore, conn):
        conn.connect("vm-added", self.vm_added)
        conn.connect("vm-removed", self.vm_removed)
        conn.connect("state-changed", self.conn_state_changed)

        if conn.get_uri() in self.conn_menuitems:
            return

        menu_item = gtk.MenuItem(conn.get_pretty_desc_inactive(), False)
        menu_item.show()
        vm_submenu = gtk.Menu()
        vm_submenu.show()
        menu_item.set_submenu(vm_submenu)

        self.conn_menuitems[conn.get_uri()] = menu_item
        self.conn_vm_menuitems[conn.get_uri()] = {}

        self.repopulate_menu_list()

        self.conn_state_changed(conn)
        self.populate_vm_list(conn)

    def conn_removed(self, engine_ignore, uri):
        if not uri in self.conn_menuitems:
            return

        menu_item = self.conn_menuitems[uri]
        self.systray_menu.remove(menu_item)
        menu_item.destroy()
        del(self.conn_menuitems[uri])
        self.conn_vm_menuitems[uri] = {}

        self.repopulate_menu_list()

    def conn_state_changed(self, conn):
        # XXX: Even 'paused' conn?
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
        for vm in conn.vms.values():
            vm_mappings[vm.get_name()] = vm.get_uuid()

        vm_names = vm_mappings.keys()
        vm_names.sort()

        if len(vm_names) == 0:
            menu_item = gtk.MenuItem(_("No virtual machines"))
            menu_item.set_sensitive(False)
            vm_submenu.insert(menu_item, 0)
            return

        for i in range(0, len(vm_names)):
            name = vm_names[i]
            uuid = vm_mappings[name]
            if uuid in self.conn_vm_menuitems[uri]:
                vm_item = self.conn_vm_menuitems[uri][uuid]
                vm_submenu.insert(vm_item, i)

    def vm_added(self, conn, uuid):
        uri = conn.get_uri()
        vm = conn.get_vm(uuid)
        if not vm:
            return
        vm.connect("status-changed", self.vm_state_changed)

        vm_mappings = self.conn_vm_menuitems[uri]
        if uuid in vm_mappings:
            return

        # Build VM list entry
        menu_item = build_image_menu_item(vm.get_name())
        vm_mappings[uuid] = menu_item
        vm_action_menu, vm_action_dict = self.build_vm_menu(vm)
        menu_item.set_submenu(vm_action_menu)
        self.vm_action_dict[uuid] = vm_action_dict

        # Add VM to menu list
        self.populate_vm_list(conn)

        # Update state
        self.vm_state_changed(vm)
        menu_item.show()

    def vm_removed(self, conn, uuid):
        uri = conn.get_uri()
        vm_mappings = self.conn_vm_menuitems[uri]
        if not vm_mappings:
            return

        if uuid in vm_mappings:
            conn_item = self.conn_menuitems[uri]
            vm_menu_item = vm_mappings[uuid]
            vm_menu = conn_item.get_submenu()
            vm_menu.remove(vm_menu_item)
            vm_menu_item.destroy()
            del(vm_mappings[uuid])

            if len(vm_menu.get_children()) == 0:
                placeholder = gtk.MenuItem(_("No virtual machines"))
                placeholder.show()
                placeholder.set_sensitive(False)
                vm_menu.add(placeholder)

    def vm_state_changed(self, vm, ignore=None, ignore2=None):
        menu_item = self._get_vm_menu_item(vm)
        if not menu_item:
            return

        self._set_vm_status_icon(vm, menu_item)

        # Update action widget states
        actions = self.vm_action_dict[vm.get_uuid()]

        is_paused = vm.is_paused()
        actions["run"].set_sensitive(vm.is_runable())
        actions["pause"].set_sensitive(vm.is_pauseable())
        actions["resume"].set_sensitive(vm.is_paused())
        actions["shutdown_menu"].set_sensitive(vm.is_active())
        actions["shutdown"].set_sensitive(vm.is_stoppable())
        actions["reboot"].set_sensitive(vm.is_stoppable())
        actions["destroy"].set_sensitive(vm.is_destroyable())

        actions["pause"].set_property("visible", not is_paused)
        actions["resume"].set_property("visible", is_paused)

    def run_vm_action(self, ignore, signal_name, uuid):
        uri = None
        for tmpuri, vm_mappings in self.conn_vm_menuitems.items():
            if vm_mappings.get(uuid):
                uri = tmpuri
                break

        if not uri:
            return

        self.emit(signal_name, uri, uuid)

    def exit_app(self, ignore):
        self.emit("action-exit-app")

vmmGObject.type_register(vmmSystray)
vmmSystray.signal_new(vmmSystray, "action-toggle-manager", [])
vmmSystray.signal_new(vmmSystray, "action-view-manager", [])
vmmSystray.signal_new(vmmSystray, "action-suspend-domain", [str, str])
vmmSystray.signal_new(vmmSystray, "action-resume-domain", [str, str])
vmmSystray.signal_new(vmmSystray, "action-run-domain", [str, str])
vmmSystray.signal_new(vmmSystray, "action-shutdown-domain", [str, str])
vmmSystray.signal_new(vmmSystray, "action-reboot-domain", [str, str])
vmmSystray.signal_new(vmmSystray, "action-destroy-domain", [str, str])
vmmSystray.signal_new(vmmSystray, "action-show-host", [str])
vmmSystray.signal_new(vmmSystray, "action-show-vm", [str, str])
vmmSystray.signal_new(vmmSystray, "action-exit-app", [])
