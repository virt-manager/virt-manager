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

from gi.repository import Gtk
from gi.repository import Gdk

import libvirt

import logging

from .autodrawer import AutoDrawer
from .baseclass import vmmGObjectUI
from .details import DETAILS_PAGE_CONSOLE
from .serialcon import vmmSerialConsole
from .sshtunnels import ConnectionInfo
from .viewers import SpiceViewer, VNCViewer


class vmmConsolePages(vmmGObjectUI):
    """
    Handles all the complex UI handling dictated by the spice/vnc widgets
    """
    # Console pages
    (CONSOLE_PAGE_UNAVAILABLE,
     CONSOLE_PAGE_AUTHENTICATE,
     CONSOLE_PAGE_VIEWER,
     CONSOLE_PAGE_OFFSET) = range(4)


    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, None, None, builder=builder, topwin=topwin)

        self.vm = vm
        self._pointer_is_grabbed = False
        self._change_title()
        self.vm.connect("config-changed", self._change_title)
        self._force_resize = False

        # State for disabling modifiers when keyboard is grabbed
        self._accel_groups = Gtk.accel_groups_from_object(self.topwin)
        self._gtk_settings_accel = None
        self._gtk_settings_mnemonic = None

        # Initialize display widget
        self._viewer = None
        self._viewerRetriesScheduled = 0
        self._viewerRetryDelay = 125
        self._viewer_is_connected = False
        self._viewer_is_connecting = False

        # Fullscreen toolbar
        self._send_key_button = None
        self._fs_toolbar = None
        self._fs_drawer = None
        self._keycombo_menu = self._build_keycombo_menu(self._do_send_key)
        self._init_fs_toolbar()

        # Make viewer widget background always be black
        black = Gdk.Color(0, 0, 0)
        self.widget("console-gfx-viewport").modify_bg(Gtk.StateType.NORMAL,
                                                      black)

        self._serial_tabs = []
        self._last_gfx_page = 0
        self._init_menus()

        # Signals are added by vmmDetails. Don't use connect_signals here
        # or it changes will be overwritten

        self._refresh_can_fullscreen()
        self._refresh_scaling_from_settings()
        self.add_gsettings_handle(
            self.vm.on_console_scaling_changed(
                self._refresh_scaling_from_settings))
        self._refresh_resizeguest_from_settings()
        self.add_gsettings_handle(
            self.vm.on_console_resizeguest_changed(
                self._refresh_resizeguest_from_settings))

        scroll = self.widget("console-gfx-scroll")
        scroll.connect("size-allocate", self._scroll_size_allocate)
        self.add_gsettings_handle(
            self.config.on_console_accels_changed(self._refresh_enable_accel))

        self._page_changed()


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

        self._keycombo_menu.destroy()
        self._keycombo_menu = None
        self._fs_drawer.destroy()
        self._fs_drawer = None
        self._fs_toolbar.destroy()
        self._fs_toolbar = None

        for serial in self._serial_tabs:
            serial.cleanup()
        self._serial_tabs = []


    ##########################
    # Initialization helpers #
    ##########################

    def _build_keycombo_menu(self, cb):
        # Shared with vmmDetails
        menu = Gtk.Menu()

        def make_item(name, combo):
            item = Gtk.MenuItem.new_with_mnemonic(name)
            item.connect("activate", cb, combo)

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

    def _init_fs_toolbar(self):
        scroll = self.widget("console-gfx-scroll")
        pages = self.widget("console-pages")
        pages.remove(scroll)

        self._fs_toolbar = Gtk.Toolbar()
        self._fs_toolbar.set_show_arrow(False)
        self._fs_toolbar.set_no_show_all(True)
        self._fs_toolbar.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)

        # Exit fullscreen button
        button = Gtk.ToolButton.new_from_stock(Gtk.STOCK_LEAVE_FULLSCREEN)
        button.set_tooltip_text(_("Leave fullscreen"))
        button.show()
        self._fs_toolbar.add(button)
        button.connect("clicked", self._leave_fullscreen)

        def keycombo_menu_clicked(src):
            ignore = src
            def menu_location(menu, toolbar):
                ignore = menu
                ignore, x, y = toolbar.get_window().get_origin()
                height = toolbar.get_window().get_height()

                return x, y + height, True

            self._keycombo_menu.popup(None, None, menu_location,
                                     self._fs_toolbar, 0,
                                     Gtk.get_current_event_time())

        self._send_key_button = Gtk.ToolButton()
        self._send_key_button.set_icon_name(
                                "preferences-desktop-keyboard-shortcuts")
        self._send_key_button.set_tooltip_text(_("Send key combination"))
        self._send_key_button.show_all()
        self._send_key_button.connect("clicked", keycombo_menu_clicked)
        self._fs_toolbar.add(self._send_key_button)

        self._fs_drawer = AutoDrawer()
        self._fs_drawer.set_active(False)
        self._fs_drawer.set_over(self._fs_toolbar)
        self._fs_drawer.set_under(scroll)
        self._fs_drawer.set_offset(-1)
        self._fs_drawer.set_fill(False)
        self._fs_drawer.set_overlap_pixels(1)
        self._fs_drawer.set_nooverlap_pixels(0)
        self._fs_drawer.period = 20
        self._fs_drawer.step = .1

        self._fs_drawer.show_all()

        pages.add(self._fs_drawer)

    def _init_menus(self):
        # Serial list menu
        smenu = Gtk.Menu()
        smenu.connect("show", self._populate_serial_menu)
        self.widget("details-menu-view-serial-list").set_submenu(smenu)


    #################
    # Internal APIs #
    #################

    def _change_title(self, ignore1=None):
        title = self.vm.get_name() + " " + _("Virtual Machine")

        if self._pointer_is_grabbed and self._viewer:
            keystr = self._viewer.console_get_grab_keys()
            keymsg = _("Press %s to release pointer.") % keystr

            title = keymsg + " " + title

        self.topwin.set_title(title)

    def _someone_has_focus(self):
        if (self._viewer and
            self._viewer.console_has_focus() and
            self._viewer_is_connected):
            return True

        for serial in self._serial_tabs:
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
        if (not self._viewer or
            not self._viewer.console_get_desktop_resolution()):
            return

        scroll = self.widget("console-gfx-scroll")
        is_scale = self._viewer.console_get_scaling()
        is_resizeguest = self._viewer.console_get_resizeguest()

        dx = 0
        dy = 0
        align_ratio = float(req.width) / float(req.height)

        # pylint: disable=unpacking-non-sequence
        desktop_w, desktop_h = self._viewer.console_get_desktop_resolution()
        if desktop_h == 0:
            return
        desktop_ratio = float(desktop_w) / float(desktop_h)

        if is_scale or self._force_resize:
            # Make sure we never show scrollbars when scaling
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        else:
            scroll.set_policy(Gtk.PolicyType.AUTOMATIC,
                              Gtk.PolicyType.AUTOMATIC)

        if not self._force_resize and is_resizeguest:
            # With resize guest, we don't want to maintain aspect ratio,
            # since the guest can resize to arbitrary resolutions.
            self._viewer.console_set_size_request(req.width, req.height)
            return

        if not is_scale or self._force_resize:
            # Scaling disabled is easy, just force the VNC widget size. Since
            # we are inside a scrollwindow, it shouldn't cause issues.
            self._force_resize = False
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

        self.topwin.unmaximize()
        self.topwin.resize(1, 1)
        self._force_resize = True
        self.widget("console-gfx-scroll").queue_resize()


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

        if (scale_type == self.config.CONSOLE_SCALE_NEVER
            and curscale is True):
            self._viewer.console_set_scaling(False)
        elif (scale_type == self.config.CONSOLE_SCALE_ALWAYS
              and curscale is False):
            self._viewer.console_set_scaling(True)
        elif (scale_type == self.config.CONSOLE_SCALE_FULLSCREEN
              and curscale != fs):
            self._viewer.console_set_scaling(fs)

        # Refresh viewer size
        self.widget("console-gfx-scroll").queue_resize()


    ###################
    # Fullscreen APIs #
    ###################

    def _refresh_can_fullscreen(self):
        cpage = self.widget("console-pages").get_current_page()
        dpage = self.widget("details-pages").get_current_page()

        allow_fullscreen = (dpage == DETAILS_PAGE_CONSOLE and
                            cpage == self.CONSOLE_PAGE_VIEWER and
                            self._viewer_is_connected)

        self.widget("control-fullscreen").set_sensitive(allow_fullscreen)
        self.widget("details-menu-view-fullscreen").set_sensitive(
            allow_fullscreen)

    def _leave_fullscreen(self, ignore=None):
        self._change_fullscreen(False)

    def _change_fullscreen(self, do_fullscreen):
        self.widget("control-fullscreen").set_active(do_fullscreen)

        if do_fullscreen:
            self.topwin.fullscreen()
            self._fs_toolbar.show()
            self._fs_drawer.set_active(True)
            self.widget("toolbar-box").hide()
            self.widget("details-menubar").hide()
        else:
            self._fs_toolbar.hide()
            self._fs_drawer.set_active(False)
            self.topwin.unfullscreen()

            if self.widget("details-menu-view-toolbar").get_active():
                self.widget("toolbar-box").show()
            self.widget("details-menubar").show()

        self._sync_scaling_with_display()


    ##########################
    # State tracking methods #
    ##########################

    def _view_vm_status(self):
        if not self.vm:
            # window has been closed and no pages to update are available.
            return
        status = self.vm.status()
        if status == libvirt.VIR_DOMAIN_SHUTOFF:
            self._activate_unavailable_page(_("Guest not running"))
        else:
            if status == libvirt.VIR_DOMAIN_CRASHED:
                self._activate_unavailable_page(_("Guest has crashed"))

    def _close_viewer(self):
        if self._viewer is None:
            return

        viewer = self._viewer
        display = getattr(viewer, "_display")
        self._viewer = None

        viewport = self.widget("console-gfx-viewport")
        if display and display in viewport.get_children():
            viewport.remove(display)

        viewer.close()
        self._viewer_is_connected = False
        self._refresh_can_fullscreen()
        self._leave_fullscreen()

        for serial in self._serial_tabs:
            serial.close()

    def _update_widget_states(self, vm, status_ignore):
        runable = vm.is_runable()
        paused = vm.is_paused()
        pages   = self.widget("console-pages")
        page    = pages.get_current_page()

        self._send_key_button.set_sensitive(not (runable or paused))

        if runable:
            if page != self.CONSOLE_PAGE_UNAVAILABLE:
                pages.set_current_page(self.CONSOLE_PAGE_UNAVAILABLE)

            self._view_vm_status()

        elif page in [self.CONSOLE_PAGE_UNAVAILABLE, self.CONSOLE_PAGE_VIEWER]:
            if self._viewer and self._viewer.console_is_open():
                self._activate_viewer_page()
            else:
                self._viewerRetriesScheduled = 0
                self._viewerRetryDelay = 125
                self._try_login()

        return


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
            self.CONSOLE_PAGE_UNAVAILABLE)
        self.widget("details-menu-vm-screenshot").set_sensitive(False)
        self.widget("details-menu-usb-redirection").set_sensitive(False)
        self.widget("console-unavailable").set_label("<b>" + msg + "</b>")

    def _activate_auth_page(self, withPassword, withUsername):
        (pw, username) = self.config.get_console_password(self.vm)
        self.widget("details-menu-vm-screenshot").set_sensitive(False)
        self.widget("details-menu-usb-redirection").set_sensitive(False)

        self.widget("console-auth-password").set_visible(withPassword)
        self.widget("label-auth-password").set_visible(withPassword)

        self.widget("console-auth-username").set_visible(withUsername)
        self.widget("label-auth-username").set_visible(withUsername)

        if withUsername:
            self.widget("console-auth-username").grab_focus()
        else:
            self.widget("console-auth-password").grab_focus()

        self.widget("console-auth-username").set_text(username)
        self.widget("console-auth-password").set_text(pw)

        self.widget("console-auth-remember").set_sensitive(
                bool(self.config.has_keyring()))
        if self.config.has_keyring():
            self.widget("console-auth-remember").set_active(bool(pw and
                                                                 username))

        self.widget("console-pages").set_current_page(
            self.CONSOLE_PAGE_AUTHENTICATE)

    def _activate_viewer_page(self):
        self.widget("console-pages").set_current_page(self.CONSOLE_PAGE_VIEWER)
        self.widget("details-menu-vm-screenshot").set_sensitive(True)
        if self._viewer:
            self._viewer.console_grab_focus()

        if (self._viewer.console_has_usb_redirection() and
            self.vm.has_spicevmc_type_redirdev()):
            self.widget("details-menu-usb-redirection").set_sensitive(True)
            return

    def _page_changed(self, ignore1=None, ignore2=None, newpage=None):
        pagenum = self.widget("console-pages").get_current_page()

        if newpage is not None:
            for i in range(self.widget("console-pages").get_n_pages()):
                w = self.widget("console-pages").get_nth_page(i)
                w.set_visible(i == newpage)

        if pagenum < self.CONSOLE_PAGE_OFFSET:
            self._last_gfx_page = pagenum
        self._refresh_can_fullscreen()


    #########################
    # Viewer login attempts #
    #########################

    def _schedule_retry(self):
        if self._viewerRetriesScheduled >= 10:
            logging.error("Too many connection failures, not retrying again")
            return

        self.timeout_add(self._viewerRetryDelay, self._try_login)

        if self._viewerRetryDelay < 2000:
            self._viewerRetryDelay = self._viewerRetryDelay * 2

    def _skip_connect_attempt(self):
        return (self._viewer or
                not self.is_visible())

    def _guest_not_avail(self):
        return (self.vm.is_shutoff() or self.vm.is_crashed())

    def _try_login(self, src_ignore=None):
        if self._viewer_is_connecting:
            return

        try:
            self._viewer_is_connecting = True
            self._do_try_login()
        finally:
            self._viewer_is_connecting = False

    def _do_try_login(self):
        if self._skip_connect_attempt():
            # Don't try and login for these cases
            return

        if self._guest_not_avail():
            # Guest isn't running, schedule another try
            self._activate_unavailable_page(_("Guest not running"))
            self._schedule_retry()
            return

        ginfo = None
        try:
            gdevs = self.vm.get_graphics_devices()
            gdev = gdevs and gdevs[0] or None
            if gdev:
                ginfo = ConnectionInfo(self.vm.conn, gdev)
        except Exception, e:
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

        if ginfo.is_bad_localhost():
            self._activate_unavailable_page(
                _("Guest is on a remote host with transport '%s'\n"
                  "but is only configured to listen on locally.\n"
                  "Connect using 'ssh' transport or change the\n"
                  "guest's listen address." % ginfo.transport))
            return

        if not ginfo.console_active():
            self._activate_unavailable_page(
                            _("Graphical console is not yet active for guest"))
            self._schedule_retry()
            return

        self._activate_unavailable_page(
            _("Connecting to graphical console for guest"))

        logging.debug("Starting connect process for %s", ginfo.logstring())
        try:
            if ginfo.gtype == "vnc":
                viewer_class = VNCViewer
            elif ginfo.gtype == "spice":
                viewer_class = SpiceViewer

            self._viewer = viewer_class()
            self._connect_viewer_signals()

            self._refresh_enable_accel()

            self._viewer.console_open_ginfo(ginfo)
        except Exception, e:
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

    def _viewer_auth_error(self, viewer, errmsg):
        viewer.close()
        self._activate_unavailable_page(errmsg)

    def _viewer_need_auth(self, ignore, withPassword, withUsername):
        self._activate_auth_page(withPassword, withUsername)

    def _viewer_agent_connected(self, ignore):
        self._refresh_resizeguest_from_settings()

    def _viewer_usb_redirect_error(self, ignore, errstr):
        self.err.show_err(_("USB redirection error"),
            text2=str(errstr), modal=True)

    def _viewer_disconnected(self, ignore):
        errout = ""
        if self._viewer:
            errout = self._viewer.console_reset_tunnels()

        self.widget("console-pages").set_current_page(
            self.CONSOLE_PAGE_UNAVAILABLE)
        self._close_viewer()
        logging.debug("Viewer disconnected")

        # Make sure modifiers are set correctly
        self._viewer_focus_changed()

        if self._guest_not_avail():
            # Exit was probably for legitimate reasons
            self._view_vm_status()
            return

        error = _("Error: viewer connection to hypervisor host got refused "
                  "or disconnected!")
        if errout:
            logging.debug("Error output from closed console: %s", errout)
            error += "\n\nError: %s" % errout

        self._activate_unavailable_page(error)
        self._refresh_resizeguest_from_settings()

    def _viewer_connected(self, ignore):
        self._viewer_is_connected = True
        self._refresh_can_fullscreen()

        logging.debug("Viewer connected")
        self._activate_viewer_page()

        # Had a successful connect, so reset counters now
        self._viewerRetriesScheduled = 0
        self._viewerRetryDelay = 125

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
        self._viewer.connect("need-auth", self._viewer_need_auth)
        self._viewer.connect("agent-connected", self._viewer_agent_connected)
        self._viewer.connect("usb-redirect-error",
            self._viewer_usb_redirect_error)


    ###########################
    # Serial console handling #
    ###########################

    def _activate_default_console_page(self):
        if self.vm.get_graphics_devices() or not self.vm.get_serial_devs():
            return

        self._populate_serial_menu()
        menu = self.widget("details-menu-view-serial-list").get_submenu()
        for child in menu.get_children():
            if isinstance(child, Gtk.SeparatorMenuItem):
                break
            if child.get_sensitive():
                child.toggled()
                break

    def _selected_serial_dev(self):
        current_page = self.widget("console-pages").get_current_page()
        if not current_page >= self.CONSOLE_PAGE_OFFSET:
            return

        serial_idx = current_page - self.CONSOLE_PAGE_OFFSET
        if len(self._serial_tabs) < serial_idx:
            return

        return self._serial_tabs[serial_idx]

    def _make_serial_menu_label(self, dev):
        if dev.virtual_device_type == "console":
            return "Text Console %d" % (dev.vmmindex + 1)
        return "Serial %d" % (dev.vmmindex + 1)

    def _console_menu_toggled(self, src, dev):
        ignore = src
        self.widget("details-pages").set_current_page(DETAILS_PAGE_CONSOLE)

        if dev.virtual_device_type == "graphics":
            self.widget("console-pages").set_current_page(self._last_gfx_page)
            return

        target_port = dev.vmmindex
        name = self._make_serial_menu_label(dev)
        serial = None
        for s in self._serial_tabs:
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
            self.widget("console-pages").append_page(serial.box, title)
            self._serial_tabs.append(serial)

        serial.open_console()
        page_idx = self._serial_tabs.index(serial) + self.CONSOLE_PAGE_OFFSET
        self.widget("console-pages").set_current_page(page_idx)

    def _build_serial_menu_items(self, menu_item_cb):
        showing_serial_dev = self._selected_serial_dev()
        devs = self.vm.get_serial_devs()

        if len(devs) == 0:
            menu_item_cb(_("No text console available"),
                         radio=False, sensitive=False)
            return

        for dev in devs:
            label = self._make_serial_menu_label(dev)
            tooltip = vmmSerialConsole.can_connect(self.vm, dev)
            sensitive = not bool(tooltip)

            active = (sensitive and
                showing_serial_dev and
                showing_serial_dev.name == label)

            menu_item_cb(label, sensitive=sensitive, active=active,
                tooltip=tooltip, cb=self._console_menu_toggled, cbdata=dev)

    def _build_graphical_menu_items(self, menu_item_cb):
        showing_graphics = (
            self.widget("console-pages").get_current_page() ==
            self.CONSOLE_PAGE_VIEWER)

        # Populate graphical devices
        devs = self.vm.get_graphics_devices()
        if len(devs) == 0:
            menu_item_cb(_("No graphical console available"),
                         radio=False, sensitive=False)
            return

        # Only one graphical device supported for now
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

            menu_item_cb(label, active=showing_graphics,
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
        return self._close_viewer()

    def details_activate_default_console_page(self):
        return self._activate_default_console_page()

    def details_update_widget_states(self, *args, **kwargs):
        return self._update_widget_states(*args, **kwargs)

    def details_build_keycombo_menu(self, *args, **kwargs):
        return self._build_keycombo_menu(*args, **kwargs)

    def details_refresh_can_fullscreen(self):
        return self._refresh_can_fullscreen()
    def details_resizeguest_ui_changed_cb(self, *args, **kwargs):
        return self._resizeguest_ui_changed_cb(*args, **kwargs)
    def details_send_key(self, *args, **kwargs):
        return self._do_send_key(*args, **kwargs)

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
        self.widget("console-pages").set_current_page(
            self.CONSOLE_PAGE_UNAVAILABLE)
        self._set_credentials()
        self._activate_viewer_page()
