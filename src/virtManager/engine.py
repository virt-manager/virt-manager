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
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
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
from virtManager.console import vmmConsole
from virtManager.asyncjob import vmmAsyncJob
from virtManager.create import vmmCreate
from virtManager.serialcon import vmmSerialConsole

class vmmEngine:
    def __init__(self, config):
        self.windowConnect = None
        self.windowPreferences = None
        self.windowAbout = None
        self.windowCreate = None
        self.connections = {}

        self.timer = None
        self.last_timeout = 0

        self.config = config
        self.config.on_stats_update_interval_changed(self.reschedule_timer)

        self.schedule_timer()
        self.tick()


    def _do_connection_disconnected(self, connection, hvuri):
        del self.connections[hvuri]

        if len(self.connections.keys()) == 0 and self.windowConnect == None:
            gtk.main_quit()

    def _connect_to_uri(self, connect, uri, readOnly):
        self.windowConnect = None

        try:
            conn = self.get_connection(uri, readOnly)
            self.show_manager(uri)
        except:
            logging.error((("Unable to open connection to hypervisor URI '%s'") % str(uri)) + \
                          ": " + str(sys.exc_info()[0]) + " " + str(sys.exc_info()[1]) + "\n" + \
                          traceback.format_exc(sys.exc_info()[2]))

            if uri is None:
                uri = "xen"
            if uri == "xen":
                dg = gtk.MessageDialog(None, 0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                       _("Unable to open a connection to the Xen hypervisor/daemon.\n\n" + \
                                         "Verify that:\n" + \
                                         " - A Xen host kernel was booted\n" + \
                                         " - The Xen service has been started\n"))
            else:
                dg = gtk.MessageDialog(None, 0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                       _("Unable to open connection to hypervisor '%s'") % str(uri))
            dg.set_title(_("Virtual Machine Manager Connection Failure"))
            dg.run()
            dg.hide()
            dg.destroy()

        if len(self.connections.keys()) == 0:
            gtk.main_quit()

    def _connect_cancelled(self, connect):
        self.windowConnect = None
        if len(self.connections.keys()) == 0:
            gtk.main_quit()


    def _do_vm_removed(self, connection, hvuri, vmuuid):
        if self.connections[hvuri]["windowDetails"].has_key(vmuuid):
            self.connections[hvuri]["windowDetails"][vmuuid].close()
            del self.connections[hvuri]["windowDetails"][vmuuid]
        if self.connections[hvuri]["windowConsole"].has_key(vmuuid):
            self.connections[hvuri]["windowConsole"][vmuuid].close()
            del self.connections[hvuri]["windowConsole"][vmuuid]
        if self.connections[hvuri]["windowSerialConsole"].has_key(vmuuid):
            self.connections[hvuri]["windowSerialConsole"][vmuuid].close()
            del self.connections[hvuri]["windowSerialConsole"][vmuuid]

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
        if self.windowConnect == None and gtk.main_level() > 0 and self.count_visible_windows() == 0:
            gtk.main_quit()

        for uri in self.connections.keys():
            try:
                self.connections[uri]["connection"].tick()
            except KeyboardInterrupt:
                raise KeyboardInterrupt
            except:
                logging.error(("Could not refresh connection %s" % (uri)) + str(sys.exc_info()[0]) + \
                              " " + str(sys.exc_info()[1]) + "\n" + \
                              traceback.format_exc(sys.exc_info()[2]))
        return 1

    def count_visible_windows(self):
        ct = 0
        for conn in self.connections.values():
            for name in [ "windowDetails", "windowConsole", "windowSerialConsole" ]:
                for window in conn[name].values():
                    ct += window.is_visible()
            if conn["windowManager"]:
                ct += conn["windowManager"].is_visible()
        if self.windowCreate:
                ct += self.windowCreate.is_visible()
        return ct

    def change_timer_interval(self,ignore1,ignore2,ignore3,ignore4):
        gobject.source_remove(self.timer)
        self.schedule_timer()

    def get_config(self):
        return self.config

    def _do_show_about(self, src):
        self.show_about()
    def _do_show_preferences(self, src):
        self.show_preferences()
    def _do_show_connect(self, src):
        self.show_connect()
    def _do_show_manager(self, src, uri):
        self.show_manager(uri)
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
    def _do_save_domain(self, src, uri, uuid):
        self.save_domain(src, uri, uuid)
    def _do_destroy_domain(self, src, uri, uuid):
        self.destroy_domain(src, uri, uuid)

    def show_about(self):
        if self.windowAbout == None:
            self.windowAbout = vmmAbout(self.get_config())
        self.windowAbout.show()

    def show_help(self, index):
        try:
            gnome.help_display(self.config.get_appname(), index)
        except gobject.GError, e:
            logging.error(("Unable to display documentation:\n%s") % e)

    def show_preferences(self):
        if self.windowPreferences == None:
            self.windowPreferences = vmmPreferences(self.get_config())
            self.windowPreferences.connect("action-show-help", self._do_show_help)
        self.windowPreferences.show()

    def show_connect(self):
        if self.windowConnect == None:
            self.windowConnect = vmmConnect(self.get_config(), self)
            self.windowConnect.connect("completed", self._connect_to_uri)
            self.windowConnect.connect("cancelled", self._connect_cancelled)
        self.windowConnect.show()

    def show_console(self, uri, uuid):
        con = self.get_connection(uri)

        if not(self.connections[uri]["windowConsole"].has_key(uuid)):
            console = vmmConsole(self.get_config(),
                                 con.get_vm(uuid))
            console.connect("action-show-details", self._do_show_details)
            console.connect("action-show-terminal", self._do_show_terminal)
            console.connect("action-save-domain", self._do_save_domain)
            console.connect("action-destroy-domain", self._do_destroy_domain)
            console.connect("action-show-help", self._do_show_help)
            self.connections[uri]["windowConsole"][uuid] = console
        self.connections[uri]["windowConsole"][uuid].show()

    def show_serial_console(self, uri, uuid):
        con = self.get_connection(uri)

        if not(self.connections[uri]["windowSerialConsole"].has_key(uuid)):
            console = vmmSerialConsole(self.get_config(),
                                       con.get_vm(uuid))
            self.connections[uri]["windowSerialConsole"][uuid] = console
        self.connections[uri]["windowSerialConsole"][uuid].show()

    def show_details_performance(self, uri, uuid):
        win = self.show_details(uri, uuid)
        win.activate_performance_page()

    def show_details_config(self, uri, uuid):
        win = self.show_details(uri, uuid)
        win.activate_config_page()
        
    def show_details(self, uri, uuid):
        con = self.get_connection(uri)

        if not(self.connections[uri]["windowDetails"].has_key(uuid)):
            details = vmmDetails(self.get_config(),
                                 con.get_vm(uuid))
            details.connect("action-show-console", self._do_show_console)
            details.connect("action-show-terminal", self._do_show_terminal)
            details.connect("action-save-domain", self._do_save_domain)
            details.connect("action-destroy-domain", self._do_destroy_domain)
            details.connect("action-show-help", self._do_show_help)
            self.connections[uri]["windowDetails"][uuid] = details
        self.connections[uri]["windowDetails"][uuid].show()
        return self.connections[uri]["windowDetails"][uuid]

    def show_manager(self, uri):
        con = self.get_connection(uri)

        if self.connections[uri]["windowManager"] == None:
            manager = vmmManager(self.get_config(),
                                 con)
            manager.connect("action-show-console", self._do_show_console)
            manager.connect("action-show-terminal", self._do_show_terminal)
            manager.connect("action-show-details", self._do_show_details)
            manager.connect("action-show-preferences", self._do_show_preferences)
            manager.connect("action-show-create", self._do_show_create)
            manager.connect("action-show-help", self._do_show_help)
            manager.connect("action-show-about", self._do_show_about)
            manager.connect("action-show-connect", self._do_show_connect)
            self.connections[uri]["windowManager"] = manager
        self.connections[uri]["windowManager"].show()

    def show_create(self, uri):
        if self.windowCreate == None:
            self.windowCreate = vmmCreate(self.get_config(), self.get_connection(uri, False))
        self.windowCreate.connect("action-show-console", self._do_show_console)
        self.windowCreate.connect("action-show-terminal", self._do_show_terminal)
        self.windowCreate.connect("action-show-help", self._do_show_help)
        self.windowCreate.reset_state()
        self.windowCreate.show()

    def get_connection(self, uri, readOnly=True):
        if not(self.connections.has_key(uri)):
            self.connections[uri] = {
                "connection": vmmConnection(self.get_config(), uri, readOnly),
                "windowManager": None,
                "windowDetails": {},
                "windowConsole": {},
                "windowSerialConsole": {},
                }
            self.connections[uri]["connection"].connect("disconnected", self._do_connection_disconnected)
            self.connections[uri]["connection"].connect("vm-removed", self._do_vm_removed)
            self.connections[uri]["connection"].tick()

        return self.connections[uri]["connection"]

    def save_domain(self, src, uri, uuid):
        con = self.get_connection(uri, False)
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
            self.fcdialog.set_do_overwrite_confirmation(True)
            response = self.fcdialog.run()
            self.fcdialog.hide()
            if(response == gtk.RESPONSE_ACCEPT):
                file_to_save = self.fcdialog.get_filename()
                progWin = vmmAsyncJob(self.config, vm.save,
                                      [file_to_save],
                                      _("Saving Virtual Machine"))
                progWin.run()
                self.fcdialog.destroy()

    def destroy_domain(self, src, uri, uuid):
        con = self.get_connection(uri, False)
        vm = con.get_vm(uuid)
        status = vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN,
                       libvirt.VIR_DOMAIN_SHUTOFF ]:
            logging.warning("Destroy requested, but machine is shutdown / shutoff")
        else:
            message_box = gtk.MessageDialog(None, \
                                            gtk.DIALOG_MODAL, \
                                            gtk.MESSAGE_WARNING, \
                                            gtk.BUTTONS_OK_CANCEL, \
                                            _("About to destroy virtual machine %s" % vm.get_name()))
            message_box.format_secondary_text(_("This will immediately destroy the VM and may corrupt its disk image. Are you sure?"))
            response_id = message_box.run()
            message_box.destroy()
            if response_id == gtk.RESPONSE_OK:
                vm.destroy()
            else:
                return
