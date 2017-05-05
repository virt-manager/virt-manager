#
# Copyright (C) 2006-2008, 2015 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
# Copyright (C) 2010 Marc-Andre Lureau <marcandre.lureau@redhat.com>
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

from .baseclass import vmmGObject, vmmGObjectUI
from .details import DETAILS_PAGE_CONSOLE
from .serialcon import vmmSerialConsole
from .sshtunnels import ConnectionInfo
from .viewers import SpiceViewer, VNCViewer, have_spice_gtk


# console-pages IDs
(_CONSOLE_PAGE_UNAVAILABLE,
 _CONSOLE_PAGE_AUTHENTICATE,
 _CONSOLE_PAGE_SERIAL,
 _CONSOLE_PAGE_VIEWER) = range(4)


class _TimedRevealer(vmmGObject):
    """
    Revealer for the fullscreen toolbar, with a bit of extra logic to
    hide/show based on mouse over
    """
    def __init__(self, toolbar):
        vmmGObject.__init__(self)

        self._in_fullscreen = False
        self._timeout_id = None

        self._revealer = Gtk.Revealer()
        self._revealer.add(toolbar)

        # Adding the revealer to the eventbox seems to ensure the
        # eventbox always has 1 invisible pixel showing at the top of the
        # screen, which we can use to grab the pointer event to show
        # the hidden toolbar.

        self._ebox = Gtk.EventBox()
        self._ebox.add(self._revealer)
        self._ebox.set_halign(Gtk.Align.CENTER)
        self._ebox.set_valign(Gtk.Align.START)
        self._ebox.show_all()

        self._ebox.connect("enter-notify-event", self._enter_notify)
        self._ebox.connect("leave-notify-event", self._enter_notify)

    def _cleanup(self):
        self._ebox.destroy()
        self._ebox = None
        self._revealer.destroy()
        self._revealer = None
        self._timeout_id = None

    def _enter_notify(self, ignore1, ignore2):
        x, y = self._ebox.get_pointer()
        alloc = self._ebox.get_allocation()
        entered = bool(x >= 0 and y >= 0 and
                       x < alloc.width and y < alloc.height)

        if not self._in_fullscreen:
            return

        # Pointer exited the toolbar, and toolbar is revealed. Schedule
        # a timeout to close it, if one isn't already scheduled
        if not entered and self._revealer.get_reveal_child():
            self._schedule_unreveal_timeout(1000)
            return

        self._unregister_timeout()
        if entered and not self._revealer.get_reveal_child():
            self._revealer.set_reveal_child(True)

    def _schedule_unreveal_timeout(self, timeout):
        if self._timeout_id:
            return

        def cb():
            self._revealer.set_reveal_child(False)
            self._timeout_id = None
        self._timeout_id = self.timeout_add(timeout, cb)

    def _unregister_timeout(self):
        if self._timeout_id:
            self.remove_gobject_timeout(self._timeout_id)
            self._timeout_id = None

    def force_reveal(self, val):
        self._unregister_timeout()
        self._in_fullscreen = val
        self._revealer.set_reveal_child(val)
        self._schedule_unreveal_timeout(2000)

    def get_overlay_widget(self):
        return self._ebox


class vmmConsolePages(vmmGObjectUI):
    """
    Handles all the complex UI handling dictated by the spice/vnc widgets
    """
    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, None, None, builder=builder, topwin=topwin)

        self.vm = vm
        self._pointer_is_grabbed = False
        self._change_title()
        self.vm.connect("state-changed", self._change_title)

        # State for disabling modifiers when keyboard is grabbed
        self._accel_groups = Gtk.accel_groups_from_object(self.topwin)
        self._gtk_settings_accel = None
        self._gtk_settings_mnemonic = None

        # Initialize display widget
        self._viewer = None

        # Fullscreen toolbar
        self._send_key_button = None
        self._overlay_toolbar = None
        self._timed_revealer = None
        self._keycombo_toolbar = self._build_keycombo_menu()
        self._keycombo_menu = self._build_keycombo_menu()
        self._init_overlay_toolbar()

        # Make viewer widget background always be black
        black = Gdk.Color(0, 0, 0)
        self.widget("console-gfx-viewport").modify_bg(Gtk.StateType.NORMAL,
                                                      black)

        self.widget("console-pages").set_show_tabs(False)
        self.widget("serial-pages").set_show_tabs(False)

        self._serial_consoles = []
        self._init_menus()

        # Signals are added by vmmDetails. Don't use connect_signals here
        # or it changes will be overwritten

        self.widget("console-gfx-scroll").connect("size-allocate",
            self._scroll_size_allocate)

        self._refresh_widget_states()
        self._refresh_scaling_from_settings()

        self.add_gsettings_handle(
            self.vm.on_console_scaling_changed(
                self._refresh_scaling_from_settings))
        self._refresh_resizeguest_from_settings()
        self.add_gsettings_handle(
            self.vm.on_console_resizeguest_changed(
                self._refresh_resizeguest_from_settings))
        self.add_gsettings_handle(
            self.config.on_console_accels_changed(self._refresh_enable_accel))


    def is_visible(self):
        if self.topwin:
            return self.topwin.get_visible()
        else:
            return False

    def _cleanup(self):
        self.vm = None

        if self._viewer:
            self._viewer.cleanup()
        self._viewer = None

        self._keycombo_toolbar.destroy()
        self._keycombo_toolbar = None
        self._overlay_toolbar.destroy()
        self._overlay_toolbar = None

        self._timed_revealer.cleanup()
        self._timed_revealer = None

        for serial in self._serial_consoles:
            serial.cleanup()
        self._serial_consoles = []


    ##########################
    # Initialization helpers #
    ##########################

    def _build_keycombo_menu(self):
        # Shared with vmmDetails
        menu = Gtk.Menu()

        def make_item(name, combo):
            item = Gtk.MenuItem.new_with_mnemonic(name)
            item.connect("activate", self._do_send_key, combo)

            menu.add(item)

        make_item("Ctrl+Alt+_Backspace", ["Control_L", "Alt_L", "BackSpace"])
        make_item("Ctrl+Alt+_Delete", ["Control_L", "Alt_L", "Delete"])
        menu.add(Gtk.SeparatorMenuItem())

        for i in range(1, 13):
            make_item("Ctrl+Alt+F_%d" % i, ["Control_L", "Alt_L", "F%d" % i])
        menu.add(Gtk.SeparatorMenuItem())

        make_item("_Printscreen", ["Print"])

        menu.show_all()
        return menu

    def _init_overlay_toolbar(self):
        self._overlay_toolbar = Gtk.Toolbar()
        self._overlay_toolbar.set_show_arrow(False)
        self._overlay_toolbar.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)

        # Exit fullscreen button
        button = Gtk.ToolButton.new_from_stock(Gtk.STOCK_LEAVE_FULLSCREEN)
        button.set_tooltip_text(_("Leave fullscreen"))
        button.show()
        self._overlay_toolbar.add(button)
        button.connect("clicked", self._leave_fullscreen)

        def keycombo_menu_clicked(src):
            ignore = src
            def menu_location(*args):
                # Signature changed at some point.
                #  f23+    : args = menu, x, y, toolbar
                #  rhel7.3 : args = menu, toolbar
                if len(args) == 4:
                    toolbar = args[3]
                else:
                    toolbar = args[1]

                ignore, x, y = toolbar.get_window().get_origin()
                height = toolbar.get_window().get_height()
                return x, y + height, True

            self._keycombo_toolbar.popup(None, None, menu_location,
                                     self._overlay_toolbar, 0,
                                     Gtk.get_current_event_time())

        self._send_key_button = Gtk.ToolButton()
        self._send_key_button.set_icon_name(
                                "preferences-desktop-keyboard-shortcuts")
        self._send_key_button.set_tooltip_text(_("Send key combination"))
        self._send_key_button.show_all()
        self._send_key_button.connect("clicked", keycombo_menu_clicked)
        self._overlay_toolbar.add(self._send_key_button)

        self._timed_revealer = _TimedRevealer(self._overlay_toolbar)
        self.widget("console-overlay").add_overlay(
                self._timed_revealer.get_overlay_widget())

    def _init_menus(self):
        # Serial list menu
        smenu = Gtk.Menu()
        smenu.connect("show", self._populate_serial_menu)
        self.widget("details-menu-view-serial-list").set_submenu(smenu)

        # Keycombo menu (ctrl+alt+del etc.)
        self.widget("details-menu-send-key").set_submenu(self._keycombo_menu)


    #################
    # Internal APIs #
    #################

    def _change_title(self, ignore1=None):
        title = (_("%(vm-name)s on %(connection-name)s") % {
            "vm-name": self.vm.get_name_or_title(),
            "connection-name": self.vm.conn.get_pretty_desc(),
        })

        if self._pointer_is_grabbed and self._viewer:
            keystr = self._viewer.console_get_grab_keys()
            keymsg = _("Press %s to release pointer.") % keystr

            title = keymsg + " " + title

        self.topwin.set_title(title)

    def _someone_has_focus(self):
        if (self._viewer and
            self._viewer.console_has_focus() and
            self._viewer.console_is_open()):
            return True

        for serial in self._serial_consoles:
            if (serial.terminal and
                serial.terminal.get_property("has-focus")):
                return True

    def _disable_modifiers(self):
        if self._gtk_settings_accel is not None:
            return

        for g in self._accel_groups:
            self.topwin.remove_accel_group(g)

        settings = Gtk.Settings.get_default()
        self._gtk_settings_accel = settings.get_property('gtk-menu-bar-accel')
        settings.set_property('gtk-menu-bar-accel', None)

        self._gtk_settings_mnemonic = settings.get_property(
            "gtk-enable-mnemonics")
        settings.set_property("gtk-enable-mnemonics", False)

    def _enable_modifiers(self):
        if self._gtk_settings_accel is None:
            return

        settings = Gtk.Settings.get_default()
        settings.set_property('gtk-menu-bar-accel', self._gtk_settings_accel)
        self._gtk_settings_accel = None

        if self._gtk_settings_mnemonic is not None:
            settings.set_property("gtk-enable-mnemonics",
                                  self._gtk_settings_mnemonic)

        for g in self._accel_groups:
            self.topwin.add_accel_group(g)

    def _refresh_enable_accel(self):
        # Make sure modifiers are up to date
        self._viewer_focus_changed()

    def _do_send_key(self, src, keys):
        ignore = src

        if keys is not None:
            self._viewer.console_send_keys(keys)


    ###########################
    # Resize and scaling APIs #
    ###########################

    def _scroll_size_allocate(self, src_ignore, req):
        if not self._viewer:
            return
        if not self._viewer.console_get_desktop_resolution():
            return

        scroll = self.widget("console-gfx-scroll")
        is_scale = self._viewer.console_get_scaling()
        is_resizeguest = self._viewer.console_get_resizeguest()

        dx = 0
        dy = 0
        align_ratio = float(req.width) / float(req.height)

        # pylint: disable=unpacking-non-sequence
        desktop_w, desktop_h = self._viewer.console_get_desktop_resolution()
        desktop_ratio = float(desktop_w) / float(desktop_h)

        if is_scale:
            # Make sure we never show scrollbars when scaling
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        else:
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
                              Gtk.PolicyType.AUTOMATIC)

        if is_resizeguest:
            # With resize guest, we don't want to maintain aspect ratio,
            # since the guest can resize to arbitrary resolutions.
            self._viewer.console_set_size_request(req.width, req.height)
            return

        if not is_scale:
            # Scaling disabled is easy, just force the VNC widget size. Since
            # we are inside a scrollwindow, it shouldn't cause issues.
            self._viewer.console_set_size_request(desktop_w, desktop_h)
            return

        # Make sure there is no hard size requirement so we can scale down
        self._viewer.console_set_size_request(-1, -1)

        # Make sure desktop aspect ratio is maintained
        if align_ratio > desktop_ratio:
            desktop_w = int(req.height * desktop_ratio)
            desktop_h = req.height
            dx = (req.width - desktop_w) / 2

        else:
            desktop_w = req.width
            desktop_h = int(req.width / desktop_ratio)
            dy = (req.height - desktop_h) / 2

        viewer_alloc = Gdk.Rectangle()
        viewer_alloc.x = dx
        viewer_alloc.y = dy
        viewer_alloc.width = desktop_w
        viewer_alloc.height = desktop_h
        self._viewer.console_size_allocate(viewer_alloc)

    def _refresh_resizeguest_from_settings(self):
        tooltip = ""
        if self._viewer:
            if self._viewer.viewer_type != "spice":
                tooltip = (
                    _("Graphics type '%s' does not support auto resize.") %
                    self._viewer.viewer_type)
            elif not self._viewer.console_has_agent():
                tooltip = _("Guest agent is not available.")

        val = self.vm.get_console_resizeguest()
        widget = self.widget("details-menu-view-resizeguest")
        widget.set_tooltip_text(tooltip)
        widget.set_sensitive(not bool(tooltip))
        if not tooltip:
            self.widget("details-menu-view-resizeguest").set_active(bool(val))

        self._sync_resizeguest_with_display()

    def _sync_resizeguest_with_display(self):
        if not self._viewer:
            return

        val = bool(self.vm.get_console_resizeguest())
        self._viewer.console_set_resizeguest(val)
        self.widget("console-gfx-scroll").queue_resize()

    def _resizeguest_ui_changed_cb(self, src):
        if not src.get_sensitive():
            return

        val = int(self.widget("details-menu-view-resizeguest").get_active())
        self.vm.set_console_resizeguest(val)
        self._sync_resizeguest_with_display()

    def _do_size_to_vm(self, src_ignore):
        # Resize the console to best fit the VM resolution
        if not self._viewer:
            return
        if not self._viewer.console_get_desktop_resolution():
            return

        top_w, top_h = self.topwin.get_size()
        viewer_alloc = self.widget("console-gfx-scroll").get_allocation()
        desktop_w, desktop_h = self._viewer.console_get_desktop_resolution()

        self.topwin.unmaximize()
        self.topwin.resize(
            desktop_w + (top_w - viewer_alloc.width),
            desktop_h + (top_h - viewer_alloc.height))


    ################
    # Scaling APIs #
    ################

    def _refresh_scaling_from_settings(self):
        scale_type = self.vm.get_console_scaling()
        self.widget("details-menu-view-scale-always").set_active(
            scale_type == self.config.CONSOLE_SCALE_ALWAYS)
        self.widget("details-menu-view-scale-never").set_active(
            scale_type == self.config.CONSOLE_SCALE_NEVER)
        self.widget("details-menu-view-scale-fullscreen").set_active(
            scale_type == self.config.CONSOLE_SCALE_FULLSCREEN)

        self._sync_scaling_with_display()

    def _scaling_ui_changed_cb(self, src):
        # Called from details.py
        if not src.get_active():
            return

        scale_type = 0
        if src == self.widget("details-menu-view-scale-always"):
            scale_type = self.config.CONSOLE_SCALE_ALWAYS
        elif src == self.widget("details-menu-view-scale-fullscreen"):
            scale_type = self.config.CONSOLE_SCALE_FULLSCREEN
        elif src == self.widget("details-menu-view-scale-never"):
            scale_type = self.config.CONSOLE_SCALE_NEVER

        self.vm.set_console_scaling(scale_type)
        self._sync_scaling_with_display()

    def _sync_scaling_with_display(self):
        if not self._viewer:
            return

        curscale = self._viewer.console_get_scaling()
        fs = self.widget("control-fullscreen").get_active()
        scale_type = self.vm.get_console_scaling()

        if (scale_type == self.config.CONSOLE_SCALE_NEVER and
            curscale is True):
            self._viewer.console_set_scaling(False)
        elif (scale_type == self.config.CONSOLE_SCALE_ALWAYS and
              curscale is False):
            self._viewer.console_set_scaling(True)
        elif (scale_type == self.config.CONSOLE_SCALE_FULLSCREEN and
              curscale != fs):
            self._viewer.console_set_scaling(fs)

        # Refresh viewer size
        self.widget("console-gfx-scroll").queue_resize()


    ###################
    # Fullscreen APIs #
    ###################

    def _refresh_can_fullscreen(self):
        cpage = self.widget("console-pages").get_current_page()
        dpage = self.widget("details-pages").get_current_page()

        allow_fullscreen = bool(dpage == DETAILS_PAGE_CONSOLE and
            cpage == _CONSOLE_PAGE_VIEWER and
            self._viewer and self._viewer.console_is_open())

        self.widget("control-fullscreen").set_sensitive(allow_fullscreen)
        self.widget("details-menu-view-fullscreen").set_sensitive(
            allow_fullscreen)

    def _leave_fullscreen(self, ignore=None):
        self._change_fullscreen(False)

    def _change_fullscreen(self, do_fullscreen):
        self.widget("control-fullscreen").set_active(do_fullscreen)

        if do_fullscreen:
            self.topwin.fullscreen()
            self._timed_revealer.force_reveal(True)
            self.widget("toolbar-box").hide()
            self.widget("details-menubar").hide()
        else:
            self._timed_revealer.force_reveal(False)
            self.topwin.unfullscreen()

            if self.widget("details-menu-view-toolbar").get_active():
                self.widget("toolbar-box").show()
            self.widget("details-menubar").show()

        self._sync_scaling_with_display()


    ##########################
    # State tracking methods #
    ##########################

    def _show_vm_status_unavailable(self):
        if self.vm.is_crashed():
            self._activate_unavailable_page(_("Guest has crashed."))
        else:
            self._activate_unavailable_page(_("Guest is not running."))

    def _close_viewer(self):
        if self._viewer is None:
            return

        self._viewer.console_remove_display_from_widget(
            self.widget("console-gfx-viewport"))
        self._viewer.cleanup()
        self._viewer = None

        self._leave_fullscreen()

        for serial in self._serial_consoles:
            serial.close()

    def _update_vm_widget_states(self):
        page = self.widget("console-pages").get_current_page()

        if self.vm.is_runable():
            self._show_vm_status_unavailable()

        elif (page == _CONSOLE_PAGE_UNAVAILABLE or
              page == _CONSOLE_PAGE_VIEWER):
            if self._viewer and self._viewer.console_is_open():
                self._activate_viewer_page()
            else:
                self._init_viewer()

        # Update other state
        self._refresh_widget_states()


    ###################
    # Page Navigation #
    ###################

    def _activate_unavailable_page(self, msg):
        """
        This function is passed to serialcon.py at least, so change
        with care
        """
        self._close_viewer()
        self.widget("console-pages").set_current_page(
            _CONSOLE_PAGE_UNAVAILABLE)
        if msg:
            self.widget("console-unavailable").set_label("<b>" + msg + "</b>")

    def _activate_auth_page(self, withPassword, withUsername):
        (pw, username) = self.config.get_console_password(self.vm)

        self.widget("console-auth-password").set_visible(withPassword)
        self.widget("label-auth-password").set_visible(withPassword)

        self.widget("console-auth-username").set_visible(withUsername)
        self.widget("label-auth-username").set_visible(withUsername)

        self.widget("console-auth-username").set_text(username)
        self.widget("console-auth-password").set_text(pw)

        self.widget("console-auth-remember").set_sensitive(
                bool(self.config.has_keyring()))
        if self.config.has_keyring():
            self.widget("console-auth-remember").set_active(
                    bool(withPassword and pw) or (withUsername and username))

        self.widget("console-pages").set_current_page(
            _CONSOLE_PAGE_AUTHENTICATE)

        if withUsername:
            self.widget("console-auth-username").grab_focus()
        else:
            self.widget("console-auth-password").grab_focus()

    def _activate_viewer_page(self):
        self.widget("console-pages").set_current_page(_CONSOLE_PAGE_VIEWER)
        if self._viewer:
            self._viewer.console_grab_focus()

    def _page_changed(self, src, origpage, newpage):
        ignore = src
        ignore = origpage

        # Hide the contents of all other pages, so they don't screw
        # up window sizing
        for i in range(self.widget("console-pages").get_n_pages()):
            self.widget("console-pages").get_nth_page(i).set_visible(
                i == newpage)

        self.idle_add(self._refresh_widget_states)

    def _refresh_widget_states(self):
        pagenum = self.widget("console-pages").get_current_page()
        paused = self.vm.is_paused()
        is_viewer = bool(pagenum == _CONSOLE_PAGE_VIEWER and
            self._viewer and self._viewer.console_is_open())

        self.widget("details-menu-vm-screenshot").set_sensitive(is_viewer)
        self.widget("details-menu-usb-redirection").set_sensitive(
            bool(is_viewer and self._viewer and
            self._viewer.console_has_usb_redirection() and
            self.vm.has_spicevmc_type_redirdev()))

        can_sendkey = (is_viewer and not paused)
        self._send_key_button.set_sensitive(can_sendkey)
        for c in self._keycombo_menu.get_children():
            c.set_sensitive(can_sendkey)

        self._refresh_can_fullscreen()


    #########################
    # Viewer login attempts #
    #########################

    def _init_viewer(self):
        if self._viewer or not self.is_visible():
            # Don't try and login for these cases
            return

        ginfo = None
        try:
            gdevs = self.vm.get_graphics_devices()
            gdev = gdevs and gdevs[0] or None
            if gdev:
                ginfo = ConnectionInfo(self.vm.conn, gdev)
        except Exception as e:
            # We can fail here if VM is destroyed: xen is a bit racy
            # and can't handle domain lookups that soon after
            logging.exception("Getting graphics console failed: %s", str(e))
            return

        if ginfo is None:
            logging.debug("No graphics configured for guest")
            self._activate_unavailable_page(
                _("Graphical console not configured for guest"))
            return

        if ginfo.gtype not in self.config.embeddable_graphics():
            logging.debug("Don't know how to show graphics type '%s' "
                          "disabling console page", ginfo.gtype)

            msg = (_("Cannot display graphical console type '%s'")
                     % ginfo.gtype)

            self._activate_unavailable_page(msg)
            return

        self._activate_unavailable_page(
            _("Connecting to graphical console for guest"))

        logging.debug("Starting connect process for %s", ginfo.logstring())
        try:
            if ginfo.gtype == "vnc":
                viewer_class = VNCViewer
            elif ginfo.gtype == "spice":
                if have_spice_gtk:
                    viewer_class = SpiceViewer
                else:
                    raise RuntimeError("Error opening Spice console, "
                                       "SpiceClientGtk missing")


            self._viewer = viewer_class(self.vm, ginfo)
            self._connect_viewer_signals()

            self._refresh_enable_accel()

            self._viewer.console_open()
        except Exception as e:
            logging.exception("Error connection to graphical console")
            self._activate_unavailable_page(
                    _("Error connecting to graphical console") + ":\n%s" % e)

    def _set_credentials(self, src_ignore=None):
        passwd = self.widget("console-auth-password")
        username = self.widget("console-auth-username")

        if passwd.get_visible():
            self._viewer.console_set_password(passwd.get_text())
        if username.get_visible():
            self._viewer.console_set_username(username.get_text())

        if self.widget("console-auth-remember").get_active():
            self.config.set_console_password(self.vm, passwd.get_text(),
                                             username.get_text())
        else:
            self.config.del_console_password(self.vm)


    ##########################
    # Viewer signal handling #
    ##########################

    def _viewer_add_display(self, ignore, display):
        self.widget("console-gfx-viewport").add(display)

        # Sync initial settings
        self._sync_scaling_with_display()
        self._refresh_resizeguest_from_settings()

    def _pointer_grabbed(self, ignore):
        self._pointer_is_grabbed = True
        self._change_title()

    def _pointer_ungrabbed(self, ignore):
        self._pointer_is_grabbed = False
        self._change_title()

    def _viewer_allocate_cb(self, src, ignore):
        self.widget("console-gfx-scroll").queue_resize()

    def _viewer_focus_changed(self, ignore1=None, ignore2=None):
        force_accel = self.config.get_console_accels()

        if force_accel:
            self._enable_modifiers()
        elif self._someone_has_focus():
            self._disable_modifiers()
        else:
            self._enable_modifiers()

    def _viewer_auth_rejected(self, ignore, errmsg):
        self._activate_unavailable_page(errmsg)

    def _viewer_auth_error(self, ignore, errmsg, viewer_will_disconnect):
        errmsg = _("Viewer authentication error: %s") % errmsg
        self.err.val_err(errmsg)

        if viewer_will_disconnect:
            # GtkVNC will disconnect after an auth error, so lets do it for
            # them and re-init the viewer (which will be triggered by
            # update_vm_widget_states if needed)
            self._activate_unavailable_page(errmsg)

        self._update_vm_widget_states()

    def _viewer_need_auth(self, ignore, withPassword, withUsername):
        self._activate_auth_page(withPassword, withUsername)

    def _viewer_agent_connected(self, ignore):
        self._refresh_resizeguest_from_settings()

    def _viewer_usb_redirect_error(self, ignore, errstr):
        self.err.show_err(_("USB redirection error"),
            text2=str(errstr), modal=True)

    def _viewer_disconnected_set_page(self, errdetails, ssherr):
        if self.vm.is_runable():
            # Exit was probably for legitimate reasons
            self._show_vm_status_unavailable()
            return

        msg = _("Viewer was disconnected.")
        if errdetails:
            msg += "\n" + errdetails
        if ssherr:
            logging.debug("SSH tunnel error output: %s", ssherr)
            msg += "\n\n"
            msg += _("SSH tunnel error output: %s") % ssherr

        self._activate_unavailable_page(msg)

    def _viewer_disconnected(self, ignore, errdetails, ssherr):
        self._activate_unavailable_page(_("Viewer disconnected."))
        logging.debug("Viewer disconnected")

        # Make sure modifiers are set correctly
        self._viewer_focus_changed()

        self._viewer_disconnected_set_page(errdetails, ssherr)
        self._refresh_resizeguest_from_settings()

    def _viewer_connected(self, ignore):
        logging.debug("Viewer connected")
        self._activate_viewer_page()

        # Make sure modifiers are set correctly
        self._viewer_focus_changed()

    def _connect_viewer_signals(self):
        self._viewer.connect("add-display-widget", self._viewer_add_display)
        self._viewer.connect("pointer-grab", self._pointer_grabbed)
        self._viewer.connect("pointer-ungrab", self._pointer_ungrabbed)
        self._viewer.connect("size-allocate", self._viewer_allocate_cb)
        self._viewer.connect("focus-in-event", self._viewer_focus_changed)
        self._viewer.connect("focus-out-event", self._viewer_focus_changed)
        self._viewer.connect("connected", self._viewer_connected)
        self._viewer.connect("disconnected", self._viewer_disconnected)
        self._viewer.connect("auth-error", self._viewer_auth_error)
        self._viewer.connect("auth-rejected", self._viewer_auth_rejected)
        self._viewer.connect("need-auth", self._viewer_need_auth)
        self._viewer.connect("agent-connected", self._viewer_agent_connected)
        self._viewer.connect("usb-redirect-error",
            self._viewer_usb_redirect_error)


    ###########################
    # Serial console handling #
    ###########################

    def _activate_default_console_page(self):
        """
        Find the default graphical or serial console for the VM
        """
        if self.vm.get_graphics_devices() or not self.vm.get_serial_devs():
            return

        # We iterate through the 'console' menu and activate the first
        # valid entry... it's the easiest thing to do to hit all the right
        # code paths.
        self._populate_serial_menu()
        menu = self.widget("details-menu-view-serial-list").get_submenu()
        for child in menu.get_children():
            if isinstance(child, Gtk.SeparatorMenuItem):
                break
            if child.get_sensitive():
                child.toggled()
                break

    def _console_menu_toggled(self, src, dev):
        self.widget("details-pages").set_current_page(DETAILS_PAGE_CONSOLE)

        if dev.virtual_device_type == "graphics":
            self.widget("console-pages").set_current_page(_CONSOLE_PAGE_VIEWER)
            return

        target_port = dev.vmmindex
        serial = None
        name = src.get_label()
        for s in self._serial_consoles:
            if s.name == name:
                serial = s
                break

        if not serial:
            serial = vmmSerialConsole(self.vm, target_port, name)
            serial.terminal.connect("focus-in-event",
                                    self._viewer_focus_changed)
            serial.terminal.connect("focus-out-event",
                                    self._viewer_focus_changed)

            title = Gtk.Label(label=name)
            self.widget("serial-pages").append_page(serial.box, title)
            self._serial_consoles.append(serial)

        serial.open_console()
        page_idx = self._serial_consoles.index(serial)
        self.widget("console-pages").set_current_page(_CONSOLE_PAGE_SERIAL)
        self.widget("serial-pages").set_current_page(page_idx)

    def _build_serial_menu_items(self, menu_item_cb):
        devs = self.vm.get_serial_devs()
        if len(devs) == 0:
            menu_item_cb(_("No text console available"),
                         radio=False, sensitive=False)
            return

        active_label = None
        if (self.widget("console-pages").get_current_page() ==
                _CONSOLE_PAGE_SERIAL):
            serial_page = self.widget("serial-pages").get_current_page()
            if len(self._serial_consoles) > serial_page:
                active_label = self._serial_consoles[serial_page].name

        for dev in devs:
            if dev.virtual_device_type == "console":
                label = _("Text Console %d") % (dev.vmmindex + 1)
            else:
                label = _("Serial %d") % (dev.vmmindex + 1)

            tooltip = vmmSerialConsole.can_connect(self.vm, dev)
            sensitive = not bool(tooltip)

            active = (sensitive and label == active_label)
            menu_item_cb(label, sensitive=sensitive, active=active,
                tooltip=tooltip, cb=self._console_menu_toggled, cbdata=dev)

    def _build_graphical_menu_items(self, menu_item_cb):
        devs = self.vm.get_graphics_devices()
        if len(devs) == 0:
            menu_item_cb(_("No graphical console available"),
                         radio=False, sensitive=False)
            return

        active = (self.widget("console-pages").get_current_page() !=
                _CONSOLE_PAGE_SERIAL)
        for idx, dev in enumerate(devs):
            label = (_("Graphical Console") + " " +
                     dev.pretty_type_simple(dev.type))

            sensitive = True
            tooltip = None
            if idx > 0:
                label += " %s" % (idx + 1)
                sensitive = False
                tooltip = _("virt-manager does not support more "
                            "that one graphical console")

            menu_item_cb(label, active=active,
                sensitive=sensitive, tooltip=tooltip,
                cb=self._console_menu_toggled, cbdata=dev)

    def _populate_serial_menu(self, ignore=None):
        src = self.widget("details-menu-view-serial-list").get_submenu()
        for child in src:
            src.remove(child)

        def menu_item_cb(label, sensitive=True, active=False,
                         radio=True, tooltip=None, cb=None, cbdata=None):
            if radio:
                item = Gtk.RadioMenuItem(menu_item_cb.radio_group)
                if menu_item_cb.radio_group is None:
                    menu_item_cb.radio_group = item
                item.set_label(label)
            else:
                item = Gtk.MenuItem.new_with_label(label)

            item.set_sensitive(sensitive)
            if active:
                item.set_active(True)
            if tooltip:
                item.set_tooltip_text(tooltip)
            if cb and sensitive:
                item.connect("toggled", cb, cbdata)
            src.add(item)
        menu_item_cb.radio_group = None

        self._build_serial_menu_items(menu_item_cb)
        src.add(Gtk.SeparatorMenuItem())
        self._build_graphical_menu_items(menu_item_cb)
        src.show_all()


    ##########################
    # API used by vmmDetails #
    ##########################

    def details_viewer_is_visible(self):
        return bool(self._viewer and self._viewer.console_get_visible())
    def details_viewer_has_usb_redirection(self):
        return bool(self._viewer and
            self._viewer.console_has_usb_redirection())
    def details_viewer_get_usb_widget(self):
        return self._viewer.console_get_usb_widget()
    def details_viewer_get_pixbuf(self):
        return self._viewer.console_get_pixbuf()

    def details_close_viewer(self):
        return self._activate_unavailable_page(_("Viewer disconnected."))

    def details_activate_default_console_page(self):
        return self._activate_default_console_page()

    def details_update_widget_states(self):
        return self._update_vm_widget_states()

    def details_refresh_can_fullscreen(self):
        return self._refresh_can_fullscreen()
    def details_resizeguest_ui_changed_cb(self, *args, **kwargs):
        return self._resizeguest_ui_changed_cb(*args, **kwargs)

    def details_page_changed(self, *args, **kwargs):
        return self._page_changed(*args, **kwargs)
    def details_scaling_ui_changed_cb(self, *args, **kwargs):
        return self._scaling_ui_changed_cb(*args, **kwargs)
    def details_size_to_vm(self, *args, **kwargs):
        return self._do_size_to_vm(*args, **kwargs)

    def details_toggle_fullscreen(self, src):
        do_fullscreen = src.get_active()
        self._change_fullscreen(do_fullscreen)

    def details_auth_login(self, ignore):
        self._set_credentials()
