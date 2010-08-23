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

import gtk.glade
import gobject

import virtManager.util as util

PREFS_PAGE_STATS    = 0
PREFS_PAGE_VM_PREFS = 1

class vmmPreferences(gobject.GObject):
    __gsignals__ = {
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                             gobject.TYPE_NONE, [str]),
        }
    def __init__(self, config):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-preferences.glade", "vmm-preferences", domain="virt-manager")
        self.config = config

        self.topwin = self.window.get_widget("vmm-preferences")

        self.config.on_view_system_tray_changed(self.refresh_view_system_tray)
        self.config.on_console_popup_changed(self.refresh_console_popup)
        self.config.on_console_keygrab_changed(self.refresh_console_keygrab)
        self.config.on_console_scaling_changed(self.refresh_console_scaling)
        self.config.on_stats_update_interval_changed(self.refresh_update_interval)
        self.config.on_stats_history_length_changed(self.refresh_history_length)
        self.config.on_sound_local_changed(self.refresh_sound_local)
        self.config.on_sound_remote_changed(self.refresh_sound_remote)
        self.config.on_stats_enable_disk_poll_changed(self.refresh_disk_poll)
        self.config.on_stats_enable_net_poll_changed(self.refresh_net_poll)

        self.config.on_confirm_forcepoweroff_changed(self.refresh_confirm_forcepoweroff)
        self.config.on_confirm_poweroff_changed(self.refresh_confirm_poweroff)
        self.config.on_confirm_pause_changed(self.refresh_confirm_pause)
        self.config.on_confirm_removedev_changed(self.refresh_confirm_removedev)
        self.config.on_confirm_interface_changed(self.refresh_confirm_interface)

        self.refresh_view_system_tray()
        self.refresh_update_interval()
        self.refresh_history_length()
        self.refresh_console_popup()
        self.refresh_console_keygrab()
        self.refresh_console_scaling()
        self.refresh_sound_local()
        self.refresh_sound_remote()
        self.refresh_disk_poll()
        self.refresh_net_poll()
        self.refresh_grabkeys_combination()
        self.refresh_confirm_forcepoweroff()
        self.refresh_confirm_poweroff()
        self.refresh_confirm_pause()
        self.refresh_confirm_removedev()
        self.refresh_confirm_interface()

        self.window.signal_autoconnect({
            "on_prefs_system_tray_toggled" : self.change_view_system_tray,
            "on_prefs_stats_update_interval_changed": self.change_update_interval,
            "on_prefs_stats_history_length_changed": self.change_history_length,
            "on_prefs_console_popup_changed": self.change_console_popup,
            "on_prefs_console_keygrab_changed": self.change_console_keygrab,
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
            "on_prefs_btn_keys_define_clicked": self.change_grab_keys,
            })
        util.bind_escape_key_close(self)

        # XXX: Help docs useless/out of date
        self.window.get_widget("prefs-help").hide()

    def close(self, ignore1=None, ignore2=None):
        self.topwin.hide()
        return 1

    def show(self):
        self.topwin.present()

    #########################
    # Config Change Options #
    #########################

    def refresh_view_system_tray(self, ignore1=None, ignore2=None,
                                 ignore3=None, ignore4=None):
        val = self.config.get_view_system_tray()
        self.window.get_widget("prefs-system-tray").set_active(bool(val))

    def refresh_update_interval(self, ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("prefs-stats-update-interval").set_value(self.config.get_stats_update_interval())
    def refresh_history_length(self, ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("prefs-stats-history-len").set_value(self.config.get_stats_history_length())

    def refresh_console_popup(self,ignore1=None,ignore2=None,ignore3=None,
                              ignore4=None):
        self.window.get_widget("prefs-console-popup").set_active(self.config.get_console_popup())
    def refresh_console_keygrab(self,ignore1=None,ignore2=None,ignore3=None,
                                ignore4=None):
        self.window.get_widget("prefs-console-keygrab").set_active(self.config.get_console_keygrab())
    def refresh_console_scaling(self,ignore1=None,ignore2=None,ignore3=None,
                                ignore4=None):
        val = self.config.get_console_scaling()
        if val == None:
            val = 0
        self.window.get_widget("prefs-console-scaling").set_active(val)

    def refresh_sound_local(self, ignore1=None, ignore2=None, ignore=None,
                            ignore4=None):
        self.window.get_widget("prefs-sound-local").set_active(self.config.get_local_sound())
    def refresh_sound_remote(self, ignore1=None, ignore2=None, ignore=None,
                             ignore4=None):
        self.window.get_widget("prefs-sound-remote").set_active(self.config.get_remote_sound())

    def refresh_disk_poll(self, ignore1=None, ignore2=None, ignore3=None,
                          ignore4=None):
        self.window.get_widget("prefs-stats-enable-disk").set_active(self.config.get_stats_enable_disk_poll())
    def refresh_net_poll(self, ignore1=None, ignore2=None, ignore3=None,
                         ignore4=None):
        self.window.get_widget("prefs-stats-enable-net").set_active(self.config.get_stats_enable_net_poll())

    def refresh_grabkeys_combination(self, ignore1=None, ignore2=None,
                           ignore3=None, ignore4=None):
        val = self.config.get_keys_combination()
        if val is None:
            val = "Control_L+Alt_L"

        prefs_button = self.window.get_widget("prefs-keys-grab-changebtn")
        self.window.get_widget("prefs-keys-grab-sequence").set_text(val)
        if not self.config.grab_keys_supported():
            util.tooltip_wrapper(prefs_button,
                                 _("Installed version of GTK-VNC doesn't "
                                   "support configurable grab keys"))
            prefs_button.set_sensitive(False)

    def refresh_confirm_forcepoweroff(self, ignore1=None, ignore2=None,
                                      ignore3=None, ignore4=None):
        self.window.get_widget("prefs-confirm-forcepoweroff").set_active(self.config.get_confirm_forcepoweroff())
    def refresh_confirm_poweroff(self, ignore1=None, ignore2=None,
                                      ignore3=None, ignore4=None):
        self.window.get_widget("prefs-confirm-poweroff").set_active(self.config.get_confirm_poweroff())
    def refresh_confirm_pause(self, ignore1=None, ignore2=None,
                              ignore3=None, ignore4=None):
        self.window.get_widget("prefs-confirm-pause").set_active(self.config.get_confirm_pause())
    def refresh_confirm_removedev(self, ignore1=None, ignore2=None,
                                  ignore3=None, ignore4=None):
        self.window.get_widget("prefs-confirm-removedev").set_active(self.config.get_confirm_removedev())
    def refresh_confirm_interface(self, ignore1=None, ignore2=None,
                                  ignore3=None, ignore4=None):
        self.window.get_widget("prefs-confirm-interface").set_active(self.config.get_confirm_interface())

    def grabkeys_get_string(self, keysyms):
        keystr = None
        for k in keysyms:
            if keystr is None:
                keystr = gtk.gdk.keyval_name(k)
            else:
                keystr = keystr + "+" + gtk.gdk.keyval_name(k)
        # Disallow none
        if keystr is None:
            keystr = ""
        return keystr

    def grabkeys_dlg_press(self, src, ev, defs):
        label = defs['label']
        # Try to get the index, it fails when not found
        try:
            defs['keysyms'].index(ev.keyval)
        except:
            defs['keysyms'].append(ev.keyval)

        label.set_text( self.grabkeys_get_string(defs['keysyms']) )

    def grabkeys_dlg_release(self, src, ev, defs):
        label = defs['label']
        defs['keysyms'].remove(ev.keyval)
        label.set_text( self.grabkeys_get_string(defs['keysyms']) )

    def change_grab_keys(self, src):
        dialog = gtk.Dialog ( _("Configure key combination"),
                              None,
                              gtk.DIALOG_MODAL | gtk.DIALOG_DESTROY_WITH_PARENT,
                              (gtk.STOCK_CANCEL, gtk.RESPONSE_REJECT,
                               gtk.STOCK_OK, gtk.RESPONSE_ACCEPT))
        label = gtk.Label( _("Please press desired grab key combination") )
        dialog.set_size_request(300, 100)
        (dialog.get_content_area()).add(label)
        defs = { 'label': label, 'keysyms': [] }
        dialog.connect("key-press-event", self.grabkeys_dlg_press, defs)
        dialog.connect("key-release-event", self.grabkeys_dlg_release, defs)
        dialog.show_all()
        result = dialog.run()

        if result == gtk.RESPONSE_ACCEPT:
            self.config.set_keys_combination( defs['keysyms'] )

        self.refresh_grabkeys_combination()
        dialog.destroy()

    def change_view_system_tray(self, src):
        self.config.set_view_system_tray(src.get_active())

    def change_update_interval(self, src):
        self.config.set_stats_update_interval(src.get_value_as_int())
    def change_history_length(self, src):
        self.config.set_stats_history_length(src.get_value_as_int())

    def change_console_popup(self, box):
        self.config.set_console_popup(box.get_active())
    def change_console_keygrab(self, box):
        self.config.set_console_keygrab(box.get_active())
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

    def show_help(self, src):
        # From the Preferences window, show the help document from
        # the Preferences page
        self.emit("action-show-help", "virt-manager-preferences-window")
