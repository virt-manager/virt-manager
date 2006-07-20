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
import gconf

import gtk.gdk

from virtManager.keyring import *

class vmmConfig:
    def __init__(self, appname, gconf_dir, glade_dir, icon_dir):
        self.appname = appname
        self.conf_dir = gconf_dir
        self.conf = gconf.client_get_default()
        self.conf.add_dir (gconf_dir,
                           gconf.CLIENT_PRELOAD_NONE)

        self.glade_dir = glade_dir
        self.icon_dir = icon_dir
        # We don;t create it straight away, since we don't want
        # to block the app pending user authorizaation to access
        # the keyring
        self.keyring = None

        self.status_icons = {
            "blocked": gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_blocked.png", 18, 18),
            "crashed": gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_crashed.png", 18, 18),
            "paused": gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_paused.png", 18, 18),
            "running": gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_running.png", 18, 18),
            "shutdown": gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_shutdown.png", 18, 18),
            "shutoff": gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_shutoff.png", 18, 18),
            "idle": gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_idle.png", 18, 18),
            }


    def get_vm_status_icon(self, state):
        return self.status_icons[state]

    def get_appname(self):
        return self.appname

    def get_glade_dir(self):
        return self.glade_dir

    def get_glade_file(self):
        return self.glade_dir + "/" + self.appname + ".glade"

    def get_icon_dir(self):
        return self.icon_dir

    def is_vmlist_domain_id_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/domain_id")

    def is_vmlist_status_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/status")

    def is_vmlist_cpu_usage_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/cpu_usage")

    def is_vmlist_virtual_cpus_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/virtual_cpus")

    def is_vmlist_memory_usage_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/memory_usage")

    def is_vmlist_disk_usage_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/disk_usage")

    def is_vmlist_network_traffic_visible(self):
        return self.conf.get_bool(self.conf_dir + "/vmlist-fields/network_traffic")



    def set_vmlist_domain_id_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/domain_id", state)

    def set_vmlist_status_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/status", state)

    def set_vmlist_cpu_usage_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/cpu_usage", state)

    def set_vmlist_virtual_cpus_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/virtual_cpus", state)

    def set_vmlist_memory_usage_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/memory_usage", state)

    def set_vmlist_disk_usage_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/disk_usage", state)

    def set_vmlist_network_traffic_visible(self, state):
        self.conf.set_bool(self.conf_dir + "/vmlist-fields/network_traffic", state)



    def on_vmlist_domain_id_visible_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/vmlist-fields/domain_id", callback)

    def on_vmlist_status_visible_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/vmlist-fields/status", callback)

    def on_vmlist_cpu_usage_visible_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/vmlist-fields/cpu_usage", callback)

    def on_vmlist_virtual_cpus_visible_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/vmlist-fields/virtual_cpus", callback)

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


    def get_secret_name(self, vm):
        return "vm-console-" + vm.get_uuid()

    def clear_console_password(self, vm):
        id = self.conf.get_int(self.conf_dir + "/console/passwords/" + vm.get_uuid())

        if id != None:
            if self.keyring == None:
                try:
                    self.keyring = vmmKeyring()
                except:
                    print "Unable to access keyring"
                    return

            self.keyring.clear_secret(id)
            self.conf.unset(self.conf_dir + "/console/passwords/" + vm.get_uuid())

    def get_console_password(self, vm):
        id = self.conf.get_int(self.conf_dir + "/console/passwords/" + vm.get_uuid())

        if id != None:
            if self.keyring == None:
                try:
                    self.keyring = vmmKeyring()
                except:
                    print "Unable to access keyring"
                    return ""

            secret = self.keyring.get_secret(id)
            if secret != None and secret.get_name() == self.get_secret_name(vm):
                # XXX validate attributes
                return secret.get_secret()
        return ""

    def set_console_password(self, vm, password):
        if self.keyring == None:
            try:
                self.keyring = vmmKeyring()
            except:
                print "Unable to access keyring"
                return

        # Nb, we don't bother to check if there is an existing
        # secret, because gnome-keyring auto-replaces an existing
        # one if the attributes match - which they will since UUID
        # is our unique key

        secret = vmmSecret(self.get_secret_name(vm), password, { "uuid" : vm.get_uuid(), "hvuri": vm.get_connection().get_uri() })
        id = self.keyring.add_secret(secret)
        self.conf.set_int(self.conf_dir + "/console/passwords/" + vm.get_uuid(), id)
