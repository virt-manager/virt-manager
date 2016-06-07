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
import Queue
import threading
import traceback

from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk

from . import packageutils
from .about import vmmAbout
from .baseclass import vmmGObject
from .clone import vmmCloneVM
from .connect import vmmConnect
from .connection import vmmConnection
from .preferences import vmmPreferences
from .manager import vmmManager
from .migrate import vmmMigrateDialog
from .details import vmmDetails
from .asyncjob import vmmAsyncJob
from .create import vmmCreate
from .host import vmmHost
from .error import vmmErrorDialog
from .systray import vmmSystray
from .delete import vmmDeleteDialog

# Enabling this will tell us, at app exit time, which vmmGObjects were not
# garbage collected. This is caused by circular references to other objects,
# like a signal that wasn't disconnected. It's not a big deal, but if we
# have objects that can be created and destroyed a lot over the course of
# the app lifecycle, every non-garbage collected class is a memory leak.
# So it's nice to poke at this every now and then and try to track down
# what we need to add to class _cleanup handling.
debug_ref_leaks = False

DETAILS_PERF = 1
DETAILS_CONFIG = 2
DETAILS_CONSOLE = 3

(PRIO_HIGH,
 PRIO_LOW) = range(1, 3)


class vmmEngine(vmmGObject):
    CLI_SHOW_DOMAIN_CREATOR = "creator"
    CLI_SHOW_DOMAIN_EDITOR = "editor"
    CLI_SHOW_DOMAIN_PERFORMANCE = "performance"
    CLI_SHOW_DOMAIN_CONSOLE = "console"
    CLI_SHOW_HOST_SUMMARY = "summary"

    __gsignals__ = {
        "conn-added": (GObject.SignalFlags.RUN_FIRST, None, [object]),
        "conn-removed": (GObject.SignalFlags.RUN_FIRST, None, [str]),
    }

    def __init__(self):
        vmmGObject.__init__(self)

        self.windowConnect = None
        self.windowPreferences = None
        self.windowAbout = None
        self.windowCreate = None
        self.windowManager = None
        self.windowMigrate = None

        self.conns = {}
        self.err = vmmErrorDialog()
        self.err.set_find_parent_cb(self._find_error_parent_cb)

        self.timer = None
        self.last_timeout = 0

        self.systray = None
        self.delete_dialog = None

        self._gtkapplication = None
        self._init_gtk_application()

        self._tick_counter = 0
        self._tick_thread_slow = False
        self._tick_thread = threading.Thread(name="Tick thread",
                                            target=self._handle_tick_queue,
                                            args=())
        self._tick_thread.daemon = True
        self._tick_queue = Queue.PriorityQueue(100)

        self.inspection = None
        self._create_inspection_thread()

        # Counter keeping track of how many manager and details windows
        # are open. When it is decremented to 0, close the app or
        # keep running in system tray if enabled
        self.windows = 0

        self.init_systray()

        self.add_gsettings_handle(
            self.config.on_stats_update_interval_changed(self.reschedule_timer))
        self.add_gsettings_handle(
            self.config.on_view_system_tray_changed(self.system_tray_changed))

        self.schedule_timer()
        self.load_stored_uris()

        self._tick_thread.start()
        self.tick()


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

    def _default_startup(self, skip_autostart):
        uris = self.conns.keys()
        if not uris:
            logging.debug("No stored URIs found.")
        else:
            logging.debug("Loading stored URIs:\n%s",
                "  \n".join(sorted(uris)))

        if not skip_autostart:
            self.idle_add(self.autostart_conns)

        if not self.config.get_conn_uris():
            # Only add default if no connections are currently known
            self.timeout_add(1000, self._add_default_conn)

    def start(self, uri, show_window, domain, skip_autostart):
        # Dispatch dbus CLI command
        data = GLib.Variant("(sss)",
            (uri or "", show_window or "", domain or ""))
        self._application.activate_action("cli_command", data)

        if self._application.get_is_remote():
            logging.debug("Connected to remote app instance.")
            return

        self._default_startup(skip_autostart)
        self._application.run(None)


    def init_systray(self):
        if self.systray:
            return

        self.systray = vmmSystray()
        self.systray.connect("action-toggle-manager", self._do_toggle_manager)
        self.systray.connect("action-suspend-domain", self._do_suspend_domain)
        self.systray.connect("action-resume-domain", self._do_resume_domain)
        self.systray.connect("action-run-domain", self._do_run_domain)
        self.systray.connect("action-shutdown-domain", self._do_shutdown_domain)
        self.systray.connect("action-reboot-domain", self._do_reboot_domain)
        self.systray.connect("action-destroy-domain", self._do_destroy_domain)
        self.systray.connect("action-reset-domain", self._do_reset_domain)
        self.systray.connect("action-save-domain", self._do_save_domain)
        self.systray.connect("action-show-domain", self._do_show_vm)
        self.systray.connect("action-migrate-domain", self._do_show_migrate)
        self.systray.connect("action-delete-domain", self._do_delete_domain)
        self.systray.connect("action-clone-domain", self._do_show_clone)
        self.systray.connect("action-exit-app", self.exit_app)

        self.connect("conn-added", self.systray.conn_added)
        self.connect("conn-removed", self.systray.conn_removed)


    def system_tray_changed(self, *ignore):
        systray_enabled = self.config.get_view_system_tray()
        if self.windows == 0 and not systray_enabled:
            # Show the manager so that the user can control the application
            self._show_manager()

    def _add_default_conn(self):
        manager = self.get_manager()

        # Manager fail message
        msg = _("Could not detect a default hypervisor. Make\n"
                "sure the appropriate virtualization packages\n"
                "are installed (kvm, qemu, libvirt, etc.), and\n"
                "that libvirtd is running.\n\n"
                "A hypervisor connection can be manually\n"
                "added via File->Add Connection")

        logging.debug("Determining default libvirt URI")

        ret = None
        try:
            libvirt_packages = self.config.libvirt_packages
            packages = self.config.hv_packages + libvirt_packages

            ret = packageutils.check_packagekit(manager, manager.err, packages)
        except:
            logging.exception("Error talking to PackageKit")

        if ret:
            tryuri = "qemu:///system"
        else:
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
            do_start = packageutils.start_libvirtd()
            connected = self.connect_to_uri(tryuri,
                autoconnect=True, do_start=do_start)
            if not connected and do_start:
                manager.err.ok(_("Libvirt service must be started"), warnmsg)

        self.idle_add(idle_connect)


    def load_stored_uris(self):
        uris = self.config.get_conn_uris() or []
        for uri in uris:
            conn = self.make_conn(uri)
            self.register_conn(conn, skip_config=True)

    def autostart_conns(self):
        """
        We serialize conn autostart, so polkit/ssh-askpass doesn't spam
        """
        queue = Queue.Queue()
        auto_conns = [uri for uri in self.conns
                      if self.conns[uri]["conn"].get_autoconnect()]

        def add_next_to_queue():
            if not auto_conns:
                queue.put(None)
            else:
                queue.put(auto_conns.pop(0))

        def state_change_cb(conn):
            if conn.is_active():
                add_next_to_queue()
                conn.disconnect_by_func(state_change_cb)

        def connect(uri):
            self.connect_to_uri(uri)

        def handle_queue():
            while True:
                uri = queue.get()
                if uri is None:
                    return
                if uri not in self.conns:
                    add_next_to_queue()
                    continue

                conn = self.conns[uri]["conn"]
                conn.connect("state-changed", state_change_cb)
                self.idle_add(connect, uri)

        add_next_to_queue()
        self._start_thread(handle_queue, "Conn autostart thread")


    def _do_vm_removed(self, conn, connkey):
        hvuri = conn.get_uri()
        if connkey not in self.conns[hvuri]["windowDetails"]:
            return

        self.conns[hvuri]["windowDetails"][connkey].cleanup()
        del(self.conns[hvuri]["windowDetails"][connkey])

    def _do_vm_renamed(self, conn, oldconnkey, newconnkey):
        hvuri = conn.get_uri()
        if oldconnkey not in self.conns[hvuri]["windowDetails"]:
            return

        self.conns[hvuri]["windowDetails"][newconnkey] = (
            self.conns[hvuri]["windowDetails"].pop(oldconnkey))

    def _do_conn_changed(self, conn):
        if conn.is_active() or conn.is_connecting():
            return

        hvuri = conn.get_uri()

        for connkey in self.conns[hvuri]["windowDetails"].keys():
            self.conns[hvuri]["windowDetails"][connkey].cleanup()
            del(self.conns[hvuri]["windowDetails"][connkey])

        if (self.windowCreate and
            self.windowCreate.conn and
            self.windowCreate.conn.get_uri() == hvuri):
            self.windowCreate.close()

    def reschedule_timer(self, *args, **kwargs):
        ignore1 = args
        ignore2 = kwargs
        self.schedule_timer()

    def schedule_timer(self):
        interval = self.config.get_stats_update_interval() * 1000

        if self.timer is not None:
            self.remove_gobject_timeout(self.timer)
            self.timer = None

        self.timer = self.timeout_add(interval, self.tick)

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

    def tick(self):
        for uri in self.conns.keys():
            conn = self.conns[uri]["conn"]
            self._add_obj_to_tick_queue(conn, False,
                                        stats_update=True, pollvm=True)
        return 1

    def _handle_tick_error(self, msg, details):
        if self.windows <= 0:
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
            except Exception, e:
                tb = "".join(traceback.format_exc())
                error_msg = (_("Error polling connection '%s': %s")
                    % (conn.get_uri(), e))
                self.idle_add(self._handle_tick_error, error_msg, tb)

            # Need to clear reference to make leak check happy
            conn = None
            self._tick_queue.task_done()
        return 1


    def increment_window_counter(self, src):
        ignore = src
        self.windows += 1
        logging.debug("window counter incremented to %s", self.windows)

    def decrement_window_counter(self, src):
        self.windows -= 1
        logging.debug("window counter decremented to %s", self.windows)

        self._exit_app_if_no_windows(src)

    def _can_exit(self):
        # Don't exit if system tray is enabled
        return (self.windows <= 0 and
                self.systray and
                not self.systray.is_visible())

    def _cleanup(self):
        self.err = None

        if self.inspection:
            self.inspection.cleanup()
            self.inspection = None

        if self.timer is not None:
            GLib.source_remove(self.timer)

        if self.systray:
            self.systray.cleanup()
            self.systray = None

        self.get_manager()
        if self.windowManager:
            self.windowManager.cleanup()
            self.windowManager = None

        if self.windowPreferences:
            self.windowPreferences.cleanup()
            self.windowPreferences = None

        if self.windowAbout:
            self.windowAbout.cleanup()
            self.windowAbout = None

        if self.windowConnect:
            self.windowConnect.cleanup()
            self.windowConnect = None

        if self.windowCreate:
            self.windowCreate.cleanup()
            self.windowCreate = None

        if self.windowMigrate:
            self.windowMigrate.cleanup()
            self.windowMigrate = None

        if self.delete_dialog:
            self.delete_dialog.cleanup()
            self.delete_dialog = None

        # Do this last, so any manually 'disconnected' signals
        # take precedence over cleanup signal removal
        for uri in self.conns:
            self.cleanup_conn(uri)
        self.conns = {}

    def _exit_app_if_no_windows(self, src=None):
        def cb():
            if self._can_exit():
                logging.debug("No windows found, requesting app exit")
                self.exit_app(src or self)
        self.idle_add(cb)

    def exit_app(self, src):
        if self.err is None:
            # Already in cleanup
            return

        self.cleanup()

        if debug_ref_leaks:
            objs = self.config.get_objects()

            # Engine will always appear to leak
            objs.remove(self.object_key)

            if src.object_key in objs:
                # UI that initiates the app exit will always appear to leak
                objs.remove(src.object_key)

            for name in objs:
                logging.debug("Leaked %s", name)

        logging.debug("Exiting app normally.")
        self._application.quit()

    def _create_inspection_thread(self):
        logging.debug("libguestfs inspection support: %s",
                      self.config.support_inspection)
        if not self.config.support_inspection:
            return

        from .inspection import vmmInspection
        self.inspection = vmmInspection()
        self.inspection.start()
        self.connect("conn-added", self.inspection.conn_added)
        self.connect("conn-removed", self.inspection.conn_removed)
        return

    def _find_error_parent_cb(self):
        """
        Search over the toplevel windows for any that are visible or have
        focus, and use that
        """
        windowlist = [self.windowManager]
        for conndict in self.conns.values():
            windowlist.extend(conndict["windowDetails"].values())
        windowlist.extend(
            [conndict["windowHost"] for conndict in self.conns.values()])

        use_win = None
        for window in windowlist:
            if not window:
                continue
            if window.topwin.has_focus():
                use_win = window
                break
            if not use_win and window.is_visible():
                use_win = window

        if use_win:
            return use_win.topwin

    def make_conn(self, uri, probe=False):
        conn = self._check_conn(uri)
        if conn:
            return conn

        conn = vmmConnection(uri)
        self.conns[uri] = {
            "conn": conn,
            "windowHost": None,
            "windowDetails": {},
            "windowClone": None,
            "probeConnection": probe
        }

        conn.connect("vm-removed", self._do_vm_removed)
        conn.connect("vm-renamed", self._do_vm_renamed)
        conn.connect("state-changed", self._do_conn_changed)
        conn.connect("connect-error", self._connect_error)
        conn.connect("priority-tick", self._schedule_priority_tick)

        return conn


    def register_conn(self, conn, skip_config=False):
        # if `skip_config' then the connection is only showed in the ui and
        # not added to the config.
        if not skip_config and conn.get_uri() not in \
                               (self.config.get_conn_uris() or []):
            self.config.add_conn(conn.get_uri())
        self.emit("conn-added", conn)


    def connect_to_uri(self, uri, autoconnect=None, do_start=True, probe=False):
        try:
            conn = self.make_conn(uri, probe=probe)
            self.register_conn(conn)

            if autoconnect is not None:
                conn.set_autoconnect(bool(autoconnect))

            if do_start:
                conn.open()
            else:
                try:
                    conn.open()
                except:
                    return None
            return conn
        except Exception:
            logging.exception("Error connecting to %s", uri)
            return None


    def cleanup_conn(self, uri):
        try:
            if self.conns[uri]["windowHost"]:
                self.conns[uri]["windowHost"].cleanup()
            if self.conns[uri]["windowClone"]:
                self.conns[uri]["windowClone"].cleanup()

            details = self.conns[uri]["windowDetails"]
            for win in details.values():
                win.cleanup()

            self.conns[uri]["conn"].cleanup()
        except:
            logging.exception("Error cleaning up conn in engine")


    def remove_conn(self, src, uri):
        ignore = src
        self.cleanup_conn(uri)
        del(self.conns[uri])

        self.emit("conn-removed", uri)
        self.config.remove_conn(uri)

    def connect(self, name, callback, *args):
        handle_id = vmmGObject.connect(self, name, callback, *args)

        if name == "conn-added":
            for uri in self.conns.keys():
                self.emit("conn-added",
                          self.conns[uri]["conn"])

        return handle_id

    def _check_conn(self, uri):
        conn = self.conns.get(uri)
        if conn:
            return conn["conn"]
        return None

    def _lookup_conn(self, uri):
        conn = self._check_conn(uri)
        if not conn:
            raise RuntimeError(_("Unknown connection URI %s") % uri)
        return conn

    def _connect_error(self, conn, errmsg, tb, warnconsole):
        errmsg = errmsg.strip(" \n")
        tb = tb.strip(" \n")
        hint = ""
        show_errmsg = True

        if conn.is_remote():
            logging.debug("connect_error: conn transport=%s",
                conn.get_uri_transport())
            if re.search(r"nc: .* -- 'U'", tb):
                hint += _("The remote host requires a version of netcat/nc\n"
                          "which supports the -U option.")
                show_errmsg = False
            elif (conn.get_uri_transport() == "ssh" and
                  re.search(r"ssh-askpass", tb)):

                if self.config.askpass_package:
                    ret = packageutils.check_packagekit(
                                            None,
                                            self.err,
                                            self.config.askpass_package)
                    if ret:
                        conn.open()
                        return

                hint += _("You need to install openssh-askpass or "
                          "similar\nto connect to this host.")
                show_errmsg = False
            else:
                hint += _("Verify that the 'libvirtd' daemon is running\n"
                          "on the remote host.")

        elif conn.is_xen():
            hint += _("Verify that:\n"
                      " - A Xen host kernel was booted\n"
                      " - The Xen service has been started")

        else:
            if warnconsole:
                hint += _("Could not detect a local session: if you are \n"
                          "running virt-manager over ssh -X or VNC, you \n"
                          "may not be able to connect to libvirt as a \n"
                          "regular user. Try running as root.")
                show_errmsg = False
            elif re.search(r"libvirt-sock", tb):
                hint += _("Verify that the 'libvirtd' daemon is running.")
                show_errmsg = False

        probe_connection = self.conns[conn.get_uri()]["probeConnection"]
        msg = _("Unable to connect to libvirt.")
        if show_errmsg:
            msg += "\n\n%s" % errmsg
        if hint:
            msg += "\n\n%s" % hint

        msg = msg.strip("\n")
        details = msg
        details += "\n\n"
        details += "Libvirt URI is: %s\n\n" % conn.get_uri()
        details += tb

        if probe_connection:
            msg += "\n\n"
            msg += _("Would you still like to remember this connection?")

        title = _("Virtual Machine Manager Connection Failure")
        if probe_connection:
            remember_connection = self.err.show_err(msg, details, title,
                    buttons=Gtk.ButtonsType.YES_NO,
                    dialog_type=Gtk.MessageType.QUESTION, modal=True)
            if remember_connection:
                self.conns[conn.get_uri()]["probeConnection"] = False
            else:
                self.idle_add(self._do_edit_connect, self.windowManager, conn)
        else:
            if self._can_exit():
                self.err.show_err(msg, details, title, modal=True)
                self._exit_app_if_no_windows(conn)
            else:
                self.err.show_err(msg, details, title)


    ####################
    # Dialog launchers #
    ####################

    def _do_show_about(self, src):
        try:
            if self.windowAbout is None:
                self.windowAbout = vmmAbout()
            self.windowAbout.show()
        except Exception, e:
            src.err.show_err(_("Error launching 'About' dialog: %s") % str(e))

    def _get_preferences(self):
        if self.windowPreferences:
            return self.windowPreferences

        obj = vmmPreferences()
        self.windowPreferences = obj
        return self.windowPreferences

    def _do_show_preferences(self, src):
        try:
            self._get_preferences().show(src.topwin)
        except Exception, e:
            src.err.show_err(_("Error launching preferences: %s") % str(e))

    def _get_host_dialog(self, uri):
        if self.conns[uri]["windowHost"]:
            return self.conns[uri]["windowHost"]

        conn = self._lookup_conn(uri)
        obj = vmmHost(conn)

        obj.connect("action-exit-app", self.exit_app)
        obj.connect("action-view-manager", self._do_show_manager)
        obj.connect("host-opened", self.increment_window_counter)
        obj.connect("host-closed", self.decrement_window_counter)

        self.conns[uri]["windowHost"] = obj
        return self.conns[uri]["windowHost"]

    def _do_show_host(self, src, uri):
        try:
            self._get_host_dialog(uri).show()
        except Exception, e:
            src.err.show_err(_("Error launching host dialog: %s") % str(e))


    def _get_connect_dialog(self):
        if self.windowConnect:
            return self.windowConnect

        def completed(src, uri, autoconnect):
            ignore = src
            return self.connect_to_uri(uri, autoconnect, probe=True)

        def cancelled(src):
            if len(self.conns.keys()) == 0:
                self.exit_app(src)

        obj = vmmConnect()
        obj.connect("completed", completed)
        obj.connect("cancelled", cancelled)
        self.windowConnect = obj
        return self.windowConnect


    def _do_show_connect(self, src, reset_state=True):
        try:
            self._get_connect_dialog().show(src.topwin, reset_state)
        except Exception, e:
            src.err.show_err(_("Error launching connect dialog: %s") % str(e))

    def _do_edit_connect(self, src, connection):
        try:
            self._do_show_connect(src, False)
        finally:
            self.remove_conn(None, connection.get_uri())


    def _get_details_dialog(self, uri, connkey):
        if connkey in self.conns[uri]["windowDetails"]:
            return self.conns[uri]["windowDetails"][connkey]

        conn = self._lookup_conn(uri)

        obj = vmmDetails(conn.get_vm(connkey))
        obj.connect("action-save-domain", self._do_save_domain)
        obj.connect("action-destroy-domain", self._do_destroy_domain)
        obj.connect("action-reset-domain", self._do_reset_domain)
        obj.connect("action-suspend-domain", self._do_suspend_domain)
        obj.connect("action-resume-domain", self._do_resume_domain)
        obj.connect("action-run-domain", self._do_run_domain)
        obj.connect("action-shutdown-domain", self._do_shutdown_domain)
        obj.connect("action-reboot-domain", self._do_reboot_domain)
        obj.connect("action-exit-app", self.exit_app)
        obj.connect("action-view-manager", self._do_show_manager)
        obj.connect("action-migrate-domain", self._do_show_migrate)
        obj.connect("action-delete-domain", self._do_delete_domain)
        obj.connect("action-clone-domain", self._do_show_clone)
        obj.connect("details-opened", self.increment_window_counter)
        obj.connect("details-closed", self.decrement_window_counter)

        self.conns[uri]["windowDetails"][connkey] = obj
        return self.conns[uri]["windowDetails"][connkey]

    def _show_vm_helper(self, src, uri, vm, page, forcepage):
        try:
            details = self._get_details_dialog(uri, vm.get_connkey())

            if forcepage or not details.is_visible():
                if page == DETAILS_PERF:
                    details.activate_performance_page()
                elif page == DETAILS_CONFIG:
                    details.activate_config_page()
                elif page == DETAILS_CONSOLE:
                    details.activate_console_page()
                elif page is None:
                    details.activate_default_page()

            details.show()
        except Exception, e:
            src.err.show_err(_("Error launching details: %s") % str(e))

    def _do_show_vm(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)
        self._show_vm_helper(src, uri, vm, None, False)

    def get_manager(self):
        if self.windowManager:
            return self.windowManager

        obj = vmmManager()
        obj.connect("action-suspend-domain", self._do_suspend_domain)
        obj.connect("action-resume-domain", self._do_resume_domain)
        obj.connect("action-run-domain", self._do_run_domain)
        obj.connect("action-shutdown-domain", self._do_shutdown_domain)
        obj.connect("action-reboot-domain", self._do_reboot_domain)
        obj.connect("action-destroy-domain", self._do_destroy_domain)
        obj.connect("action-reset-domain", self._do_reset_domain)
        obj.connect("action-save-domain", self._do_save_domain)
        obj.connect("action-migrate-domain", self._do_show_migrate)
        obj.connect("action-delete-domain", self._do_delete_domain)
        obj.connect("action-clone-domain", self._do_show_clone)
        obj.connect("action-show-domain", self._do_show_vm)
        obj.connect("action-show-preferences", self._do_show_preferences)
        obj.connect("action-show-create", self._do_show_create)
        obj.connect("action-show-about", self._do_show_about)
        obj.connect("action-show-host", self._do_show_host)
        obj.connect("action-show-connect", self._do_show_connect)
        obj.connect("action-exit-app", self.exit_app)
        obj.connect("manager-opened", self.increment_window_counter)
        obj.connect("manager-closed", self.decrement_window_counter)
        obj.connect("remove-conn", self.remove_conn)

        self.connect("conn-added", obj.add_conn)
        self.connect("conn-removed", obj.remove_conn)

        self.windowManager = obj
        return self.windowManager

    def _do_toggle_manager(self, ignore):
        manager = self.get_manager()
        if manager.is_visible():
            manager.close()
        else:
            manager.show()

    def _do_show_manager(self, src):
        try:
            manager = self.get_manager()
            manager.show()
        except Exception, e:
            if not src:
                raise
            src.err.show_err(_("Error launching manager: %s") % str(e))

    def _get_create_dialog(self):
        if self.windowCreate:
            return self.windowCreate

        obj = vmmCreate(self)
        obj.connect("action-show-domain", self._do_show_vm)
        obj.connect("create-opened", self.increment_window_counter)
        obj.connect("create-closed", self.decrement_window_counter)
        self.windowCreate = obj
        return self.windowCreate

    def _do_show_create(self, src, uri):
        try:
            self._get_create_dialog().show(src.topwin, uri)
        except Exception, e:
            src.err.show_err(_("Error launching manager: %s") % str(e))

    def _do_show_migrate(self, src, uri, connkey):
        try:
            conn = self._lookup_conn(uri)
            vm = conn.get_vm(connkey)

            if not self.windowMigrate:
                self.windowMigrate = vmmMigrateDialog(self)

            self.windowMigrate.show(src.topwin, vm)
        except Exception, e:
            src.err.show_err(_("Error launching migrate dialog: %s") % str(e))

    def _do_show_clone(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        orig_vm = conn.get_vm(connkey)
        clone_window = self.conns[uri]["windowClone"]

        try:
            if clone_window is None:
                clone_window = vmmCloneVM(orig_vm)
                self.conns[uri]["windowClone"] = clone_window
            else:
                clone_window.set_orig_vm(orig_vm)

            clone_window.show(src.topwin)
        except Exception, e:
            src.err.show_err(_("Error setting clone parameters: %s") % str(e))

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

        for vm in self.conns[uri]["conn"].list_vms():
            if clistr == vm.get_id():
                return vm
            elif clistr == vm.get_name():
                return vm
            elif clistr == vm.get_uuid():
                return vm

    def _cli_show_vm_helper(self, uri, clistr, page):
        src = self.get_manager()

        vm = self._find_vm_by_cli_str(uri, clistr)
        if not vm:
            src.err.show_err("%s does not have VM '%s'" %
                (uri, clistr), modal=True)
            return

        self._show_vm_helper(src, uri, vm, page, True)

    def _show_manager(self):
        self._do_show_manager(None)

    def _show_host_summary(self, uri):
        self._do_show_host(self.get_manager(), uri)

    def _show_domain_creator(self, uri):
        self._do_show_create(self.get_manager(), uri)

    def _show_domain_console(self, uri, clistr):
        self._cli_show_vm_helper(uri, clistr, DETAILS_CONSOLE)

    def _show_domain_editor(self, uri, clistr):
        self._cli_show_vm_helper(uri, clistr, DETAILS_CONFIG)

    def _show_domain_performance(self, uri, clistr):
        self._cli_show_vm_helper(uri, clistr, DETAILS_PERF)

    def _launch_cli_window(self, uri, show_window, clistr):
        try:
            logging.debug("Launching requested window '%s'", show_window)
            if show_window == self.CLI_SHOW_DOMAIN_CREATOR:
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
        except:
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
            self._show_manager()
            return

        conn = self.make_conn(uri)
        self.register_conn(conn, skip_config=True)

        if conn.is_disconnected():
            # Schedule connection open
            def connect():
                # We need to wrap this to ignore the return value, otherwise
                # the callback will be rescheduled
                self.connect_to_uri(uri)
            self.idle_add(connect)

        if show_window:
            if conn.is_active():
                self.idle_add(self._launch_cli_window,
                    uri, show_window, domain)
            else:
                conn.connect_opt_out("state-changed",
                    self._cli_conn_connected_cb, uri, show_window, domain)
        else:
            self.get_manager().set_initial_selection(uri)
            self._show_manager()

    def _handle_cli_command(self, actionobj, variant):
        try:
            return self._do_handle_cli_command(actionobj, variant)
        except:
            # In case of cli error, we may need to exit the app
            logging.debug("Error handling cli command", exc_info=True)
            self._exit_app_if_no_windows()


    #######################################
    # Domain actions run/destroy/save ... #
    #######################################

    def _do_save_domain(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)

        if not src.err.chkbox_helper(self.config.get_confirm_poweroff,
            self.config.set_confirm_poweroff,
            text1=_("Are you sure you want to save '%s'?") % vm.get_name()):
            return

        _cancel_cb = None
        if vm.getjobinfo_supported:
            _cancel_cb = (self._save_cancel, vm)

        def cb(asyncjob):
            vm.save(meter=asyncjob.get_meter())
        def finish_cb(error, details):
            if error is not None:
                error = _("Error saving domain: %s") % error
                src.err.show_err(error, details=details)

        progWin = vmmAsyncJob(cb, [],
                    finish_cb, [],
                    _("Saving Virtual Machine"),
                    _("Saving virtual machine memory to disk "),
                    src.topwin, cancel_cb=_cancel_cb)
        progWin.run()

    def _save_cancel(self, asyncjob, vm):
        logging.debug("Cancelling save job")
        if not vm:
            return

        try:
            vm.abort_job()
        except Exception, e:
            logging.exception("Error cancelling save job")
            asyncjob.show_warning(_("Error cancelling save job: %s") % str(e))
            return

        asyncjob.job_canceled = True
        return

    def _do_destroy_domain(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)

        if not src.err.chkbox_helper(
            self.config.get_confirm_forcepoweroff,
            self.config.set_confirm_forcepoweroff,
            text1=_("Are you sure you want to force poweroff '%s'?" %
                    vm.get_name()),
            text2=_("This will immediately poweroff the VM without "
                    "shutting down the OS and may cause data loss.")):
            return

        logging.debug("Destroying vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.destroy, [], src,
                                        _("Error shutting down domain"))

    def _do_suspend_domain(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)

        if not src.err.chkbox_helper(self.config.get_confirm_pause,
            self.config.set_confirm_pause,
            text1=_("Are you sure you want to pause '%s'?" %
                    vm.get_name())):
            return

        logging.debug("Pausing vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.suspend, [], src,
                                        _("Error pausing domain"))

    def _do_resume_domain(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)

        logging.debug("Unpausing vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.resume, [], src,
                                        _("Error unpausing domain"))

    def _do_run_domain(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)

        logging.debug("Starting vm '%s'", vm.get_name())

        if vm.has_managed_save():
            def errorcb(error, details):
                # This is run from the main thread
                res = src.err.show_err(
                    _("Error restoring domain") + ": " + error,
                    details=details,
                    text2=_(
                        "The domain could not be restored. Would you like\n"
                        "to remove the saved state and perform a regular\n"
                        "start up?"),
                    dialog_type=Gtk.MessageType.WARNING,
                    buttons=Gtk.ButtonsType.YES_NO,
                    modal=True)

                if not res:
                    return

                try:
                    vm.remove_saved_image()
                    self._do_run_domain(src, uri, connkey)
                except Exception, e:
                    src.err.show_err(_("Error removing domain state: %s")
                                     % str(e))

            # VM will be restored, which can take some time, so show progress
            title = _("Restoring Virtual Machine")
            text = _("Restoring virtual machine memory from disk")
            vmmAsyncJob.simple_async(vm.startup, [], src,
                                     title, text, "", errorcb=errorcb)

        else:
            # Regular startup
            errorintro  = _("Error starting domain")
            vmmAsyncJob.simple_async_noshow(vm.startup, [], src, errorintro)

    def _do_shutdown_domain(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)

        if not src.err.chkbox_helper(self.config.get_confirm_poweroff,
            self.config.set_confirm_poweroff,
            text1=_("Are you sure you want to poweroff '%s'?" %
                    vm.get_name())):
            return

        logging.debug("Shutting down vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.shutdown, [], src,
                                        _("Error shutting down domain"))

    def _do_reboot_domain(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)

        if not src.err.chkbox_helper(self.config.get_confirm_poweroff,
            self.config.set_confirm_poweroff,
            text1=_("Are you sure you want to reboot '%s'?" %
                    vm.get_name())):
            return

        logging.debug("Rebooting vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.reboot, [], src,
            _("Error rebooting domain"))

    def _do_reset_domain(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)

        if not src.err.chkbox_helper(
            self.config.get_confirm_forcepoweroff,
            self.config.set_confirm_forcepoweroff,
            text1=_("Are you sure you want to force reset '%s'?" %
                    vm.get_name()),
            text2=_("This will immediately reset the VM without "
                    "shutting down the OS and may cause data loss.")):
            return

        logging.debug("Resetting vm '%s'", vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.reset, [], src,
                                        _("Error resetting domain"))

    def _do_delete_domain(self, src, uri, connkey):
        conn = self._lookup_conn(uri)
        vm = conn.get_vm(connkey)

        try:
            if not self.delete_dialog:
                self.delete_dialog = vmmDeleteDialog()
            self.delete_dialog.show(vm, src.topwin)
        except Exception, e:
            src.err.show_err(_("Error launching delete dialog: %s") % str(e))
