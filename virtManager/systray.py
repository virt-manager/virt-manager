# Copyright (C) 2009, 2013 Red Hat, Inc.
# Copyright (C) 2009 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

from gi.repository import Gio
from gi.repository import Gtk

from virtinst import util

from . import vmmenu
from .baseclass import vmmGObject
from .connmanager import vmmConnectionManager

try:
    # pylint: disable=ungrouped-imports
    from gi.repository import AppIndicator3
except Exception:
    AppIndicator3 = None


def _toggle_manager(*args, **kwargs):
    ignore = args
    ignore = kwargs
    from .manager import vmmManager
    manager = vmmManager.get_instance(None)
    if manager.is_visible():
        manager.close()
    else:
        manager.show()


def _conn_connect_cb(src, uri):
    connmanager = vmmConnectionManager.get_instance()
    conn = connmanager.conns[uri]
    if conn.is_disconnected():
        conn.open()


def _conn_disconnect_cb(src, uri):
    connmanager = vmmConnectionManager.get_instance()
    conn = connmanager.conns[uri]
    if not conn.is_disconnected():
        conn.close()


def _has_appindicator_dbus():
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        dbus = Gio.DBusProxy.new_sync(bus, 0, None,
                "org.freedesktop.DBus",
                "/org/freedesktop/DBus",
                "org.freedesktop.DBus", None)
        if dbus.NameHasOwner("(s)", "org.kde.StatusNotifierWatcher"):
            return True
        if dbus.NameHasOwner("(s)", "org.freedesktop.StatusNotifierWatcher"):
            return True
        return False
    except Exception:
        logging.exception("Error checking for appindicator dbus")
        return False


###########################
# systray backend classes #
###########################

class _Systray(object):
    def is_embedded(self):
        raise NotImplementedError()
    def show(self):
        raise NotImplementedError()
    def hide(self):
        raise NotImplementedError()
    def set_menu(self, menu):
        raise NotImplementedError()


class _SystrayIndicator(_Systray):
    def __init__(self):
        self._icon = AppIndicator3.Indicator.new(
                "virt-manager", "virt-manager",
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS)

    def set_menu(self, menu):
        hide_item = Gtk.MenuItem.new_with_mnemonic(
                _("_Show Virtual Machine Manager"))
        hide_item.connect("activate", _toggle_manager)
        hide_item.show()
        menu.insert(hide_item, len(menu.get_children()) - 1)

        self._icon.set_menu(menu)
        self._icon.set_secondary_activate_target(hide_item)

    def is_embedded(self):
        if not self._icon.get_property("connected"):
            return False
        return (self._icon.get_status() !=
                AppIndicator3.IndicatorStatus.PASSIVE)

    def show(self):
        self._icon.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
    def hide(self):
        self._icon.set_status(AppIndicator3.IndicatorStatus.PASSIVE)


class _SystrayStatusIcon(_Systray):
    def __init__(self):
        self._icon = Gtk.StatusIcon()
        self._icon.set_property("icon-name", "virt-manager")
        self._icon.connect("activate", _toggle_manager)
        self._icon.connect("popup-menu", self._popup_cb)
        self._icon.set_tooltip_text(_("Virtual Machine Manager"))
        self._menu = None

    def is_embedded(self):
        return self._icon.is_embedded()

    def set_menu(self, menu):
        self._menu = menu

    def _popup_cb(self, src, button, event_time):
        if button != 3:
            return

        self._menu.popup(None, None,
                Gtk.StatusIcon.position_menu,
                self._icon, 0, event_time)

    def show(self):
        self._icon.set_visible(True)
    def hide(self):
        self._icon.set_visible(False)


class vmmSystray(vmmGObject):
    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = vmmSystray()
        return cls._instance

    def __init__(self):
        vmmGObject.__init__(self)
        self._cleanup_on_app_close()
        self.topwin = None  # Need this for error callbacks from VMActionMenu

        self._systray = None
        self._using_appindicator = False

        if AppIndicator3:
            if not _has_appindicator_dbus():
                logging.debug("AppIndicator3 is available, but didn't "
                              "find any dbus watcher.")
            else:
                self._using_appindicator = True
                logging.debug("Using AppIndicator3 for systray")

        connmanager = vmmConnectionManager.get_instance()
        connmanager.connect("conn-added", self._conn_added_cb)
        connmanager.connect("conn-removed", self._rebuild_menu)
        for conn in connmanager.conns.values():
            self._conn_added_cb(connmanager, conn)

        self.add_gsettings_handle(
            self.config.on_view_system_tray_changed(
                self._show_systray_changed_cb))
        self._startup()


    def is_embedded(self):
        return self._systray and self._systray.is_embedded()

    def _cleanup(self):
        self._hide_systray()
        self._systray = None


    ###########################
    # Initialization routines #
    ###########################

    def _show_systray(self):
        if not self._systray:
            if self._using_appindicator:
                self._systray = _SystrayIndicator()
            else:
                self._systray = _SystrayStatusIcon()
        self._rebuild_menu(force=True)
        self._systray.show()

    def _hide_systray(self):
        if not self._systray:
            return
        self._systray.hide()

    def _show_systray_changed_cb(self):
        do_show = self.config.get_view_system_tray()
        logging.debug("Showing systray: %s", do_show)

        if do_show:
            self._show_systray()
        else:
            self._hide_systray()

    def _startup(self):
        # This will trigger the actual UI showing
        self._show_systray_changed_cb()


    #################
    # Menu building #
    #################

    def _build_vm_menuitem(self, vm):
        menu_item = Gtk.ImageMenuItem.new_with_label(vm.get_name_or_title())
        menu_item.set_use_underline(False)
        vm_action_menu = vmmenu.VMActionMenu(self, lambda: vm)
        vm_action_menu.update_widget_states(vm)
        menu_item.set_submenu(vm_action_menu)
        return menu_item

    def _build_conn_menuitem(self, conn):
        menu_item = Gtk.MenuItem.new_with_label(conn.get_pretty_desc())
        if conn.is_active():
            label = menu_item.get_child()
            markup = "<b>%s</b>" % util.xml_escape(conn.get_pretty_desc())
            label.set_markup(markup)

        menu = Gtk.Menu()
        vms = conn.list_vms()
        vms.sort(key=lambda v: v.get_name_or_title())

        for vm in vms:
            menu.add(self._build_vm_menuitem(vm))
        if not vms:
            vmitem = Gtk.MenuItem.new_with_label(_("No virtual machines"))
            vmitem.set_sensitive(False)
            menu.add(vmitem)

        menu.add(Gtk.SeparatorMenuItem())
        if conn.is_active():
            citem = Gtk.ImageMenuItem.new_from_stock(
                    Gtk.STOCK_DISCONNECT, None)
            citem.connect("activate", _conn_disconnect_cb, conn.get_uri())
        else:
            citem = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_CONNECT, None)
            citem.connect("activate", _conn_connect_cb, conn.get_uri())
        menu.add(citem)

        menu_item.set_submenu(menu)
        return menu_item

    def _build_menu(self):
        connmanager = vmmConnectionManager.get_instance()
        conns = list(connmanager.conns.values())
        menu = Gtk.Menu()

        conns.sort(key=lambda c: c.get_pretty_desc().lower())
        conns.sort(key=lambda c: not c.is_active())

        for conn in conns:
            connmenu = self._build_conn_menuitem(conn)
            menu.add(connmenu)

        menu.add(Gtk.SeparatorMenuItem())

        exit_item = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_QUIT, None)
        exit_item.connect("activate", self._exit_app_cb)
        menu.add(exit_item)
        menu.show_all()
        return menu

    def _rebuild_menu(self, *args, **kwargs):
        ignore = args
        ignore = kwargs
        if "force" not in kwargs and not self.is_embedded():
            return
        if vmmConnectionManager.get_instance() is True:
            # In app cleanup, don't do anything
            return

        # Yeah, this is kinda nutty, we rebuild the whole menu widget
        # on any conn or VM state change. We kinda need to do this
        # for appindicator, because we communicate with the remote
        # UI via changing the menu widget, unlike statusicon which
        # we could delay until 'show' time. This is likely slow as
        # dirt for a virt-manager instance with a lot of connections
        # and VMs...
        menu = self._build_menu()
        self._systray.set_menu(menu)

    def _conn_added_cb(self, src, conn):
        conn.connect("vm-added", self._vm_added_cb)
        conn.connect("vm-removed", self._rebuild_menu)
        conn.connect("state-changed", self._rebuild_menu)
        self._rebuild_menu()

    def _vm_added_cb(self, conn, connkey):
        vm = conn.get_vm(connkey)
        vm.connect("state-changed", self._rebuild_menu)
        self._rebuild_menu()

    def _exit_app_cb(self, src):
        from .engine import vmmEngine
        vmmEngine.get_instance().exit_app()
