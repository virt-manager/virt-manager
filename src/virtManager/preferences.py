import gtk.glade

class vmmPreferences:
    def __init__(self, config):
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-preferences")
        self.config = config
        self.window.get_widget("vmm-preferences").hide()

        self.config.on_stats_update_interval_changed(self.refresh_update_interval)
        self.config.on_stats_history_length_changed(self.refresh_history_length)

        self.refresh_update_interval()
        self.refresh_history_length()

        self.window.signal_autoconnect({
            "on_stats_update_interval_changed": self.change_update_interval,
            "on_stats_history_length_changed": self.change_history_length,

            "on_close_clicked": self.close,
            "on_vmm_preferences_delete_event": self.close,
            })

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-preferences").hide()
        return 1

    def show(self):
        win = self.window.get_widget("vmm-preferences")
        win.show_all()
        win.present()

    def refresh_update_interval(self, ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("stats-update-interval").set_value(self.config.get_stats_update_interval())

    def refresh_history_length(self, ignore1=None,ignore2=None,ignore3=None,ignore4=None):
        self.window.get_widget("stats-history-length").set_value(self.config.get_stats_history_length())

    def change_update_interval(self, src):
        self.config.set_stats_update_interval(src.get_value_as_int())

    def change_history_length(self, src):
        self.config.set_stats_history_length(src.get_value_as_int())

