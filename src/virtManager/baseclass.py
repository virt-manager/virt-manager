#
# Copyright (C) 2010 Red Hat, Inc.
# Copyright (C) 2010 Cole Robinson <crobinso@redhat.com>
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

import os
import sys
import logging

import gtk
import gobject

import virtManager.config

def _safe_wrapper(func, *args):
    gtk.gdk.threads_enter()
    try:
        return func(*args)
    finally:
        gtk.gdk.threads_leave()

class vmmGObject(gobject.GObject):

    @staticmethod
    def type_register(*args, **kwargs):
        gobject.type_register(*args, **kwargs)

    def __init__(self):
        gobject.GObject.__init__(self)
        self.config = virtManager.config.running_config

        self._gobject_handles = []
        self._gobject_timeouts = []
        self._gconf_handles = []

        self.object_key = str(self)

        # Config might not be available if we error early in startup
        if self.config:
            self.config.add_object(self.object_key)

    def cleanup(self):
        # Do any cleanup required to drop reference counts so object is
        # actually reaped by python. Usually means unregistering callbacks
        try:
            for h in self._gconf_handles[:]:
                self.remove_gconf_handle(h)
            for h in self._gobject_handles[:]:
                self.disconnect(h)
            for h in self._gobject_timeouts[:]:
                self.remove_gobject_timeout(h)
        except:
            logging.exception("Error cleaning up %s" % self)

    def connect(self, name, callback, *args):
        ret = gobject.GObject.connect(self, name, callback, *args)
        self._gobject_handles.append(ret)
        return ret
    def disconnect(self, handle):
        ret = gobject.GObject.disconnect(self, handle)
        self._gobject_handles.remove(handle)
        return ret

    def add_gconf_handle(self, handle):
        self._gconf_handles.append(handle)
    def remove_gconf_handle(self, handle):
        self.config.remove_notifier(handle)
        self._gconf_handles.remove(handle)

    def add_gobject_timeout(self, handle):
        self._gobject_timeouts.append(handle)
    def remove_gobject_timeout(self, handle):
        gobject.source_remove(handle)
        self._gobject_timeouts.remove(handle)

    def _logtrace(self, msg):
        import traceback
        logging.debug("%s (%s %s)\n:%s" %
                      (msg, self.object_key, self.refcount(),
                       "".join(traceback.format_stack())))

    def refcount(self):
        # Function generates 2 temporary refs, so adjust total accordingly
        return (sys.getrefcount(self) - 2)

    def get_hal_helper(self):
        from virtManager import halhelper
        return halhelper.get_hal_helper()

    def connect_once(self, signal, func, *args):
        id_list = []

        def wrap_func(*wrapargs):
            if id_list:
                self.disconnect(id_list[0])

            return func(*wrapargs)

        conn_id = self.connect(signal, wrap_func, *args)
        id_list.append(conn_id)

        return conn_id

    def connect_opt_out(self, signal, func, *args):
        id_list = []

        def wrap_func(*wrapargs):
            ret = func(*wrapargs)
            if ret and id_list:
                self.disconnect(id_list[0])

        conn_id = self.connect(signal, wrap_func, *args)
        id_list.append(conn_id)

        return conn_id

    def idle_emit(self, signal, *args):
        """
        Safe wrapper for using 'self.emit' with gobject.idle_add
        """
        def emitwrap(_s, *_a):
            self.emit(_s, *_a)
            return False

        self.safe_idle_add(emitwrap, signal, *args)

    def safe_idle_add(self, func, *args):
        """
        Make sure idle functions are run thread safe
        """
        return gobject.idle_add(_safe_wrapper, func, *args)

    def safe_timeout_add(self, timeout, func, *args):
        """
        Make sure timeout functions are run thread safe
        """
        return gobject.timeout_add(timeout, _safe_wrapper, func, *args)

    def __del__(self):
        if hasattr(gobject.GObject, "__del__"):
            getattr(gobject.GObject, "__del__")(self)

        try:
            if self.config:
                self.config.remove_object(self.object_key)
        except:
            logging.exception("Error removing %s" % self.object_key)

class vmmGObjectUI(vmmGObject):
    def __init__(self, filename, windowname):
        vmmGObject.__init__(self)

        self.windowname = windowname
        self.window = None
        self.topwin = None
        self.gladefile = None
        self.err = None

        if filename:
            self.gladefile = os.path.join(self.config.get_glade_dir(),
                                          filename)
            self.window = gtk.glade.XML(self.gladefile,
                                        self.windowname,
                                        domain="virt-manager")
            self.topwin = self.window.get_widget(self.windowname)
            self.topwin.hide()

            self.err = virtManager.error.vmmErrorDialog(self.topwin)

    def cleanup(self):
        vmmGObject.cleanup(self)
        self.window = None
        self.topwin.destroy()
        self.topwin = None
        self.gladefile = None
        self.err = None
