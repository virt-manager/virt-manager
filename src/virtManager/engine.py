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

import gobject
import gtk

import logging
import traceback
import threading
import os

import libvirt
import virtinst
import dbus

from virtManager.about import vmmAbout
from virtManager.baseclass import vmmGObject
from virtManager.clone import vmmCloneVM
from virtManager.connect import vmmConnect
from virtManager.connection import vmmConnection
from virtManager.createmeter import vmmCreateMeter
from virtManager.preferences import vmmPreferences
from virtManager.manager import vmmManager
from virtManager.migrate import vmmMigrateDialog
from virtManager.details import vmmDetails
from virtManager.asyncjob import vmmAsyncJob
from virtManager.create import vmmCreate
from virtManager.host import vmmHost
from virtManager.error import vmmErrorDialog
from virtManager.systray import vmmSystray
import virtManager.uihelpers as uihelpers
import virtManager.util as util

# Enable this to get a report of leaked objects on app shutdown
debug_ref_leaks = True

def default_uri():
    tryuri = None
    if os.path.exists("/var/lib/xend") and os.path.exists("/proc/xen"):
        tryuri = "xen:///"
    elif (os.path.exists("/dev/kvm") or
          os.path.exists("/usr/bin/qemu") or
          os.path.exists("/usr/bin/qemu-kvm") or
          os.path.exists("/usr/bin/kvm") or
          os.path.exists("/usr/libexec/qemu-kvm")):
        tryuri = "qemu:///system"

    return tryuri

#############################
# PackageKit lookup helpers #
#############################

def check_packagekit(errbox, packages, libvirt_packages):
    """
    Returns None when we determine nothing useful.
    Returns (success, did we just install libvirt) otherwise.
    """
    if not packages:
        logging.debug("No PackageKit packages to search for.")
        return

    logging.debug("Asking PackageKit what's installed locally.")
    try:
        session = dbus.SystemBus()

        pk_control = dbus.Interface(
                        session.get_object("org.freedesktop.PackageKit",
                                           "/org/freedesktop/PackageKit"),
                        "org.freedesktop.PackageKit")
    except Exception:
        logging.exception("Couldn't connect to packagekit")
        return

    found = []
    progWin = vmmAsyncJob(_do_async_search,
                          [session, pk_control, packages],
                          _("Searching for available hypervisors..."),
                          _("Searching for available hypervisors..."),
                          None, run_main=False)
    error, ignore = progWin.run()
    if error:
        return

    found = progWin.get_data()

    not_found = filter(lambda x: x not in found, packages)
    logging.debug("Missing packages: %s" % not_found)

    do_install = not_found
    if not do_install:
        if not not_found:
            # Got everything we wanted, try to connect
            logging.debug("All packages found locally.")
            return (True, False)

        else:
            logging.debug("No packages are available for install.")
            return

    msg = (_("The following packages are not installed:\n%s\n\n"
             "These are required to create KVM guests locally.\n"
             "Would you like to install them now?") %
            reduce(lambda x, y: x + "\n" + y, do_install, ""))

    ret = errbox.yes_no(_("Packages required for KVM usage"), msg)

    if not ret:
        logging.debug("Package install declined.")
        return

    try:
        packagekit_install(do_install)
    except Exception, e:
        errbox.show_err(_("Error talking to PackageKit: %s") % str(e))
        return

    need_libvirt = False
    for p in libvirt_packages:
        if p in do_install:
            need_libvirt = True
            break

    return (True, need_libvirt)

def _do_async_search(asyncjob, session, pk_control, packages):
    found = []
    try:
        for name in packages:
            ret_found = packagekit_search(session, pk_control, name, packages)
            found += ret_found

    except Exception, e:
        logging.exception("Error searching for installed packages")
        asyncjob.set_error(str(e), "".join(traceback.format_exc()))

    asyncjob.set_data(found)

def packagekit_install(package_list):
    session = dbus.SessionBus()

    pk_control = dbus.Interface(
                    session.get_object("org.freedesktop.PackageKit",
                                       "/org/freedesktop/PackageKit"),
                        "org.freedesktop.PackageKit.Modify")

    # Set 2 hour timeout
    timeout = 60 * 60 * 2
    logging.debug("Installing packages: %s" % package_list)
    pk_control.InstallPackageNames(0, package_list, "hide-confirm-search",
                                   timeout=timeout)

def packagekit_search(session, pk_control, package_name, packages):
    tid = pk_control.GetTid()
    pk_trans = dbus.Interface(
                    session.get_object("org.freedesktop.PackageKit", tid),
                    "org.freedesktop.PackageKit.Transaction")

    found = []
    def package(info, package_id, summary):
        ignore = info
        ignore = summary

        found_name = str(package_id.split(";")[0])
        if found_name in packages:
            found.append(found_name)

    def error(code, details):
        raise RuntimeError("PackageKit search failure: %s %s" %
                            (code, details))

    def finished(ignore, runtime_ignore):
        gtk.main_quit()

    pk_trans.connect_to_signal('Finished', finished)
    pk_trans.connect_to_signal('ErrorCode', error)
    pk_trans.connect_to_signal('Package', package)
    try:
        pk_trans.SearchNames("installed", [package_name])
    except dbus.exceptions.DBusException, e:
        if e.get_dbus_name() != "org.freedesktop.DBus.Error.UnknownMethod":
            raise

        # Try older search API
        pk_trans.SearchName("installed", package_name)

    # Call main() so this function is synchronous
    gtk.main()

    return found



class vmmEngine(vmmGObject):
    __gsignals__ = {
        "connection-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                             [object]),
        "connection-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                               [str])
        }

    def __init__(self):
        vmmGObject.__init__(self)

        self.windowConnect = None
        self.windowPreferences = None
        self.windowAbout = None
        self.windowCreate = None
        self.windowManager = None
        self.windowMigrate = None

        self.connections = {}
        self.err = vmmErrorDialog()

        self.timer = None
        self.last_timeout = 0

        self.systray = None

        self._tick_thread = None
        self._tick_thread_slow = False
        if not self.config.support_threading:
            logging.debug("Libvirt doesn't support threading, skipping.")

        # Counter keeping track of how many manager and details windows
        # are open. When it is decremented to 0, close the app or
        # keep running in system tray if enabled
        self.windows = 0

        self.init_systray()

        self.add_gconf_handle(
            self.config.on_stats_update_interval_changed(self.reschedule_timer))
        self.add_gconf_handle(
            self.config.on_view_system_tray_changed(self.system_tray_changed))

        self.schedule_timer()
        self.load_stored_uris()
        self.tick()


    def init_systray(self):
        if self.systray:
            return

        self.systray = vmmSystray(self)
        self.systray.connect("action-toggle-manager", self._do_toggle_manager)
        self.systray.connect("action-suspend-domain", self._do_suspend_domain)
        self.systray.connect("action-resume-domain", self._do_resume_domain)
        self.systray.connect("action-run-domain", self._do_run_domain)
        self.systray.connect("action-shutdown-domain", self._do_shutdown_domain)
        self.systray.connect("action-reboot-domain", self._do_reboot_domain)
        self.systray.connect("action-destroy-domain", self._do_destroy_domain)
        self.systray.connect("action-show-console", self._do_show_console)
        self.systray.connect("action-show-details", self._do_show_details)
        self.systray.connect("action-exit-app", self.exit_app)

    def system_tray_changed(self, *ignore):
        systray_enabled = self.config.get_view_system_tray()
        if self.windows == 0 and not systray_enabled:
            # Show the manager so that the user can control the application
            self.show_manager()

    ########################
    # First run PackageKit #
    ########################

    def add_default_connection(self):
        # Only add default if no connections are currently known
        if self.config.get_connections():
            return

        # Manager fail message
        msg = _("Could not detect a default hypervisor. Make\n"
                "sure the appropriate virtualization packages\n"
                "are installed (kvm, qemu, libvirt, etc.), and\n"
                "that libvirtd is running.\n\n"
                "A hypervisor connection can be manually\n"
                "added via File->Add Connection")

        manager = self.get_manager()
        logging.debug("Determining default libvirt URI")

        ret = None
        did_install_libvirt = False
        try:
            libvirt_packages = self.config.libvirt_packages
            packages = self.config.hv_packages + libvirt_packages

            ret = check_packagekit(self.err, packages, libvirt_packages)
        except:
            logging.exception("Error talking to PackageKit")

        if ret:
            # We found the default packages via packagekit: use default URI
            ignore, did_install_libvirt = ret
            tryuri = "qemu:///system"

        else:
            tryuri = default_uri()

        if tryuri is None:
            manager.set_startup_error(msg)
            return

        if did_install_libvirt:
            warnmsg = _(
                "Libvirt was just installed, so the 'libvirtd' service will\n"
                "will need to be started. This can be done with one \n"
                "of the following:\n\n"
                "- From GNOME menus: System->Administration->Services\n"
                "- From the terminal: su -c 'service libvirtd restart'\n"
                "- Restart your computer\n\n"
                "virt-manager will connect to libvirt on the next application\n"
                "start up.")
            self.err.ok(_("Libvirt service must be started"), warnmsg)

        self.connect_to_uri(tryuri, autoconnect=True,
                            do_start=not did_install_libvirt)


    def load_stored_uris(self):
        uris = self.config.get_connections()
        if uris != None:
            logging.debug("About to connect to uris %s" % uris)
            for uri in uris:
                self.add_connection(uri)

    def autostart_connections(self):
        for uri in self.connections:
            conn = self.connections[uri]["connection"]
            if conn.get_autoconnect():
                self.connect_to_uri(uri)

    def connect_to_uri(self, uri, readOnly=None, autoconnect=False,
                       do_start=True):
        try:
            conn = self._check_connection(uri)
            if not conn:
                # Unknown connection, add it
                conn = self.add_connection(uri, readOnly, autoconnect)

            self.show_manager()
            if do_start:
                conn.open()
            return conn
        except Exception:
            logging.exception("Error connecting to %s" % uri)
            return None

    def _do_connect(self, src_ignore, uri):
        return self.connect_to_uri(uri)

    def _connect_cancelled(self, src):
        if len(self.connections.keys()) == 0:
            self.exit_app(src)


    def _do_vm_removed(self, connection, hvuri, vmuuid):
        ignore = connection
        if vmuuid not in self.connections[hvuri]["windowDetails"]:
            return

        self.connections[hvuri]["windowDetails"][vmuuid].cleanup()
        del(self.connections[hvuri]["windowDetails"][vmuuid])

    def _do_connection_changed(self, connection):
        if (connection.get_state() == connection.STATE_ACTIVE or
            connection.get_state() == connection.STATE_CONNECTING):
            return

        hvuri = connection.get_uri()

        for vmuuid in self.connections[hvuri]["windowDetails"].keys():
            self.connections[hvuri]["windowDetails"][vmuuid].cleanup()
            del(self.connections[hvuri]["windowDetails"][vmuuid])

        if (self.windowCreate and
            self.windowCreate.conn and
            self.windowCreate.conn.get_uri() == hvuri):
            self.windowCreate.close()

    def reschedule_timer(self, ignore1, ignore2, ignore3, ignore4):
        self.schedule_timer()

    def schedule_timer(self):
        interval = self.config.get_stats_update_interval() * 1000

        if self.timer != None:
            gobject.source_remove(self.timer)
            self.timer = None

        # No need to use 'safe_timeout_add', the tick should be
        # manually made thread safe
        self.timer = gobject.timeout_add(interval, self.tick)

    def tick(self):
        if not self.config.support_threading:
            return self._tick()

        if self._tick_thread and self._tick_thread.isAlive():
            if not self._tick_thread_slow:
                logging.debug("Tick is slow, not running at requested rate.")
                self._tick_thread_slow = True
            return 1

        self._tick_thread = threading.Thread(name="Tick thread",
                                            target=self._tick, args=())
        self._tick_thread.daemon = True
        self._tick_thread.start()
        return 1

    def _tick(self):
        for uri in self.connections.keys():
            conn = self.connections[uri]["connection"]
            try:
                conn.tick()
            except KeyboardInterrupt:
                raise
            except libvirt.libvirtError, e:
                if (e.get_error_domain() == libvirt.VIR_FROM_REMOTE and
                    e.get_error_code() == libvirt.VIR_ERR_SYSTEM_ERROR):
                    logging.exception("Could not refresh connection %s." % uri)
                    logging.debug("Closing connection since libvirtd "
                                  "appears to have stopped.")
                    self.safe_idle_add(conn.close)
                else:
                    raise
        return 1

    def change_timer_interval(self, ignore1, ignore2, ignore3, ignore4):
        gobject.source_remove(self.timer)
        self.schedule_timer()

    def increment_window_counter(self, src):
        ignore = src
        self.windows += 1
        logging.debug("window counter incremented to %s" % self.windows)

    def decrement_window_counter(self, src):
        self.windows -= 1
        logging.debug("window counter decremented to %s" % self.windows)

        # Don't exit if system tray is enabled
        if (self.windows <= 0 and
            self.systray and
            not self.systray.is_visible()):
            self.exit_app(src)

    def cleanup(self):
        try:
            vmmGObject.cleanup(self)
            uihelpers.cleanup()
            self.err = None

            if self.timer != None:
                gobject.source_remove(self.timer)

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

            # Do this last, so any manually 'disconnected' signals
            # take precedence over cleanup signal removal
            for uri in self.connections:
                self.cleanup_connection(uri)
            self.connections = {}
        except:
            logging.exception("Error cleaning up engine")

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
                logging.debug("Leaked %s" % name)

        logging.debug("Exiting app normally.")
        gtk.main_quit()

    def add_connection(self, uri, readOnly=None, autoconnect=False):
        conn = self._check_connection(uri)
        if conn:
            return conn

        conn = vmmConnection(uri, readOnly=readOnly)
        self.connections[uri] = {
            "connection": conn,
            "windowHost": None,
            "windowDetails": {},
            "windowClone": None,
        }

        conn.connect("vm-removed", self._do_vm_removed)
        conn.connect("state-changed", self._do_connection_changed)
        conn.tick()
        self.emit("connection-added", conn)
        self.config.add_connection(conn.get_uri())

        if autoconnect:
            conn.set_autoconnect(True)

        return conn

    def cleanup_connection(self, uri):
        try:
            if self.connections[uri]["windowHost"]:
                self.connections[uri]["windowHost"].cleanup()
            if self.connections[uri]["windowClone"]:
                self.connections[uri]["windowClone"].cleanup()

            details = self.connections[uri]["windowDetails"]
            for win in details.values():
                win.cleanup()

            self.connections[uri]["connection"].cleanup()
        except:
            logging.exception("Error cleaning up conn in engine")


    def remove_connection(self, uri):
        self.cleanup_connection(uri)
        del(self.connections[uri])

        self.emit("connection-removed", uri)
        self.config.remove_connection(uri)

    def connect(self, name, callback, *args):
        handle_id = vmmGObject.connect(self, name, callback, *args)

        if name == "connection-added":
            for uri in self.connections.keys():
                self.emit("connection-added",
                          self.connections[uri]["connection"])

        return handle_id

    def _check_connection(self, uri):
        conn = self.connections.get(uri)
        if conn:
            return conn["connection"]
        return None

    def _lookup_connection(self, uri):
        conn = self._check_connection(uri)
        if not conn:
            raise RuntimeError(_("Unknown connection URI %s") % uri)
        return conn

    ####################
    # Dialog launchers #
    ####################

    def _do_show_about(self, src):
        try:
            if self.windowAbout == None:
                self.windowAbout = vmmAbout()
            self.windowAbout.show()
        except Exception, e:
            src.err.show_err(_("Error launching 'About' dialog: %s") % str(e))

    def _do_show_help(self, src, index):
        try:
            uri = "ghelp:%s" % self.config.get_appname()
            if index:
                uri += "#%s" % index

            logging.debug("Showing help for %s" % uri)
            gtk.show_uri(None, uri, gtk.get_current_event_time())
        except Exception, e:
            src.err.show_err(_("Unable to display documentation: %s") % e)

    def _get_preferences(self):
        if self.windowPreferences:
            return self.windowPreferences

        obj = vmmPreferences()
        obj.connect("action-show-help", self._do_show_help)
        self.windowPreferences = obj
        return self.windowPreferences

    def _do_show_preferences(self, src):
        try:
            self._get_preferences().show(src.topwin)
        except Exception, e:
            src.err.show_err(_("Error launching preferences: %s") % str(e))

    def _get_host_dialog(self, uri):
        if self.connections[uri]["windowHost"]:
            return self.connections[uri]["windowHost"]

        con = self._lookup_connection(uri)
        obj = vmmHost(con)

        obj.connect("action-show-help", self._do_show_help)
        obj.connect("action-exit-app", self.exit_app)
        obj.connect("action-view-manager", self._do_show_manager)
        obj.connect("action-restore-domain", self._do_restore_domain)
        obj.connect("host-opened", self.increment_window_counter)
        obj.connect("host-closed", self.decrement_window_counter)

        self.connections[uri]["windowHost"] = obj
        return self.connections[uri]["windowHost"]

    def _do_show_host(self, src, uri):
        try:
            self._get_host_dialog(uri).show()
        except Exception, e:
            src.err.show_err(_("Error launching host dialog: %s") % str(e))

    def _get_connect_dialog(self):
        if self.windowConnect:
            return self.windowConnect

        def connect_wrap(src_ignore, *args):
            return self.connect_to_uri(*args)

        obj = vmmConnect()
        obj.connect("completed", connect_wrap)
        obj.connect("cancelled", self._connect_cancelled)
        self.windowConnect = obj
        return self.windowConnect

    def _do_show_connect(self, src):
        try:
            self._get_connect_dialog().show(src.topwin)
        except Exception, e:
            src.err.show_err(_("Error launching connect dialog: %s") % str(e))

    def _get_details_dialog(self, uri, uuid):
        if uuid in self.connections[uri]["windowDetails"]:
            return self.connections[uri]["windowDetails"][uuid]

        con = self._lookup_connection(uri)

        obj = vmmDetails(con.get_vm(uuid))
        obj.connect("action-save-domain", self._do_save_domain)
        obj.connect("action-destroy-domain", self._do_destroy_domain)
        obj.connect("action-show-help", self._do_show_help)
        obj.connect("action-suspend-domain", self._do_suspend_domain)
        obj.connect("action-resume-domain", self._do_resume_domain)
        obj.connect("action-run-domain", self._do_run_domain)
        obj.connect("action-shutdown-domain", self._do_shutdown_domain)
        obj.connect("action-reboot-domain", self._do_reboot_domain)
        obj.connect("action-exit-app", self.exit_app)
        obj.connect("action-view-manager", self._do_show_manager)
        obj.connect("action-migrate-domain", self._do_show_migrate)
        obj.connect("action-clone-domain", self._do_show_clone)
        obj.connect("details-opened", self.increment_window_counter)
        obj.connect("details-closed", self.decrement_window_counter)

        self.connections[uri]["windowDetails"][uuid] = obj
        self.connections[uri]["windowDetails"][uuid].show()
        return self.connections[uri]["windowDetails"][uuid]

    def _do_show_details(self, src, uri, uuid):
        try:
            details = self._get_details_dialog(uri, uuid)
            details.show()
            return details
        except Exception, e:
            src.err.show_err(_("Error launching details: %s") % str(e))

    def _do_show_console(self, src, uri, uuid):
        win = self._do_show_details(src, uri, uuid)
        if not win:
            return
        win.activate_console_page()

    def get_manager(self):
        if self.windowManager:
            return self.windowManager

        obj = vmmManager(self)
        obj.connect("action-suspend-domain", self._do_suspend_domain)
        obj.connect("action-resume-domain", self._do_resume_domain)
        obj.connect("action-run-domain", self._do_run_domain)
        obj.connect("action-shutdown-domain", self._do_shutdown_domain)
        obj.connect("action-reboot-domain", self._do_reboot_domain)
        obj.connect("action-destroy-domain", self._do_destroy_domain)
        obj.connect("action-save-domain", self._do_save_domain)
        obj.connect("action-migrate-domain", self._do_show_migrate)
        obj.connect("action-clone-domain", self._do_show_clone)
        obj.connect("action-show-console", self._do_show_console)
        obj.connect("action-show-details", self._do_show_details)
        obj.connect("action-show-preferences", self._do_show_preferences)
        obj.connect("action-show-create", self._do_show_create)
        obj.connect("action-show-help", self._do_show_help)
        obj.connect("action-show-about", self._do_show_about)
        obj.connect("action-show-host", self._do_show_host)
        obj.connect("action-show-connect", self._do_show_connect)
        obj.connect("action-connect", self._do_connect)
        obj.connect("action-exit-app", self.exit_app)
        obj.connect("manager-opened", self.increment_window_counter)
        obj.connect("manager-closed", self.decrement_window_counter)

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
        obj.connect("action-show-console", self._do_show_console)
        obj.connect("action-show-help", self._do_show_help)
        self.windowCreate = obj
        return self.windowCreate

    def _do_show_create(self, src, uri):
        try:
            self._get_create_dialog().show(src.topwin, uri)
        except Exception, e:
            src.err.show_err(_("Error launching manager: %s") % str(e))

    def _do_show_migrate(self, src, uri, uuid):
        try:
            conn = self._lookup_connection(uri)
            vm = conn.get_vm(uuid)

            if not self.windowMigrate:
                self.windowMigrate = vmmMigrateDialog(vm, self)

            self.windowMigrate.set_state(vm)
            self.windowMigrate.show(src.topwin)
        except Exception, e:
            src.err.show_err(_("Error launching migrate dialog: %s") % str(e))

    def _do_show_clone(self, src, uri, uuid):
        con = self._lookup_connection(uri)
        orig_vm = con.get_vm(uuid)
        clone_window = self.connections[uri]["windowClone"]

        try:
            if clone_window == None:
                clone_window = vmmCloneVM(orig_vm)
                clone_window.connect("action-show-help", self._do_show_help)
                self.connections[uri]["windowClone"] = clone_window
            else:
                clone_window.set_orig_vm(orig_vm)

            clone_window.show(src.topwin)
        except Exception, e:
            src.err.show_err(_("Error setting clone parameters: %s") % str(e))

    ##########################################
    # Window launchers from virt-manager cli #
    ##########################################

    def show_manager(self):
        self._do_show_manager(None)

    def show_connect(self):
        self._do_show_connect(self.get_manager())

    def show_host_summary(self, uri):
        self._do_show_host(self.get_manager(), uri)

    def show_domain_creator(self, uri):
        self._do_show_create(self.get_manager(), uri)

    def show_domain_console(self, uri, uuid):
        win = self._do_show_details(self.get_manager(), uri, uuid)
        if not win:
            return
        win.activate_console_page()

    def show_domain_editor(self, uri, uuid):
        win = self._do_show_details(self.get_manager(), uri, uuid)
        if not win:
            return
        win.activate_config_page()

    def show_domain_performance(self, uri, uuid):
        win = self._do_show_details(self.get_manager(), uri, uuid)
        if not win:
            return
        win.activate_performance_page()

    #######################################
    # Domain actions run/destroy/save ... #
    #######################################

    def _do_save_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)
        managed = bool(vm.managedsave_supported)

        if not managed and conn.is_remote():
            src.err.val_err(_("Saving virtual machines over remote "
                              "connections is not supported with this "
                              "libvirt version or hypervisor."))
            return

        if util.chkbox_helper(src, self.config.get_confirm_poweroff,
            self.config.set_confirm_poweroff,
            text1=_("Are you sure you want to save '%s'?" % vm.get_name())):
            return

        path = None
        if not managed:
            path = util.browse_local(src.topwin,
                                     _("Save Virtual Machine"),
                                     conn,
                                     dialog_type=gtk.FILE_CHOOSER_ACTION_SAVE,
                                     browse_reason=self.config.CONFIG_DIR_SAVE)
            if not path:
                return

        _cancel_back = None
        _cancel_args = []
        if vm.getjobinfo_supported:
            _cancel_back = self._save_cancel
            _cancel_args = [vm]

        progWin = vmmAsyncJob(self._save_callback,
                    [vm, path],
                    _("Saving Virtual Machine"),
                    _("Saving virtual machine memory to disk "),
                    src.topwin,
                    cancel_back=_cancel_back,
                    cancel_args=_cancel_args)
        error, details = progWin.run()

        if error is not None:
            error = _("Error saving domain: %s") % error
            src.err.show_err(error,
                             details=details)

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

    def _save_callback(self, asyncjob, vm, file_to_save):
        conn = util.dup_conn(vm.connection)
        newvm = conn.get_vm(vm.get_uuid())
        meter = vmmCreateMeter(asyncjob)

        newvm.save(file_to_save, meter=meter)

    def _do_restore_domain(self, src, uri):
        conn = self._lookup_connection(uri)
        if conn.is_remote():
            src.err.val_err(_("Restoring virtual machines over remote "
                              "connections is not yet supported"))
            return

        path = util.browse_local(src.topwin,
                                 _("Restore Virtual Machine"),
                                 conn,
                                 browse_reason=self.config.CONFIG_DIR_RESTORE)

        if not path:
            return

        def cb():
            newconn = util.dup_conn(conn)
            newconn.restore(path)

        vmmAsyncJob.simple_async_noshow(cb, [], src,
                                        _("Error restoring domain"))

    def _do_destroy_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)

        if util.chkbox_helper(src, self.config.get_confirm_forcepoweroff,
            self.config.set_confirm_forcepoweroff,
            text1=_("Are you sure you want to force poweroff '%s'?" %
                    vm.get_name()),
            text2=_("This will immediately poweroff the VM without "
                    "shutting down the OS and may cause data loss.")):
            return

        logging.debug("Destroying vm '%s'." % vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.destroy, [], src,
                                        _("Error shutting down domain"))

    def _do_suspend_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)

        if util.chkbox_helper(src, self.config.get_confirm_pause,
            self.config.set_confirm_pause,
            text1=_("Are you sure you want to pause '%s'?" %
                    vm.get_name())):
            return

        logging.debug("Pausing vm '%s'." % vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.suspend, [], src,
                                        _("Error pausing domain"))

    def _do_resume_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)

        logging.debug("Unpausing vm '%s'." % vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.resume, [], src,
                                        _("Error unpausing domain"))

    def _do_run_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)

        logging.debug("Starting vm '%s'." % vm.get_name())

        if vm.hasSavedImage():
            # VM will be restored, which can take some time, so show a
            # progress dialog.
            errorintro  = _("Error restoring domain")
            title = _("Restoring Virtual Machine")
            text = _("Restoring virtual machine memory from disk")
            vmmAsyncJob.simple_async(vm.startup,
                                     [], title, text, src,
                                     errorintro)

        else:
            # Regular startup
            errorintro  = _("Error starting domain")
            vmmAsyncJob.simple_async_noshow(vm.startup, [], src, errorintro)

    def _do_shutdown_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)

        if util.chkbox_helper(src, self.config.get_confirm_poweroff,
            self.config.set_confirm_poweroff,
            text1=_("Are you sure you want to poweroff '%s'?" %
                    vm.get_name())):
            return

        logging.debug("Shutting down vm '%s'." % vm.get_name())
        vmmAsyncJob.simple_async_noshow(vm.shutdown, [], src,
                                        _("Error shutting down domain"))

    def _do_reboot_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)

        if util.chkbox_helper(src, self.config.get_confirm_poweroff,
            self.config.set_confirm_poweroff,
            text1=_("Are you sure you want to reboot '%s'?" %
                    vm.get_name())):
            return

        logging.debug("Rebooting vm '%s'." % vm.get_name())

        def reboot_cb():
            no_support = False
            reboot_err = None
            try:
                vm.reboot()
            except Exception, reboot_err:
                no_support = virtinst.support.is_error_nosupport(reboot_err)
                if not no_support:
                    src.err.show_err(_("Error rebooting domain: %s" %
                                     str(reboot_err)))

            if not no_support:
                return

            # Reboot isn't supported. Let's try to emulate it
            logging.debug("Hypervisor doesn't support reboot, let's fake it")
            try:
                vm.manual_reboot()
            except:
                logging.exception("Could not fake a reboot")

                # Raise the original error message
                src.err.show_err(_("Error rebooting domain: %s" %
                                 str(reboot_err)))

        vmmAsyncJob.simple_async_noshow(reboot_cb, [], src, "")

vmmGObject.type_register(vmmEngine)
