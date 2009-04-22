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
import gconf
import os
import gnome

import gtk.gdk
import libvirt

from virtManager.keyring import vmmKeyring
from virtManager.secret import vmmSecret

CONSOLE_POPUP_NEVER = 0
CONSOLE_POPUP_NEW_ONLY = 1
CONSOLE_POPUP_ALWAYS = 2

CONSOLE_KEYGRAB_NEVER = 0
CONSOLE_KEYGRAB_FULLSCREEN = 1
CONSOLE_KEYGRAB_MOUSEOVER = 2

DEFAULT_XEN_IMAGE_DIR = "/var/lib/xen/images"
DEFAULT_XEN_SAVE_DIR = "/var/lib/xen/dump"

DEFAULT_VIRT_IMAGE_DIR = "/var/lib/libvirt/images"
DEFAULT_VIRT_SAVE_DIR = "/var/lib/libvirt"

class vmmConfig:

    CONSOLE_SCALE_NEVER = 0
    CONSOLE_SCALE_FULLSCREEN = 1
    CONSOLE_SCALE_ALWAYS = 2

    def __init__(self, appname, appversion, gconf_dir, glade_dir, icon_dir,
                 data_dir):
        self.appname = appname
        self.appversion = appversion
        self.conf_dir = gconf_dir
        self.conf = gconf.client_get_default()
        self.conf.add_dir (gconf_dir,
                           gconf.CLIENT_PRELOAD_NONE)

        self.glade_dir = glade_dir
        self.icon_dir = icon_dir
        self.data_dir = data_dir
        # We don't create it straight away, since we don't want
        # to block the app pending user authorizaation to access
        # the keyring
        self.keyring = None

        self.status_icons = {
            libvirt.VIR_DOMAIN_BLOCKED: gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_blocked.png", 18, 18),
            libvirt.VIR_DOMAIN_CRASHED: gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_crashed.png", 18, 18),
            libvirt.VIR_DOMAIN_PAUSED: gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_paused.png", 18, 18),
            libvirt.VIR_DOMAIN_RUNNING: gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_running.png", 18, 18),
            libvirt.VIR_DOMAIN_SHUTDOWN: gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_shutdown.png", 18, 18),
            libvirt.VIR_DOMAIN_SHUTOFF: gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_shutoff.png", 18, 18),
            libvirt.VIR_DOMAIN_NOSTATE: gtk.gdk.pixbuf_new_from_file_at_size(self.get_icon_dir() + "/state_idle.png", 18, 18),
            }
        #initialize the help stuff
        props = { gnome.PARAM_APP_DATADIR : self.get_data_dir()}
        gnome.program_init(self.get_appname(), self.get_appversion(), \
                               properties=props)



    def get_vm_status_icon(self, state):
        return self.status_icons[state]

    def get_appname(self):
        return self.appname

    def get_appversion(self):
        return self.appversion

    def get_glade_dir(self):
        return self.glade_dir

    def get_glade_file(self):
        return self.glade_dir + "/" + self.appname + ".glade"

    def get_icon_dir(self):
        return self.icon_dir

    def get_data_dir(self):
        return self.data_dir

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

    def is_vmlist_disk_io_visible(self):
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

    def set_vmlist_disk_io_visible(self, state):
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

    def on_vmlist_disk_io_visible_changed(self, callback):
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


    # Disable/Enable different stats polling
    def get_stats_enable_disk_poll(self):
        return self.conf.get_bool(self.conf_dir + "/stats/enable-disk-poll")
    def get_stats_enable_net_poll(self):
        return self.conf.get_bool(self.conf_dir + "/stats/enable-net-poll")
    def get_stats_enable_mem_poll(self):
        return self.conf.get_bool(self.conf_dir + "/stats/enable-mem-poll")
    def get_stats_enable_cpu_poll(self):
        return self.conf.get_bool(self.conf_dir + "/stats/enable-cpu-poll")

    def set_stats_enable_disk_poll(self, val):
        self.conf.set_bool(self.conf_dir + "/stats/enable-disk-poll", val)
    def set_stats_enable_net_poll(self, val):
        self.conf.set_bool(self.conf_dir + "/stats/enable-net-poll", val)
    def set_stats_enable_mem_poll(self, val):
        self.conf.set_bool(self.conf_dir + "/stats/enable-mem-poll", val)
    def set_stats_enable_cpu_poll(self, val):
        self.conf.set_bool(self.conf_dir + "/stats/enable-cpu-poll", val)

    def on_stats_enable_disk_poll_changed(self, cb, userdata=None):
        self.conf.notify_add(self.conf_dir + "/stats/enable-disk-poll", cb,
                             userdata)
    def on_stats_enable_net_poll_changed(self, cb, userdata=None):
        self.conf.notify_add(self.conf_dir + "/stats/enable-net-poll", cb,
                             userdata)
    def on_stats_enable_mem_poll_changed(self, cb, userdata=None):
        self.conf.notify_add(self.conf_dir + "/stats/enable-mem-poll", cb,
                             userdata)
    def on_stats_enable_cpu_poll_changed(self, cb, userdata=None):
        self.conf.notify_add(self.conf_dir + "/stats/enable-cpu-poll", cb,
                             userdata)

    # VM Console preferences
    def on_console_popup_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/console/popup", callback)
    def get_console_popup(self):
        console_pref = self.conf.get_int(self.conf_dir + "/console/popup")
        if console_pref == None:
            console_pref = 0
        return console_pref
    def set_console_popup(self, pref):
        self.conf.set_int(self.conf_dir + "/console/popup", pref)

    def on_console_keygrab_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/console/keygrab", callback)
    def get_console_keygrab(self):
        console_pref = self.conf.get_int(self.conf_dir + "/console/keygrab")
        if console_pref == None:
            console_pref = 0
        return console_pref
    def set_console_keygrab(self, pref):
        self.conf.set_int(self.conf_dir + "/console/keygrab", pref)

    def on_console_scaling_changed(self, callback):
        self.conf.notify_add(self.conf_dir + "/console/scaling", callback)
    def get_console_scaling(self):
        console_pref = self.conf.get_int(self.conf_dir + "/console/scaling")
        if console_pref == None:
            console_pref = 0
        return console_pref
    def set_console_scaling(self, pref):
        self.conf.set_int(self.conf_dir + "/console/scaling", pref)

    def show_console_grab_notify(self):
        return self.conf.get_bool(self.conf_dir + "/console/grab-notify")
    def set_console_grab_notify(self, state):
        self.conf.set_bool(self.conf_dir + "/console/grab-notify", state)

    def get_details_show_toolbar(self):
        res = self.conf.get_bool(self.conf_dir + "/details/show-toolbar")
        if res == None:
            res = True
        return res

    def set_details_show_toolbar(self, state):
        self.conf.set_bool(self.conf_dir + "/details/show-toolbar", state)

    def get_local_sound(self):
        return self.conf.get_bool(self.conf_dir + "/new-vm/local-sound")

    def get_remote_sound(self):
        return self.conf.get_bool(self.conf_dir + "/new-vm/remote-sound")

    def set_local_sound(self, state):
        self.conf.set_bool(self.conf_dir + "/new-vm/local-sound", state)

    def set_remote_sound(self, state):
        self.conf.set_bool(self.conf_dir + "/new-vm/remote-sound", state)

    def on_sound_local_changed(self, cb, userdata=None):
        self.conf.notify_add(self.conf_dir + "/new-vm/local-sound", cb,
                             userdata)

    def on_sound_remote_changed(self, cb, userdata=None):
        self.conf.notify_add(self.conf_dir + "/new-vm/remote-sound", cb,
                             userdata)

    def get_secret_name(self, vm):
        return "vm-console-" + vm.get_uuid()

    def has_keyring(self):
        if self.keyring == None:
            self.keyring = vmmKeyring()
        return self.keyring.is_available()

    def clear_console_password(self, vm):
        _id = self.conf.get_int(self.conf_dir + "/console/passwords/" + vm.get_uuid())

        if _id != None:
            if not(self.has_keyring()):
                return

            if self.keyring.clear_secret(_id):
                self.conf.unset(self.conf_dir + "/console/passwords/" + vm.get_uuid())

    def get_console_password(self, vm):
        _id = self.conf.get_int(self.conf_dir + "/console/passwords/" + vm.get_uuid())

        if _id != None:
            if not(self.has_keyring()):
                return ""

            secret = self.keyring.get_secret(_id)
            if secret != None and secret.get_name() == self.get_secret_name(vm):
                if not(secret.has_attribute("hvuri")):
                    return ""
                if secret.get_attribute("hvuri") != vm.get_connection().get_uri():
                    return ""
                if not(secret.has_attribute("uuid")):
                    return ""
                if secret.get_attribute("uuid") != vm.get_uuid():
                    return ""

                return secret.get_secret()
        return ""

    def set_console_password(self, vm, password):
        if not(self.has_keyring()):
            return

        # Nb, we don't bother to check if there is an existing
        # secret, because gnome-keyring auto-replaces an existing
        # one if the attributes match - which they will since UUID
        # is our unique key

        secret = vmmSecret(self.get_secret_name(vm), password, { "uuid" : vm.get_uuid(), "hvuri": vm.get_connection().get_uri() })
        _id = self.keyring.add_secret(secret)
        if _id != None:
            self.conf.set_int(self.conf_dir + "/console/passwords/" + vm.get_uuid(), _id)

    def get_url_list_length(self):
        length = self.conf.get_int(self.conf_dir + "/urls/url-list-length")
        if length < 5:
            return 5
        return length

    def set_url_list_length(self, length):
        self.conf.set_int(self.conf_dir + "/urls/url-list-length", length)

    def add_media_url(self, url):
        urls = self.conf.get_list(self.conf_dir + "/urls/media", gconf.VALUE_STRING)
        if urls == None:
            urls = []
        if urls.count(url) == 0 and len(url)>0 and not url.isspace():
            #the url isn't already in the list, so add it
            urls.insert(0,url)
            length = self.get_url_list_length()
            if len(urls) > length:
                del urls[len(urls) -1]
            self.conf.set_list(self.conf_dir + "/urls/media", gconf.VALUE_STRING, urls)

    def add_kickstart_url(self, url):
        urls = self.conf.get_list(self.conf_dir + "/urls/kickstart", gconf.VALUE_STRING)
        if urls == None:
            urls = []
        if urls.count(url) == 0:
            # the url isn't already in the list, so add it
            urls.insert(0,url)
            length = self.get_url_list_length()
            if len(urls) > length:
                del urls[len(urls) -1]
            self.conf.set_list(self.conf_dir + "/urls/kickstart", gconf.VALUE_STRING, urls)

    def add_connection(self, uri):
        uris = self.conf.get_list(self.conf_dir + "/connections/uris", gconf.VALUE_STRING)
        if uris == None:
            uris = []
        if uris.count(uri) == 0:
            # the url isn't already in the list, so add it
            uris.insert(len(uris) - 1,uri)
            self.conf.set_list(self.conf_dir + "/connections/uris", gconf.VALUE_STRING, uris)

    def remove_connection(self, uri):
        uris = self.conf.get_list(self.conf_dir + "/connections/uris", gconf.VALUE_STRING)
        if uris == None:
            return
        if uris.count(uri) != 0:
            uris.remove(uri)
            self.conf.set_list(self.conf_dir + "/connections/uris", gconf.VALUE_STRING, uris)
        if self.get_conn_autoconnect(uri):
            uris = self.conf.get_list(self.conf_dir + \
                                      "/connections/autoconnect",\
                                      gconf.VALUE_STRING)
            uris.remove(uri)
            self.conf.set_list(self.conf_dir + "/connections/autoconnect", \
                               gconf.VALUE_STRING, uris)


    def get_conn_autoconnect(self, uri):
        uris = self.conf.get_list(self.conf_dir + "/connections/autoconnect",\
                                  gconf.VALUE_STRING)
        return ((uris is not None) and (uri in uris))

    def toggle_conn_autoconnect(self, uri):
        uris = self.conf.get_list(self.conf_dir + "/connections/autoconnect",\
                                  gconf.VALUE_STRING)
        if uris is None:
            uris = []
        if uri in uris:
            uris.remove(uri)
        else:
            uris.append(uri)
        self.conf.set_list(self.conf_dir + "/connections/autoconnect", \
                           gconf.VALUE_STRING, uris)

    def get_media_urls(self):
        return self.conf.get_list(self.conf_dir + "/urls/media", gconf.VALUE_STRING)

    def get_kickstart_urls(self):
        return self.conf.get_list(self.conf_dir + "/urls/kickstart", gconf.VALUE_STRING)
    def get_connections(self):
        return self.conf.get_list(self.conf_dir + "/connections/uris", gconf.VALUE_STRING)


    def get_default_image_dir(self, connection):
        if connection.get_type() == "Xen":
            return DEFAULT_XEN_IMAGE_DIR

        if (connection.is_qemu_session() or
            not os.access(DEFAULT_VIRT_IMAGE_DIR, os.W_OK)):
            return os.getcwd()

        # Just return the default dir since the intention is that it
        # is a managed pool and the user will be able to install to it.
        return DEFAULT_VIRT_IMAGE_DIR

    def get_default_save_dir(self, connection):
        if connection.get_type() == "Xen":
            return DEFAULT_XEN_SAVE_DIR
        elif os.access(DEFAULT_VIRT_SAVE_DIR, os.W_OK):
            return DEFAULT_VIRT_SAVE_DIR
        else:
            return os.getcwd()


