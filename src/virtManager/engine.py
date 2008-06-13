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
import sys
import libvirt
import logging
import gnome
import traceback

from virtManager.about import vmmAbout
from virtManager.connect import vmmConnect
from virtManager.connection import vmmConnection
from virtManager.preferences import vmmPreferences
from virtManager.manager import vmmManager
from virtManager.details import vmmDetails
from virtManager.asyncjob import vmmAsyncJob
from virtManager.create import vmmCreate
from virtManager.host import vmmHost
from virtManager.error import vmmErrorDialog

class vmmEngine(gobject.GObject):
    __gsignals__ = {
        "connection-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                             [object]),
        "connection-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                               [object])
        }

    def __init__(self, config):
        self.__gobject_init__()
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

        # Counter keeping track of how many manager and details windows
        # are open. When it is decremented to 0, close the app
        self.windows = 0

        self._save_callback_info = []

        self.config = config
        self.config.on_stats_update_interval_changed(self.reschedule_timer)

        self.schedule_timer()
        self.load_stored_uris()
        self.tick()

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
            conn = self.get_connection(uri, readOnly, autoconnect)
            self.show_manager()
            conn.open()
            return conn
        except:
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
        if connection.get_state() == connection.STATE_ACTIVE:
            return

        hvuri = connection.get_uri()
        for vmuuid in self.connections[hvuri]["windowDetails"].keys():
            self.connections[hvuri]["windowDetails"][vmuuid].close()
            del self.connections[hvuri]["windowDetails"][vmuuid]
        if self.connections[hvuri]["windowHost"] is not None:
            self.connections[hvuri]["windowHost"].close()
            self.connections[hvuri]["windowHost"] = None
        if self.connections[hvuri]["windowCreate"] is not None:
            self.connections[hvuri]["windowCreate"].close()
            self.connections[hvuri]["windowCreate"] = None

    def reschedule_timer(self, ignore1,ignore2,ignore3,ignore4):
        self.schedule_timer()

    def schedule_timer(self):
        interval = self.get_config().get_stats_update_interval() * 1000

        if self.timer != None:
            gobject.source_remove(self.timer)
            self.timer = None

        self.timer = gobject.timeout_add(interval, self.tick)

    def tick(self):
        gtk.gdk.threads_enter()
        try:
            return self._tick()
        finally:
            gtk.gdk.threads_leave()

    def _tick(self):
        for uri in self.connections.keys():
            try:
                self.connections[uri]["connection"].tick()
            except KeyboardInterrupt:
                raise KeyboardInterrupt
            except:
                logging.error(("Could not refresh connection %s\n" % (uri)) + str(sys.exc_info()[0]) + \
                              " " + str(sys.exc_info()[1]) + "\n" + \
                              traceback.format_exc(sys.exc_info()[2]))
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
    def _do_show_terminal(self, src, uri, uuid):
        self.show_serial_console(uri, uuid)
    def _do_show_manager(self, src):
        self.show_manager()
    def _do_refresh_console(self, src, uri, uuid):
        self.refresh_console(uri, uuid)
    def _do_refresh_terminal(self, src, uri, uuid):
        self.refresh_serial_console(uri, uuid)
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
        con = self.get_connection(uri)

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

    def show_manager(self):
        self.windowManager.show()

    def show_console(self, uri, uuid):
        win = self.show_details(uri, uuid)
        win.activate_console_page()

    def refresh_console(self, uri, uuid):
        con = self.get_connection(uri)

        if not(self.connections[uri]["windowConsole"].has_key(uuid)):
            return

        console = self.connections[uri]["windowConsole"][uuid]
        if not(console.is_visible()):
            return

        console.show()

    def refresh_serial_console(self, uri, uuid):
        con = self.get_connection(uri)

        if not(self.connections[uri]["windowSerialConsole"].has_key(uuid)):
            return

        console = self.connections[uri]["windowSerialConsole"][uuid]
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
        con = self.get_connection(uri)

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
            self.windowManager.connect("action-refresh-terminal", self._do_refresh_terminal)
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
        con = self.get_connection(uri)

        if self.connections[uri]["windowCreate"] == None:
            create = vmmCreate(self.get_config(), con)
            create.connect("action-show-console", self._do_show_console)
            create.connect("action-show-terminal", self._do_show_terminal)
            create.connect("action-show-help", self._do_show_help)
            self.connections[uri]["windowCreate"] = create
        self.connections[uri]["windowCreate"].show()

    def add_connection(self, uri, readOnly=None, autoconnect=False):
        conn = vmmConnection(self.get_config(), uri, readOnly)
        self.connections[uri] = {
            "connection": conn,
            "windowHost": None,
            "windowCreate": None,
            "windowDetails": {},
            "windowConsole": {},
            "windowSerialConsole": {},
            }
        self.connections[uri]["connection"].connect("vm-removed", self._do_vm_removed)
        self.connections[uri]["connection"].connect("state-changed", self._do_connection_changed)
        self.connections[uri]["connection"].tick()
        self.emit("connection-added", conn)
        self.config.add_connection(conn.get_uri())
        if autoconnect:
            conn.toggle_autoconnect()

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

    def get_connection(self, uri, readOnly=None, autoconnect=False):
        if not(self.connections.has_key(uri)):
            self.add_connection(uri, readOnly, autoconnect)

        return self.connections[uri]["connection"]

    def save_domain(self, src, uri, uuid):
        con = self.get_connection(uri, False)
        if con.is_remote():
            self.err.val_err(_("Saving virtual machines over remote connections is not yet supported."))
            return
        
        vm = con.get_vm(uuid)
        status = vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF,
                       libvirt.VIR_DOMAIN_CRASHED,
                       libvirt.VIR_DOMAIN_PAUSED ]:
            logging.warning("Save requested, but machine is shutdown / shutoff / paused")
        else:
            self.fcdialog = gtk.FileChooserDialog(_("Save Virtual Machine"),
                                                  src.window.get_widget("vmm-details"),
                                                  gtk.FILE_CHOOSER_ACTION_SAVE,
                                                  (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                                   gtk.STOCK_SAVE, gtk.RESPONSE_ACCEPT),
                                                  None)
            self.fcdialog.set_default_response(gtk.RESPONSE_ACCEPT)
            self.fcdialog.set_current_folder(self.config.get_default_save_dir(con))
            self.fcdialog.set_do_overwrite_confirmation(True)
            response = self.fcdialog.run()
            self.fcdialog.hide()
            if(response == gtk.RESPONSE_ACCEPT):
                file_to_save = self.fcdialog.get_filename()
                progWin = vmmAsyncJob(self.config, self._save_callback,
                                      [vm, file_to_save],
                                      _("Saving Virtual Machine"))
                progWin.run()
                self.fcdialog.destroy()

            if self._save_callback_info != []:
                self.err.show_err(_("Error saving domain: %s" % self._save_callback_info[0]), self._save_callback_info[1])
                self._save_callback_info = []

    def _save_callback(self, vm, file_to_save, ignore1=None):
        try:
            vm.save(file_to_save)
        except Exception, e:
            self._save_callback_info = [str(e), \
                                        "".join(traceback.format_exc())]

    def destroy_domain(self, src, uri, uuid):
        con = self.get_connection(uri, False)
        vm = con.get_vm(uuid)
        status = vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF ]:
            logging.warning("Destroy requested, but machine is shutdown / shutoff")
        else:
            resp = self.err.yes_no(text1=_("About to poweroff virtual machine %s" % vm.get_name()), text2=_("This will immediately poweroff the VM without shutting down the OS and may cause data loss. Are you sure?"))
            if resp:
                try:
                    vm.destroy()
                except Exception, e:
                   self.err.show_err(_("Error shutting down domain: %s" % str(e)), "".join(traceback.format_exc()))

    def suspend_domain(self, src, uri, uuid):
        con = self.get_connection(uri, False)
        vm = con.get_vm(uuid)
        status = vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, \
                       libvirt.VIR_DOMAIN_SHUTOFF, \
                       libvirt.VIR_DOMAIN_CRASHED ]:
            logging.warning("Pause requested, but machine is shutdown / shutoff")
        elif status in [ libvirt.VIR_DOMAIN_PAUSED ]:
            logging.warning("Pause requested, but machine is already paused")
        else:
            try:
                vm.suspend()
            except Exception, e:
                self.err.show_err(_("Error pausing domain: %s" % str(e)),
                                  "".join(traceback.format_exc()))
    
    def resume_domain(self, src, uri, uuid):
        con = self.get_connection(uri, False)
        vm = con.get_vm(uuid)
        status = vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, \
                       libvirt.VIR_DOMAIN_SHUTOFF, \
                       libvirt.VIR_DOMAIN_CRASHED ]:
            logging.warning("Resume requested, but machine is shutdown / shutoff")
        elif status in [ libvirt.VIR_DOMAIN_PAUSED ]:
            try:
                vm.resume()
            except Exception, e:
                self.err.show_err(_("Error unpausing domain: %s" % str(e)),
                                  "".join(traceback.format_exc()))
        else:
            logging.warning("Resume requested, but machine is already running")
    
    def run_domain(self, src, uri, uuid):
        con = self.get_connection(uri, False)
        vm = con.get_vm(uuid)
        status = vm.status()
        if status != libvirt.VIR_DOMAIN_SHUTOFF:
            logging.warning("Run requested, but domain isn't shutoff.")
        else:
            try:
                vm.startup()
            except Exception, e:
                self.err.show_err(_("Error starting domain: %s" % str(e)),
                                  "".join(traceback.format_exc()))
            
    def shutdown_domain(self, src, uri, uuid):
        con = self.get_connection(uri, False)
        vm = con.get_vm(uuid)
        status = vm.status()
        if not(status in [ libvirt.VIR_DOMAIN_SHUTDOWN, \
                           libvirt.VIR_DOMAIN_SHUTOFF, \
                           libvirt.VIR_DOMAIN_CRASHED ]):
            try:
                vm.shutdown()
            except Exception, e:
                self.err.show_err(_("Error shutting down domain: %s" % str(e)),
                                  "".join(traceback.format_exc()))
        else:
            logging.warning("Shutdown requested, but machine is already shutting down / shutoff")

    def reboot_domain(self, src, uri, uuid):
        con = self.get_connection(uri, False)
        vm = con.get_vm(uuid)
        status = vm.status()
        if not(status in [ libvirt.VIR_DOMAIN_SHUTDOWN, \
                           libvirt.VIR_DOMAIN_SHUTOFF, \
                           libvirt.VIR_DOMAIN_CRASHED ]):
            try:
                vm.reboot()
            except Exception, e:
                self.err.show_err(_("Error shutting down domain: %s" % str(e)),
                                  "".join(traceback.format_exc()))
        else:
            logging.warning("Reboot requested, but machine is already shutting down / shutoff")



gobject.type_register(vmmEngine)
