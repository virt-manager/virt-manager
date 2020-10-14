# Copyright (C) 2006-2008, 2013, 2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gdk
from gi.repository import Gtk

from virtinst import log

from . import vmmenu
from .baseclass import vmmGObjectUI
from .engine import vmmEngine
from .details.console import vmmConsolePages
from .details.details import vmmDetails
from .details.snapshots import vmmSnapshotPage


# Main tab pages
(DETAILS_PAGE_DETAILS,
 DETAILS_PAGE_CONSOLE,
 DETAILS_PAGE_SNAPSHOTS) = range(3)


class vmmVMWindow(vmmGObjectUI):
    __gsignals__ = {
        "customize-finished": (vmmGObjectUI.RUN_FIRST, None, [object]),
        "closed": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    @classmethod
    def get_instance(cls, parentobj, vm):
        try:
            # Maintain one dialog per VM
            key = "%s+%s" % (vm.conn.get_uri(), vm.get_uuid())
            if cls._instances is None:
                cls._instances = {}
            if key not in cls._instances:
                cls._instances[key] = vmmVMWindow(vm)
            return cls._instances[key]
        except Exception as e:  # pragma: no cover
            if not parentobj:
                raise
            parentobj.err.show_err(
                    _("Error launching details: %s") % str(e))

    def __init__(self, vm, parent=None):
        vmmGObjectUI.__init__(self, "vmwindow.ui", "vmm-vmwindow")
        self.vm = vm

        self.is_customize_dialog = False
        if parent:
            # Details window is being abused as a 'configure before install'
            # dialog, set things as appropriate
            self.is_customize_dialog = True
            self.topwin.set_type_hint(Gdk.WindowTypeHint.DIALOG)
            self.topwin.set_transient_for(parent)

            self.widget("toolbar-box").show()
            self.widget("customize-toolbar").show()
            self.widget("details-toolbar").hide()
            self.widget("details-menubar").hide()
            pages = self.widget("details-pages")
            pages.set_current_page(DETAILS_PAGE_DETAILS)
        else:
            self.conn.connect("vm-removed", self._vm_removed_cb)

        self.ignoreDetails = False

        self._console = vmmConsolePages(self.vm, self.builder, self.topwin)
        self.widget("console-placeholder").add(self._console.top_box)
        self._console.connect("page-changed", self._console_page_changed_cb)
        self._console.connect("leave-fullscreen",
                self._console_leave_fullscreen_cb)
        self._console.connect("change-title",
                self._console_change_title_cb)

        self._snapshots = vmmSnapshotPage(self.vm, self.builder, self.topwin)
        self.widget("snapshot-placeholder").add(self._snapshots.top_box)

        self._details = vmmDetails(self.vm, self.builder, self.topwin,
                self.is_customize_dialog)
        self.widget("details-placeholder").add(self._details.top_box)

        # Set default window size
        w, h = self.vm.get_details_window_size()
        if w <= 0 or h <= 0:
            self._set_initial_window_size()
        else:
            self.topwin.set_default_size(w, h)
        self._window_size = None

        self._shutdownmenu = None
        self._vmmenu = None
        self.init_menus()

        self.builder.connect_signals({
            "on_close_details_clicked": self.close,
            "on_details_menu_close_activate": self.close,
            "on_vmm_details_delete_event": self._window_delete_event,
            "on_vmm_details_configure_event": self.window_resized,
            "on_details_menu_quit_activate": self.exit_app,

            "on_control_vm_details_toggled": self.details_console_changed,
            "on_control_vm_console_toggled": self.details_console_changed,
            "on_control_snapshots_toggled": self.details_console_changed,
            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,
            "on_control_fullscreen_toggled": self.control_fullscreen,

            "on_details_customize_finish_clicked": self.customize_finish,
            "on_details_cancel_customize_clicked": self._customize_cancel_clicked,

            "on_details_menu_virtual_manager_activate": self.control_vm_menu,
            "on_details_menu_screenshot_activate": self.control_vm_screenshot,
            "on_details_menu_usb_redirection": self.control_vm_usb_redirection,
            "on_details_menu_autoclipboard_toggled": self.control_vm_auto_clipboard,
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_manager_activate": self.view_manager,
            "on_details_menu_view_details_toggled": self.details_console_changed,
            "on_details_menu_view_console_toggled": self.details_console_changed,
            "on_details_menu_view_snapshots_toggled": self.details_console_changed,

            "on_details_pages_switch_page": self._details_page_switch_cb,

            "on_details_menu_view_fullscreen_activate": self._fullscreen_changed_cb,
            "on_details_menu_view_size_to_vm_activate": self._size_to_vm_cb,
            "on_details_menu_view_scale_always_toggled": self._scaling_ui_changed_cb,
            "on_details_menu_view_scale_fullscreen_toggled": self._scaling_ui_changed_cb,
            "on_details_menu_view_scale_never_toggled": self._scaling_ui_changed_cb,
            "on_details_menu_view_resizeguest_toggled": self._resizeguest_ui_changed_cb,
            "on_details_menu_view_autoconnect_activate": self._autoconnect_ui_changed_cb,
        })

        # Deliberately keep all this after signal connection
        self.vm.connect("state-changed", self._vm_state_changed_cb)
        self.vm.connect("resources-sampled", self._resources_sampled_cb)

        self._sync_console_page_menu_state()

        self._console_refresh_scaling_from_settings()
        self.add_gsettings_handle(
            self.vm.on_console_scaling_changed(
                self._console_refresh_scaling_from_settings))

        self._console_refresh_resizeguest_from_settings()
        self.add_gsettings_handle(
            self.vm.on_console_resizeguest_changed(
                self._console_refresh_resizeguest_from_settings))

        self._console_refresh_autoconnect_from_settings()
        self.add_gsettings_handle(
            self.vm.on_console_autoconnect_changed(
                self._console_refresh_autoconnect_from_settings))

        self._console_refresh_auto_clipboard_from_settings()
        self.add_gsettings_handle(
            self.vm.on_console_auto_clipboard_changed(
                self._console_refresh_auto_clipboard_from_settings))

        self._refresh_vm_state()
        self.activate_default_page()


    @property
    def conn(self):
        return self.vm.conn

    def _cleanup(self):
        self._console.cleanup()
        self._console = None
        self._snapshots.cleanup()
        self._snapshots = None
        self._details.cleanup()
        self._details = None
        self._shutdownmenu.destroy()
        self._shutdownmenu = None
        self._vmmenu.destroy()
        self._vmmenu = None

        if self._window_size:
            self.vm.set_details_window_size(*self._window_size)

        self.conn.disconnect_by_obj(self)
        self.vm = None

    def show(self):
        log.debug("Showing VM details: %s", self.vm)
        vis = self.is_visible()
        self.topwin.present()
        if vis:
            return

        vmmEngine.get_instance().increment_window_counter()
        self._refresh_vm_state()

    def customize_finish(self, src):
        ignore = src
        if self._details.vmwindow_has_unapplied_changes():
            return
        self.emit("customize-finished", self.vm)

    def _set_initial_window_size(self):
        """
        We want the window size for new windows to be 1024x768 viewer
        size, plus whatever it takes to fit the toolbar+menubar, etc.
        To achieve this, we force the display box to the desired size
        with set_size_request, wait for the window to report it has
        been resized, and then unset the hardcoded size request so
        the user can manually resize the window however they want.
        """
        w = 1024
        h = 768
        hid = []
        def win_cb(src, event):
            self.widget("details-pages").set_size_request(-1, -1)
            self.topwin.disconnect(hid[0])
        self.widget("details-pages").set_size_request(w, h)
        hid.append(self.topwin.connect("configure-event", win_cb))

    def _vm_removed_cb(self, _conn, vm):
        if self.vm == vm:
            self.cleanup()

    def _customize_cancel(self):
        log.debug("Asking to cancel customization")

        result = self.err.yes_no(
            _("This will abort the installation. Are you sure?"))
        if not result:
            log.debug("Customize cancel aborted")
            return

        log.debug("Canceling customization")
        return self._close()

    def _customize_cancel_clicked(self, src):
        ignore = src
        return self._customize_cancel()

    def _window_delete_event(self, ignore1=None, ignore2=None):
        return self.close()

    def close(self, ignore1=None, ignore2=None):
        if self.is_visible():
            log.debug("Closing VM details: %s", self.vm)
        return self._close()

    def _close(self):
        fs = self.widget("details-menu-view-fullscreen")
        if fs.get_active():
            fs.set_active(False)  # pragma: no cover

        if not self.is_visible():
            return

        self.topwin.hide()
        self._console.vmwindow_close()
        self._details.vmwindow_close()

        self.emit("closed")
        vmmEngine.get_instance().decrement_window_counter()
        return 1


    ##########################
    # Initialization helpers #
    ##########################

    def init_menus(self):
        # Virtual Machine menu
        self._shutdownmenu = vmmenu.VMShutdownMenu(self, lambda: self.vm)
        self.widget("control-shutdown").set_menu(self._shutdownmenu)
        self.widget("control-shutdown").set_icon_name("system-shutdown")

        topmenu = self.widget("details-vm-menu")
        submenu = topmenu.get_submenu()
        self._vmmenu = vmmenu.VMActionMenu(
                self, lambda: self.vm, show_open=False)
        for child in submenu.get_children():
            submenu.remove(child)
            self._vmmenu.add(child)
        topmenu.set_submenu(self._vmmenu)
        topmenu.show_all()

        self.widget("details-pages").set_show_tabs(False)
        self.widget("details-menu-view-toolbar").set_active(
                                    self.config.get_details_show_toolbar())

        # Keycombo menu (ctrl+alt+del etc.)
        self.widget("details-menu-send-key").set_submenu(
                self._console.vmwindow_get_keycombo_menu())

        # Serial list menu
        self.widget("details-menu-view-console-list").set_submenu(
                self._console.vmwindow_get_console_list_menu())


    ##########################
    # Window state listeners #
    ##########################

    def window_resized(self, ignore, ignore2):
        if not self.is_visible():
            return  # pragma: no cover
        self._window_size = self.topwin.get_size()

    def control_fullscreen(self, src):
        menu = self.widget("details-menu-view-fullscreen")
        if src.get_active() != menu.get_active():
            menu.set_active(src.get_active())

    def toggle_toolbar(self, src):
        if self.is_customize_dialog:
            return

        active = src.get_active()
        self.config.set_details_show_toolbar(active)
        fsactive = self.widget("details-menu-view-fullscreen").get_active()
        self.widget("toolbar-box").set_visible(active and not fsactive)

    def details_console_changed(self, src):
        if self.ignoreDetails:
            return

        if not src.get_active():
            return

        is_details = (src == self.widget("control-vm-details") or
                      src == self.widget("details-menu-view-details"))
        is_snapshot = (src == self.widget("control-snapshots") or
                       src == self.widget("details-menu-view-snapshots"))

        pages = self.widget("details-pages")
        if pages.get_current_page() == DETAILS_PAGE_DETAILS:
            if self._details.vmwindow_has_unapplied_changes():
                self._sync_toolbar_page_buttons(pages.get_current_page())
                return

        if is_details:
            pages.set_current_page(DETAILS_PAGE_DETAILS)
        elif is_snapshot:
            pages.set_current_page(DETAILS_PAGE_SNAPSHOTS)
        else:
            pages.set_current_page(DETAILS_PAGE_CONSOLE)

    def _sync_toolbar_page_buttons(self, newpage):
        details = self.widget("control-vm-details")
        details_menu = self.widget("details-menu-view-details")
        console = self.widget("control-vm-console")
        console_menu = self.widget("details-menu-view-console")
        snapshot = self.widget("control-snapshots")
        snapshot_menu = self.widget("details-menu-view-snapshots")

        is_details = newpage == DETAILS_PAGE_DETAILS
        is_snapshot = newpage == DETAILS_PAGE_SNAPSHOTS
        is_console = not is_details and not is_snapshot

        try:
            self.ignoreDetails = True

            details.set_active(is_details)
            details_menu.set_active(is_details)
            snapshot.set_active(is_snapshot)
            snapshot_menu.set_active(is_snapshot)
            console.set_active(is_console)
            console_menu.set_active(is_console)
        finally:
            self.ignoreDetails = False

    def _details_page_switch_cb(self, notebook, pagewidget, newpage):
        for i in range(notebook.get_n_pages()):
            w = notebook.get_nth_page(i)
            w.set_visible(i == newpage)

        self._refresh_current_page(newpage)
        self._sync_toolbar_page_buttons(newpage)
        self._sync_console_page_menu_state()

    def change_run_text(self, can_restore):
        if can_restore:
            text = _("_Restore")
        else:
            text = _("_Run")
        strip_text = text.replace("_", "")

        self.widget("details-vm-menu").get_submenu().change_run_text(text)
        self.widget("control-run").set_label(strip_text)

    def _refresh_title(self):
        title = (_("%(vm-name)s on %(connection-name)s") % {
            "vm-name": self.vm.get_name_or_title(),
            "connection-name": self.vm.conn.get_pretty_desc(),
        })

        grabmsg = self._console.vmwindow_get_title_message()
        if grabmsg:
            title = grabmsg + " " + title

        self.topwin.set_title(title)

    def _refresh_vm_state(self):
        vm = self.vm
        self._refresh_title()

        self.widget("details-menu-view-toolbar").set_active(
            self.config.get_details_show_toolbar())
        self.toggle_toolbar(self.widget("details-menu-view-toolbar"))

        run = vm.is_runable()
        stop = vm.is_stoppable()
        paused = vm.is_paused()

        if vm.managedsave_supported:
            self.change_run_text(vm.has_managed_save())

        self.widget("control-run").set_sensitive(run)
        self.widget("control-shutdown").set_sensitive(stop)
        self.widget("control-shutdown").get_menu().update_widget_states(vm)
        self.widget("control-pause").set_sensitive(stop)

        if paused:
            pauseTooltip = _("Resume the virtual machine")
        else:
            pauseTooltip = _("Pause the virtual machine")
        self.widget("control-pause").set_tooltip_text(pauseTooltip)

        self.widget("details-vm-menu").get_submenu().update_widget_states(vm)
        self.set_pause_state(paused)

        errmsg = self.vm.snapshots_supported()
        cansnap = not bool(errmsg)
        self.widget("control-snapshots").set_sensitive(cansnap)
        self.widget("details-menu-view-snapshots").set_sensitive(cansnap)
        tooltip = _("Manage VM snapshots")
        if not cansnap:
            tooltip += "\n" + errmsg
        self.widget("control-snapshots").set_tooltip_text(tooltip)

        self._refresh_current_page()


    #############################
    # External action listeners #
    #############################

    def view_manager(self, _src):
        from .manager import vmmManager
        vmmManager.get_instance(self).show()

    def exit_app(self, _src):
        vmmEngine.get_instance().exit_app()

    def activate_default_console_page(self):
        self._console.vmwindow_activate_default_console_page()

    # activate_* are called from engine.py via CLI options
    def activate_default_page(self):
        if self.is_customize_dialog:
            return
        pages = self.widget("details-pages")
        pages.set_current_page(DETAILS_PAGE_CONSOLE)
        self.activate_default_console_page()

    def activate_console_page(self):
        pages = self.widget("details-pages")
        pages.set_current_page(DETAILS_PAGE_CONSOLE)

    def activate_performance_page(self):
        self.widget("details-pages").set_current_page(DETAILS_PAGE_DETAILS)
        self._details.vmwindow_activate_performance_page()

    def activate_config_page(self):
        self.widget("details-pages").set_current_page(DETAILS_PAGE_DETAILS)

    def set_pause_state(self, state):
        src = self.widget("control-pause")
        try:
            src.handler_block_by_func(self.control_vm_pause)
            src.set_active(state)
        finally:
            src.handler_unblock_by_func(self.control_vm_pause)

    def control_vm_pause(self, src):
        do_pause = src.get_active()

        # Set button state back to original value: just let the status
        # update function fix things for us
        self.set_pause_state(not do_pause)

        if do_pause:
            vmmenu.VMActionUI.suspend(self, self.vm)
        else:
            vmmenu.VMActionUI.resume(self, self.vm)

    def control_vm_menu(self, src_ignore):
        can_auto_clipboard = bool(self.vm.has_spicevmc_type_channel() and
                                  self._console.vmwindow_get_can_auto_clipboard())
        self.widget("details-menu-auto-clipboard").set_sensitive(can_auto_clipboard)

        can_usb = bool(self.vm.has_spicevmc_type_redirdev() and
                       self._console.vmwindow_viewer_has_usb_redirection())
        self.widget("details-menu-usb-redirection").set_sensitive(can_usb)

    def control_vm_run(self, src_ignore):
        if self._details.vmwindow_has_unapplied_changes():
            return
        vmmenu.VMActionUI.run(self, self.vm)

    def control_vm_shutdown(self, src_ignore):
        vmmenu.VMActionUI.shutdown(self, self.vm)

    def control_vm_screenshot(self, src):
        ignore = src
        try:
            return self._take_screenshot()
        except Exception as e:  # pragma: no cover
            self.err.show_err(_("Error taking screenshot: %s") % str(e))

    def control_vm_usb_redirection(self, src):
        ignore = src
        spice_usbdev_dialog = self.err

        spice_usbdev_widget = self._console.vmwindow_viewer_get_usb_widget()
        if not spice_usbdev_widget:  # pragma: no cover
            self.err.show_err(_("Error initializing spice USB device widget"))
            return

        spice_usbdev_widget.show()
        spice_usbdev_dialog.show_info(_("Select USB devices for redirection"),
                                      widget=spice_usbdev_widget,
                                      buttons=Gtk.ButtonsType.CLOSE)

    def control_vm_auto_clipboard(self, src):
        if not src.get_sensitive():
            return  # pragma: no cover

        val = bool(self.widget("details-menu-auto-clipboard").get_active())
        self.vm.set_console_auto_clipboard(val)
        self._console.vmwindow_viewer_set_auto_clipboard(val)

    def _take_screenshot(self):
        image = self._console.vmwindow_viewer_get_pixbuf()

        metadata = {
            'tEXt::Hypervisor URI': self.vm.conn.get_uri(),
            'tEXt::Domain Name': self.vm.get_name(),
            'tEXt::Domain UUID': self.vm.get_uuid(),
            'tEXt::Generator App': self.config.get_appname(),
            'tEXt::Generator Version': self.config.get_appversion(),
        }

        ret = image.save_to_bufferv(
            'png', list(metadata.keys()), list(metadata.values())
        )
        # On Fedora 19, ret is (bool, str)
        # Someday the bindings might be fixed to just return the str, try
        # and future proof it a bit
        if isinstance(ret, tuple) and len(ret) >= 2:
            ret = ret[1]
        # F24 rawhide, ret[1] is a named tuple with a 'buffer' element...
        if hasattr(ret, "buffer"):
            ret = ret.buffer  # pragma: no cover

        import datetime
        now = str(datetime.datetime.now()).split(".")[0].replace(" ", "_")
        default = "Screenshot_%s_%s.png" % (self.vm.get_name(), now)

        path = self.err.browse_local(
            self.vm.conn, _("Save Virtual Machine Screenshot"),
            _type=("png", _("PNG files")),
            dialog_type=Gtk.FileChooserAction.SAVE,
            browse_reason=self.config.CONFIG_DIR_SCREENSHOT,
            default_name=default)
        if not path:  # pragma: no cover
            log.debug("No screenshot path given, skipping save.")
            return

        filename = path
        if not filename.endswith(".png"):
            filename += ".png"  # pragma: no cover
        open(filename, "wb").write(ret)


    ########################
    # Details page refresh #
    ########################

    def _refresh_resources(self):
        details = self.widget("details-pages")
        page = details.get_current_page()

        if page == DETAILS_PAGE_DETAILS:
            self._details.vmwindow_resources_refreshed()

    def _refresh_current_page(self, newpage=None):
        newpage = newpage or self.widget("details-pages").get_current_page()

        is_details = newpage == DETAILS_PAGE_DETAILS
        self._details.vmwindow_refresh_vm_state(is_details)

        if newpage == DETAILS_PAGE_CONSOLE:
            self._console.vmwindow_refresh_vm_state()
        elif newpage == DETAILS_PAGE_SNAPSHOTS:
            self._snapshots.vmwindow_refresh_vm_state()


    #########################
    # Console page handling #
    #########################

    def _sync_console_page_menu_state(self):
        if not self.vm:
            # This is triggered via cleanup + idle_add, so vm might
            # disappear and spam the logs
            return  # pragma: no cover

        paused = self.vm.is_paused()
        is_viewer = self._console.vmwindow_get_viewer_is_visible()
        can_auto_clipboard = self._console.vmwindow_get_can_auto_clipboard()
        can_usb = self._console.vmwindow_get_can_usb_redirect()

        self.widget("details-menu-vm-screenshot").set_sensitive(is_viewer)
        self.widget("details-menu-auto-clipboard").set_sensitive(can_auto_clipboard)
        self.widget("details-menu-usb-redirection").set_sensitive(can_usb)
        keycombo_menu = self._console.vmwindow_get_keycombo_menu()

        can_sendkey = (is_viewer and not paused)
        for c in keycombo_menu.get_children():
            c.set_sensitive(can_sendkey)

        self._console_refresh_can_fullscreen()
        self._console_refresh_resizeguest_from_settings()

    def _console_refresh_can_fullscreen(self):
        allow_fullscreen = self._console.vmwindow_get_viewer_is_visible()

        self.widget("control-fullscreen").set_sensitive(allow_fullscreen)
        self.widget("details-menu-view-fullscreen").set_sensitive(
            allow_fullscreen)

    def _console_refresh_scaling_from_settings(self):
        scale_type = self.vm.get_console_scaling()
        self.widget("details-menu-view-scale-always").set_active(
            scale_type == self.config.CONSOLE_SCALE_ALWAYS)
        self.widget("details-menu-view-scale-never").set_active(
            scale_type == self.config.CONSOLE_SCALE_NEVER)
        self.widget("details-menu-view-scale-fullscreen").set_active(
            scale_type == self.config.CONSOLE_SCALE_FULLSCREEN)

        self._console.vmwindow_sync_scaling_with_display()

    def _console_refresh_auto_clipboard_from_settings(self):
        val = self.vm.get_console_auto_clipboard()
        self.widget("details-menu-auto-clipboard").set_active(val)

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

    def _fullscreen_changed_cb(self, src):
        do_fullscreen = src.get_active()
        self.widget("control-fullscreen").set_active(do_fullscreen)
        self._console.vmwindow_set_fullscreen(do_fullscreen)

        self.widget("details-menubar").set_visible(not do_fullscreen)

        show_toolbar = not do_fullscreen
        if not self.widget("details-menu-view-toolbar").get_active():
            show_toolbar = False  # pragma: no cover
        self.widget("toolbar-box").set_visible(show_toolbar)

    def _resizeguest_ui_changed_cb(self, src):
        if not src.get_sensitive():
            return  # pragma: no cover

        val = int(self.widget("details-menu-view-resizeguest").get_active())
        self.vm.set_console_resizeguest(val)
        self._console.vmwindow_sync_resizeguest_with_display()

    def _console_refresh_resizeguest_from_settings(self):
        tooltip = self._console.vmwindow_get_resizeguest_tooltip()
        val = self.vm.get_console_resizeguest()
        widget = self.widget("details-menu-view-resizeguest")
        widget.set_tooltip_text(tooltip)
        widget.set_sensitive(not bool(tooltip))
        if not tooltip:
            self.widget("details-menu-view-resizeguest").set_active(bool(val))

        self._console.vmwindow_sync_resizeguest_with_display()

    def _autoconnect_ui_changed_cb(self, src):
        val = int(self.widget("details-menu-view-autoconnect").get_active())
        self.vm.set_console_autoconnect(val)

    def _console_refresh_autoconnect_from_settings(self):
        val = self.vm.get_console_autoconnect()
        self.widget("details-menu-view-autoconnect").set_active(val)

    def _size_to_vm_cb(self, src):
        self._console.vmwindow_set_size_to_vm()

    def _console_leave_fullscreen_cb(self, src):
        # This will trigger de-fullscreening in a roundabout way
        self.widget("control-fullscreen").set_active(False)

    def _console_change_title_cb(self, src):
        self._refresh_title()

    def _vm_state_changed_cb(self, src):
        if self.is_visible():
            self._refresh_vm_state()

    def _resources_sampled_cb(self, src):
        if self.is_visible():
            self._refresh_resources()

    def _console_page_changed_cb(self, src):
        self._sync_console_page_menu_state()
