# Copyright (C) 2006-2008, 2015 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
# Copyright (C) 2010 Marc-Andre Lureau <marcandre.lureau@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk
from gi.repository import Gdk

from virtinst import log

from .serialcon import vmmSerialConsole
from .sshtunnels import ConnectionInfo
from .viewers import SpiceViewer, VNCViewer, have_spice_gtk
from ..baseclass import vmmGObject, vmmGObjectUI
from ..lib.keyring import vmmKeyring


# console-pages IDs
(_CONSOLE_PAGE_UNAVAILABLE,
 _CONSOLE_PAGE_SERIAL,
 _CONSOLE_PAGE_GRAPHICS) = range(3)

# console-gfx-pages IDs
(_GFX_PAGE_VIEWER,
 _GFX_PAGE_AUTH,
 _GFX_PAGE_UNAVAILABLE,
 _GFX_PAGE_CONNECT) = range(4)


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
            return  # pragma: no cover

        def cb():
            self._revealer.set_reveal_child(False)
            self._timeout_id = None
        self._timeout_id = self.timeout_add(timeout, cb)

    def _unregister_timeout(self):
        if self._timeout_id:  # pragma: no cover
            self.remove_gobject_timeout(self._timeout_id)
            self._timeout_id = None

    def force_reveal(self, val):
        self._unregister_timeout()
        self._in_fullscreen = val
        self._revealer.set_reveal_child(val)
        self._schedule_unreveal_timeout(2000)

    def get_overlay_widget(self):
        return self._ebox


def build_keycombo_menu(on_send_key_fn):
    menu = Gtk.Menu()

    def make_item(accel, combo):
        name = Gtk.accelerator_get_label(*Gtk.accelerator_parse(accel))
        item = Gtk.MenuItem(name)
        item.connect("activate", on_send_key_fn, combo)

        menu.add(item)

    make_item("<Control><Alt>BackSpace", ["Control_L", "Alt_L", "BackSpace"])
    make_item("<Control><Alt>Delete", ["Control_L", "Alt_L", "Delete"])
    menu.add(Gtk.SeparatorMenuItem())

    for i in range(1, 13):
        make_item("<Control><Alt>F%d" % i, ["Control_L", "Alt_L", "F%d" % i])
    menu.add(Gtk.SeparatorMenuItem())

    make_item("Print", ["Print"])

    menu.show_all()
    return menu


class vmmOverlayToolbar:
    def __init__(self, on_leave_fn, on_send_key_fn):
        self._send_key_button = None
        self._keycombo_menu = None
        self._toolbar = None

        self.timed_revealer = None
        self._init_ui(on_leave_fn, on_send_key_fn)

    def _init_ui(self, on_leave_fn, on_send_key_fn):
        self._keycombo_menu = build_keycombo_menu(on_send_key_fn)

        self._toolbar = Gtk.Toolbar()
        self._toolbar.set_show_arrow(False)
        self._toolbar.set_style(Gtk.ToolbarStyle.BOTH_HORIZ)
        self._toolbar.get_accessible().set_name("Fullscreen Toolbar")

        # Exit button
        button = Gtk.ToolButton.new_from_stock(Gtk.STOCK_LEAVE_FULLSCREEN)
        button.set_tooltip_text(_("Leave fullscreen"))
        button.show()
        button.get_accessible().set_name("Fullscreen Exit")
        self._toolbar.add(button)
        button.connect("clicked", on_leave_fn)

        self._send_key_button = Gtk.ToolButton()
        self._send_key_button.set_icon_name(
                                "preferences-desktop-keyboard-shortcuts")
        self._send_key_button.set_tooltip_text(_("Send key combination"))
        self._send_key_button.show_all()
        self._send_key_button.connect("clicked",
                self._on_send_key_button_clicked_cb)
        self._send_key_button.get_accessible().set_name("Fullscreen Send Key")
        self._toolbar.add(self._send_key_button)

        self.timed_revealer = _TimedRevealer(self._toolbar)

    def _on_send_key_button_clicked_cb(self, src):
        event = Gtk.get_current_event()
        win = self._toolbar.get_window()
        rect = Gdk.Rectangle()

        rect.y = win.get_height()
        self._keycombo_menu.popup_at_rect(win, rect,
                Gdk.Gravity.NORTH_WEST, Gdk.Gravity.NORTH_WEST, event)

    def cleanup(self):
        self._keycombo_menu.destroy()
        self._keycombo_menu = None
        self._toolbar.destroy()
        self._toolbar = None
        self.timed_revealer.cleanup()
        self.timed_revealer = None


class _ConsoleMenu:
    """
    Helper class for building the text/graphical console menu list
    """

    ################
    # Internal API #
    ################

    def _build_serial_menu_items(self, vm):
        devs = vmmSerialConsole.get_serialcon_devices(vm)
        if len(devs) == 0:
            return [[_("No text console available"), None, None]]

        ret = []
        for dev in devs:
            if dev.DEVICE_TYPE == "console":
                label = _("Text Console %d") % (dev.get_xml_idx() + 1)
            else:
                label = _("Serial %d") % (dev.get_xml_idx() + 1)

            tooltip = vmmSerialConsole.can_connect(vm, dev)
            ret.append([label, dev, tooltip])
        return ret

    def _build_graphical_menu_items(self, vm):
        devs = vm.xmlobj.devices.graphics
        if len(devs) == 0:
            return [[_("No graphical console available"), None, None]]

        from ..device.gfxdetails import vmmGraphicsDetails

        ret = []
        for idx, dev in enumerate(devs):
            label = (_("Graphical Console") + " " +
                     vmmGraphicsDetails.graphics_pretty_type_simple(dev.type))

            tooltip = None
            if idx > 0:
                label += " %s" % (idx + 1)
                tooltip = _("virt-manager does not support more "
                            "than one graphical console")

            ret.append([label, dev, tooltip])
        return ret


    ##############
    # Public API #
    ##############

    def rebuild_menu(self, vm, submenu, toggled_cb):
        oldlabel = None
        for child in submenu.get_children():
            if hasattr(child, 'get_active') and child.get_active():
                oldlabel = child.get_label()
            submenu.remove(child)

        graphics = self._build_graphical_menu_items(vm)
        serials = self._build_serial_menu_items(vm)

        # Use label == None to tell the loop to add a separator
        items = graphics + [[None, None, None]] + serials

        last_item = None
        for (label, dev, tooltip) in items:
            if label is None:
                submenu.add(Gtk.SeparatorMenuItem())
                continue

            cb = toggled_cb
            cbdata = dev
            sensitive = dev and not tooltip

            active = False
            if oldlabel is None and sensitive:
                # Select the first selectable option
                oldlabel = label
            if label == oldlabel:
                active = True

            item = Gtk.RadioMenuItem()
            if last_item is None:
                last_item = item
            else:
                item.join_group(last_item)

            item.set_label(label)
            item.set_active(active and sensitive)
            if cbdata and sensitive:
                item.connect("toggled", cb, cbdata)

            item.set_sensitive(sensitive)
            item.set_tooltip_text(tooltip or None)
            submenu.add(item)

        submenu.show_all()

    def activate_default(self, menu):
        for child in menu.get_children():
            if child.get_sensitive() and hasattr(child, "toggled"):
                child.toggled()
                return True
        return False


class vmmConsolePages(vmmGObjectUI):
    """
    Handles all the complex UI handling dictated by the spice/vnc widgets
    """
    __gsignals__ = {
        "page-changed": (vmmGObjectUI.RUN_FIRST, None, []),
        "leave-fullscreen": (vmmGObjectUI.RUN_FIRST, None, []),
        "change-title": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    def __init__(self, vm, builder, topwin):
        vmmGObjectUI.__init__(self, "console.ui",
                              None, builder=builder, topwin=topwin)

        self.vm = vm
        self.top_box = self.widget("console-pages")
        self._pointer_is_grabbed = False

        # State for disabling modifiers when keyboard is grabbed
        self._accel_groups = Gtk.accel_groups_from_object(self.topwin)
        self._gtk_settings_accel = None
        self._gtk_settings_mnemonic = None

        # Initialize display widget
        self._viewer = None
        self._viewer_connect_clicked = False
        self._in_fullscreen = False

        # Fullscreen toolbar
        self._keycombo_menu = build_keycombo_menu(self._do_send_key)
        self._console_list_menu = Gtk.Menu()
        self._console_list_menu.connect("show",
                self._populate_console_list_menu)

        self._overlay_toolbar_fullscreen = vmmOverlayToolbar(
            on_leave_fn=self._leave_fullscreen,
            on_send_key_fn=self._do_send_key)
        self.widget("console-overlay").add_overlay(
                self._overlay_toolbar_fullscreen.timed_revealer.get_overlay_widget())

        # Make viewer widget background always be black
        black = Gdk.Color(0, 0, 0)
        self.widget("console-gfx-viewport").modify_bg(Gtk.StateType.NORMAL,
                                                      black)

        self.widget("console-pages").set_show_tabs(False)
        self.widget("serial-pages").set_show_tabs(False)
        self.widget("console-gfx-pages").set_show_tabs(False)

        self._consolemenu = _ConsoleMenu()
        self._serial_consoles = []

        # Signals are added by vmmVMWindow. Don't use connect_signals here
        # or it changes will be overwritten

        self.builder.connect_signals({
            "on_console_pages_switch_page": self._page_changed_cb,
            "on_console_auth_password_activate": self._auth_login_cb,
            "on_console_auth_login_clicked": self._auth_login_cb,
            "on_console_connect_button_clicked": self._connect_button_clicked_cb,
        })

        self.widget("console-gfx-scroll").connect("size-allocate",
            self._scroll_size_allocate)
        self.widget("console-gfx-pages").connect("switch-page",
                self._page_changed_cb)


    def _cleanup(self):
        self.vm = None

        if self._viewer:
            self._viewer.cleanup()  # pragma: no cover
        self._viewer = None

        self._overlay_toolbar_fullscreen.cleanup()

        for serial in self._serial_consoles:
            serial.cleanup()
        self._serial_consoles = []


    #################
    # Internal APIs #
    #################

    def _disable_modifiers(self):
        if self._gtk_settings_accel is not None:
            return  # pragma: no cover

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

        res = self._viewer.console_get_desktop_resolution()
        if res is None:
            if not self.config.CLITestOptions.fake_console_resolution:
                return
            res = (800, 600)

        scroll = self.widget("console-gfx-scroll")
        is_scale = self._viewer.console_get_scaling()
        is_resizeguest = self._viewer.console_get_resizeguest()

        dx = 0
        dy = 0
        align_ratio = float(req.width) / float(req.height)

        # pylint: disable=unpacking-non-sequence
        desktop_w, desktop_h = res
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
            viewer_alloc = Gdk.Rectangle()
            viewer_alloc.width = req.width
            viewer_alloc.height = req.height
            self._viewer.console_size_allocate(viewer_alloc)
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
            dx = (req.width - desktop_w) // 2

        else:
            desktop_w = req.width
            desktop_h = int(req.width // desktop_ratio)
            dy = (req.height - desktop_h) // 2

        viewer_alloc = Gdk.Rectangle()
        viewer_alloc.x = dx
        viewer_alloc.y = dy
        viewer_alloc.width = desktop_w
        viewer_alloc.height = desktop_h
        self._viewer.console_size_allocate(viewer_alloc)

    def _viewer_get_resizeguest_tooltip(self):
        tooltip = ""
        if self._viewer:
            if self._viewer.viewer_type != "spice":
                tooltip = (
                    _("Graphics type '%s' does not support auto resize.") %
                    self._viewer.viewer_type)
            elif not self._viewer.console_has_agent():
                tooltip = _("Guest agent is not available.")
        return tooltip

    def _sync_resizeguest_with_display(self):
        if not self._viewer:
            return

        val = bool(self.vm.get_console_resizeguest())
        self._viewer.console_set_resizeguest(val)
        self.widget("console-gfx-scroll").queue_resize()

    def _set_size_to_vm(self):
        # Resize the console to best fit the VM resolution
        if not self._viewer:
            return  # pragma: no cover
        if not self._viewer.console_get_desktop_resolution():
            return  # pragma: no cover

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

    def _sync_scaling_with_display(self):
        if not self._viewer:
            return

        fs = self._in_fullscreen
        curscale = self._viewer.console_get_scaling()
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

    def _leave_fullscreen(self, ignore=None):
        self.emit("leave-fullscreen")

    def _change_fullscreen(self, do_fullscreen):
        if do_fullscreen:
            self._in_fullscreen = True
            self.topwin.fullscreen()
            self._overlay_toolbar_fullscreen.timed_revealer.force_reveal(True)
        else:
            self._in_fullscreen = False
            self._overlay_toolbar_fullscreen.timed_revealer.force_reveal(False)
            self.topwin.unfullscreen()

        self._sync_scaling_with_display()


    ##########################
    # State tracking methods #
    ##########################

    def _show_vm_status_unavailable(self):
        if self.vm.is_crashed():  # pragma: no cover
            self._activate_vm_unavailable_page(_("Guest has crashed."))
        else:
            self._activate_vm_unavailable_page(_("Guest is not running."))

    def _close_viewer(self):
        self._leave_fullscreen()
        self._viewer_connect_clicked = False

        for serial in self._serial_consoles:
            serial.close()

        if self._viewer is None:
            return
        self._viewer.console_remove_display_from_widget(
            self.widget("console-gfx-viewport"))
        self._viewer.cleanup()
        self._viewer = None
        log.debug("Viewer disconnected")

    def _refresh_vm_state(self):
        self._activate_default_console_page()


    ###########################
    # console page navigation #
    ###########################

    def _activate_gfx_unavailable_page(self, msg):
        self._close_viewer()
        self.widget("console-gfx-pages").set_current_page(
                _GFX_PAGE_UNAVAILABLE)
        if msg:
            self.widget("console-gfx-unavailable").set_label(
                    "<b>" + msg + "</b>")

    def _activate_vm_unavailable_page(self, msg):
        """
        This is the top level error page. We should only set it for very
        specific error cases, because when it is set and the VM is running
        we take that to mean we should attempt to connect to the default
        console.
        """
        self._close_viewer()
        self.widget("console-pages").set_current_page(
                _CONSOLE_PAGE_UNAVAILABLE)
        if msg:
            self.widget("console-unavailable").set_label(
                    "<b>" + msg + "</b>")
        self._activate_gfx_unavailable_page(msg)

    def _activate_auth_page(self, withPassword, withUsername):
        (pw, username) = vmmKeyring.get_instance().get_console_password(self.vm)

        self.widget("console-auth-password").set_visible(withPassword)
        self.widget("label-auth-password").set_visible(withPassword)

        self.widget("console-auth-username").set_visible(withUsername)
        self.widget("label-auth-username").set_visible(withUsername)

        self.widget("console-auth-username").set_text(username)
        self.widget("console-auth-password").set_text(pw)

        has_keyring = vmmKeyring.get_instance().is_available()
        remember = bool(withPassword and pw) or (withUsername and username)
        remember = has_keyring and remember
        self.widget("console-auth-remember").set_sensitive(has_keyring)
        self.widget("console-auth-remember").set_active(remember)

        self.widget("console-gfx-pages").set_current_page(_GFX_PAGE_AUTH)

        if withUsername:
            self.widget("console-auth-username").grab_focus()
        else:
            self.widget("console-auth-password").grab_focus()

    def _activate_gfx_viewer_page(self):
        self.widget("console-pages").set_current_page(_CONSOLE_PAGE_GRAPHICS)
        self.widget("console-gfx-pages").set_current_page(_GFX_PAGE_VIEWER)
        if self._viewer:
            self._viewer.console_grab_focus()

    def _activate_gfx_connect_page(self):
        self.widget("console-gfx-pages").set_current_page(_GFX_PAGE_CONNECT)

    def _viewer_is_visible(self):
        is_visible = self.widget("console-pages").is_visible()
        cpage = self.widget("console-pages").get_current_page()
        gpage = self.widget("console-gfx-pages").get_current_page()

        return bool(
            is_visible and
            cpage == _CONSOLE_PAGE_GRAPHICS and
            gpage == _GFX_PAGE_VIEWER and
            self._viewer and self._viewer.console_is_open())

    def _viewer_can_auto_clipboard(self):
        return (self._viewer_is_visible() and
                self._viewer.console_has_auto_clipboard() and
                self.vm.has_spicevmc_type_channel())

    def _viewer_can_usb_redirect(self):
        return (self._viewer_is_visible() and
                self._viewer.console_has_usb_redirection() and
                self.vm.has_spicevmc_type_redirdev())


    #########################
    # Viewer login attempts #
    #########################

    def _init_viewer(self):
        if self._viewer or not self.is_visible():
            # Don't try and login for these cases
            return

        ginfo = None
        try:
            gdevs = self.vm.xmlobj.devices.graphics
            gdev = gdevs and gdevs[0] or None
            if gdev:
                ginfo = ConnectionInfo(self.vm.conn, gdev)
        except Exception as e:  # pragma: no cover
            # We can fail here if VM is destroyed: xen is a bit racy
            # and can't handle domain lookups that soon after
            log.exception("Getting graphics console failed: %s", str(e))
            return

        if ginfo is None:
            log.debug("No graphics configured for guest")
            self._activate_gfx_unavailable_page(
                _("Graphical console not configured for guest"))
            return

        if ginfo.gtype not in self.config.embeddable_graphics():
            log.debug("Don't know how to show graphics type '%s' "
                          "disabling console page", ginfo.gtype)

            msg = (_("Cannot display graphical console type '%s'")
                     % ginfo.gtype)

            self._activate_gfx_unavailable_page(msg)
            return

        if (not self.vm.get_console_autoconnect() and
            not self._viewer_connect_clicked):
            self._activate_gfx_connect_page()
            return

        self._activate_gfx_unavailable_page(
            _("Connecting to graphical console for guest"))

        log.debug("Starting connect process for %s", ginfo.logstring())
        try:
            if ginfo.gtype == "vnc":
                viewer_class = VNCViewer
            elif ginfo.gtype == "spice":
                if not have_spice_gtk:  # pragma: no cover
                    raise RuntimeError("Error opening Spice console, "
                                       "SpiceClientGtk missing")
                viewer_class = SpiceViewer

            self._viewer = viewer_class(self.vm, ginfo)
            self._connect_viewer_signals()

            self._viewer.console_open()
            self._viewer.console_set_auto_clipboard(self.vm.get_console_auto_clipboard())
        except Exception as e:
            log.exception("Error connecting to graphical console")
            self._activate_gfx_unavailable_page(
                    _("Error connecting to graphical console:\n%s") % e)

    def _set_credentials(self, src_ignore=None):
        passwd = self.widget("console-auth-password")
        username = self.widget("console-auth-username")

        if passwd.get_visible():
            self._viewer.console_set_password(passwd.get_text())
        if username.get_visible():
            self._viewer.console_set_username(username.get_text())

        if self.widget("console-auth-remember").get_active():
            vmmKeyring.get_instance().set_console_password(
                    self.vm, passwd.get_text(), username.get_text())
        else:
            vmmKeyring.get_instance().del_console_password(self.vm)


    ##########################
    # Viewer signal handling #
    ##########################

    def _viewer_add_display(self, ignore, display):
        self.widget("console-gfx-viewport").add(display)

        # Sync initial settings
        self._sync_scaling_with_display()
        self._sync_resizeguest_with_display()

    def _pointer_grabbed(self, ignore):
        self._pointer_is_grabbed = True
        self.emit("change-title")

    def _pointer_ungrabbed(self, ignore):
        self._pointer_is_grabbed = False
        self.emit("change-title")

    def _viewer_allocate_cb(self, src, ignore):
        self.widget("console-gfx-scroll").queue_resize()

    def _viewer_keyboard_grab_cb(self, src):
        self._viewer_sync_modifiers()

    def _serial_focus_changed_cb(self, src, event):
        self._viewer_sync_modifiers()

    def _viewer_sync_modifiers(self):
        serial_has_focus = any([s.has_focus() for s in self._serial_consoles])
        viewer_keyboard_grab = (self._viewer and
                self._viewer.console_has_keyboard_grab())

        if serial_has_focus or viewer_keyboard_grab:
            self._disable_modifiers()
        else:
            self._enable_modifiers()

    def _viewer_auth_error(self, ignore, errmsg, viewer_will_disconnect):
        errmsg = _("Viewer authentication error: %s") % errmsg
        self.err.val_err(errmsg)

        if viewer_will_disconnect:
            # GtkVNC will disconnect after an auth error, so lets do it for
            # them and re-init the viewer (which will be triggered by
            # _refresh_vm_state if needed)
            self._activate_vm_unavailable_page(errmsg)

        self._refresh_vm_state()

    def _viewer_need_auth(self, ignore, withPassword, withUsername):
        self._activate_auth_page(withPassword, withUsername)

    def _viewer_agent_connected(self, ignore):
        # Tell the vmwindow to trigger a state refresh, since
        # resizeguest setting depends on the agent value
        if self.widget("console-pages").is_visible():  # pragma: no cover
            self.emit("page-changed")

    def _viewer_usb_redirect_error(self, ignore, errstr):
        self.err.show_err(
                _("USB redirection error"),
                text2=str(errstr), modal=True)  # pragma: no cover

    def _viewer_disconnected_set_page(self, errdetails, ssherr):
        if self.vm.is_runable():  # pragma: no cover
            # Exit was probably for legitimate reasons
            self._show_vm_status_unavailable()
            return

        msg = _("Viewer was disconnected.")
        if errdetails:
            msg += "\n" + errdetails
        if ssherr:
            log.debug("SSH tunnel error output: %s", ssherr)
            msg += "\n\n"
            msg += _("SSH tunnel error output: %s") % ssherr

        self._activate_gfx_unavailable_page(msg)

    def _viewer_disconnected(self, ignore, errdetails, ssherr):
        self._activate_gfx_unavailable_page(_("Viewer disconnected."))
        log.debug("Viewer disconnected")

        # Make sure modifiers are set correctly
        self._viewer_sync_modifiers()

        self._viewer_disconnected_set_page(errdetails, ssherr)

    def _viewer_connected(self, ignore):
        log.debug("Viewer connected")
        self._activate_gfx_viewer_page()

        # Make sure modifiers are set correctly
        self._viewer_sync_modifiers()

    def _connect_viewer_signals(self):
        self._viewer.connect("add-display-widget", self._viewer_add_display)
        self._viewer.connect("pointer-grab", self._pointer_grabbed)
        self._viewer.connect("pointer-ungrab", self._pointer_ungrabbed)
        self._viewer.connect("size-allocate", self._viewer_allocate_cb)
        self._viewer.connect("keyboard-grab", self._viewer_keyboard_grab_cb)
        self._viewer.connect("keyboard-ungrab", self._viewer_keyboard_grab_cb)
        self._viewer.connect("connected", self._viewer_connected)
        self._viewer.connect("disconnected", self._viewer_disconnected)
        self._viewer.connect("auth-error", self._viewer_auth_error)
        self._viewer.connect("need-auth", self._viewer_need_auth)
        self._viewer.connect("agent-connected", self._viewer_agent_connected)
        self._viewer.connect("usb-redirect-error",
            self._viewer_usb_redirect_error)


    ##############################
    # Console list menu handling #
    ##############################

    def _console_list_menu_toggled(self, src, dev):
        if not dev or dev.DEVICE_TYPE == "graphics":
            self.widget("console-pages").set_current_page(
                    _CONSOLE_PAGE_GRAPHICS)
            self.idle_add(self._init_viewer)
            return

        target_port = dev.get_xml_idx()
        serial = None
        name = src.get_label()
        for s in self._serial_consoles:
            if s.name == name:
                serial = s
                break

        if not serial:
            serial = vmmSerialConsole(self.vm, target_port, name)
            serial.set_focus_callbacks(self._serial_focus_changed_cb,
                                       self._serial_focus_changed_cb)

            title = Gtk.Label(label=name)
            self.widget("serial-pages").append_page(serial.get_box(), title)
            self._serial_consoles.append(serial)

        serial.open_console()
        page_idx = self._serial_consoles.index(serial)
        self.widget("console-pages").set_current_page(_CONSOLE_PAGE_SERIAL)
        self.widget("serial-pages").set_current_page(page_idx)

    def _populate_console_list_menu(self, ignore=None):
        self._consolemenu.rebuild_menu(
                self.vm, self._console_list_menu,
                self._console_list_menu_toggled)

    def _toggle_first_console_menu_item(self):
        # We iterate through the 'console' menu and activate the first
        # valid entry... hacky but it works
        self._populate_console_list_menu()
        found = self._consolemenu.activate_default(self._console_list_menu)
        if not found:
            # Calling this with dev=None will trigger _init_viewer
            # which shows some meaningful errors
            self._console_list_menu_toggled(None, None)

    def _activate_default_console_page(self):
        if self.vm.is_runable():
            self._show_vm_status_unavailable()
            return

        viewer_initialized = (self._viewer and self._viewer.console_is_open())
        if viewer_initialized:
            return

        cpage = self.widget("console-pages").get_current_page()
        if cpage != _CONSOLE_PAGE_UNAVAILABLE:
            return

        # If we are in this condition it should mean the VM was
        # just started, so connect to the default page
        self._toggle_first_console_menu_item()


    ################
    # UI listeners #
    ################

    def _auth_login_cb(self, src):
        self._set_credentials()

    def _connect_button_clicked_cb(self, src):
        self._viewer_connect_clicked = True
        self._init_viewer()

    def _page_changed_cb(self, src, origpage, newpage):
        # Hide the contents of all other pages, so they don't screw
        # up window sizing
        for i in range(src.get_n_pages()):
            src.get_nth_page(i).set_visible(i == newpage)

        # Dispatch the next bit in idle_add, so the UI size can change
        self.idle_emit("page-changed")


    ###########################
    # API used by vmmVMWindow #
    ###########################

    def vmwindow_get_can_auto_clipboard(self):
        return self._viewer_can_auto_clipboard()
    def vmwindow_viewer_set_auto_clipboard(self, enabled):
        self._viewer.console_set_auto_clipboard(enabled)

    def vmwindow_viewer_has_usb_redirection(self):
        return bool(self._viewer and
            self._viewer.console_has_usb_redirection())
    def vmwindow_viewer_get_usb_widget(self):
        return self._viewer.console_get_usb_widget()
    def vmwindow_viewer_get_pixbuf(self):
        return self._viewer.console_get_pixbuf()

    def vmwindow_close(self):
        return self._activate_vm_unavailable_page(
                _("Viewer disconnected."))
    def vmwindow_get_title_message(self):
        if self._pointer_is_grabbed and self._viewer:
            keystr = self._viewer.console_get_grab_keys()
            return _("Press %s to release pointer.") % keystr

    def vmwindow_activate_default_console_page(self):
        return self._activate_default_console_page()
    def vmwindow_refresh_vm_state(self):
        return self._refresh_vm_state()

    def vmwindow_set_size_to_vm(self):
        return self._set_size_to_vm()
    def vmwindow_set_fullscreen(self, do_fullscreen):
        self._change_fullscreen(do_fullscreen)

    def vmwindow_get_keycombo_menu(self):
        return self._keycombo_menu
    def vmwindow_get_console_list_menu(self):
        return self._console_list_menu
    def vmwindow_get_viewer_is_visible(self):
        return self._viewer_is_visible()
    def vmwindow_get_can_usb_redirect(self):
        return self._viewer_can_usb_redirect()
    def vmwindow_get_resizeguest_tooltip(self):
        return self._viewer_get_resizeguest_tooltip()

    def vmwindow_sync_scaling_with_display(self):
        return self._sync_scaling_with_display()
    def vmwindow_sync_resizeguest_with_display(self):
        return self._sync_resizeguest_with_display()
