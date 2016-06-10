#
# Copyright (C) 2006, 2012-2015 Red Hat, Inc.
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
import os
import logging

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

from virtinst import CPU
from .keyring import vmmKeyring, vmmSecret

RUNNING_CONFIG = None


class SettingsWrapper(object):
    """
    Wrapper class to simplify interacting with gsettings APIs
    """
    def __init__(self, settings_id, schemadir):
        self._root = settings_id

        os.environ["GSETTINGS_SCHEMA_DIR"] = schemadir
        self._settings = Gio.Settings.new(self._root)

        self._settingsmap = {"": self._settings}
        self._handler_map = {}

        for child in self._settings.list_children():
            childschema = self._root + "." + child
            self._settingsmap[child] = Gio.Settings.new(childschema)


    def _parse_key(self, key):
        value = key.strip("/")
        settingskey = ""
        if "/" in value:
            settingskey, value = value.rsplit("/", 1)
        return settingskey, value

    def make_vm_settings(self, key):
        """
        Initialize per-VM relocatable schema if necessary
        """
        settingskey = self._parse_key(key)[0]
        if settingskey in self._settingsmap:
            return True

        schema = self._root + ".vm"
        path = "/" + self._root.replace(".", "/") + key.rsplit("/", 1)[0] + "/"
        self._settingsmap[settingskey] = Gio.Settings.new_with_path(
                schema, path)
        return True

    def make_conn_settings(self, key):
        """
        Initialize per-conn relocatable schema if necessary
        """
        settingskey = self._parse_key(key)[0]
        if settingskey in self._settingsmap:
            return True

        schema = self._root + ".connection"
        path = "/" + self._root.replace(".", "/") + key.rsplit("/", 1)[0] + "/"
        self._settingsmap[settingskey] = Gio.Settings.new_with_path(
                schema, path)
        return True

    def _find_settings(self, key):
        settingskey, value = self._parse_key(key)
        return self._settingsmap[settingskey], value

    def _cmd_helper(self, cmd, key, *args, **kwargs):
        settings, key = self._find_settings(key)
        return getattr(settings, cmd)(key, *args, **kwargs)

    def notify_add(self, key, cb, *args, **kwargs):
        settings, key = self._find_settings(key)
        def wrapcb(*ignore):
            return cb(*args, **kwargs)
        ret = settings.connect("changed::%s" % key, wrapcb, *args, **kwargs)
        self._handler_map[ret] = settings
        return ret
    def notify_remove(self, h):
        settings = self._handler_map.pop(h)
        return settings.disconnect(h)

    def get(self, key):
        return self._cmd_helper("get_value", key).unpack()
    def set(self, key, value, *args, **kwargs):
        fmt = self._cmd_helper("get_value", key).get_type_string()
        return self._cmd_helper("set_value", key,
                                GLib.Variant(fmt, value),
                                *args, **kwargs)


class vmmConfig(object):
    # key names for saving last used paths
    CONFIG_DIR_IMAGE = "image"
    CONFIG_DIR_ISO_MEDIA = "isomedia"
    CONFIG_DIR_FLOPPY_MEDIA = "floppymedia"
    CONFIG_DIR_SCREENSHOT = "screenshot"
    CONFIG_DIR_FS = "fs"

    # Metadata mapping for browse types. Prob shouldn't go here, but works
    # for now.
    browse_reason_data = {
        CONFIG_DIR_IMAGE : {
            "enable_create" : True,
            "storage_title" : _("Locate or create storage volume"),
            "local_title"   : _("Locate existing storage"),
            "dialog_type"   : Gtk.FileChooserAction.SAVE,
            "choose_button" : Gtk.STOCK_OPEN,
        },

        CONFIG_DIR_ISO_MEDIA : {
            "enable_create" : False,
            "storage_title" : _("Locate ISO media volume"),
            "local_title"   : _("Locate ISO media"),
        },

        CONFIG_DIR_FLOPPY_MEDIA : {
            "enable_create" : False,
            "storage_title" : _("Locate floppy media volume"),
            "local_title"   : _("Locate floppy media"),
        },

        CONFIG_DIR_FS : {
            "enable_create" : False,
            "storage_title" : _("Locate directory volume"),
            "local_title"   : _("Locate directory volume"),
            "dialog_type"   : Gtk.FileChooserAction.SELECT_FOLDER,
        },
    }

    CONSOLE_SCALE_NEVER = 0
    CONSOLE_SCALE_FULLSCREEN = 1
    CONSOLE_SCALE_ALWAYS = 2

    def __init__(self, appname, CLIConfig, test_first_run=False):
        self.appname = appname
        self.appversion = CLIConfig.version
        self.conf_dir = "/org/virt-manager/%s/" % self.appname
        self.ui_dir = CLIConfig.ui_dir
        self.test_first_run = bool(test_first_run)

        self.conf = SettingsWrapper("org.virt-manager.virt-manager",
                CLIConfig.gsettings_dir)

        # We don't create it straight away, since we don't want
        # to block the app pending user authorization to access
        # the keyring
        self.keyring = None

        self.default_qemu_user = CLIConfig.default_qemu_user
        self.preferred_distros = CLIConfig.preferred_distros
        self.hv_packages = CLIConfig.hv_packages
        self.libvirt_packages = CLIConfig.libvirt_packages
        self.askpass_package = CLIConfig.askpass_package
        self.default_graphics_from_config = CLIConfig.default_graphics
        self.default_hvs = CLIConfig.default_hvs
        self.cli_usbredir = None

        self.default_storage_format_from_config = "qcow2"
        self.cpu_default_from_config = CPU.SPECIAL_MODE_HOST_MODEL_ONLY
        self.default_console_resizeguest = 0
        self.default_add_spice_usbredir = "yes"

        self._objects = []

        self.support_inspection = self.check_inspection()

        self._spice_error = None

        global RUNNING_CONFIG
        RUNNING_CONFIG = self


    def check_inspection(self):
        try:
            # Check we can open the Python guestfs module.
            from guestfs import GuestFS  # pylint: disable=import-error
            g = GuestFS(close_on_exit=False)
            return bool(getattr(g, "add_libvirt_dom", None))
        except:
            return False

    # General app wide helpers (gsettings agnostic)

    def get_appname(self):
        return self.appname
    def get_appversion(self):
        return self.appversion
    def get_ui_dir(self):
        return self.ui_dir

    def embeddable_graphics(self):
        ret = ["vnc", "spice"]
        return ret

    def remove_notifier(self, h):
        self.conf.notify_remove(h)

    # Used for debugging reference leaks, we keep track of all objects
    # come and go so we can do a leak report at app shutdown
    def add_object(self, obj):
        self._objects.append(obj)
    def remove_object(self, obj):
        self._objects.remove(obj)
    def get_objects(self):
        return self._objects[:]


    #####################################
    # Wrappers for setting per-VM value #
    #####################################

    def _make_pervm_key(self, uuid, key):
        return "/vms/%s%s" % (uuid.replace("-", ""), key)

    def listen_pervm(self, uuid, key, *args, **kwargs):
        key = self._make_pervm_key(uuid, key)
        self.conf.make_vm_settings(key)
        return self.conf.notify_add(key, *args, **kwargs)

    def set_pervm(self, uuid, key, *args, **kwargs):
        key = self._make_pervm_key(uuid, key)
        self.conf.make_vm_settings(key)
        ret = self.conf.set(key, *args, **kwargs)
        return ret

    def get_pervm(self, uuid, key):
        key = self._make_pervm_key(uuid, key)
        self.conf.make_vm_settings(key)
        return self.conf.get(key)


    ########################################
    # Wrappers for setting per-conn values #
    ########################################

    def _make_perconn_key(self, uri, key):
        return "/conns/%s%s" % (uri.replace("/", ""), key)

    def listen_perconn(self, uri, key, *args, **kwargs):
        key = self._make_perconn_key(uri, key)
        self.conf.make_conn_settings(key)
        return self.conf.notify_add(key, *args, **kwargs)

    def set_perconn(self, uri, key, *args, **kwargs):
        key = self._make_perconn_key(uri, key)
        self.conf.make_conn_settings(key)
        ret = self.conf.set(key, *args, **kwargs)
        return ret

    def get_perconn(self, uri, key):
        key = self._make_perconn_key(uri, key)
        self.conf.make_conn_settings(key)
        return self.conf.get(key)


    ###################
    # General helpers #
    ###################

    # Manager stats view preferences
    def is_vmlist_guest_cpu_usage_visible(self):
        return self.conf.get("/vmlist-fields/cpu-usage")
    def is_vmlist_host_cpu_usage_visible(self):
        return self.conf.get("/vmlist-fields/host-cpu-usage")
    def is_vmlist_memory_usage_visible(self):
        return self.conf.get("/vmlist-fields/memory-usage")
    def is_vmlist_disk_io_visible(self):
        return self.conf.get("/vmlist-fields/disk-usage")
    def is_vmlist_network_traffic_visible(self):
        return self.conf.get("/vmlist-fields/network-traffic")

    def set_vmlist_guest_cpu_usage_visible(self, state):
        self.conf.set("/vmlist-fields/cpu-usage", state)
    def set_vmlist_host_cpu_usage_visible(self, state):
        self.conf.set("/vmlist-fields/host-cpu-usage", state)
    def set_vmlist_memory_usage_visible(self, state):
        self.conf.set("/vmlist-fields/memory-usage", state)
    def set_vmlist_disk_io_visible(self, state):
        self.conf.set("/vmlist-fields/disk-usage", state)
    def set_vmlist_network_traffic_visible(self, state):
        self.conf.set("/vmlist-fields/network-traffic", state)

    def on_vmlist_guest_cpu_usage_visible_changed(self, cb):
        return self.conf.notify_add("/vmlist-fields/cpu-usage", cb)
    def on_vmlist_host_cpu_usage_visible_changed(self, cb):
        return self.conf.notify_add("/vmlist-fields/host-cpu-usage", cb)
    def on_vmlist_memory_usage_visible_changed(self, cb):
        return self.conf.notify_add("/vmlist-fields/memory-usage", cb)
    def on_vmlist_disk_io_visible_changed(self, cb):
        return self.conf.notify_add("/vmlist-fields/disk-usage", cb)
    def on_vmlist_network_traffic_visible_changed(self, cb):
        return self.conf.notify_add("/vmlist-fields/network-traffic", cb)

    # Keys preferences
    def get_keys_combination(self):
        ret = self.conf.get("/console/grab-keys")
        if not ret:
            # Left Control + Left Alt
            return "65507,65513"
        return ret
    def set_keys_combination(self, val):
        # Val have to be a list of integers
        val = ','.join([str(v) for v in val])
        self.conf.set("/console/grab-keys", val)
    def on_keys_combination_changed(self, cb):
        return self.conf.notify_add("/console/grab-keys", cb)

    # This key is not intended to be exposed in the UI yet
    def get_keyboard_grab_default(self):
        return self.conf.get("/console/grab-keyboard")
    def set_keyboard_grab_default(self, val):
        self.conf.set("/console/grab-keyboard", val)
    def on_keyboard_grab_default_changed(self, cb):
        return self.conf.notify_add("/console/grab-keyboard", cb)

    # Confirmation preferences
    def get_confirm_forcepoweroff(self):
        return self.conf.get("/confirm/forcepoweroff")
    def get_confirm_poweroff(self):
        return self.conf.get("/confirm/poweroff")
    def get_confirm_pause(self):
        return self.conf.get("/confirm/pause")
    def get_confirm_removedev(self):
        return self.conf.get("/confirm/removedev")
    def get_confirm_interface(self):
        return self.conf.get("/confirm/interface-power")
    def get_confirm_unapplied(self):
        return self.conf.get("/confirm/unapplied-dev")
    def get_confirm_delstorage(self):
        return self.conf.get("/confirm/delete-storage")


    def set_confirm_forcepoweroff(self, val):
        self.conf.set("/confirm/forcepoweroff", val)
    def set_confirm_poweroff(self, val):
        self.conf.set("/confirm/poweroff", val)
    def set_confirm_pause(self, val):
        self.conf.set("/confirm/pause", val)
    def set_confirm_removedev(self, val):
        self.conf.set("/confirm/removedev", val)
    def set_confirm_interface(self, val):
        self.conf.set("/confirm/interface-power", val)
    def set_confirm_unapplied(self, val):
        self.conf.set("/confirm/unapplied-dev", val)
    def set_confirm_delstorage(self, val):
        self.conf.set("/confirm/delete-storage", val)


    # System tray visibility
    def on_view_system_tray_changed(self, cb):
        return self.conf.notify_add("/system-tray", cb)
    def get_view_system_tray(self):
        return self.conf.get("/system-tray")
    def set_view_system_tray(self, val):
        self.conf.set("/system-tray", val)


    # Stats history and interval length
    def get_stats_history_length(self):
        return 120
    def get_stats_update_interval(self):
        interval = self.conf.get("/stats/update-interval")
        if interval < 1:
            return 1
        return interval
    def set_stats_update_interval(self, interval):
        self.conf.set("/stats/update-interval", interval)
    def on_stats_update_interval_changed(self, cb):
        return self.conf.notify_add("/stats/update-interval", cb)


    # Disable/Enable different stats polling
    def get_stats_enable_cpu_poll(self):
        return self.conf.get("/stats/enable-cpu-poll")
    def get_stats_enable_disk_poll(self):
        return self.conf.get("/stats/enable-disk-poll")
    def get_stats_enable_net_poll(self):
        return self.conf.get("/stats/enable-net-poll")
    def get_stats_enable_memory_poll(self):
        return self.conf.get("/stats/enable-memory-poll")

    def set_stats_enable_cpu_poll(self, val):
        self.conf.set("/stats/enable-cpu-poll", val)
    def set_stats_enable_disk_poll(self, val):
        self.conf.set("/stats/enable-disk-poll", val)
    def set_stats_enable_net_poll(self, val):
        self.conf.set("/stats/enable-net-poll", val)
    def set_stats_enable_memory_poll(self, val):
        self.conf.set("/stats/enable-memory-poll", val)

    def on_stats_enable_cpu_poll_changed(self, cb, row=None):
        return self.conf.notify_add("/stats/enable-cpu-poll", cb, row)
    def on_stats_enable_disk_poll_changed(self, cb, row=None):
        return self.conf.notify_add("/stats/enable-disk-poll", cb, row)
    def on_stats_enable_net_poll_changed(self, cb, row=None):
        return self.conf.notify_add("/stats/enable-net-poll", cb, row)
    def on_stats_enable_memory_poll_changed(self, cb, row=None):
        return self.conf.notify_add("/stats/enable-memory-poll", cb, row)

    # VM Console preferences
    def on_console_accels_changed(self, cb):
        return self.conf.notify_add("/console/enable-accels", cb)
    def get_console_accels(self):
        console_pref = self.conf.get("/console/enable-accels")
        if console_pref is None:
            console_pref = False
        return console_pref
    def set_console_accels(self, pref):
        self.conf.set("/console/enable-accels", pref)

    def on_console_scaling_changed(self, cb):
        return self.conf.notify_add("/console/scaling", cb)
    def get_console_scaling(self):
        return self.conf.get("/console/scaling")
    def set_console_scaling(self, pref):
        self.conf.set("/console/scaling", pref)

    def on_console_resizeguest_changed(self, cb):
        return self.conf.notify_add("/console/resize-guest", cb)
    def get_console_resizeguest(self):
        val = self.conf.get("/console/resize-guest")
        if val == -1:
            val = self.default_console_resizeguest
        return val
    def set_console_resizeguest(self, pref):
        self.conf.set("/console/resize-guest", pref)

    def get_auto_redirection(self):
        if self.cli_usbredir is not None:
            return self.cli_usbredir
        return self.conf.get("/console/auto-redirect")
    def set_auto_redirection(self, state):
        self.conf.set("/console/auto-redirect", state)

    # Show VM details toolbar
    def get_details_show_toolbar(self):
        res = self.conf.get("/details/show-toolbar")
        if res is None:
            res = True
        return res
    def set_details_show_toolbar(self, state):
        self.conf.set("/details/show-toolbar", state)

    # VM details default size
    def get_details_window_size(self):
        w = self.conf.get("/details/window_width")
        h = self.conf.get("/details/window_height")
        return (w, h)
    def set_details_window_size(self, w, h):
        self.conf.set("/details/window_width", w)
        self.conf.set("/details/window_height", h)


    # New VM preferences
    def get_new_vm_sound(self):
        return self.conf.get("/new-vm/add-sound")
    def set_new_vm_sound(self, state):
        self.conf.set("/new-vm/add-sound", state)

    def get_graphics_type(self, raw=False):
        ret = self.conf.get("/new-vm/graphics-type")
        if ret not in ["system", "vnc", "spice"]:
            ret = "system"
        if ret == "system" and not raw:
            return self.default_graphics_from_config
        return ret
    def set_graphics_type(self, gtype):
        self.conf.set("/new-vm/graphics-type", gtype.lower())

    def get_add_spice_usbredir(self, raw=False):
        ret = self.conf.get("/new-vm/add-spice-usbredir")
        if ret not in ["system", "yes", "no"]:
            ret = "system"
        if not raw and self.get_graphics_type() != "spice":
            return "no"
        if ret == "system" and not raw:
            return self.default_add_spice_usbredir
        return ret
    def set_add_spice_usbredir(self, val):
        self.conf.set("/new-vm/add-spice-usbredir", val)

    def get_default_storage_format(self, raw=False):
        ret = self.conf.get("/new-vm/storage-format")
        if ret not in ["default", "raw", "qcow2"]:
            ret = "default"
        if ret == "default" and not raw:
            return self.default_storage_format_from_config
        return ret
    def set_storage_format(self, typ):
        self.conf.set("/new-vm/storage-format", typ.lower())

    def get_default_cpu_setting(self, raw=False, for_cpu=False):
        ret = self.conf.get("/new-vm/cpu-default")
        whitelist = [CPU.SPECIAL_MODE_HOST_MODEL_ONLY,
                     CPU.SPECIAL_MODE_HOST_MODEL,
                     CPU.SPECIAL_MODE_HV_DEFAULT]

        if ret not in whitelist:
            ret = "default"
        if ret == "default" and not raw:
            ret = self.cpu_default_from_config
            if ret not in whitelist:
                ret = whitelist[0]

        if for_cpu and ret == CPU.SPECIAL_MODE_HOST_MODEL:
            # host-model has known issues, so use our 'copy cpu'
            # behavior until host-model does what we need
            ret = CPU.SPECIAL_MODE_HOST_COPY

        return ret
    def set_default_cpu_setting(self, val):
        self.conf.set("/new-vm/cpu-default", val.lower())


    # URL/Media path history
    def _url_add_helper(self, gsettings_path, url):
        maxlength = 10
        urls = self.conf.get(gsettings_path)
        if urls is None:
            urls = []

        if urls.count(url) == 0 and len(url) > 0 and not url.isspace():
            # The url isn't already in the list, so add it
            urls.insert(0, url)
            if len(urls) > maxlength:
                del urls[len(urls) - 1]
            self.conf.set(gsettings_path, urls)

    def add_media_url(self, url):
        self._url_add_helper("/urls/urls", url)
    def add_iso_path(self, path):
        self._url_add_helper("/urls/isos", path)

    def get_media_urls(self):
        return self.conf.get("/urls/urls")
    def get_iso_paths(self):
        return self.conf.get("/urls/isos")


    # Whether to ask about fixing path permissions
    def add_perms_fix_ignore(self, pathlist):
        current_list = self.get_perms_fix_ignore() or []
        for path in pathlist:
            if path in current_list:
                continue
            current_list.append(path)
        self.conf.set("/paths/perms-fix-ignore", current_list)
    def get_perms_fix_ignore(self):
        return self.conf.get("/paths/perms-fix-ignore")


    # Manager view connection list
    def add_conn(self, uri):
        if self.test_first_run:
            return

        uris = self.conf.get("/connections/uris")
        if uris is None:
            uris = []

        if uris.count(uri) == 0:
            uris.insert(len(uris) - 1, uri)
            self.conf.set("/connections/uris", uris)
    def remove_conn(self, uri):
        uris = self.conf.get("/connections/uris")

        if uris is None:
            return

        if uris.count(uri) != 0:
            uris.remove(uri)
            self.conf.set("/connections/uris", uris)

        if self.get_conn_autoconnect(uri):
            uris = self.conf.get("/connections/autoconnect")
            uris.remove(uri)
            self.conf.set("/connections/autoconnect", uris)

    def get_conn_uris(self):
        if self.test_first_run:
            return []
        return self.conf.get("/connections/uris")

    # Manager default window size
    def get_manager_window_size(self):
        w = self.conf.get("/manager-window-width")
        h = self.conf.get("/manager-window-height")
        return (w, h)
    def set_manager_window_size(self, w, h):
        self.conf.set("/manager-window-width", w)
        self.conf.set("/manager-window-height", h)

    # URI autoconnect
    def get_conn_autoconnect(self, uri):
        uris = self.conf.get("/connections/autoconnect")
        return ((uris is not None) and (uri in uris))

    def set_conn_autoconnect(self, uri, val):
        if self.test_first_run:
            return

        uris = self.conf.get("/connections/autoconnect")
        if uris is None:
            uris = []
        if not val and uri in uris:
            uris.remove(uri)
        elif val and uri not in uris:
            uris.append(uri)

        self.conf.set("/connections/autoconnect", uris)


    # Default directory location dealings
    def _get_default_dir_key(self, _type):
        if (_type in [self.CONFIG_DIR_ISO_MEDIA,
                      self.CONFIG_DIR_FLOPPY_MEDIA]):
            return "media"
        if (_type in [self.CONFIG_DIR_IMAGE,
                      self.CONFIG_DIR_SCREENSHOT]):
            return _type
        return None

    def get_default_directory(self, conn, _type):
        ignore = conn
        key = self._get_default_dir_key(_type)
        path = None

        if key:
            path = self.conf.get("/paths/%s-default" % key)

        if not path:
            if (_type == self.CONFIG_DIR_IMAGE or
                _type == self.CONFIG_DIR_ISO_MEDIA or
                _type == self.CONFIG_DIR_FLOPPY_MEDIA):
                path = os.getcwd()

        logging.debug("directory for type=%s returning=%s", _type, path)
        return path

    def set_default_directory(self, folder, _type):
        key = self._get_default_dir_key(_type)
        if not key:
            return

        logging.debug("saving directory for type=%s to %s", key, folder)
        self.conf.set("/paths/%s-default" % key, folder)

    # Keyring / VNC password dealings
    def get_secret_name(self, vm):
        return "vm-console-" + vm.get_uuid()

    def has_keyring(self):
        if self.keyring is None:
            self.keyring = vmmKeyring()
        return self.keyring.is_available()

    def get_console_password(self, vm):
        if not self.has_keyring():
            return ("", "")

        username, keyid = vm.get_console_password()

        if keyid == -1:
            return ("", "")

        secret = self.keyring.get_secret(keyid)
        if secret is None or secret.get_name() != self.get_secret_name(vm):
            return ("", "")

        if (secret.attributes.get("hvuri", None) != vm.conn.get_uri() or
            secret.attributes.get("uuid", None) != vm.get_uuid()):
            return ("", "")

        return (secret.get_secret(), username or "")

    def set_console_password(self, vm, password, username=""):
        if not self.has_keyring():
            return

        secret = vmmSecret(self.get_secret_name(vm), password,
                           {"uuid" : vm.get_uuid(),
                            "hvuri": vm.conn.get_uri()})
        keyid = self.keyring.add_secret(secret)
        if keyid is None:
            return

        vm.set_console_password(username, keyid)

    def del_console_password(self, vm):
        if not self.has_keyring():
            return

        ignore, keyid = vm.get_console_password()

        if keyid == -1:
            return

        self.keyring.del_secret(keyid)

        vm.del_console_password()
