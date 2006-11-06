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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#
import gtk.glade

class vmmPreferences:
    def __init__(self, config):
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-preferences")
        self.config = config
        self.window.get_widget("vmm-preferences").hide()

        self.config.on_console_popup_changed(self.refresh_console_popup)
        self.config.on_console_keygrab_changed(self.refresh_console_keygrab)
        self.config.on_stats_update_interval_changed(self.refresh_update_interval)
        self.config.on_stats_history_length_changed(self.refresh_history_length)

        self.refresh_update_interval()
        self.refresh_history_length()
        self.refresh_console_popup()
        self.refresh_console_keygrab()

        self.window.signal_autoconnect({
            "on_stats_update_interval_changed": self.change_update_interval,
            "on_stats_history_length_changed": self.change_history_length,
            "on_console_popup_changed": self.change_console_popup,
            "on_console_keygrab_changed": self.change_console_keygrab,
            "on_close_clicked": self.close,
            "on_vmm_preferences_delete_event": self.close,
            })

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-preferences").hide()
        return 1

    def show(self):
        win = self.window.get_widget("vmm-preferences")
        win.show()
        # win.present()

    def refresh_update_interval(self, ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("stats-update-interval").set_value(self.config.get_stats_update_interval())

    def refresh_history_length(self, ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("stats-history-length").set_value(self.config.get_stats_history_length())

    def refresh_console_popup(self,ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("console-popup").set_active(self.config.get_console_popup())

    def refresh_console_keygrab(self,ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("console-keygrab").set_active(self.config.get_console_keygrab())

    def change_update_interval(self, src):
        self.config.set_stats_update_interval(src.get_value_as_int())

    def change_history_length(self, src):
        self.config.set_stats_history_length(src.get_value_as_int())

    def change_console_popup(self, box):
        self.config.set_console_popup(box.get_active())

    def change_console_keygrab(self, box):
        self.config.set_console_keygrab(box.get_active())

