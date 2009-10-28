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
import libvirt
import logging
import gnome
import traceback
import threading

from virtManager.about import vmmAbout
from virtManager.netdevhelper import vmmNetDevHelper
from virtManager.clone import vmmCloneVM
from virtManager.connect import vmmConnect
from virtManager.connection import vmmConnection
from virtManager.createmeter import vmmCreateMeter
from virtManager.domain import vmmDomain
from virtManager.preferences import vmmPreferences
from virtManager.manager import vmmManager
from virtManager.details import vmmDetails
from virtManager.asyncjob import vmmAsyncJob
from virtManager.create import vmmCreate
from virtManager.host import vmmHost
from virtManager.error import vmmErrorDialog
from virtManager.systray import vmmSystray
import virtManager.util as util

class vmmEngine(gobject.GObject):
    __gsignals__ = {
        "connection-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                             [object]),
        "connection-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                               [object])
        }

    def __init__(self, config):
        self.__gobject_init__()

        self.config = config
        self.windowConnect = None
        self.windowPreferences = None
        self.windowAbout = None
        self.windowCreate = None
        self.windowManager = None
        self.connections = {}
        self.err = vmmErrorDialog(None,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))

        self.timer = None
        self.last_timeout = 0

        self.systray = None

        self._tick_thread = None
        self._tick_thread_slow = False
        self._libvirt_support_threading = (libvirt.getVersion() >= 6000)
        if not self._libvirt_support_threading:
            logging.debug("Libvirt doesn't support threading, skipping.")

        # Counter keeping track of how many manager and details windows
        # are open. When it is decremented to 0, close the app
        self.windows = 0

        self.netdevHelper = vmmNetDevHelper(self.config)
        self.init_systray()

        self.config.on_stats_update_interval_changed(self.reschedule_timer)

        self.schedule_timer()
        self.load_stored_uris()
        self.tick()

    def init_systray(self):
        if self.systray:
            return

        self.systray = vmmSystray(self.config, self)
        self.systray.connect("action-view-manager", self._do_show_manager)
        self.systray.connect("action-suspend-domain", self._do_suspend_domain)
        self.systray.connect("action-resume-domain", self._do_resume_domain)
        self.systray.connect("action-run-domain", self._do_run_domain)
        self.systray.connect("action-shutdown-domain", self._do_shutdown_domain)
        self.systray.connect("action-reboot-domain", self._do_reboot_domain)
        self.systray.connect("action-destroy-domain", self._do_destroy_domain)
        self.systray.connect("action-show-console", self._do_show_console)
        self.systray.connect("action-show-details", self._do_show_details)
        self.systray.connect("action-exit-app", self._do_exit_app)

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

    def connect_to_uri(self, uri, readOnly=None, autoconnect=False):
        return self._connect_to_uri(None, uri, readOnly, autoconnect)

    def _connect_to_uri(self, connect, uri, readOnly, autoconnect):
        self.windowConnect = None

        try:
            try:
                conn = self._lookup_connection(uri)
            except Exception, e:
                conn = self.add_connection(uri, readOnly, autoconnect)

            self.show_manager()
            conn.open()
            return conn
        except Exception, e:
            return None

    def _connect_cancelled(self, connect):
        self.windowConnect = None
        if len(self.connections.keys()) == 0:
            self.exit_app()


    def _do_vm_removed(self, connection, hvuri, vmuuid):
        if self.connections[hvuri]["windowDetails"].has_key(vmuuid):
            self.connections[hvuri]["windowDetails"][vmuuid].close()
            del self.connections[hvuri]["windowDetails"][vmuuid]

    def _do_connection_changed(self, connection):
        if connection.get_state() == connection.STATE_ACTIVE or \
           connection.get_state() == connection.STATE_CONNECTING:
            return

        hvuri = connection.get_uri()
        for vmuuid in self.connections[hvuri]["windowDetails"].keys():
            self.connections[hvuri]["windowDetails"][vmuuid].close()
            del self.connections[hvuri]["windowDetails"][vmuuid]
        if self.connections[hvuri]["windowHost"] is not None:
            self.connections[hvuri]["windowHost"].close()
            self.connections[hvuri]["windowHost"] = None
        if (self.windowCreate and self.windowCreate.conn and
            self.windowCreate.conn.get_uri() == hvuri):
            self.windowCreate.close()

    def reschedule_timer(self, ignore1,ignore2,ignore3,ignore4):
        self.schedule_timer()

    def schedule_timer(self):
        interval = self.get_config().get_stats_update_interval() * 1000

        if self.timer != None:
            gobject.source_remove(self.timer)
            self.timer = None

        self.timer = gobject.timeout_add(interval, self.tick)

    def tick(self):
        if not self._libvirt_support_threading:
            return self._tick()

        if self._tick_thread and self._tick_thread.isAlive():
            if not self._tick_thread_slow:
                logging.debug("Tick is slow, not running at requested rate.")
                self._tick_thread_slow = True
            return 1

        self._tick_thread = threading.Thread(name="Tick thread",
                                            target=self._tick, args=())
        self._tick_thread.daemon = False
        self._tick_thread.start()
        return 1

    def _tick(self):
        for uri in self.connections.keys():
            try:
                self.connections[uri]["connection"].tick()
            except KeyboardInterrupt:
                raise
            except libvirt.libvirtError, e:
                if e.get_error_code() == libvirt.VIR_ERR_SYSTEM_ERROR:
                    logging.exception("Could not refresh connection %s." % uri)
                    logging.debug("Closing connection since libvirtd "
                                  "appears to have stopped.")
                    self.connections[uri]["connection"].close()
                else:
                    raise
        return 1

    def change_timer_interval(self,ignore1,ignore2,ignore3,ignore4):
        gobject.source_remove(self.timer)
        self.schedule_timer()

    def get_config(self):
        return self.config

    def _do_show_about(self, src):
        self.show_about()
    def _do_show_preferences(self, src):
        self.show_preferences()
    def _do_show_host(self, src, uri):
        self.show_host(uri)
    def _do_show_connect(self, src):
        self.show_connect()
    def _do_connect(self, src, uri):
        self.connect_to_uri(uri)
    def _do_show_details(self, src, uri, uuid):
        self.show_details(uri, uuid)
    def _do_show_create(self, src, uri):
        self.show_create(uri)
    def _do_show_help(self, src, index):
        self.show_help(index)
    def _do_show_console(self, src, uri, uuid):
        self.show_console(uri, uuid)
    def _do_show_manager(self, src):
        self.show_manager()
    def _do_refresh_console(self, src, uri, uuid):
        self.refresh_console(uri, uuid)
    def _do_save_domain(self, src, uri, uuid):
        self.save_domain(src, uri, uuid)
    def _do_destroy_domain(self, src, uri, uuid):
        self.destroy_domain(src, uri, uuid)
    def _do_suspend_domain(self, src, uri, uuid):
        self.suspend_domain(src, uri, uuid)
    def _do_resume_domain(self, src, uri, uuid):
        self.resume_domain(src, uri, uuid)
    def _do_run_domain(self, src, uri, uuid):
        self.run_domain(src, uri, uuid)
    def _do_shutdown_domain(self, src, uri, uuid):
        self.shutdown_domain(src, uri, uuid)
    def _do_reboot_domain(self, src, uri, uuid):
        self.reboot_domain(src, uri, uuid)
    def _do_migrate_domain(self, src, uri, uuid, desturi):
        self.migrate_domain(uri, uuid, desturi)
    def _do_clone_domain(self, src, uri, uuid):
        self.clone_domain(uri, uuid)
    def _do_exit_app(self, src):
        self.exit_app()

    def show_about(self):
        if self.windowAbout == None:
            self.windowAbout = vmmAbout(self.get_config())
        self.windowAbout.show()

    def show_help(self, index):
        try:
            logging.debug("Showing help for %s" % index)
            gnome.help_display(self.config.get_appname(), index)
        except gobject.GError, e:
            logging.error(("Unable to display documentation:\n%s") % e)

    def show_preferences(self):
        if self.windowPreferences == None:
            self.windowPreferences = vmmPreferences(self.get_config())
            self.windowPreferences.connect("action-show-help", self._do_show_help)
        self.windowPreferences.show()

    def show_host(self, uri):
        con = self._lookup_connection(uri)

        if self.connections[uri]["windowHost"] == None:
            manager = vmmHost(self.get_config(), con)
            manager.connect("action-show-help", self._do_show_help)
            self.connections[uri]["windowHost"] = manager
        self.connections[uri]["windowHost"].show()

    def show_connect(self):
        if self.windowConnect == None:
            self.windowConnect = vmmConnect(self.get_config(), self)
            self.windowConnect.connect("completed", self._connect_to_uri)
            self.windowConnect.connect("cancelled", self._connect_cancelled)
        self.windowConnect.show()

    def show_console(self, uri, uuid):
        win = self.show_details(uri, uuid)
        win.activate_console_page()

    def refresh_console(self, uri, uuid):
        if not(self.connections[uri]["windowConsole"].has_key(uuid)):
            return

        console = self.connections[uri]["windowConsole"][uuid]
        if not(console.is_visible()):
            return

        console.show()

    def show_details_performance(self, uri, uuid):
        win = self.show_details(uri, uuid)
        win.activate_performance_page()

    def show_details_config(self, uri, uuid):
        win = self.show_details(uri, uuid)
        win.activate_config_page()

    def show_details(self, uri, uuid):
        con = self._lookup_connection(uri)

        if not(self.connections[uri]["windowDetails"].has_key(uuid)):
            try:
                details = vmmDetails(self.get_config(), con.get_vm(uuid), self)
                details.connect("action-save-domain", self._do_save_domain)
                details.connect("action-destroy-domain", self._do_destroy_domain)
                details.connect("action-show-help", self._do_show_help)
                details.connect("action-suspend-domain", self._do_suspend_domain)
                details.connect("action-resume-domain", self._do_resume_domain)
                details.connect("action-run-domain", self._do_run_domain)
                details.connect("action-shutdown-domain", self._do_shutdown_domain)
                details.connect("action-reboot-domain", self._do_reboot_domain)
                details.connect("action-exit-app", self._do_exit_app)
                details.connect("action-view-manager", self._do_show_manager)
                details.connect("action-migrate-domain", self._do_migrate_domain)
                details.connect("action-clone-domain", self._do_clone_domain)

            except Exception, e:
                self.err.show_err(_("Error bringing up domain details: %s") % str(e),
                                  "".join(traceback.format_exc()))
            self.connections[uri]["windowDetails"][uuid] = details
        self.connections[uri]["windowDetails"][uuid].show()
        return self.connections[uri]["windowDetails"][uuid]

    def get_manager(self):
        if self.windowManager == None:
            self.windowManager = vmmManager(self.get_config(), self)
            self.windowManager.connect("action-suspend-domain", self._do_suspend_domain)
            self.windowManager.connect("action-resume-domain", self._do_resume_domain)
            self.windowManager.connect("action-run-domain", self._do_run_domain)
            self.windowManager.connect("action-shutdown-domain", self._do_shutdown_domain)
            self.windowManager.connect("action-reboot-domain", self._do_reboot_domain)
            self.windowManager.connect("action-destroy-domain", self._do_destroy_domain)
            self.windowManager.connect("action-migrate-domain", self._do_migrate_domain)
            self.windowManager.connect("action-clone-domain", self._do_clone_domain)
            self.windowManager.connect("action-show-console", self._do_show_console)
            self.windowManager.connect("action-show-details", self._do_show_details)
            self.windowManager.connect("action-show-preferences", self._do_show_preferences)
            self.windowManager.connect("action-show-create", self._do_show_create)
            self.windowManager.connect("action-show-help", self._do_show_help)
            self.windowManager.connect("action-show-about", self._do_show_about)
            self.windowManager.connect("action-show-host", self._do_show_host)
            self.windowManager.connect("action-show-connect", self._do_show_connect)
            self.windowManager.connect("action-connect", self._do_connect)
            self.windowManager.connect("action-refresh-console", self._do_refresh_console)
            self.windowManager.connect("action-exit-app", self._do_exit_app)
        return self.windowManager

    def show_manager(self):
        self.get_manager().show()

    def increment_window_counter(self):
        self.windows += 1
        logging.debug("window counter incremented to %s" % self.windows)

    def decrement_window_counter(self):
        self.windows -= 1
        logging.debug("window counter decremented to %s" % self.windows)
        if self.windows <= 0:
            self.exit_app()

    def exit_app(self):
        conns = self.connections.values()
        for conn in conns:
            conn["connection"].close()
        logging.debug("Exiting app normally.")
        gtk.main_quit()

    def wait_for_open(self, uri):
        # Used to ensure connection fully starts before running
        # ONLY CALL FROM WITHIN A THREAD
        conn = self.connect_to_uri(uri)
        conn.connectThreadEvent.wait()
        if conn.state != conn.STATE_ACTIVE:
            return False
        return True

    def show_create(self, uri):
        if self.windowCreate == None:
            create = vmmCreate(self.get_config(), self)
            create.connect("action-show-console", self._do_show_console)
            create.connect("action-show-help", self._do_show_help)
            self.windowCreate = create
        self.windowCreate.show(uri)

    def add_connection(self, uri, readOnly=None, autoconnect=False):
        conn = vmmConnection(self.get_config(), uri, readOnly,
                             self.netdevHelper)
        self.connections[uri] = {
            "connection": conn,
            "windowHost": None,
            "windowDetails": {},
            "windowConsole": {},
            "windowClone": None,
            }
        self.connections[uri]["connection"].connect("vm-removed", self._do_vm_removed)
        self.connections[uri]["connection"].connect("state-changed", self._do_connection_changed)
        self.connections[uri]["connection"].tick()
        self.emit("connection-added", conn)
        self.config.add_connection(conn.get_uri())
        if autoconnect:
            conn.toggle_autoconnect()

        return conn

    def remove_connection(self, uri):
        conn = self.connections[uri]["connection"]
        conn.close()
        self.emit("connection-removed", conn)
        del self.connections[uri]
        self.config.remove_connection(conn.get_uri())

    def connect(self, name, callback):
        handle_id = gobject.GObject.connect(self, name, callback)

        if name == "connection-added":
            for uri in self.connections.keys():
                self.emit("connection-added", self.connections[uri]["connection"])

        return handle_id

    def _lookup_connection(self, uri):
        conn = self.connections.get(uri)
        if not conn:
            raise RuntimeError(_("Unknown connection URI %s") % uri)

        return conn["connection"]

    def save_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        if conn.is_remote():
            # FIXME: This should work with remote storage stuff
            self.err.val_err(_("Saving virtual machines over remote "
                               "connections is not yet supported."))
            return

        vm = conn.get_vm(uuid)
        status = vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF,
                       libvirt.VIR_DOMAIN_CRASHED,
                       libvirt.VIR_DOMAIN_PAUSED ]:
            logging.warning("Save requested, but machine is shutdown / "
                            "shutoff / paused")
            return

        path = util.browse_local(src.window.get_widget("vmm-details"),
                                 _("Save Virtual Machine"),
                                 self.config, conn,
                                 dialog_type=gtk.FILE_CHOOSER_ACTION_SAVE,
                                 browse_reason=self.config.CONFIG_DIR_SAVE)

        if not path:
            return

        progWin = vmmAsyncJob(self.config, self._save_callback, [vm, path],
                              _("Saving Virtual Machine"))
        progWin.run()
        error, details = progWin.get_error()

        if error is not None:
            self.err.show_err(_("Error saving domain: %s") % error, details)

    def _save_callback(self, vm, file_to_save, asyncjob):
        try:
            vm.save(file_to_save)
        except Exception, e:
            asyncjob.set_error(str(e), "".join(traceback.format_exc()))

    def destroy_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)
        status = vm.status()

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF ]:
            logging.warning("Destroy requested, but machine is "
                            "shutdown/shutoff")
            return

        resp = self.err.yes_no(text1=_("About to poweroff virtual "
                                         "machine %s" % vm.get_name()),
                               text2=_("This will immediately poweroff the VM "
                                       "without shutting down the OS and may "
                                       "cause data loss. Are you sure?"))
        if not resp:
            return

        logging.debug("Destroying vm '%s'." % vm.get_name())
        try:
            vm.destroy()
        except Exception, e:
            self.err.show_err(_("Error shutting down domain: %s" % str(e)),
                              "".join(traceback.format_exc()))

    def suspend_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)
        status = vm.status()

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF,
                       libvirt.VIR_DOMAIN_CRASHED ]:
            logging.warning("Pause requested, but machine is shutdown/shutoff")
            return

        elif status in [ libvirt.VIR_DOMAIN_PAUSED ]:
            logging.warning("Pause requested, but machine is already paused")
            return

        logging.debug("Pausing vm '%s'." % vm.get_name())
        try:
            vm.suspend()
        except Exception, e:
            self.err.show_err(_("Error pausing domain: %s" % str(e)),
                              "".join(traceback.format_exc()))

    def resume_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)
        status = vm.status()

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF,
                       libvirt.VIR_DOMAIN_CRASHED ]:
            logging.warning("Resume requested, but machine is "
                            "shutdown/shutoff")
            return

        elif status not in [ libvirt.VIR_DOMAIN_PAUSED ]:
            logging.warning("Unpause requested, but machine is not paused.")
            return

        logging.debug("Unpausing vm '%s'." % vm.get_name())
        try:
            vm.resume()
        except Exception, e:
            self.err.show_err(_("Error unpausing domain: %s" % str(e)),
                              "".join(traceback.format_exc()))

    def run_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)
        status = vm.status()

        if status != libvirt.VIR_DOMAIN_SHUTOFF:
            logging.warning("Run requested, but domain isn't shutoff.")
            return

        logging.debug("Starting vm '%s'." % vm.get_name())
        try:
            vm.startup()
        except Exception, e:
            self.err.show_err(_("Error starting domain: %s" % str(e)),
                              "".join(traceback.format_exc()))

    def shutdown_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)
        status = vm.status()

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF,
                       libvirt.VIR_DOMAIN_CRASHED ]:
            logging.warning("Shut down requested, but the virtual machine is "
                            "already shutting down / powered off")
            return

        logging.debug("Shutting down vm '%s'." % vm.get_name())
        try:
            vm.shutdown()
        except Exception, e:
            self.err.show_err(_("Error shutting down domain: %s" % str(e)),
                              "".join(traceback.format_exc()))

    def reboot_domain(self, src, uri, uuid):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)
        status = vm.status()

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF,
                       libvirt.VIR_DOMAIN_CRASHED ]:
            logging.warning("Reboot requested, but machine is already "
                            "shutting down / shutoff")
            return

        logging.debug("Rebooting vm '%s'." % vm.get_name())
        try:
            vm.reboot()
        except Exception, e:
            self.err.show_err(_("Error shutting down domain: %s" % str(e)),
                              "".join(traceback.format_exc()))

    def migrate_domain(self, uri, uuid, desturi):
        conn = self._lookup_connection(uri)
        vm = conn.get_vm(uuid)
        destconn = self._lookup_connection(desturi)

        resp = self.err.yes_no(_("Are you sure you want to migrate %s from "
                                 "%s to %s?") %
                                (vm.get_name(), conn.get_hostname(),
                                 destconn.get_hostname()))
        if not resp:
            return

        progWin = vmmAsyncJob(self.config, self._async_migrate, [vm, destconn],
                              title=_("Migrating VM '%s'" % vm.get_name()),
                              text=(_("Migrating VM '%s' from %s to %s. "
                                      "This may take awhile.") %
                                      (vm.get_name(), conn.get_hostname(),
                                       destconn.get_hostname())))
        progWin.run()
        error, details = progWin.get_error()

        if error:
            self.err.show_err(error, details)

        self.windowManager.conn_refresh_resources(vm.get_connection())
        self.windowManager.conn_refresh_resources(destconn)

    def _async_migrate(self, origvm, origdconn, asyncjob):
        errinfo = None
        try:
            try:
                ignore = vmmCreateMeter(asyncjob)

                srcconn = util.dup_conn(self.config, origvm.get_connection(),
                                        return_conn_class=True)
                dstconn = util.dup_conn(self.config, origdconn,
                                        return_conn_class=True)

                vminst = srcconn.vmm.lookupByName(origvm.get_name())
                vm = vmmDomain(self.config, srcconn, vminst, vminst.UUID())

                logging.debug("Migrating vm=%s from %s to %s", vm.get_name(),
                              srcconn.get_uri(), dstconn.get_uri())
                vm.migrate(dstconn)
            except Exception, e:
                errinfo = (str(e), ("Unable to migrate guest:\n %s" %
                                    "".join(traceback.format_exc())))
        finally:
            if errinfo:
                asyncjob.set_error(errinfo[0], errinfo[1])


    def populate_migrate_menu(self, menu, migrate_func, vm):
        conns = self.get_available_migrate_hostnames(vm)

        # Clear menu
        for item in menu:
            menu.remove(item)

        for ignore, val_list in conns.items():
            can_migrate, label, tooltip, uri = val_list
            mitem = gtk.ImageMenuItem(label)
            mitem.set_sensitive(can_migrate)
            mitem.connect("activate", migrate_func, uri)
            if tooltip:
                util.tooltip_wrapper(mitem, tooltip)
            mitem.show()

            menu.add(mitem)

        if len(menu) == 0:
            mitem = gtk.ImageMenuItem(_("No connections available."))
            mitem.show()
            menu.add(mitem)

    def get_available_migrate_hostnames(self, vm):
        driver = vm.get_connection().get_driver()
        origuri = vm.get_connection().get_uri()
        available_migrate_hostnames = {}

        # Returns list of lists of the form
        #   [ Can we migrate to this connection?,
        #     String to use as list entry,
        #     Tooltip reason,
        #     Conn URI ]

        # 1. connected(ACTIVE, INACTIVE) host
        for key, value in self.connections.items():
            if not value.has_key("connection"):
                continue
            conn = value["connection"]

            can_migrate = False
            desc = "%s (%s)" % (conn.get_hostname(), conn.get_driver())
            reason = ""
            desturi = conn.get_uri()

            if conn.get_driver() != driver:
                reason = _("Connection hypervisors do not match.")
            elif conn.get_state() == vmmConnection.STATE_DISCONNECTED:
                reason = _("Connection is disconnected.")
            elif key == origuri:
                reason = _("Cannot migrate to same connection.")

                # Explicitly don't include this in the list
                continue
            elif conn.get_state() == vmmConnection.STATE_ACTIVE:
                # Assumably we can migrate to this connection
                can_migrate = True
                reason = desturi


            available_migrate_hostnames[key] = [can_migrate, desc, reason,
                                                desturi]

        return available_migrate_hostnames

    def clone_domain(self, uri, uuid):
        con = self._lookup_connection(uri)
        orig_vm = con.get_vm(uuid)
        clone_window = self.connections[uri]["windowClone"]

        try:
            if clone_window == None:
                clone_window = vmmCloneVM(self.get_config(), orig_vm)
                clone_window.connect("action-show-help", self._do_show_help)
                self.connections[uri]["windowClone"] = clone_window
            else:
                clone_window.set_orig_vm(orig_vm)

            clone_window.show()
        except Exception, e:
            self.err.show_err(_("Error setting clone parameters: %s") %
                              str(e), "".join(traceback.format_exc()))


gobject.type_register(vmmEngine)
