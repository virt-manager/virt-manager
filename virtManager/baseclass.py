#
# Copyright (C) 2010, 2013 Red Hat, Inc.
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

import logging
import os
import sys
import threading
import traceback

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk

from . import config


class vmmGObject(GObject.GObject):
    _leak_check = True

    @staticmethod
    def idle_add(func, *args, **kwargs):
        """
        Make sure idle functions are run thread safe
        """
        def cb():
            return func(*args, **kwargs)
        return GLib.idle_add(cb)

    def __init__(self):
        GObject.GObject.__init__(self)
        self.config = config.RUNNING_CONFIG

        self._gobject_handles = []
        self._gobject_timeouts = []
        self._gsettings_handles = []

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
            for h in self._gsettings_handles[:]:
                self.remove_gsettings_handle(h)
            for h in self._gobject_handles[:]:
                if GObject.GObject.handler_is_connected(self, h):
                    self.disconnect(h)
            for h in self._gobject_timeouts[:]:
                self.remove_gobject_timeout(h)

            self._cleanup()
        except Exception:
            logging.exception("Error cleaning up %s", self)

    def _cleanup(self):
        raise NotImplementedError("_cleanup must be implemented in subclass")

    def __del__(self):
        try:
            if self.config and self._leak_check:
                self.config.remove_object(self.object_key)
        except Exception:
            logging.exception("Error removing %s", self.object_key)

    # pylint: disable=arguments-differ
    # Newer pylint can detect, but warns that overridden arguments are wrong

    def connect(self, name, callback, *args):
        """
        GObject connect() wrapper to simplify callers, and track handles
        for easy cleanup
        """
        ret = GObject.GObject.connect(self, name, callback, *args)
        self._gobject_handles.append(ret)
        return ret

    def disconnect(self, handle):
        """
        GObject disconnect() wrapper to simplify callers
        """
        ret = GObject.GObject.disconnect(self, handle)
        self._gobject_handles.remove(handle)
        return ret

    def timeout_add(self, timeout, func, *args):
        """
        GLib timeout_add wrapper to simplify callers, and track handles
        for easy cleanup
        """
        ret = GLib.timeout_add(timeout, func, *args)
        self.add_gobject_timeout(ret)
        return ret

    def emit(self, signal_name, *args):
        """
        GObject emit() wrapper to simplify callers
        """
        return GObject.GObject.emit(self, signal_name, *args)

    def add_gsettings_handle(self, handle):
        self._gsettings_handles.append(handle)
    def remove_gsettings_handle(self, handle):
        self.config.remove_notifier(handle)
        self._gsettings_handles.remove(handle)

    def add_gobject_timeout(self, handle):
        self._gobject_timeouts.append(handle)
    def remove_gobject_timeout(self, handle):
        GLib.source_remove(handle)
        self._gobject_timeouts.remove(handle)

    def _logtrace(self, msg=""):
        if msg:
            msg += " "
        logging.debug("%s(%s %s)\n:%s",
                      msg, self.object_key, self._refcount(),
                       "".join(traceback.format_stack()))

    def _refcount(self):
        # Function generates 2 temporary refs, so adjust total accordingly
        return (sys.getrefcount(self) - 2)

    def _start_thread(self, target=None, name=None, args=None, kwargs=None):
        # Helper for starting a daemonized thread
        t = threading.Thread(target=target, name=name,
            args=args or [], kwargs=kwargs or {})
        t.daemon = True
        t.start()


    ##############################
    # Custom signal/idle helpers #
    ##############################

    def connect_once(self, signal, func, *args):
        """
        Like standard glib connect(), but only runs the signal handler
        once, then unregisters it
        """
        id_list = []

        def wrap_func(*wrapargs):
            if id_list:
                self.disconnect(id_list[0])

            return func(*wrapargs)

        conn_id = self.connect(signal, wrap_func, *args)
        id_list.append(conn_id)

        return conn_id

    def connect_opt_out(self, signal, func, *args):
        """
        Like standard glib connect(), but allows the signal handler to
        unregister itself if it returns True
        """
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


class vmmGObjectUI(vmmGObject):
    @staticmethod
    def bind_escape_key_close_helper(topwin, close_cb):
        def close_on_escape(src_ignore, event):
            if Gdk.keyval_name(event.keyval) == "Escape":
                close_cb()
        topwin.connect("key-press-event", close_on_escape)

    def __init__(self, filename, windowname, builder=None, topwin=None):
        vmmGObject.__init__(self)
        self._external_topwin = bool(topwin)

        if filename:
            uifile = os.path.join(self.config.get_ui_dir(), filename)

            self.builder = Gtk.Builder()
            self.builder.set_translation_domain("virt-manager")
            self.builder.add_from_file(uifile)

            if not topwin:
                self.topwin = self.widget(windowname)
                self.topwin.hide()
            else:
                self.topwin = topwin
        else:
            self.builder = builder
            self.topwin = topwin

        self._err = None

    def _get_err(self):
        if self._err is None:
            from . import error
            self._err = error.vmmErrorDialog(self.topwin)
        return self._err
    err = property(_get_err)

    def widget(self, name):
        return self.builder.get_object(name)

    def cleanup(self):
        self.close()
        vmmGObject.cleanup(self)
        self.builder = None
        if not self._external_topwin:
            self.topwin.destroy()
        self.topwin = None
        self._err = None

    def _cleanup(self):
        raise NotImplementedError("_cleanup must be implemented in subclass")

    def close(self, ignore1=None, ignore2=None):
        pass

    def bind_escape_key_close(self):
        self.bind_escape_key_close_helper(self.topwin, self.close)

    def set_finish_cursor(self):
        self.topwin.set_sensitive(False)
        gdk_window = self.topwin.get_window()
        cursor = Gdk.Cursor.new_from_name(gdk_window.get_display(), "progress")
        gdk_window.set_cursor(cursor)

    def reset_finish_cursor(self, topwin=None):
        if not topwin:
            topwin = self.topwin

        topwin.set_sensitive(True)
        gdk_window = topwin.get_window()
        if not gdk_window:
            return
        cursor = Gdk.Cursor.new_from_name(gdk_window.get_display(), "default")
        gdk_window.set_cursor(cursor)
