# Copyright (C) 2006, 2012-2013 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gtk
from gi.repository import Gdk

from virtinst import DomainCpu
from virtinst import log

from .lib import uiutil
from .baseclass import vmmGObjectUI
from .lib.inspection import vmmInspection
from .systray import vmmSystray


class vmmPreferences(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj):
        try:
            if not cls._instance:
                cls._instance = vmmPreferences()
            cls._instance.show(parentobj.topwin)
        except Exception as e:  # pragma: no cover
            parentobj.err.show_err(
                    _("Error launching preferences: %s") % str(e))

    def __init__(self):
        vmmGObjectUI.__init__(self, "preferences.ui", "vmm-preferences")
        self._cleanup_on_app_close()

        self._init_ui()

        self._orig_libguestfs_val = None

        self.refresh_view_system_tray()
        self.refresh_xmleditor()
        self.refresh_libguestfs()
        self.refresh_update_interval()
        self.refresh_console_scaling()
        self.refresh_console_resizeguest()
        self.refresh_console_autoredir()
        self.refresh_console_autoclipboard()
        self.refresh_console_autoconnect()
        self.refresh_graphics_type()
        self.refresh_storage_format()
        self.refresh_cpu_default()
        self.refresh_cpu_poll()
        self.refresh_disk_poll()
        self.refresh_net_poll()
        self.refresh_memory_poll()
        self.refresh_grabkeys_combination()
        self.refresh_confirm_forcepoweroff()
        self.refresh_confirm_poweroff()
        self.refresh_confirm_pause()
        self.refresh_confirm_removedev()
        self.refresh_confirm_unapplied()
        self.refresh_confirm_delstorage()

        self.builder.connect_signals({
            "on_vmm_preferences_delete_event": self.close,
            "on_prefs_close_clicked": self.close,

            "on_prefs_system_tray_toggled": self.change_view_system_tray,
            "on_prefs_xmleditor_toggled": self.change_xmleditor,
            "on_prefs_libguestfs_toggled": self.change_libguestfs,
            "on_prefs_stats_update_interval_changed": self.change_update_interval,
            "on_prefs_console_scaling_changed": self.change_console_scaling,
            "on_prefs_console_resizeguest_changed": self.change_console_resizeguest,
            "on_prefs_console_autoredir_changed": self.change_console_autoredir,
            "on_prefs_console_autoclipboard_changed": self.change_console_autoclipboard,
            "on_prefs_console_autoconnect_toggled": self.change_console_autoconnect,
            "on_prefs_graphics_type_changed": self.change_graphics_type,
            "on_prefs_storage_format_changed": self.change_storage_format,
            "on_prefs_cpu_default_changed": self.change_cpu_default,
            "on_prefs_stats_enable_cpu_toggled": self.change_cpu_poll,
            "on_prefs_stats_enable_disk_toggled": self.change_disk_poll,
            "on_prefs_stats_enable_net_toggled": self.change_net_poll,
            "on_prefs_stats_enable_memory_toggled": self.change_memory_poll,
            "on_prefs_confirm_forcepoweroff_toggled": self.change_confirm_forcepoweroff,
            "on_prefs_confirm_poweroff_toggled": self.change_confirm_poweroff,
            "on_prefs_confirm_pause_toggled": self.change_confirm_pause,
            "on_prefs_confirm_removedev_toggled": self.change_confirm_removedev,
            "on_prefs_confirm_unapplied_toggled": self.change_confirm_unapplied,
            "on_prefs_confirm_delstorage_toggled": self.change_confirm_delstorage,
            "on_prefs_btn_keys_define_clicked": self.change_grab_keys,
        })

        self.widget("prefs-graphics-type").emit("changed")

        self.bind_escape_key_close()

    def close(self, ignore1=None, ignore2=None):
        log.debug("Closing preferences")
        self.topwin.hide()
        return 1

    def show(self, parent):
        log.debug("Showing preferences")
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def _cleanup(self):
        pass

    def _init_ui(self):
        combo = self.widget("prefs-console-scaling")
        # [gsettings value, string]
        model = Gtk.ListStore(int, str)
        for row in [[0, _("Never")],
                    [1, _("Fullscreen only")],
                    [2, _("Always")]]:
            model.append(row)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        combo = self.widget("prefs-console-resizeguest")
        # [gsettings value, string]
        model = Gtk.ListStore(int, str)
        vals = {
            0: _("Off"),
            1: _("On"),
        }
        model.append([-1, _("System default (%s)") %
            vals[self.config.default_console_resizeguest]])
        for key, val in vals.items():
            model.append([key, val])
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        combo = self.widget("prefs-console-autoredir")
        # [gsettings value, string]
        model = Gtk.ListStore(bool, str)
        vals = {
            False: _("Manual redirect only"),
            True: _("Auto redirect on USB attach"),
        }
        for key, val in vals.items():
            model.append([key, val])
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        combo = self.widget("prefs-console-autoclipboard")
        # [gsettings value, string]
        model = Gtk.ListStore(bool, str)
        vals = {
            False: _("Disabled by default"),
            True: _("Enabled by default"),
        }
        for key, val in vals.items():
            model.append([key, val])
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        combo = self.widget("prefs-graphics-type")
        # [gsettings value, string]
        model = Gtk.ListStore(str, str)
        for row in [["system", _("System default (%s)") %
                     self.config.default_graphics_from_config],
                    ["vnc", "VNC"], ["spice", "Spice"]]:
            model.append(row)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        combo = self.widget("prefs-storage-format")
        # [gsettings value, string]
        model = Gtk.ListStore(str, str)
        for row in [["default", _("System default (%s)") %
                    self.config.default_storage_format_from_config],
                    ["raw", "Raw"],
                    ["qcow2", "QCOW2"]]:
            model.append(row)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        combo = self.widget("prefs-cpu-default")
        # [gsettings value, string]
        model = Gtk.ListStore(str, str)
        for row in [
            [DomainCpu.SPECIAL_MODE_APP_DEFAULT, _("Application default")],
            [DomainCpu.SPECIAL_MODE_HV_DEFAULT, _("Hypervisor default")],
            [DomainCpu.SPECIAL_MODE_HOST_MODEL_ONLY,
                _("Nearest host CPU model")],
            [DomainCpu.SPECIAL_MODE_HOST_MODEL, "host-model"],
            [DomainCpu.SPECIAL_MODE_HOST_PASSTHROUGH, "host-passthrough"]]:
            model.append(row)
        combo.set_model(model)
        uiutil.init_combo_text_column(combo, 1)

        if not vmmInspection.libguestfs_installed():  # pragma: no cover
            self.widget("prefs-libguestfs").set_sensitive(False)
            self.widget("prefs-libguestfs").set_tooltip_text(
                    _("python libguestfs support is not installed"))


    #########################
    # Config Change Options #
    #########################

    def refresh_view_system_tray(self):
        errmsg = vmmSystray.systray_disabled_message()
        val = bool(self.config.get_view_system_tray() and not errmsg)
        self.widget("prefs-system-tray").set_sensitive(not bool(errmsg))
        self.widget("prefs-system-tray").set_tooltip_text(errmsg)
        self.widget("prefs-system-tray").set_active(val)

    def refresh_xmleditor(self):
        val = self.config.get_xmleditor_enabled()
        self.widget("prefs-xmleditor").set_active(bool(val))

    def refresh_libguestfs(self):
        val = self.config.get_libguestfs_inspect_vms()
        if self._orig_libguestfs_val is None:
            self._orig_libguestfs_val = val
        self.widget("prefs-libguestfs").set_active(bool(val))

    def refresh_update_interval(self):
        self.widget("prefs-stats-update-interval").set_value(
            self.config.get_stats_update_interval())

    def refresh_console_scaling(self):
        combo = self.widget("prefs-console-scaling")
        val = self.config.get_console_scaling()
        uiutil.set_list_selection(combo, val)
    def refresh_console_resizeguest(self):
        combo = self.widget("prefs-console-resizeguest")
        val = self.config.get_console_resizeguest()
        uiutil.set_list_selection(combo, val)
    def refresh_console_autoredir(self):
        combo = self.widget("prefs-console-autoredir")
        val = self.config.get_auto_usbredir()
        uiutil.set_list_selection(combo, val)
    def refresh_console_autoclipboard(self):
        combo = self.widget("prefs-console-autoclipboard")
        val = self.config.get_auto_clipboard()
        uiutil.set_list_selection(combo, val)
    def refresh_console_autoconnect(self):
        val = self.config.get_console_autoconnect()
        self.widget("prefs-console-autoconnect").set_active(val)

    def refresh_graphics_type(self):
        combo = self.widget("prefs-graphics-type")
        gtype = self.config.get_graphics_type(raw=True)
        uiutil.set_list_selection(combo, gtype)
    def refresh_storage_format(self):
        combo = self.widget("prefs-storage-format")
        val = self.config.get_default_storage_format(raw=True)
        uiutil.set_list_selection(combo, val)
    def refresh_cpu_default(self):
        combo = self.widget("prefs-cpu-default")
        val = self.config.get_default_cpu_setting()
        uiutil.set_list_selection(combo, val)

    def refresh_cpu_poll(self):
        self.widget("prefs-stats-enable-cpu").set_active(
            self.config.get_stats_enable_cpu_poll())
    def refresh_disk_poll(self):
        self.widget("prefs-stats-enable-disk").set_active(
            self.config.get_stats_enable_disk_poll())
    def refresh_net_poll(self):
        self.widget("prefs-stats-enable-net").set_active(
            self.config.get_stats_enable_net_poll())
    def refresh_memory_poll(self):
        self.widget("prefs-stats-enable-memory").set_active(
            self.config.get_stats_enable_memory_poll())

    def _process_grabkeys(self, val):
        # We convert keysyms to names
        keys = []
        for k in val.split(','):
            try:
                key = int(k)
                keys.append(Gdk.keyval_name(key))
            except Exception:  # pragma: no cover
                continue
        return "+".join(keys)

    def refresh_grabkeys_combination(self):
        val = self.config.get_keys_combination()
        keystr = self._process_grabkeys(val)
        self.widget("prefs-keys-grab-sequence").set_text(keystr or "")

    def refresh_confirm_forcepoweroff(self):
        self.widget("prefs-confirm-forcepoweroff").set_active(
                                self.config.get_confirm_forcepoweroff())
    def refresh_confirm_poweroff(self):
        self.widget("prefs-confirm-poweroff").set_active(
                                self.config.get_confirm_poweroff())
    def refresh_confirm_pause(self):
        self.widget("prefs-confirm-pause").set_active(
                                self.config.get_confirm_pause())
    def refresh_confirm_removedev(self):
        self.widget("prefs-confirm-removedev").set_active(
                                self.config.get_confirm_removedev())
    def refresh_confirm_unapplied(self):
        self.widget("prefs-confirm-unapplied").set_active(
                                self.config.get_confirm_unapplied())
    def refresh_confirm_delstorage(self):
        self.widget("prefs-confirm-delstorage").set_active(
                                self.config.get_confirm_delstorage())

    def grabkeys_get_string(self, events):
        keystr = ""
        for ignore, keyval in events:
            if keystr:
                keystr += "+"
            keystr += Gdk.keyval_name(keyval)
        return keystr

    def grabkeys_dlg_press(self, src_ignore, event, label, events):
        if not [e for e in events if e[0] == event.hardware_keycode]:
            events.append((event.hardware_keycode, event.keyval))

        label.set_text(self.grabkeys_get_string(events))

    def grabkeys_dlg_release(self, src_ignore, event, label, events):
        for e in [e for e in events if e[0] == event.hardware_keycode]:
            events.remove(e)

        label.set_text(self.grabkeys_get_string(events))

    def change_grab_keys(self, src_ignore):
        dialog = Gtk.Dialog(_("Configure grab key combination"),
                            self.topwin,
                            Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
                            (Gtk.STOCK_CANCEL, Gtk.ResponseType.REJECT,
                             Gtk.STOCK_OK, Gtk.ResponseType.ACCEPT))
        dialog.set_default_size(325, 160)
        dialog.set_border_width(6)

        infolabel = Gtk.Label(
            label=_("You can now define grab keys by pressing them.\n"
                    "To confirm your selection please click OK button\n"
                    "while you have desired keys pressed."))
        keylabel = Gtk.Label(label=_("Please press desired grab key combination"))

        vbox = Gtk.VBox()
        vbox.set_spacing(12)
        vbox.pack_start(infolabel, False, False, 0)
        vbox.pack_start(keylabel, False, False, 0)
        dialog.get_content_area().add(vbox)

        events = []
        dialog.connect("key-press-event", self.grabkeys_dlg_press,
                       keylabel, events)
        dialog.connect("key-release-event", self.grabkeys_dlg_release,
                       keylabel, events)
        dialog.show_all()
        result = dialog.run()

        if result == Gtk.ResponseType.ACCEPT:
            self.config.set_keys_combination([e[1] for e in events])

        self.refresh_grabkeys_combination()
        dialog.destroy()

    def change_view_system_tray(self, src):
        self.config.set_view_system_tray(src.get_active())
    def change_xmleditor(self, src):
        self.config.set_xmleditor_enabled(src.get_active())
    def change_libguestfs(self, src):
        val = src.get_active()
        self.config.set_libguestfs_inspect_vms(val)

        vis = (val != self._orig_libguestfs_val and
               self.widget("prefs-libguestfs").get_sensitive())
        uiutil.set_grid_row_visible(
                self.widget("prefs-libguestfs-warn-box"), vis)

    def change_update_interval(self, src):
        self.config.set_stats_update_interval(src.get_value_as_int())

    def change_console_scaling(self, box):
        self.config.set_console_scaling(box.get_active())
    def change_console_resizeguest(self, box):
        val = uiutil.get_list_selection(box)
        self.config.set_console_resizeguest(val)
    def change_console_autoredir(self, box):
        val = uiutil.get_list_selection(box)
        self.config.set_auto_usbredir(val)
    def change_console_autoclipboard(self, box):
        val = uiutil.get_list_selection(box)
        self.config.set_auto_clipboard(val)
    def change_console_autoconnect(self, src):
        self.config.set_console_autoconnect(bool(src.get_active()))

    def change_graphics_type(self, src):
        val = uiutil.get_list_selection(src)
        self.config.set_graphics_type(val)
    def change_storage_format(self, src):
        typ = uiutil.get_list_selection(src) or "default"
        self.config.set_storage_format(typ.lower())
    def change_cpu_default(self, src):
        typ = uiutil.get_list_selection(src) or "default"
        self.config.set_default_cpu_setting(typ.lower())

    def change_cpu_poll(self, src):
        self.config.set_stats_enable_cpu_poll(src.get_active())
    def change_disk_poll(self, src):
        self.config.set_stats_enable_disk_poll(src.get_active())
    def change_net_poll(self, src):
        self.config.set_stats_enable_net_poll(src.get_active())
    def change_memory_poll(self, src):
        self.config.set_stats_enable_memory_poll(src.get_active())

    def change_confirm_forcepoweroff(self, src):
        self.config.set_confirm_forcepoweroff(src.get_active())
    def change_confirm_poweroff(self, src):
        self.config.set_confirm_poweroff(src.get_active())
    def change_confirm_pause(self, src):
        self.config.set_confirm_pause(src.get_active())
    def change_confirm_removedev(self, src):
        self.config.set_confirm_removedev(src.get_active())
    def change_confirm_unapplied(self, src):
        self.config.set_confirm_unapplied(src.get_active())
    def change_confirm_delstorage(self, src):
        self.config.set_confirm_delstorage(src.get_active())
