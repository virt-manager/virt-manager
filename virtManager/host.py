# Copyright (C) 2007, 2013-2014 Red Hat, Inc.
# Copyright (C) 2007 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from virtinst import log

from .lib import uiutil
from .baseclass import vmmGObjectUI
from .engine import vmmEngine
from .lib.graphwidgets import Sparkline
from .hostnets import vmmHostNets
from .hoststorage import vmmHostStorage


class vmmHost(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj, conn):
        try:
            # Maintain one dialog per connection
            uri = conn.get_uri()
            if cls._instances is None:
                cls._instances = {}
            if uri not in cls._instances:
                cls._instances[uri] = vmmHost(conn)
            cls._instances[uri].show()
        except Exception as e:  # pragma: no cover
            if not parentobj:
                raise
            parentobj.err.show_err(
                    _("Error launching host dialog: %s") % str(e))

    def __init__(self, conn):
        vmmGObjectUI.__init__(self, "host.ui", "vmm-host")
        self.conn = conn

        # Set default window size
        w, h = self.conn.get_details_window_size()
        if w <= 0:
            w = 800
        if h <= 0:
            h = 600
        self.topwin.set_default_size(w, h)
        self._window_size = None

        self._cpu_usage_graph = None
        self._memory_usage_graph = None
        self._init_conn_state()

        self._storagelist = None
        self._init_storage_state()

        self._hostnets = None
        self._init_net_state()

        self.builder.connect_signals({
            "on_menu_file_view_manager_activate": self._view_manager_cb,
            "on_menu_file_quit_activate": self._exit_app_cb,
            "on_menu_file_close_activate": self.close,
            "on_vmm_host_delete_event": self.close,
            "on_vmm_host_configure_event": self._window_resized_cb,
            "on_host_page_switch": self._page_changed_cb,

            "on_overview_name_changed": self._overview_name_changed_cb,
            "on_config_autoconnect_toggled": self._autoconnect_toggled_cb,
        })

        self.conn.connect("state-changed", self._conn_state_changed_cb)
        self.conn.connect("resources-sampled", self._conn_resources_sampled_cb)

        self._refresh_resources()
        self._refresh_conn_state()
        self.widget("config-autoconnect").set_active(
            self.conn.get_autoconnect())

        self._cleanup_on_conn_removed()


    #######################
    # Standard UI methods #
    #######################

    def show(self):
        log.debug("Showing host details: %s", self.conn)
        vis = self.is_visible()
        self.topwin.present()
        if vis:
            return  # pragma: no cover

        vmmEngine.get_instance().increment_window_counter()

    def close(self, src=None, event=None):
        dummy = src
        dummy = event
        log.debug("Closing host window for %s", self.conn)
        if not self.is_visible():
            return

        self.topwin.hide()
        vmmEngine.get_instance().decrement_window_counter()

        return 1

    def _cleanup(self):
        if self._window_size:
            self.conn.set_details_window_size(*self._window_size)

        self.conn = None

        self._storagelist.cleanup()
        self._storagelist = None

        self._hostnets.cleanup()
        self._hostnets = None

        self._cpu_usage_graph.destroy()
        self._cpu_usage_graph = None

        self._memory_usage_graph.destroy()
        self._memory_usage_graph = None


    ###########
    # UI init #
    ###########

    def _init_net_state(self):
        self._hostnets = vmmHostNets(self.conn, self.builder, self.topwin)
        self.widget("net-align").add(self._hostnets.top_box)

    def _init_storage_state(self):
        self._storagelist = vmmHostStorage(self.conn, self.builder, self.topwin)
        self.widget("storage-align").add(self._storagelist.top_box)

    def _init_conn_state(self):
        uri = self.conn.get_uri()
        auto = self.conn.get_autoconnect()

        self.widget("overview-uri").set_text(uri)
        self.widget("config-autoconnect").set_active(auto)

        self._cpu_usage_graph = Sparkline()
        self._cpu_usage_graph.show()
        self.widget("performance-cpu-align").add(self._cpu_usage_graph)

        self._memory_usage_graph = Sparkline()
        self._memory_usage_graph.show()
        self.widget("performance-memory-align").add(self._memory_usage_graph)


    ######################
    # UI conn populating #
    ######################

    def _refresh_resources(self):
        vm_memory = uiutil.pretty_mem(self.conn.stats_memory())
        host_memory = uiutil.pretty_mem(self.conn.host_memory_size())

        cpu_vector = self.conn.host_cpu_time_vector()
        memory_vector = self.conn.stats_memory_vector()
        cpu_vector.reverse()
        memory_vector.reverse()

        self.widget("performance-cpu").set_text("%d %%" %
                                        self.conn.host_cpu_time_percentage())
        self.widget("performance-memory").set_text(
                            _("%(currentmem)s of %(maxmem)s") %
                            {'currentmem': vm_memory, 'maxmem': host_memory})

        self._cpu_usage_graph.set_property("data_array", cpu_vector)
        self._memory_usage_graph.set_property("data_array", memory_vector)

    def _refresh_conn_state(self):
        conn_active = self.conn.is_active()

        self.topwin.set_title(
            _("%(connection)s - Connection Details") %
            {"connection": self.conn.get_pretty_desc()})
        if not self.widget("overview-name").has_focus():
            self.widget("overview-name").set_text(self.conn.get_pretty_desc())

        if conn_active:
            return
        self._hostnets.close()
        self._storagelist.close()


    ################
    # UI listeners #
    ################

    def _view_manager_cb(self, src):
        from .manager import vmmManager
        vmmManager.get_instance(self).show()

    def _exit_app_cb(self, src):
        vmmEngine.get_instance().exit_app()

    def _window_resized_cb(self, src, event):
        if not self.is_visible():
            return
        self._window_size = self.topwin.get_size()

    def _overview_name_changed_cb(self, src):
        src = self.widget("overview-name")
        self.conn.set_config_pretty_name(src.get_text())

    def _autoconnect_toggled_cb(self, src):
        self.conn.set_autoconnect(src.get_active())

    def _page_changed_cb(self, src, child, pagenum):
        if pagenum == 1:
            self._hostnets.refresh_page()
        elif pagenum == 2:
            self._storagelist.refresh_page()

    def _conn_state_changed_cb(self, conn):
        self._refresh_conn_state()

    def _conn_resources_sampled_cb(self, conn):
        self._refresh_resources()
