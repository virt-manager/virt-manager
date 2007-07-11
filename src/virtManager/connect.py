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
import virtinst
import logging

HV_XEN = 0
HV_QEMU = 1

CONN_LOCAL = 0
CONN_TLS = 1
CONN_SSH = 2

class vmmConnect(gobject.GObject):
    __gsignals__ = {
        "completed": (gobject.SIGNAL_RUN_FIRST,
                      gobject.TYPE_NONE, (str,object)),
        "cancelled": (gobject.SIGNAL_RUN_FIRST,
                      gobject.TYPE_NONE, ())
        }

    def __init__(self, config, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-open-connection.glade", "vmm-open-connection", domain="virt-manager")
        self.engine = engine
        self.window.get_widget("vmm-open-connection").hide()

        self.window.signal_autoconnect({
            "on_connection_changed": self.update_widget_states,
            "on_cancel_clicked": self.cancel,
            "on_connect_clicked": self.open_connection,
            "on_vmm_open_connection_delete_event": self.cancel,
            })

        default = virtinst.util.default_connection()
        if default is None:
            self.window.get_widget("hypervisor").set_active(-1)
        elif default[0:3] == "xen":
            self.window.get_widget("hypervisor").set_active(0)
        elif default[0:4] == "qemu":
            self.window.get_widget("hypervisor").set_active(1)

        self.window.get_widget("connection").set_active(0)
        self.window.get_widget("connect").grab_default()



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

    def update_widget_states(self, src):
        if src.get_active() > 0:
            self.window.get_widget("hostname").set_sensitive(True)
        else:
            self.window.get_widget("hostname").set_sensitive(False)

    def open_connection(self, src):
        hv = self.window.get_widget("hypervisor").get_active()
        conn = self.window.get_widget("connection").get_active()
        host = self.window.get_widget("hostname").get_text()
        uri = None

        readOnly = None
        if hv == -1:
            pass
        elif hv == HV_XEN:
            if conn == CONN_LOCAL:
                uri = "xen://"
                if os.getuid() != 0:
                    readOnly = True
            elif conn == CONN_TLS:
                uri = "xen+tls://" + host + "/"
            elif conn == CONN_SSH:
                uri = "xen+ssh://root@" + host + "/"
        else:
            if conn == CONN_LOCAL:
                if os.getuid() == 0:
                    uri = "qemu:///system"
                else:
                    uri = "qemu:///session"
            elif conn == CONN_TLS:
                uri = "qemu+tls://" + host + "/system"
            elif conn == CONN_SSH:
                uri = "qemu+ssh://root@" + host + "/system"

        logging.debug("Connection to open is %s" % uri)
        self.close()
        self.emit("completed", uri, readOnly)

gobject.type_register(vmmConnect)
