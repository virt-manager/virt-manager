#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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

from virtManager.baseclass import vmmGObjectUI

PREFS_PAGE_STATS    = 0
PREFS_PAGE_VM_PREFS = 1

class vmmPreferences(vmmGObjectUI):
    def __init__(self):
        vmmGObjectUI.__init__(self, "vmm-preferences.ui", "vmm-preferences")

        self.add_gconf_handle(self.config.on_view_system_tray_changed(self.refresh_view_system_tray))
        self.add_gconf_handle(self.config.on_console_accels_changed(self.refresh_console_accels))
        self.add_gconf_handle(self.config.on_console_scaling_changed(self.refresh_console_scaling))
        self.add_gconf_handle(self.config.on_stats_update_interval_changed(self.refresh_update_interval))
        self.add_gconf_handle(self.config.on_stats_history_length_changed(self.refresh_history_length))
        self.add_gconf_handle(self.config.on_sound_local_changed(self.refresh_sound_local))
        self.add_gconf_handle(self.config.on_sound_remote_changed(self.refresh_sound_remote))
        self.add_gconf_handle(self.config.on_graphics_type_changed(self.refresh_graphics_type))
        self.add_gconf_handle(self.config.on_storage_format_changed(self.refresh_storage_format))
        self.add_gconf_handle(self.config.on_stats_enable_disk_poll_changed(self.refresh_disk_poll))
        self.add_gconf_handle(self.config.on_stats_enable_net_poll_changed(self.refresh_net_poll))

        self.add_gconf_handle(self.config.on_confirm_forcepoweroff_changed(self.refresh_confirm_forcepoweroff))
        self.add_gconf_handle(self.config.on_confirm_poweroff_changed(self.refresh_confirm_poweroff))
        self.add_gconf_handle(self.config.on_confirm_pause_changed(self.refresh_confirm_pause))
        self.add_gconf_handle(self.config.on_confirm_removedev_changed(self.refresh_confirm_removedev))
        self.add_gconf_handle(self.config.on_confirm_interface_changed(self.refresh_confirm_interface))
        self.add_gconf_handle(self.config.on_confirm_unapplied_changed(self.refresh_confirm_unapplied))

        self.refresh_view_system_tray()
        self.refresh_update_interval()
        self.refresh_history_length()
        self.refresh_console_accels()
        self.refresh_console_scaling()
        self.refresh_sound_local()
        self.refresh_sound_remote()
        self.refresh_graphics_type()
        self.refresh_storage_format()
        self.refresh_disk_poll()
        self.refresh_net_poll()
        self.refresh_grabkeys_combination()
        self.refresh_confirm_forcepoweroff()
        self.refresh_confirm_poweroff()
        self.refresh_confirm_pause()
        self.refresh_confirm_removedev()
        self.refresh_confirm_interface()
        self.refresh_confirm_unapplied()

        self.window.connect_signals({
            "on_prefs_system_tray_toggled" : self.change_view_system_tray,
            "on_prefs_stats_update_interval_changed": self.change_update_interval,
            "on_prefs_stats_history_length_changed": self.change_history_length,
            "on_prefs_console_accels_toggled": self.change_console_accels,
            "on_prefs_console_scaling_changed": self.change_console_scaling,
            "on_prefs_close_clicked": self.close,
            "on_vmm_preferences_delete_event": self.close,
            "on_prefs_help_clicked": self.show_help,
            "on_prefs_sound_local_toggled": self.change_local_sound,
            "on_prefs_sound_remote_toggled": self.change_remote_sound,
            "on_prefs_stats_enable_disk_toggled": self.change_disk_poll,
            "on_prefs_stats_enable_net_toggled": self.change_net_poll,
            "on_prefs_confirm_forcepoweroff_toggled": self.change_confirm_forcepoweroff,
            "on_prefs_confirm_poweroff_toggled": self.change_confirm_poweroff,
            "on_prefs_confirm_pause_toggled": self.change_confirm_pause,
            "on_prefs_confirm_removedev_toggled": self.change_confirm_removedev,
            "on_prefs_confirm_interface_toggled": self.change_confirm_interface,
            "on_prefs_confirm_unapplied_toggled": self.change_confirm_unapplied,
            "on_prefs_btn_keys_define_clicked": self.change_grab_keys,
            "on_prefs_graphics_type_changed": self.change_graphics_type,
            "on_prefs_storage_format_changed": self.change_storage_format,
            })
        self.bind_escape_key_close()

        # XXX: Help docs useless/out of date
        self.widget("prefs-help").hide()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing preferences")
        self.topwin.hide()
        return 1

    def show(self, parent):
        logging.debug("Showing preferences")
        self.topwin.set_transient_for(parent)
        self.topwin.present()

    def _cleanup(self):
        pass

    #########################
    # Config Change Options #
    #########################

    def refresh_view_system_tray(self, ignore1=None, ignore2=None,
                                 ignore3=None, ignore4=None):
        val = self.config.get_view_system_tray()
        self.widget("prefs-system-tray").set_active(bool(val))

    def refresh_update_interval(self, ignore1=None, ignore2=None,
                                ignore3=None, ignore4=None):
        self.widget("prefs-stats-update-interval").set_value(
            self.config.get_stats_update_interval())
    def refresh_history_length(self, ignore1=None, ignore2=None,
                               ignore3=None, ignore4=None):
        self.widget("prefs-stats-history-len").set_value(
            self.config.get_stats_history_length())

    def refresh_console_accels(self, ignore1=None, ignore2=None,
                                ignore3=None, ignore4=None):
        self.widget("prefs-console-accels").set_active(
            self.config.get_console_accels())
    def refresh_console_scaling(self, ignore1=None, ignore2=None,
                                ignore3=None, ignore4=None):
        val = self.config.get_console_scaling()
        if val == None:
            val = 0
        self.widget("prefs-console-scaling").set_active(val)

    def refresh_sound_local(self, ignore1=None, ignore2=None, ignore=None,
                            ignore4=None):
        self.widget("prefs-sound-local").set_active(
            self.config.get_local_sound())
    def refresh_sound_remote(self, ignore1=None, ignore2=None, ignore=None,
                             ignore4=None):
        self.widget("prefs-sound-remote").set_active(
            self.config.get_remote_sound())
    def refresh_graphics_type(self, ignore1=None, ignore2=None, ignore=None,
                             ignore4=None):
        combo = self.widget("prefs-graphics-type")
        model = combo.get_model()
        gtype = self.config.get_graphics_type()

        # Default to row 0 == vnc
        active = 0
        for rowidx in range(len(model)):
            if model[rowidx][0].lower() == gtype:
                active = rowidx
                break

        self.widget("prefs-graphics-type").set_active(active)
    def refresh_storage_format(self, ignore1=None, ignore2=None, ignore=None,
                               ignore4=None):
        combo = self.widget("prefs-storage-format")
        model = combo.get_model()
        gtype = self.config.get_storage_format()

        # Default to row 0 == raw
        active = 0
        for rowidx in range(len(model)):
            if model[rowidx][0].lower() == gtype:
                active = rowidx
                break

        self.widget("prefs-storage-format").set_active(active)

    def refresh_disk_poll(self, ignore1=None, ignore2=None, ignore3=None,
                          ignore4=None):
        self.widget("prefs-stats-enable-disk").set_active(
            self.config.get_stats_enable_disk_poll())
    def refresh_net_poll(self, ignore1=None, ignore2=None, ignore3=None,
                         ignore4=None):
        self.widget("prefs-stats-enable-net").set_active(
            self.config.get_stats_enable_net_poll())

    def refresh_grabkeys_combination(self, ignore1=None, ignore2=None,
                           ignore3=None, ignore4=None):
        val = self.config.get_keys_combination()

        # We convert keysyms to names
        if not val:
            keystr = "Control_L+Alt_L"
        else:
            keystr = None
            for k in val.split(','):
                try:
                    key = int(k)
                except:
                    key = None

                if key is not None:
                    if keystr is None:
                        keystr = gtk.gdk.keyval_name(key)
                    else:
                        keystr = keystr + "+" + gtk.gdk.keyval_name(key)


        self.widget("prefs-keys-grab-sequence").set_text(keystr)

    def refresh_confirm_forcepoweroff(self, ignore1=None, ignore2=None,
                                      ignore3=None, ignore4=None):
        self.widget("prefs-confirm-forcepoweroff").set_active(
                                self.config.get_confirm_forcepoweroff())
    def refresh_confirm_poweroff(self, ignore1=None, ignore2=None,
                                      ignore3=None, ignore4=None):
        self.widget("prefs-confirm-poweroff").set_active(
                                self.config.get_confirm_poweroff())
    def refresh_confirm_pause(self, ignore1=None, ignore2=None,
                              ignore3=None, ignore4=None):
        self.widget("prefs-confirm-pause").set_active(
                                self.config.get_confirm_pause())
    def refresh_confirm_removedev(self, ignore1=None, ignore2=None,
                                  ignore3=None, ignore4=None):
        self.widget("prefs-confirm-removedev").set_active(
                                self.config.get_confirm_removedev())
    def refresh_confirm_interface(self, ignore1=None, ignore2=None,
                                  ignore3=None, ignore4=None):
        self.widget("prefs-confirm-interface").set_active(
                                self.config.get_confirm_interface())
    def refresh_confirm_unapplied(self, ignore1=None, ignore2=None,
                                  ignore3=None, ignore4=None):
        self.widget("prefs-confirm-unapplied").set_active(
                                self.config.get_confirm_unapplied())

    def grabkeys_get_string(self, events):
        keystr = ""
        for ignore, keyval in events:
            if keystr:
                keystr += "+"
            keystr += gtk.gdk.keyval_name(keyval)
        return keystr

    def grabkeys_dlg_press(self, src_ignore, event, label, events):
        if not filter(lambda e: e[0] == event.hardware_keycode, events):
            events.append((event.hardware_keycode, event.keyval))

        label.set_text(self.grabkeys_get_string(events))

    def grabkeys_dlg_release(self, src_ignore, event, label, events):
        for e in filter(lambda e: e[0] == event.hardware_keycode, events):
            events.remove(e)

        label.set_text(self.grabkeys_get_string(events))

    def change_grab_keys(self, src_ignore):
        dialog = gtk.Dialog(_("Configure grab key combination"),
                            self.topwin,
                            gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
                            (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
                             gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
        dialog.set_default_size(325, 160)
        dialog.set_border_width(6)

        infolabel = gtk.Label(
                    _("You can now define grab keys by pressing them.\n"
                      "To confirm your selection please click OK button\n"
                      "while you have desired keys pressed."))
        keylabel = gtk.Label(_("Please press desired grab key combination"))

        vbox = gtk.VBox()
        vbox.set_spacing(12)
        vbox.pack_start(infolabel, False, False)
        vbox.pack_start(keylabel, False, False)
        dialog.get_content_area().add(vbox)

        events = []
        dialog.connect("key-press-event", self.grabkeys_dlg_press,
                       keylabel, events)
        dialog.connect("key-release-event", self.grabkeys_dlg_release,
                       keylabel, events)
        dialog.show_all()
        result = dialog.run()

        if result == gtk.RESPONSE_ACCEPT:
            self.config.set_keys_combination(map(lambda e: e[1], events))

        self.refresh_grabkeys_combination()
        dialog.destroy()

    def change_view_system_tray(self, src):
        self.config.set_view_system_tray(src.get_active())

    def change_update_interval(self, src):
        self.config.set_stats_update_interval(src.get_value_as_int())
    def change_history_length(self, src):
        self.config.set_stats_history_length(src.get_value_as_int())

    def change_console_accels(self, src):
        self.config.set_console_accels(src.get_active())
    def change_console_scaling(self, box):
        self.config.set_console_scaling(box.get_active())

    def change_local_sound(self, src):
        self.config.set_local_sound(src.get_active())
    def change_remote_sound(self, src):
        self.config.set_remote_sound(src.get_active())

    def change_disk_poll(self, src):
        self.config.set_stats_enable_disk_poll(src.get_active())
    def change_net_poll(self, src):
        self.config.set_stats_enable_net_poll(src.get_active())

    def change_confirm_forcepoweroff(self, src):
        self.config.set_confirm_forcepoweroff(src.get_active())
    def change_confirm_poweroff(self, src):
        self.config.set_confirm_poweroff(src.get_active())
    def change_confirm_pause(self, src):
        self.config.set_confirm_pause(src.get_active())
    def change_confirm_removedev(self, src):
        self.config.set_confirm_removedev(src.get_active())
    def change_confirm_interface(self, src):
        self.config.set_confirm_interface(src.get_active())
    def change_confirm_unapplied(self, src):
        self.config.set_confirm_unapplied(src.get_active())

    def change_graphics_type(self, src):
        gtype = 'vnc'
        idx = src.get_active()
        if idx >= 0:
            gtype = src.get_model()[idx][0]
        self.config.set_graphics_type(gtype.lower())
    def change_storage_format(self, src):
        typ = 'default'
        idx = src.get_active()
        if idx >= 0:
            typ = src.get_model()[idx][0]
        self.config.set_storage_format(typ.lower())

    def show_help(self, src_ignore):
        # From the Preferences window, show the help document from
        # the Preferences page
        self.emit("action-show-help", "virt-manager-preferences-window")

vmmPreferences.type_register(vmmPreferences)
vmmPreferences.signal_new(vmmPreferences, "action-show-help", [str])
