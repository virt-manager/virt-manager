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

import virtManager

# pylint: disable=E0611
from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
# pylint: enable=E0611


class vmmGObject(GObject.GObject):
    _leak_check = True

    def __init__(self):
        GObject.GObject.__init__(self)
        self.config = virtManager.util.running_config

        self._gobject_handles = []
        self._gobject_timeouts = []
        self._gconf_handles = []

        self._signal_id_map = {}
        self._next_signal_id = 1

        self.object_key = str(self)

        # Config might not be available if we error early in startup
        if self.config and self._leak_check:
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

            self._cleanup()
        except:
            logging.exception("Error cleaning up %s", self)

    def _cleanup(self):
        raise NotImplementedError("_cleanup must be implemented in subclass")

    def connect(self, name, callback, *args):
        ret = GObject.GObject.connect(self, name, callback, *args)
        self._gobject_handles.append(ret)
        return ret

    def disconnect(self, handle):
        ret = GObject.GObject.disconnect(self, handle)
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
        GLib.source_remove(handle)
        self._gobject_timeouts.remove(handle)

    def _logtrace(self, msg=""):
        import traceback
        if msg:
            msg += " "
        logging.debug("%s(%s %s)\n:%s",
                      msg, self.object_key, self._refcount(),
                       "".join(traceback.format_stack()))

    def _refcount(self):
        # Function generates 2 temporary refs, so adjust total accordingly
        return (sys.getrefcount(self) - 2)

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
        Safe wrapper for using 'self.emit' with GLib.idle_add
        """
        def emitwrap(_s, *_a):
            self.emit(_s, *_a)
            return False

        self.idle_add(emitwrap, signal, *args)

    def idle_add(self, func, *args):
        """
        Make sure idle functions are run thread safe
        """
        return GLib.idle_add(func, *args)

    def timeout_add(self, timeout, func, *args):
        """
        Make sure timeout functions are run thread safe
        """
        return GLib.timeout_add(timeout, func, *args)

    def emit(self, signal_name, *args):
        return GObject.GObject.emit(self, signal_name, *args)

    def __del__(self):
        try:
            if self.config and self._leak_check:
                self.config.remove_object(self.object_key)
        except:
            logging.exception("Error removing %s", self.object_key)


class vmmGObjectUI(vmmGObject):
    def __init__(self, filename, windowname):
        vmmGObject.__init__(self)

        self.windowname = windowname
        self.builder = None
        self.topwin = None
        self.uifile = None
        self.err = None

        if filename:
            self.uifile = os.path.join(self.config.get_ui_dir(), filename)

            self.builder = Gtk.Builder()
            self.builder.set_translation_domain("virt-manager")
            self.builder.add_from_string(
                file(self.uifile).read())

            self.topwin = self.widget(self.windowname)
            self.topwin.hide()

            self.err = virtManager.error.vmmErrorDialog(self.topwin)

    def widget(self, name):
        return self.builder.get_object(name)

    def cleanup(self):
        self.close()
        vmmGObject.cleanup(self)
        self.builder = None
        self.topwin.destroy()
        self.topwin = None
        self.uifile = None
        self.err = None

    def _cleanup(self):
        raise NotImplementedError("_cleanup must be implemented in subclass")

    def close(self, ignore1=None, ignore2=None):
        pass

    def bind_escape_key_close(self):
        def close_on_escape(src_ignore, event):
            if Gdk.keyval_name(event.keyval) == "Escape":
                self.close()

        self.topwin.connect("key-press-event", close_on_escape)
