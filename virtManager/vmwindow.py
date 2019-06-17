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
        except Exception as e:
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
            self.conn.connect("vm-removed", self._vm_removed)

        self._mediacombo = None

        self.ignoreDetails = False

        from .details.console import vmmConsolePages
        self.console = vmmConsolePages(self.vm, self.builder, self.topwin)
        self.snapshots = vmmSnapshotPage(self.vm, self.builder, self.topwin)
        self.widget("snapshot-placeholder").add(self.snapshots.top_box)
        self._details = vmmDetails(self.vm, self.builder, self.topwin,
                self.is_customize_dialog)
        self.widget("details-placeholder").add(self._details.top_box)

        # Set default window size
        w, h = self.vm.get_details_window_size()
        if w <= 0:
            w = 800
        if h <= 0:
            h = 600
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
            "on_details_menu_view_toolbar_activate": self.toggle_toolbar,
            "on_details_menu_view_manager_activate": self.view_manager,
            "on_details_menu_view_details_toggled": self.details_console_changed,
            "on_details_menu_view_console_toggled": self.details_console_changed,
            "on_details_menu_view_snapshots_toggled": self.details_console_changed,

            "on_details_pages_switch_page": self.switch_page,

            # Listeners stored in vmmConsolePages
            "on_details_menu_view_fullscreen_activate": (
                self.console.details_toggle_fullscreen),
            "on_details_menu_view_size_to_vm_activate": (
                self.console.details_size_to_vm),
            "on_details_menu_view_scale_always_toggled": (
                self.console.details_scaling_ui_changed_cb),
            "on_details_menu_view_scale_fullscreen_toggled": (
                self.console.details_scaling_ui_changed_cb),
            "on_details_menu_view_scale_never_toggled": (
                self.console.details_scaling_ui_changed_cb),
            "on_details_menu_view_resizeguest_toggled": (
                self.console.details_resizeguest_ui_changed_cb),

            "on_console_pages_switch_page": (
                self.console.details_page_changed),
            "on_console_auth_password_activate": (
                self.console.details_auth_login),
            "on_console_auth_login_clicked": (
                self.console.details_auth_login),
        })

        # Deliberately keep all this after signal connection
        self.vm.connect("state-changed", self.refresh_vm_state)
        self.vm.connect("resources-sampled", self.refresh_resources)
        self.vm.connect("inspection-changed",
                lambda *x: self._details.refresh_os_page())

        self.refresh_vm_state()
        self.activate_default_page()


    @property
    def conn(self):
        return self.vm.conn

    def _cleanup(self):
        self.console.cleanup()
        self.console = None
        self.snapshots.cleanup()
        self.snapshots = None
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
        self.refresh_vm_state()

    def customize_finish(self, src):
        ignore = src
        if self._details.vmwindow_has_unapplied_changes():
            return
        self.emit("customize-finished", self.vm)

    def _vm_removed(self, _conn, connkey):
        if self.vm.get_connkey() == connkey:
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
            fs.set_active(False)

        if not self.is_visible():
            return

        self.topwin.hide()
        if self.console.details_viewer_is_visible():
            try:
                self.console.details_close_viewer()
            except Exception:
                log.error("Failure when disconnecting from desktop server")

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


    ##########################
    # Window state listeners #
    ##########################

    def window_resized(self, ignore, ignore2):
        if not self.is_visible():
            return
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

        if (active and not
            self.widget("details-menu-view-fullscreen").get_active()):
            self.widget("toolbar-box").show()
        else:
            self.widget("toolbar-box").hide()

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
                self.sync_details_console_view(True)
                return
            self._details.disable_apply()

        if is_details:
            pages.set_current_page(DETAILS_PAGE_DETAILS)
        elif is_snapshot:
            self.snapshots.show_page()
            pages.set_current_page(DETAILS_PAGE_SNAPSHOTS)
        else:
            pages.set_current_page(DETAILS_PAGE_CONSOLE)

    def sync_details_console_view(self, newpage):
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

    def switch_page(self, notebook=None, ignore2=None, newpage=None):
        for i in range(notebook.get_n_pages()):
            w = notebook.get_nth_page(i)
            w.set_visible(i == newpage)

        self.page_refresh(newpage)

        self.sync_details_console_view(newpage)
        self.console.details_refresh_can_fullscreen()

    def change_run_text(self, can_restore):
        if can_restore:
            text = _("_Restore")
        else:
            text = _("_Run")
        strip_text = text.replace("_", "")

        self.widget("details-vm-menu").get_submenu().change_run_text(text)
        self.widget("control-run").set_label(strip_text)

    def refresh_vm_state(self, ignore=None):
        vm = self.vm

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

        details = self.widget("details-pages")
        self.page_refresh(details.get_current_page())

        self._details.vmwindow_refresh_vm_state()
        self.console.details_update_widget_states()
        if not run:
            self.activate_default_console_page()


    #############################
    # External action listeners #
    #############################

    def view_manager(self, _src):
        from .manager import vmmManager
        vmmManager.get_instance(self).show()

    def exit_app(self, _src):
        vmmEngine.get_instance().exit_app()

    def activate_default_console_page(self):
        pages = self.widget("details-pages")

        # console.activate_default_console_page() will as a side effect
        # switch to DETAILS_PAGE_CONSOLE. However this code path is triggered
        # when the user runs a VM while they are focused on the details page,
        # and we don't want to switch pages out from under them.
        origpage = pages.get_current_page()
        self.console.details_activate_default_console_page()
        pages.set_current_page(origpage)

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
        can_usb = bool(self.console.details_viewer_has_usb_redirection() and
                       self.vm.has_spicevmc_type_redirdev())
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
        except Exception as e:
            self.err.show_err(_("Error taking screenshot: %s") % str(e))

    def control_vm_usb_redirection(self, src):
        ignore = src
        spice_usbdev_dialog = self.err

        spice_usbdev_widget = self.console.details_viewer_get_usb_widget()
        if not spice_usbdev_widget:
            self.err.show_err(_("Error initializing spice USB device widget"))
            return

        spice_usbdev_widget.show()
        spice_usbdev_dialog.show_info(_("Select USB devices for redirection"),
                                      widget=spice_usbdev_widget,
                                      buttons=Gtk.ButtonsType.CLOSE)

    def _take_screenshot(self):
        image = self.console.details_viewer_get_pixbuf()

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
            ret = ret.buffer

        import datetime
        now = str(datetime.datetime.now()).split(".")[0].replace(" ", "_")
        default = "Screenshot_%s_%s.png" % (self.vm.get_name(), now)

        path = self.err.browse_local(
            self.vm.conn, _("Save Virtual Machine Screenshot"),
            _type=("png", _("PNG files")),
            dialog_type=Gtk.FileChooserAction.SAVE,
            browse_reason=self.config.CONFIG_DIR_SCREENSHOT,
            default_name=default)
        if not path:
            log.debug("No screenshot path given, skipping save.")
            return

        filename = path
        if not filename.endswith(".png"):
            filename += ".png"
        open(filename, "wb").write(ret)


    ########################
    # Details page refresh #
    ########################

    def refresh_resources(self, ignore):
        details = self.widget("details-pages")
        page = details.get_current_page()

        # If the dialog is visible, we want to make sure the XML is always
        # up to date
        try:
            if self.is_visible():
                self.vm.ensure_latest_xml()
        except Exception as e:
            if self.conn.support.is_libvirt_error_no_domain(e):
                self.close()
                return
            raise

        if page == DETAILS_PAGE_DETAILS:
            self._details.vmwindow_resources_refreshed()

    def page_refresh(self, page):
        if page == DETAILS_PAGE_DETAILS:
            self._details.vmwindow_page_refresh()
