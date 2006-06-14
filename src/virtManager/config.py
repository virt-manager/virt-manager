import gconf

class vmmConfig:
    def __init__(self, appname, gconf_dir, glade_dir, icon_dir):
        self.appname = appname
        self.conf_dir = gconf_dir
        self.conf = gconf.client_get_default()
        self.conf.add_dir (gconf_dir,
                           gconf.CLIENT_PRELOAD_NONE)

        self.glade_dir = glade_dir
        self.icon_dir = icon_dir

    def get_appname(self):
        return self.appname

    def get_glade_dir(self):
        return self.glade_dir

    def get_glade_file(self):
        return self.glade_dir + "/" + self.appname + ".glade"

    def get_icon_dir(self):
        return self.icon_dir

    def is_vmlist_status_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/status")

    def is_vmlist_cpu_usage_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/cpu_usage")

    def is_vmlist_memory_usage_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/memory_usage")

    def is_vmlist_disk_usage_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/disk_usage")

    def is_vmlist_network_traffic_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/network_traffic")



    def set_vmlist_status_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/status", state)

    def set_vmlist_cpu_usage_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/cpu_usage", state)

    def set_vmlist_memory_usage_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/memory_usage", state)

    def set_vmlist_disk_usage_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/disk_usage", state)

    def set_vmlist_network_traffic_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/network_traffic", state)



    def on_vmlist_status_visible_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/vmlist-fields/status", callback)

    def on_vmlist_cpu_usage_visible_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/vmlist-fields/cpu_usage", callback)

    def on_vmlist_memory_usage_visible_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/vmlist-fields/memory_usage", callback)

    def on_vmlist_disk_usage_visible_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/vmlist-fields/disk_usage", callback)

    def on_vmlist_network_traffic_visible_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/vmlist-fields/network_traffic", callback)



    def get_stats_update_interval(self):
        interval = self.conf.get_int(self.conf_dir + "/stats/update-interval")
        if interval < 1:
            return 1
        return interval

    def get_stats_history_length(self):
        history = self.conf.get_int(self.conf_dir + "/stats/history-length")
        if history < 10:
            return 10
        return history


    def set_stats_update_interval(self, interval):
        self.conf.set_int(self.conf_dir + "/stats/update-interval", interval)

    def set_stats_history_length(self, length):
        self.conf.set_int(self.conf_dir + "/stats/history-length", length)


    def on_stats_update_interval_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/stats/update-interval", callback)

    def on_stats_history_length_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/stats/history-length", callback)


