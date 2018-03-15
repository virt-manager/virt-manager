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
import re
import queue
import threading
import traceback

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import Gtk

from . import packageutils
from .baseclass import vmmGObject
from .connmanager import vmmConnectionManager
from .connect import vmmConnect
from .error import vmmErrorDialog
from .inspection import vmmInspection

DETAILS_PERF = 1
DETAILS_CONFIG = 2
DETAILS_CONSOLE = 3

(PRIO_HIGH,
 PRIO_LOW) = range(1, 3)


class vmmEngine(vmmGObject):
    CLI_SHOW_MANAGER = "manager"
    CLI_SHOW_DOMAIN_CREATOR = "creator"
    CLI_SHOW_DOMAIN_EDITOR = "editor"
    CLI_SHOW_DOMAIN_PERFORMANCE = "performance"
    CLI_SHOW_DOMAIN_CONSOLE = "console"
    CLI_SHOW_HOST_SUMMARY = "summary"

    _instance = None

    @classmethod
    def get_instance(cls):
        if not cls._instance:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        vmmGObject.__init__(self)

        self.err = vmmErrorDialog()

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
        self.err = None

        if self._timer is not None:
            GLib.source_remove(self._timer)

        vmmConnectionManager.get_instance().cleanup()


    #################
    # init handling #
    #################

    def _default_startup(self, skip_autostart, cliuri):
        """
        Actual startup routines if we are running a new instance of the app
        """
        from .systray import vmmSystray
        vmmSystray.get_instance()
        vmmInspection.get_instance()

        self.add_gsettings_handle(
            self.config.on_stats_update_interval_changed(
                self._timer_changed_cb))

        self._schedule_timer()
        for _uri in self._connobjs:
            self._add_conn(_uri, False, force_init=True)

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

        warnmsg = _("The 'libvirtd' service will need to be started.\n\n"
                    "After that, virt-manager will connect to libvirt on\n"
                    "the next application start up.")

        # Do the initial connection in an idle callback, so the
        # packagekit async dialog has a chance to go away
        def idle_connect():
            libvirtd_started = packageutils.start_libvirtd()
            connected = False
            try:
                self._connect_to_uri(tryuri, autoconnect=True)
                connected = True
            except Exception:
                logging.exception("Error connecting to %s", tryuri)

            if not connected and not libvirtd_started:
                manager.err.ok(_("Libvirt service must be started"), warnmsg)

        self.idle_add(idle_connect)

    def _autostart_conns(self):
        """
        We serialize conn autostart, so polkit/ssh-askpass doesn't spam
        """
        connections_queue = queue.Queue()
        auto_conns = [conn.get_uri() for conn in self._connobjs.values() if
                      conn.get_autoconnect()]

        def add_next_to_queue():
            if not auto_conns:
                connections_queue.put(None)
            else:
                connections_queue.put(auto_conns.pop(0))

        def state_change_cb(conn):
            if conn.is_active():
                add_next_to_queue()
                conn.disconnect_by_func(state_change_cb)

        def handle_queue():
            while True:
                uri = connections_queue.get()
                if uri is None:
                    return
                if uri not in self._connobjs:
                    add_next_to_queue()
                    continue

                conn = self._connobjs[uri]
                conn.connect("state-changed", state_change_cb)
                self.idle_add(self._connect_to_uri, uri)

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
        self._application.activate_action("cli_command", data)

        if self._application.get_is_remote():
            logging.debug("Connected to remote app instance.")
            return

        self._default_startup(skip_autostart, uri)
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

    def _schedule_priority_tick(self, conn, kwargs):
        self._add_obj_to_tick_queue(conn, True, **kwargs)

    def _tick(self):
        for conn in self._connobjs.values():
            self._add_obj_to_tick_queue(conn, False,
                                        stats_update=True, pollvm=True)
        return 1

    def _handle_tick_error(self, msg, details):
        from .systray import vmmSystray
        if (self._window_count == 1 and
            vmmSystray.get_instance().is_visible()):
            # This means the systray icon is running. Don't raise an error
            # here to avoid spamming dialogs out of nowhere.
            logging.debug(msg + "\n\n" + details)
            return
        self.err.show_err(msg, details=details)

    def _handle_tick_queue(self):
        while True:
            ignore1, ignore2, conn, kwargs = self._tick_queue.get()
            try:
                conn.tick_from_engine(**kwargs)
            except Exception as e:
                tb = "".join(traceback.format_exc())
                error_msg = (_("Error polling connection '%s': %s")
                    % (conn.get_uri(), e))
                self.idle_add(self._handle_tick_error, error_msg, tb)

            # Need to clear reference to make leak check happy
            conn = None
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

    def _can_exit(self):
        return self._window_count <= 0

    def _exit_app_if_no_windows(self):
        if self._can_exit():
            logging.debug("No windows found, requesting app exit")
            self.exit_app()

    def exit_app(self):
        """
        Public call, manager/details/... use this to force exit the app
        """
        if self._exiting:
            return

        try:
            self._exiting = True
            src = self
            self.cleanup()

            if self.config.test_leak_debug:
                objs = self.config.get_objects()

                # Engine will always appear to leak
                objs.remove(self.object_key)

                if src and src.object_key in objs:
                    # UI that initiates the app exit will always appear to leak
                    objs.remove(src.object_key)

                for name in objs:
                    logging.debug("LEAK: %s", name)

            logging.debug("Exiting app normally.")
        finally:
            self._application.quit()

    def _add_conn(self, uri, probe, force_init=False):
        is_init = (uri not in self._connobjs)
        conn = vmmConnectionManager.get_instance().add_conn(uri)
        if is_init or force_init:
            conn.connect("connect-error", self._connect_error)
            conn.connect("priority-tick", self._schedule_priority_tick)
            setattr(conn, "_from_connect_wizard", probe)
        return conn

    def _connect_to_uri(self, uri, autoconnect=None, probe=False):
        conn = self._add_conn(uri, probe=probe)

        if autoconnect is not None:
            conn.set_autoconnect(bool(autoconnect))

        conn.open()

    def _connect_error(self, conn, errmsg, tb, warnconsole):
        errmsg = errmsg.strip(" \n")
        tb = tb.strip(" \n")
        hint = ""
        show_errmsg = True

        if conn.is_remote():
            logging.debug("connect_error: conn transport=%s",
                conn.get_uri_transport())
            if re.search(r"nc: .* -- 'U'", tb):
                hint += _("The remote host requires a version of netcat/nc "
                          "which supports the -U option.")
                show_errmsg = False
            elif (conn.get_uri_transport() == "ssh" and
                  re.search(r"ssh-askpass", tb)):

                askpass = (self.config.askpass_package and
                           self.config.askpass_package[0] or
                           "openssh-askpass")
                hint += _("You need to install %s or "
                          "similar to connect to this host.") % askpass
                show_errmsg = False
            else:
                hint += _("Verify that the 'libvirtd' daemon is running "
                          "on the remote host.")

        elif conn.is_xen():
            hint += _("Verify that:\n"
                      " - A Xen host kernel was booted\n"
                      " - The Xen service has been started")

        else:
            if warnconsole:
                hint += _("Could not detect a local session: if you are "
                          "running virt-manager over ssh -X or VNC, you "
                          "may not be able to connect to libvirt as a "
                          "regular user. Try running as root.")
                show_errmsg = False
            elif re.search(r"libvirt-sock", tb):
                hint += _("Verify that the 'libvirtd' daemon is running.")
                show_errmsg = False

        msg = _("Unable to connect to libvirt %s." % conn.get_uri())
        if show_errmsg:
            msg += "\n\n%s" % errmsg
        if hint:
            msg += "\n\n%s" % hint

        msg = msg.strip("\n")
        details = msg
        details += "\n\n"
        details += "Libvirt URI is: %s\n\n" % conn.get_uri()
        details += tb

        _from_connect_wizard = getattr(conn, "_from_connect_wizard", False)
        if _from_connect_wizard:
            msg += "\n\n"
            msg += _("Would you still like to remember this connection?")

        title = _("Virtual Machine Manager Connection Failure")
        if _from_connect_wizard:
            remember_connection = self.err.show_err(msg, details, title,
                    buttons=Gtk.ButtonsType.YES_NO,
                    dialog_type=Gtk.MessageType.QUESTION, modal=True)
            if remember_connection:
                setattr(conn, "_from_connect_wizard", False)
            else:
                self._edit_connect(conn.get_uri())
        else:
            if self._can_exit():
                self.err.show_err(msg, details, title, modal=True)
                self._exit_app_if_no_windows()
            else:
                self.err.show_err(msg, details, title)


    ##################################
    # callbacks and dialog launchers #
    ##################################

    def _connect_completed(self, _src, uri, autoconnect):
        self._connect_to_uri(uri, autoconnect, probe=True)

    def _connect_cancelled(self, _src):
        if not self._connobjs:
            self.exit_app()

    def _show_connect_dialog(self, src, reset_state):
        is_init = vmmConnect.is_initialized()
        obj = vmmConnect.get_instance(src)
        if not is_init:
            obj.connect("completed", self._connect_completed)
            obj.connect("cancelled", self._connect_cancelled)
        obj.show(src.topwin, reset_state)

    def do_show_connect(self, src, reset_state=True):
        try:
            self._show_connect_dialog(src, reset_state)
        except Exception as e:
            src.err.show_err(_("Error launching connect dialog: %s") % str(e))

    def _edit_connect(self, uri):
        vmmConnectionManager.get_instance().remove_conn(uri)
        self.do_show_connect(self._get_manager(), reset_state=False)


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
        return vmmManager.get_instance(self)

    def _show_manager_uri(self, uri):
        manager = self._get_manager()
        manager.set_initial_selection(uri)
        manager.show()

    def _show_host_summary(self, uri):
        from .host import vmmHost
        vmmHost.show_instance(self._get_manager(), self._connobjs[uri])

    def _show_domain_creator(self, uri):
        from .create import vmmCreate
        vmmCreate.show_instance(self._get_manager(), uri)

    def _show_domain_console(self, uri, clistr):
        self._cli_show_vm_helper(uri, clistr, DETAILS_CONSOLE)

    def _show_domain_editor(self, uri, clistr):
        self._cli_show_vm_helper(uri, clistr, DETAILS_CONFIG)

    def _show_domain_performance(self, uri, clistr):
        self._cli_show_vm_helper(uri, clistr, DETAILS_PERF)

    def _launch_cli_window(self, uri, show_window, clistr):
        try:
            logging.debug("Launching requested window '%s'", show_window)
            if show_window == self.CLI_SHOW_MANAGER:
                self._show_manager_uri(uri)
            elif show_window == self.CLI_SHOW_DOMAIN_CREATOR:
                self._show_domain_creator(uri)
            elif show_window == self.CLI_SHOW_DOMAIN_EDITOR:
                self._show_domain_editor(uri, clistr)
            elif show_window == self.CLI_SHOW_DOMAIN_PERFORMANCE:
                self._show_domain_performance(uri, clistr)
            elif show_window == self.CLI_SHOW_DOMAIN_CONSOLE:
                self._show_domain_console(uri, clistr)
            elif show_window == self.CLI_SHOW_HOST_SUMMARY:
                self._show_host_summary(uri)
            else:
                raise RuntimeError("Unknown cli window command '%s'" %
                    show_window)
        finally:
            # In case of cli error, we may need to exit the app
            self._exit_app_if_no_windows()

    def _cli_conn_connected_cb(self, conn, uri, show_window, domain):
        try:
            ignore = conn

            if conn.is_disconnected():
                raise RuntimeError("failed to connect to cli uri=%s" % uri)

            if conn.is_active():
                self._launch_cli_window(uri, show_window, domain)
                return True

            return False
        except Exception:
            # In case of cli error, we may need to exit the app
            logging.debug("Error in cli connection callback", exc_info=True)
            self._exit_app_if_no_windows()
            return True

    def _do_handle_cli_command(self, actionobj, variant):
        ignore = actionobj
        uri = variant[0]
        show_window = variant[1]
        domain = variant[2]

        logging.debug("processing cli command uri=%s show_window=%s domain=%s",
            uri, show_window, domain)
        if not uri:
            logging.debug("No cli action requested, launching default window")
            self._get_manager().show()
            return

        conn = self._add_conn(uri, False)

        if conn.is_disconnected():
            # Schedule connection open
            self.idle_add(self._connect_to_uri, uri)

        if show_window:
            if conn.is_active():
                self.idle_add(self._launch_cli_window,
                    uri, show_window, domain)
            else:
                conn.connect_opt_out("state-changed",
                    self._cli_conn_connected_cb, uri, show_window, domain)
        else:
            self._show_manager_uri(uri)

    def _handle_cli_command(self, actionobj, variant):
        try:
            return self._do_handle_cli_command(actionobj, variant)
        except Exception:
            # In case of cli error, we may need to exit the app
            logging.debug("Error handling cli command", exc_info=True)
            self._exit_app_if_no_windows()
