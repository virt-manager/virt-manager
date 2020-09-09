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
from ..vmwindow import DETAILS_PAGE_CONSOLE


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
            return  # pragma: no cover

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

    def set_sensitive(self, can_sendkey):
        self._send_key_button.set_sensitive(can_sendkey)


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
                break


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
        self._keycombo_menu = build_keycombo_menu(self._do_send_key)

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

        self._consolemenu = _ConsoleMenu()
        self._serial_consoles = []
        self._init_menus()

        # Signals are added by vmmVMWindow. Don't use connect_signals here
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


    def _cleanup(self):
        self.vm = None

        if self._viewer:
            self._viewer.cleanup()
        self._viewer = None

        self._overlay_toolbar_fullscreen.cleanup()

        for serial in self._serial_consoles:
            serial.cleanup()
        self._serial_consoles = []


    ##########################
    # Initialization helpers #
    ##########################


    def _init_menus(self):
        # Serial list menu
        smenu = Gtk.Menu()
        smenu.connect("show", self._populate_serial_menu)
        self.widget("details-menu-view-console-list").set_submenu(smenu)

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
            if serial.has_focus():
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
            return  # pragma: no cover

        val = int(self.widget("details-menu-view-resizeguest").get_active())
        self.vm.set_console_resizeguest(val)
        self._sync_resizeguest_with_display()

    def _do_size_to_vm(self, src_ignore):
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
            self._overlay_toolbar_fullscreen.timed_revealer.force_reveal(True)
            self.widget("toolbar-box").hide()
            self.widget("details-menubar").hide()
        else:
            self._overlay_toolbar_fullscreen.timed_revealer.force_reveal(False)
            self.topwin.unfullscreen()

            if self.widget("details-menu-view-toolbar").get_active():
                self.widget("toolbar-box").show()
            self.widget("details-menubar").show()

        self._sync_scaling_with_display()


    ##########################
    # State tracking methods #
    ##########################

    def _show_vm_status_unavailable(self):
        if self.vm.is_crashed():  # pragma: no cover
            self._activate_unavailable_page(_("Guest has crashed."))
        else:
            self._activate_unavailable_page(_("Guest is not running."))

    def _close_viewer(self):
        self._leave_fullscreen()

        for serial in self._serial_consoles:
            serial.close()

        if self._viewer is None:
            return
        self._viewer.console_remove_display_from_widget(
            self.widget("console-gfx-viewport"))
        self._viewer.cleanup()
        self._viewer = None

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

        # Dispatch the next bit in idle_add, so the UI size can change
        self.idle_add(self._refresh_widget_states)

    def _refresh_widget_states(self):
        if not self.vm:
            # This is triggered via cleanup + idle_add, so vm might
            # disappear and spam the logs
            return  # pragma: no cover

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
        for c in self._keycombo_menu.get_children():
            c.set_sensitive(can_sendkey)
        self._overlay_toolbar_fullscreen.set_sensitive(can_sendkey)

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
            self._activate_unavailable_page(
                _("Graphical console not configured for guest"))
            return

        if ginfo.gtype not in self.config.embeddable_graphics():
            log.debug("Don't know how to show graphics type '%s' "
                          "disabling console page", ginfo.gtype)

            msg = (_("Cannot display graphical console type '%s'")
                     % ginfo.gtype)

            self._activate_unavailable_page(msg)
            return

        self._activate_unavailable_page(
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

            self._refresh_enable_accel()

            self._viewer.console_open()
        except Exception as e:
            log.exception("Error connection to graphical console")
            self._activate_unavailable_page(
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
            self._enable_modifiers()  # pragma: no cover
        elif self._someone_has_focus():
            self._disable_modifiers()
        else:
            self._enable_modifiers()

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
        self._refresh_resizeguest_from_settings()  # pragma: no cover

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

        self._activate_unavailable_page(msg)

    def _viewer_disconnected(self, ignore, errdetails, ssherr):
        self._activate_unavailable_page(_("Viewer disconnected."))
        log.debug("Viewer disconnected")

        # Make sure modifiers are set correctly
        self._viewer_focus_changed()

        self._viewer_disconnected_set_page(errdetails, ssherr)
        self._refresh_resizeguest_from_settings()

    def _viewer_connected(self, ignore):
        log.debug("Viewer connected")
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
        self._viewer.connect("need-auth", self._viewer_need_auth)
        self._viewer.connect("agent-connected", self._viewer_agent_connected)
        self._viewer.connect("usb-redirect-error",
            self._viewer_usb_redirect_error)


    ###########################
    # Serial console handling #
    ###########################

    def _activate_default_console_page(self):
        """
        Toggle default console page from the menu
        """
        # We iterate through the 'console' menu and activate the first
        # valid entry... hacky but it works
        self._populate_serial_menu()
        menu = self.widget("details-menu-view-console-list").get_submenu()
        self._consolemenu.activate_default(menu)

    def _console_menu_toggled(self, src, dev):
        self.widget("details-pages").set_current_page(DETAILS_PAGE_CONSOLE)

        if dev and dev.DEVICE_TYPE == "graphics":
            self.widget("console-pages").set_current_page(_CONSOLE_PAGE_VIEWER)
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
            serial.set_focus_callbacks(self._viewer_focus_changed,
                                       self._viewer_focus_changed)

            title = Gtk.Label(label=name)
            self.widget("serial-pages").append_page(serial.get_box(), title)
            self._serial_consoles.append(serial)

        serial.open_console()
        page_idx = self._serial_consoles.index(serial)
        self.widget("console-pages").set_current_page(_CONSOLE_PAGE_SERIAL)
        self.widget("serial-pages").set_current_page(page_idx)

    def _populate_serial_menu(self, ignore=None):
        submenu = self.widget("details-menu-view-console-list").get_submenu()
        self._consolemenu.rebuild_menu(
                self.vm, submenu, self._console_menu_toggled)



    ###########################
    # API used by vmmVMWindow #
    ###########################

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
