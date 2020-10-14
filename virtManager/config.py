# Copyright (C) 2006, 2012-2015 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

from virtinst import DomainCpu
from virtinst import log

from .lib.inspection import vmmInspection


CSSDATA = """
/* Lighter colored text in some wizard summary fields */
.vmm-lighter {
    color: @insensitive_fg_color
}

/* Text on the blue header in our wizards */
.vmm-header-text {
    color: white
}

/* Subtext on the blue header in our wizards */
.vmm-header-subtext {
    color: #59B0E2
}

/* The blue header */
.vmm-header {
    background-color: #0072A8
}
"""


class _SettingsWrapper(object):
    """
    Wrapper class to simplify interacting with gsettings APIs.
    Basically it allows simple get/set of gconf style paths, and
    we internally convert it to the settings nested hierarchy. Makes
    client code much smaller.
    """
    def __init__(self, settings_id, gsettings_keyfile):
        self._root = settings_id

        if gsettings_keyfile:
            backend = Gio.keyfile_settings_backend_new(gsettings_keyfile, "/")
        else:
            backend = Gio.SettingsBackend.get_default()

        self._settings = Gio.Settings.new_with_backend(self._root, backend)

        self._settingsmap = {"": self._settings}
        self._handler_map = {}

        for child in self._settings.list_children():
            childschema = self._root + "." + child
            self._settingsmap[child] = Gio.Settings.new_with_backend(
                    childschema, backend)


    ###################
    # Private helpers #
    ###################

    def _parse_key(self, key):
        value = key.strip("/")
        settingskey = ""
        if "/" in value:
            settingskey, value = value.rsplit("/", 1)
        return settingskey, value

    def _find_settings(self, key):
        settingskey, value = self._parse_key(key)
        return self._settingsmap[settingskey], value


    ###############
    # Public APIs #
    ###############

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
        settings, key = self._find_settings(key)
        return settings.get_value(key).unpack()
    def set(self, key, value, *args, **kwargs):
        settings, key = self._find_settings(key)
        fmt = settings.get_value(key).get_type_string()
        return settings.set_value(key, GLib.Variant(fmt, value),
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
        CONFIG_DIR_IMAGE: {
            "enable_create":  True,
            "storage_title":  _("Locate or create storage volume"),
            "local_title":    _("Locate existing storage"),
            "dialog_type":    Gtk.FileChooserAction.SAVE,
            "choose_button":  Gtk.STOCK_OPEN,
            "gsettings_key": "image",
        },

        CONFIG_DIR_SCREENSHOT: {
            "gsettings_key": "screenshot",
        },

        CONFIG_DIR_ISO_MEDIA: {
            "enable_create":  False,
            "storage_title":  _("Locate ISO media volume"),
            "local_title":    _("Locate ISO media"),
            "gsettings_key": "media",
        },

        CONFIG_DIR_FLOPPY_MEDIA: {
            "enable_create":  False,
            "storage_title":  _("Locate floppy media volume"),
            "local_title":    _("Locate floppy media"),
            "gsettings_key": "media",
        },

        CONFIG_DIR_FS: {
            "enable_create":  False,
            "storage_title":  _("Locate directory volume"),
            "local_title":    _("Locate directory volume"),
            "dialog_type":    Gtk.FileChooserAction.SELECT_FOLDER,
        },
    }

    CONSOLE_SCALE_NEVER = 0
    CONSOLE_SCALE_FULLSCREEN = 1
    CONSOLE_SCALE_ALWAYS = 2

    _instance = None

    @classmethod
    def get_instance(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = vmmConfig(*args, **kwargs)
        return cls._instance

    @classmethod
    def is_initialized(cls):
        return bool(cls._instance)

    def __init__(self, BuildConfig, CLITestOptions):
        self.appname = "virt-manager"
        self.appversion = BuildConfig.version
        self.conf_dir = "/org/virt-manager/%s/" % self.appname
        self.ui_dir = BuildConfig.ui_dir

        self.conf = _SettingsWrapper("org.virt-manager.virt-manager",
                CLITestOptions.gsettings_keyfile)

        self.CLITestOptions = CLITestOptions
        if self.CLITestOptions.xmleditor_enabled:
            self.set_xmleditor_enabled(True)
        if self.CLITestOptions.enable_libguestfs:
            self.set_libguestfs_inspect_vms(True)
        if self.CLITestOptions.disable_libguestfs:
            self.set_libguestfs_inspect_vms(False)

        # We don't create it straight away, since we don't want
        # to block the app pending user authorization to access
        # the keyring
        self._keyring = None

        self.default_graphics_from_config = BuildConfig.default_graphics
        self.default_hvs = BuildConfig.default_hvs

        self.default_storage_format_from_config = "qcow2"
        self.default_console_resizeguest = 0

        self._objects = []
        self.color_insensitive = None
        self._init_css()

    def _init_css(self):
        from gi.repository import Gdk
        screen = Gdk.Screen.get_default()

        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSSDATA.encode("utf-8"))

        context = Gtk.StyleContext()
        context.add_provider_for_screen(screen, css_provider,
             Gtk.STYLE_PROVIDER_PRIORITY_USER)

        found, color = context.lookup_color("insensitive_fg_color")
        if not found:  # pragma: no cover
            log.debug("Didn't find insensitive_fg_color in theme")
            return
        self.color_insensitive = color.to_string()


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

    def inspection_supported(self):
        if not vmmInspection.libguestfs_installed():
            return False  # pragma: no cover
        return self.get_libguestfs_inspect_vms()

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

    # Confirmation preferences
    def get_confirm_forcepoweroff(self):
        return self.conf.get("/confirm/forcepoweroff")
    def get_confirm_poweroff(self):
        return self.conf.get("/confirm/poweroff")
    def get_confirm_pause(self):
        return self.conf.get("/confirm/pause")
    def get_confirm_removedev(self):
        return self.conf.get("/confirm/removedev")
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


    # XML editor enabled
    def on_xmleditor_enabled_changed(self, cb):
        return self.conf.notify_add("/xmleditor-enabled", cb)
    def get_xmleditor_enabled(self):
        return self.conf.get("/xmleditor-enabled")
    def set_xmleditor_enabled(self, val):
        self.conf.set("/xmleditor-enabled", val)


    # Libguestfs VM inspection
    def get_libguestfs_inspect_vms(self):
        return self.conf.get("/enable-libguestfs-vm-inspection")
    def set_libguestfs_inspect_vms(self, val):
        self.conf.set("/enable-libguestfs-vm-inspection", val)


    # Stats history and interval length
    def get_stats_history_length(self):
        return 120
    def get_stats_update_interval(self):
        if self.CLITestOptions.short_poll:
            return .1
        interval = self.conf.get("/stats/update-interval")
        return max(interval, 1)
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

    def get_console_scaling(self):
        return self.conf.get("/console/scaling")
    def set_console_scaling(self, pref):
        self.conf.set("/console/scaling", pref)

    def get_console_resizeguest(self):
        val = self.conf.get("/console/resize-guest")
        if val == -1:
            val = self.default_console_resizeguest
        return val
    def set_console_resizeguest(self, pref):
        self.conf.set("/console/resize-guest", pref)

    def get_auto_usbredir(self):
        return bool(self.conf.get("/console/auto-redirect"))
    def set_auto_usbredir(self, state):
        self.conf.set("/console/auto-redirect", state)

    def get_auto_clipboard(self):
        return bool(self.conf.get("/console/auto-clipboard"))
    def set_auto_clipboard(self, state):
        self.conf.set("/console/auto-clipboard", state)

    def get_console_autoconnect(self):
        return bool(self.conf.get("/console/autoconnect"))
    def set_console_autoconnect(self, val):
        return self.conf.set("/console/autoconnect", val)

    # Show VM details toolbar
    def get_details_show_toolbar(self):
        res = self.conf.get("/details/show-toolbar")
        if res is None:
            res = True  # pragma: no cover
        return res
    def set_details_show_toolbar(self, state):
        self.conf.set("/details/show-toolbar", state)

    # New VM preferences
    def get_graphics_type(self, raw=False):
        ret = self.conf.get("/new-vm/graphics-type")
        if ret not in ["system", "vnc", "spice"]:
            ret = "system"  # pragma: no cover
        if ret == "system" and not raw:
            return self.default_graphics_from_config
        return ret
    def set_graphics_type(self, gtype):
        self.conf.set("/new-vm/graphics-type", gtype.lower())

    def get_default_storage_format(self, raw=False):
        ret = self.conf.get("/new-vm/storage-format")
        if ret not in ["default", "raw", "qcow2"]:
            ret = "default"  # pragma: no cover
        if ret == "default" and not raw:
            return self.default_storage_format_from_config
        return ret
    def set_storage_format(self, typ):
        self.conf.set("/new-vm/storage-format", typ.lower())

    def get_default_cpu_setting(self):
        ret = self.conf.get("/new-vm/cpu-default")

        if ret not in DomainCpu.SPECIAL_MODES:
            ret = DomainCpu.SPECIAL_MODE_APP_DEFAULT  # pragma: no cover
        return ret
    def set_default_cpu_setting(self, val):
        self.conf.set("/new-vm/cpu-default", val.lower())


    # URL/Media path history
    def _url_add_helper(self, gsettings_path, url):
        maxlength = 10
        urls = self.conf.get(gsettings_path) or []

        if urls.count(url) == 0 and len(url) > 0 and not url.isspace():
            # The url isn't already in the list, so add it
            urls.insert(0, url)
            if len(urls) > maxlength:
                del urls[len(urls) - 1]  # pragma: no cover
            self.conf.set(gsettings_path, urls)

    def add_container_url(self, url):
        self._url_add_helper("/urls/containers", url)
    def get_container_urls(self):
        return self.conf.get("/urls/containers") or []

    def add_media_url(self, url):
        self._url_add_helper("/urls/urls", url)
    def get_media_urls(self):
        return self.conf.get("/urls/urls") or []

    def add_iso_path(self, path):
        self._url_add_helper("/urls/isos", path)
    def get_iso_paths(self):
        return self.conf.get("/urls/isos") or []
    def on_iso_paths_changed(self, cb):
        return self.conf.notify_add("/urls/isos", cb)


    # Whether to ask about fixing path permissions
    def add_perms_fix_ignore(self, pathlist):
        current_list = self.get_perms_fix_ignore() or []
        for path in pathlist:
            if path in current_list:
                continue  # pragma: no cover
            current_list.append(path)
        self.conf.set("/paths/perms-fix-ignore", current_list)
    def get_perms_fix_ignore(self):
        return self.conf.get("/paths/perms-fix-ignore")


    # Manager view connection list
    def get_conn_uris(self):
        return self.conf.get("/connections/uris") or []
    def add_conn_uri(self, uri):
        uris = self.get_conn_uris()
        if uri not in uris:
            uris.insert(len(uris) - 1, uri)
            self.conf.set("/connections/uris", uris)
    def remove_conn_uri(self, uri):
        uris = self.get_conn_uris()
        if uri in uris:
            uris.remove(uri)
            self.conf.set("/connections/uris", uris)

        if self.get_conn_autoconnect(uri):
            uris = self.conf.get("/connections/autoconnect")
            uris.remove(uri)
            self.conf.set("/connections/autoconnect", uris)

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
        uris = self.conf.get("/connections/autoconnect") or []
        if not val and uri in uris:
            uris.remove(uri)
        elif val and uri not in uris:
            uris.append(uri)

        self.conf.set("/connections/autoconnect", uris)


    # Default directory location dealings
    def get_default_directory(self, conn, _type):
        ignore = conn
        browsedata = self.browse_reason_data.get(_type, {})
        key = browsedata.get("gsettings_key", None)
        path = None

        if key:
            path = self.conf.get("/paths/%s-default" % key)

        log.debug("directory for type=%s returning=%s", _type, path)
        return path

    def set_default_directory(self, folder, _type):
        browsedata = self.browse_reason_data.get(_type, {})
        key = browsedata.get("gsettings_key", None)
        if not key:
            return  # pragma: no cover

        log.debug("saving directory for type=%s to %s", key, folder)
        self.conf.set("/paths/%s-default" % key, folder)
