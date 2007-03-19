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
import gtk.glade
import os

class vmmConnect(gobject.GObject):
    __gsignals__ = {
        "completed": (gobject.SIGNAL_RUN_FIRST,
                      gobject.TYPE_NONE, (str,bool)),
        "cancelled": (gobject.SIGNAL_RUN_FIRST,
                      gobject.TYPE_NONE, ())
        }
    def __init__(self, config, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-open-connection.glade", "vmm-open-connection", domain="virt-manager")
        self.engine = engine
        self.window.get_widget("vmm-open-connection").hide()

        # Not securely implemented yet by XenD/QEMU yet so disable it
        self.window.get_widget("type-remote-host").set_sensitive(False)

        self.window.get_widget("connect").grab_default()

        self.window.signal_autoconnect({
            "on_type_local_host_toggled": self.update_widget_states,
            "on_type_remote_host_toggled": self.update_widget_states,
            "on_type_hypervisor_changed": self.update_widget_states,
            "on_cancel_clicked": self.cancel,
            "on_connect_clicked": self.open_connection,
            "on_vmm_open_connection_delete_event": self.cancel,
            })

        self.window.get_widget("type-hypervisor").set_active(0)

    def cancel(self,ignore1=None,ignore2=None):
        self.close()
        self.emit("cancelled")
        return 1

    def close(self):
        self.window.get_widget("vmm-open-connection").hide()

    def show(self):
        win = self.window.get_widget("vmm-open-connection")
        win.show_all()
        win.present()

    def update_widget_states(self, ignore=None):
        type = self.window.get_widget("type-hypervisor")
        local = self.window.get_widget("type-local-host")
        remote = self.window.get_widget("type-remote-host")

        if local.get_active():
            self.window.get_widget("remote-host-options").set_sensitive(False)
        else:
            self.window.get_widget("remote-host-options").set_sensitive(True)

        if local.get_active() and os.getuid() != 0 and type.get_active() == 0:
            self.window.get_widget("option-read-only").set_sensitive(False)
            self.window.get_widget("option-read-only").set_active(True)
        else:
            self.window.get_widget("option-read-only").set_active(False)
            self.window.get_widget("option-read-only").set_sensitive(True)


    def open_connection(self, src):
        type = self.window.get_widget("type-hypervisor")
        local = self.window.get_widget("type-local-host")
        remote = self.window.get_widget("type-remote-host")
        uri = None

        readOnly = self.window.get_widget("option-read-only").get_active()

        if local.get_active():
            if type.get_active() == 0:
                uri = "xen"
                if os.getuid() != 0:
                    readOnly = True
            else:
                if os.getuid() == 0:
                    # Disabled for now, since the systemwide instance
                    # has no init script just yet
                    #uri = "qemu///system"
                    uri = "qemu:///session"
                else:
                    uri = "qemu:///session"
        else:
            if type.get_active() == 0:
                # XXX fixme these URIs should switch to the secure libvirtd when its finally written
                uri = "http://" + self.window.get_widget("remote-host").get_text() + ":" + self.window.get_widget("remote-port").get_text()
            else:
                uri = "qemu://" + self.window.get_widget("remote-host").get_text() + ":" + self.window.get_widget("remote-port").get_text() + "/system"
        self.close()
        self.emit("completed", uri, readOnly)

gobject.type_register(vmmConnect)
