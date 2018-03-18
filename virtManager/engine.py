#
# Copyright (C) 2006, 2013-2014 Red Hat, Inc.
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
import queue
import threading

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

from . import packageutils
from .baseclass import vmmGObject
from .connect import vmmConnect
from .connmanager import vmmConnectionManager
from .inspection import vmmInspection
from .systray import vmmSystray

DETAILS_PERF = 1
DETAILS_CONFIG = 2
DETAILS_CONSOLE = 3

(PRIO_HIGH,
 PRIO_LOW) = range(1, 3)


def _show_startup_error(fn):
    """
    Decorator to show a modal error dialog if an exception is raised
    from a startup routine
    """
    # pylint: disable=protected-access
    def newfn(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as e:
            modal = self._can_exit()
            self.err.show_err(str(e), modal=modal)
            self._exit_app_if_no_windows()
    return newfn


class vmmEngine(vmmGObject):
    CLI_SHOW_MANAGER = "manager"
    CLI_SHOW_DOMAIN_CREATOR = "creator"
    CLI_SHOW_DOMAIN_EDITOR = "editor"
    CLI_SHOW_DOMAIN_PERFORMANCE = "performance"
    CLI_SHOW_DOMAIN_CONSOLE = "console"
    CLI_SHOW_HOST_SUMMARY = "summary"

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = vmmEngine()
        return cls._instance

    __gsignals__ = {
        "app-closing": (vmmGObject.RUN_FIRST, None, []),
    }

    def __init__(self):
        vmmGObject.__init__(self)

        self._exiting = False

        self._window_count = 0
        self._gtkapplication = None
        self._init_gtk_application()

        self._timer = None
        self._tick_counter = 0
        self._tick_thread_slow = False
        self._tick_thread = threading.Thread(name="Tick thread",
                                            target=self._handle_tick_queue,
                                            args=())
        self._tick_thread.daemon = True
        self._tick_queue = queue.PriorityQueue(100)


    @property
    def _connobjs(self):
        return vmmConnectionManager.get_instance().conns


    def _cleanup(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)


    #################
    # init handling #
    #################

    def _default_startup(self, skip_autostart, cliuri):
        """
        Actual startup routines if we are running a new instance of the app
        """
        vmmSystray.get_instance()
        vmmInspection.get_instance()

        self.add_gsettings_handle(
            self.config.on_stats_update_interval_changed(
                self._timer_changed_cb))

        self._schedule_timer()
        self._tick_thread.start()
        self._tick()

        uris = list(self._connobjs.keys())
        if not uris:
            logging.debug("No stored URIs found.")
        else:
            logging.debug("Loading stored URIs:\n%s",
                "  \n".join(sorted(uris)))

        if not skip_autostart:
            self.idle_add(self._autostart_conns)

        if not self.config.get_conn_uris() and not cliuri:
            # Only add default if no connections are currently known
            self.timeout_add(1000, self._add_default_conn)

    def _add_default_conn(self):
        """
        If there's no cached connections, or any requested on the command
        line, try to determine a default URI and open it, possibly talking
        to packagekit and other bits
        """
        manager = self._get_manager()

        # Manager fail message
        msg = _("Could not detect a default hypervisor. Make\n"
                "sure the appropriate virtualization packages\n"
                "containing kvm, qemu, libvirt, etc. are\n"
                "installed, and that libvirtd is running.\n\n"
                "A hypervisor connection can be manually\n"
                "added via File->Add Connection")

        logging.debug("Determining default libvirt URI")

        packages_verified = False
        try:
            libvirt_packages = self.config.libvirt_packages
            packages = self.config.hv_packages + libvirt_packages

            packages_verified = packageutils.check_packagekit(
                    manager, manager.err, packages)
        except Exception:
            logging.exception("Error talking to PackageKit")

        tryuri = None
        if packages_verified:
            tryuri = "qemu:///system"
        elif not self.config.test_first_run:
            tryuri = vmmConnect.default_uri()

        if tryuri is None:
            manager.set_startup_error(msg)
            return

        # packagekit API via gnome-software doesn't even work nicely these
        # days. Not sure what the state of this warning is...
        #
        # warnmsg = _("The 'libvirtd' service will need to be started.\n\n"
        #            "After that, virt-manager will connect to libvirt on\n"
        #            "the next application start up.")
        # if not connected and not libvirtd_started:
        #    manager.err.ok(_("Libvirt service must be started"), warnmsg)

        def idle_connect():
            def _open_completed(c, ConnectError):
                if ConnectError:
                    self._handle_conn_error(c, ConnectError)

            packageutils.start_libvirtd()
            conn = vmmConnectionManager.get_instance().add_conn(tryuri)
            conn.set_autoconnect(True)
            conn.connect_once("open-completed", _open_completed)
            conn.open()
        self.idle_add(idle_connect)

    def _autostart_conns(self):
        """
        We serialize conn autostart, so polkit/ssh-askpass doesn't spam
        """
        if self._exiting:
            return

        connections_queue = queue.Queue()
        auto_conns = [conn.get_uri() for conn in self._connobjs.values() if
                      conn.get_autoconnect()]

        def add_next_to_queue():
            if not auto_conns:
                connections_queue.put(None)
            else:
                connections_queue.put(auto_conns.pop(0))

        def conn_open_completed(_conn, ConnectError):
            # Explicitly ignore connection errors, we've done that
            # for a while and it can be noisy
            logging.debug("Autostart connection error: %s",
                    ConnectError.details)
            add_next_to_queue()

        def handle_queue():
            while True:
                uri = connections_queue.get()
                if uri is None:
                    return
                if self._exiting:
                    return
                if uri not in self._connobjs:
                    add_next_to_queue()
                    continue

                conn = self._connobjs[uri]
                conn.connect_once("open-completed", conn_open_completed)
                self.idle_add(conn.open)

        add_next_to_queue()
        self._start_thread(handle_queue, "Conn autostart thread")


    ############################
    # Gtk Application handling #
    ############################

    def _on_gtk_application_activated(self, ignore):
        """
        Invoked after application.run()
        """
        if not self._application.get_windows():
            logging.debug("Initial gtkapplication activated")
            self._application.add_window(Gtk.Window())

    def _init_gtk_application(self):
        self._application = Gtk.Application(
            application_id="org.virt-manager.virt-manager", flags=0)
        self._application.register(None)
        self._application.connect("activate",
            self._on_gtk_application_activated)

        action = Gio.SimpleAction.new("cli_command",
            GLib.VariantType.new("(sss)"))
        action.connect("activate", self._handle_cli_command)
        self._application.add_action(action)

    def start(self, uri, show_window, domain, skip_autostart):
        """
        Public entrypoint from virt-manager cli. If app is already
        running, connect to it and exit, otherwise run our functional
        default startup.
        """
        # Dispatch dbus CLI command
        if uri and not show_window:
            show_window = self.CLI_SHOW_MANAGER
        data = GLib.Variant("(sss)",
            (uri or "", show_window or "", domain or ""))

        is_remote = self._application.get_is_remote()
        if not is_remote:
            self._default_startup(skip_autostart, uri)
        self._application.activate_action("cli_command", data)

        if is_remote:
            logging.debug("Connected to remote app instance.")
            return

        self._application.run(None)


    ###########################
    # timer and tick handling #
    ###########################

    def _timer_changed_cb(self, *args, **kwargs):
        ignore1 = args
        ignore2 = kwargs
        self._schedule_timer()

    def _schedule_timer(self):
        interval = self.config.get_stats_update_interval() * 1000

        if self._timer is not None:
            self.remove_gobject_timeout(self._timer)
            self._timer = None

        self._timer = self.timeout_add(interval, self._tick)

    def _add_obj_to_tick_queue(self, obj, isprio, **kwargs):
        if self._tick_queue.full():
            if not self._tick_thread_slow:
                logging.debug("Tick is slow, not running at requested rate.")
                self._tick_thread_slow = True
            return

        self._tick_counter += 1
        self._tick_queue.put((isprio and PRIO_HIGH or PRIO_LOW,
                              self._tick_counter,
                              obj, kwargs))

    def schedule_priority_tick(self, conn, kwargs):
        # Called directly from connection
        self._add_obj_to_tick_queue(conn, True, **kwargs)

    def _tick(self):
        for conn in self._connobjs.values():
            self._add_obj_to_tick_queue(conn, False,
                                        stats_update=True, pollvm=True)
        return 1

    def _handle_tick_queue(self):
        while True:
            ignore1, ignore2, conn, kwargs = self._tick_queue.get()
            try:
                conn.tick_from_engine(**kwargs)
            except Exception:
                # Don't attempt to show any UI error here, since it
                # can cause dialogs to appear from nowhere if say
                # libvirtd is shut down
                logging.debug("Error polling connection %s",
                        conn.get_uri(), exc_info=True)
            self._tick_queue.task_done()
        return 1


    #####################################
    # window counting and exit handling #
    #####################################

    def increment_window_counter(self):
        """
        Public function, called by toplevel windows
        """
        self._window_count += 1
        logging.debug("window counter incremented to %s", self._window_count)

    def decrement_window_counter(self):
        """
        Public function, called by toplevel windows
        """
        self._window_count -= 1
        logging.debug("window counter decremented to %s", self._window_count)

        self._exit_app_if_no_windows()

    def _systray_is_embedded(self):
        """
        We don't use window tracking here: systray isn't a window and even
        when 'show' has been requested it may not be embedded in a visible
        tray area, so we have to check it separately.
        """
        return vmmSystray.get_instance().is_embedded()

    def _can_exit(self):
        return (self._window_count <= 0 and not
                self._systray_is_embedded())

    def _exit_app_if_no_windows(self):
        if self._exiting:
            return
        if self._can_exit():
            logging.debug("No windows found, requesting app exit")
            self.exit_app()

    def exit_app(self):
        """
        Public call, manager/details/... use this to force exit the app
        """
        if self._exiting:
            return

        self._exiting = True

        def _do_exit():
            try:
                vmmConnectionManager.get_instance().cleanup()
                self.emit("app-closing")
                self.cleanup()

                if self.config.test_leak_debug:
                    objs = self.config.get_objects()
                    # Engine will always appear to leak
                    objs.remove(self.object_key)

                    for name in objs:
                        logging.debug("LEAK: %s", name)

                logging.debug("Exiting app normally.")
            finally:
                self._application.quit()

        # We stick this in an idle callback, so the exit_app() caller
        # reference is dropped, and leak check debug doesn't give a
        # false positive
        self.idle_add(_do_exit)


    ##########################################
    # Window launchers from virt-manager cli #
    ##########################################

    def _find_vm_by_cli_str(self, uri, clistr):
        """
        Lookup a VM by a string passed in on the CLI. Can be either
        ID, domain name, or UUID
        """
        if clistr.isdigit():
            clistr = int(clistr)

        for vm in self._connobjs[uri].list_vms():
            if clistr == vm.get_id():
                return vm
            elif clistr == vm.get_name():
                return vm
            elif clistr == vm.get_uuid():
                return vm

    def _cli_show_vm_helper(self, uri, clistr, page):
        src = self._get_manager()

        vm = self._find_vm_by_cli_str(uri, clistr)
        if not vm:
            src.err.show_err("%s does not have VM '%s'" %
                (uri, clistr), modal=True)
            return

        try:
            from .details import vmmDetails
            details = vmmDetails.get_instance(src, vm)

            if page == DETAILS_PERF:
                details.activate_performance_page()
            elif page == DETAILS_CONFIG:
                details.activate_config_page()
            elif page == DETAILS_CONSOLE:
                details.activate_console_page()
            elif page is None:
                details.activate_default_page()

            details.show()
        except Exception as e:
            src.err.show_err(_("Error launching details: %s") % str(e))

    def _get_manager(self):
        from .manager import vmmManager
        return vmmManager.get_instance(None)

    @_show_startup_error
    def _launch_cli_window(self, uri, show_window, clistr):
        logging.debug("Launching requested window '%s'", show_window)
        if show_window == self.CLI_SHOW_MANAGER:
            manager = self._get_manager()
            manager.set_initial_selection(uri)
            manager.show()
        elif show_window == self.CLI_SHOW_DOMAIN_CREATOR:
            from .create import vmmCreate
            # Launch the manager here since there's no way to get
            # back to it.
            vmmCreate.show_instance(self._get_manager(), uri)
        elif show_window == self.CLI_SHOW_DOMAIN_EDITOR:
            self._cli_show_vm_helper(uri, clistr, DETAILS_CONFIG)
        elif show_window == self.CLI_SHOW_DOMAIN_PERFORMANCE:
            self._cli_show_vm_helper(uri, clistr, DETAILS_PERF)
        elif show_window == self.CLI_SHOW_DOMAIN_CONSOLE:
            self._cli_show_vm_helper(uri, clistr, DETAILS_CONSOLE)
        elif show_window == self.CLI_SHOW_HOST_SUMMARY:
            from .host import vmmHost
            vmmHost.show_instance(None, self._connobjs[uri])
        else:
            raise RuntimeError("Unknown cli window command '%s'" %
                show_window)

    def _handle_conn_error(self, _conn, ConnectError):
        msg, details, title = ConnectError
        modal = self._can_exit()
        self.err.show_err(msg, details, title, modal=modal)
        self._exit_app_if_no_windows()

    @_show_startup_error
    def _handle_cli_command(self, actionobj, variant):
        ignore = actionobj
        uri = variant[0]
        show_window = variant[1] or self.CLI_SHOW_MANAGER
        domain = variant[2]

        logging.debug("processing cli command uri=%s show_window=%s domain=%s",
            uri, show_window, domain)
        if not uri:
            logging.debug("No cli action requested, launching default window")
            self._get_manager().show()
            return

        conn_is_new = uri not in self._connobjs
        conn = vmmConnectionManager.get_instance().add_conn(uri)
        if conn.is_active():
            self.idle_add(self._launch_cli_window,
                uri, show_window, domain)
            return

        def _open_completed(_c, ConnectError):
            if ConnectError:
                if conn_is_new:
                    logging.debug("Removing failed uri=%s", uri)
                    vmmConnectionManager.get_instance().remove_conn(uri)
                self._handle_conn_error(conn, ConnectError)
            else:
                self._launch_cli_window(uri, show_window, domain)

        conn.connect_once("open-completed", _open_completed)
        conn.open()
