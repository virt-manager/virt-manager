#
# Copyright (C) 2006, 2013 Red Hat, Inc.
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

import os
import termios
import tty
import pty
import fcntl
import logging

import gi
from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gtk

# We can use either 2.91 or 2.90. This is just to silence runtime warnings
# pylint: disable=wrong-import-position
try:
    gi.require_version("Vte", "2.91")
    logging.debug("Using VTE API 2.91")
except ValueError:
    gi.require_version("Vte", "2.90")
    logging.debug("Using VTE API 2.90")
from gi.repository import Vte

import libvirt

from .baseclass import vmmGObject


class ConsoleConnection(vmmGObject):
    def __init__(self, vm):
        vmmGObject.__init__(self)

        self.vm = vm
        self.conn = vm.conn

    def _cleanup(self):
        self.close()

        self.vm = None
        self.conn = None

    def is_open(self):
        raise NotImplementedError()
    def open(self, dev, terminal):
        raise NotImplementedError()
    def close(self):
        raise NotImplementedError()

    def send_data(self, src, text, length, terminal):
        """
        Callback when data has been entered into VTE terminal
        """
        raise NotImplementedError()


class LocalConsoleConnection(ConsoleConnection):
    def __init__(self, vm):
        ConsoleConnection.__init__(self, vm)

        self.fd = None
        self.source = None
        self.origtermios = None

    def is_open(self):
        return self.fd is not None

    def open(self, dev, terminal):
        if self.fd is not None:
            self.close()

        ipty = dev and dev.source_path or None
        logging.debug("Opening serial tty path: %s", ipty)
        if ipty is None:
            return

        self.fd = pty.slave_open(ipty)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, os.O_NONBLOCK)
        self.source = GLib.io_add_watch(self.fd,
                            GLib.IO_IN | GLib.IO_ERR | GLib.IO_HUP,
                            self.display_data, terminal)

        # Save term settings & set to raw mode
        self.origtermios = termios.tcgetattr(self.fd)
        tty.setraw(self.fd, termios.TCSANOW)

    def close(self):
        if self.fd is None:
            return

        # Restore term settings
        try:
            if self.origtermios:
                termios.tcsetattr(self.fd, termios.TCSANOW, self.origtermios)
        except Exception:
            # domain may already have exited, destroying the pty, so ignore
            pass

        os.close(self.fd)
        self.fd = None

        GLib.source_remove(self.source)
        self.source = None
        self.origtermios = None

    def send_data(self, src, text, length, terminal):
        ignore = src
        ignore = length
        ignore = terminal

        if self.fd is None:
            return

        os.write(self.fd, text)

    def display_data(self, src, cond, terminal):
        ignore = src

        if cond != GLib.IO_IN:
            self.close()
            return False

        data = os.read(self.fd, 1024)
        terminal.feed(data)
        return True


class LibvirtConsoleConnection(ConsoleConnection):
    def __init__(self, vm):
        ConsoleConnection.__init__(self, vm)

        self.stream = None

        self.streamToTerminal = b""
        self.terminalToStream = ""

    def _event_on_stream(self, stream, events, opaque):
        ignore = stream
        terminal = opaque

        if (events & libvirt.VIR_EVENT_HANDLE_ERROR or
            events & libvirt.VIR_EVENT_HANDLE_HANGUP):
            logging.debug("Received stream ERROR/HANGUP, closing console")
            self.close()
            return

        if events & libvirt.VIR_EVENT_HANDLE_READABLE:
            try:
                got = self.stream.recv(1024 * 100)
            except Exception:
                logging.exception("Error receiving stream data")
                self.close()
                return

            if got == -2:
                # This is basically EAGAIN
                return
            if len(got) == 0:
                logging.debug("Received EOF from stream, closing")
                self.close()
                return

            queued_text = bool(self.streamToTerminal)
            self.streamToTerminal += got
            if not queued_text:
                self.idle_add(self.display_data, terminal)

        if (events & libvirt.VIR_EVENT_HANDLE_WRITABLE and
            self.terminalToStream):

            try:
                done = self.stream.send(self.terminalToStream.encode())
            except Exception:
                logging.exception("Error sending stream data")
                self.close()
                return

            if done == -2:
                # This is basically EAGAIN
                return

            self.terminalToStream = self.terminalToStream[done:]

        if not self.terminalToStream:
            self.stream.eventUpdateCallback(libvirt.VIR_STREAM_EVENT_READABLE |
                                            libvirt.VIR_STREAM_EVENT_ERROR |
                                            libvirt.VIR_STREAM_EVENT_HANGUP)


    def is_open(self):
        return self.stream is not None

    def open(self, dev, terminal):
        if self.stream:
            self.close()

        name = dev and dev.alias.name or None
        logging.debug("Opening console stream for dev=%s alias=%s",
                      dev, name)
        # libxl doesn't set aliases, their open_console just defaults to
        # opening the first console device, so don't force prescence of
        # an alias

        stream = self.conn.get_backend().newStream(libvirt.VIR_STREAM_NONBLOCK)
        self.vm.open_console(name, stream)
        self.stream = stream

        self.stream.eventAddCallback((libvirt.VIR_STREAM_EVENT_READABLE |
                                      libvirt.VIR_STREAM_EVENT_ERROR |
                                      libvirt.VIR_STREAM_EVENT_HANGUP),
                                     self._event_on_stream,
                                     terminal)

    def close(self):
        if self.stream:
            try:
                self.stream.eventRemoveCallback()
            except Exception:
                logging.exception("Error removing stream callback")
            try:
                self.stream.finish()
            except Exception:
                logging.exception("Error finishing stream")

        self.stream = None

    def send_data(self, src, text, length, terminal):
        ignore = src
        ignore = length
        ignore = terminal

        if self.stream is None:
            return

        self.terminalToStream += text
        if self.terminalToStream:
            self.stream.eventUpdateCallback(libvirt.VIR_STREAM_EVENT_READABLE |
                                            libvirt.VIR_STREAM_EVENT_WRITABLE |
                                            libvirt.VIR_STREAM_EVENT_ERROR |
                                            libvirt.VIR_STREAM_EVENT_HANGUP)

    def display_data(self, terminal):
        if not self.streamToTerminal:
            return

        terminal.feed(self.streamToTerminal)
        self.streamToTerminal = b""


class vmmSerialConsole(vmmGObject):
    @staticmethod
    def support_remote_console(vm):
        """
        Check if we can connect to a remote console
        """
        return bool(vm.remote_console_supported)

    @staticmethod
    def can_connect(vm, dev):
        """
        Check if we think we can actually open passed console/serial dev
        """
        usable_types = ["pty"]

        ctype = dev.type
        path = dev.source_path
        is_remote = vm.conn.is_remote()
        support_tunnel = vmmSerialConsole.support_remote_console(vm)

        err = ""

        if is_remote and not support_tunnel:
            err = _("Remote serial console not supported for this "
                    "connection")
        elif not vm.is_active():
            err = _("Serial console not available for inactive guest")
        elif ctype not in usable_types:
            err = (_("Console for device type '%s' not yet supported") %
                     ctype)
        elif (not is_remote and
              not support_tunnel and
              (path and not os.access(path, os.R_OK | os.W_OK))):
            err = _("Can not access console path '%s'") % str(path)

        return err

    def __init__(self, vm, target_port, name):
        vmmGObject.__init__(self)

        self.vm = vm
        self.target_port = target_port
        self.name = name
        self.lastpath = None

        # Always use libvirt console streaming if available, so
        # we exercise the same code path (it's what virsh console does)
        if vmmSerialConsole.support_remote_console(self.vm):
            self.console = LibvirtConsoleConnection(self.vm)
        else:
            self.console = LocalConsoleConnection(self.vm)

        self.serial_popup = None
        self.serial_copy = None
        self.serial_paste = None
        self.serial_close = None
        self.init_popup()

        self.terminal = None
        self.init_terminal()

        self.box = None
        self.error_label = None
        self.init_ui()

        self.vm.connect("state-changed", self.vm_status_changed)

    def init_terminal(self):
        self.terminal = Vte.Terminal()
        self.terminal.set_scrollback_lines(1000)
        self.terminal.set_audible_bell(False)
        self.terminal.get_accessible().set_name("Serial Terminal")

        self.terminal.connect("button-press-event", self.show_serial_rcpopup)
        self.terminal.connect("commit", self.console.send_data, self.terminal)
        self.terminal.show()

    def init_popup(self):
        self.serial_popup = Gtk.Menu()

        self.serial_copy = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_COPY,
                                                            None)
        self.serial_copy.connect("activate", self.serial_copy_text)
        self.serial_popup.add(self.serial_copy)

        self.serial_paste = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_PASTE,
                                                             None)
        self.serial_paste.connect("activate", self.serial_paste_text)
        self.serial_popup.add(self.serial_paste)

    def init_ui(self):
        self.box = Gtk.Notebook()
        self.box.set_show_tabs(False)
        self.box.set_show_border(False)

        align = Gtk.Alignment()
        align.set_padding(2, 2, 2, 2)
        evbox = Gtk.EventBox()
        evbox.modify_bg(Gtk.StateType.NORMAL, Gdk.Color(0, 0, 0))
        terminalbox = Gtk.HBox()
        scrollbar = Gtk.VScrollbar()
        self.error_label = Gtk.Label()
        self.error_label.set_width_chars(40)
        self.error_label.set_line_wrap(True)

        if self.terminal:
            scrollbar.set_adjustment(self.terminal.get_vadjustment())
            align.add(self.terminal)

        evbox.add(align)
        terminalbox.pack_start(evbox, True, True, 0)
        terminalbox.pack_start(scrollbar, False, False, 0)

        self.box.append_page(terminalbox, Gtk.Label(""))
        self.box.append_page(self.error_label, Gtk.Label(""))
        self.box.show_all()

        scrollbar.hide()
        scrollbar.get_adjustment().connect(
            "changed", self._scrollbar_adjustment_changed, scrollbar)

    def _scrollbar_adjustment_changed(self, adjustment, scrollbar):
        scrollbar.set_visible(
            adjustment.get_upper() > adjustment.get_page_size())

    def _cleanup(self):
        self.console.cleanup()
        self.console = None

        self.vm = None
        self.terminal = None
        self.box = None

    def close(self):
        if self.console:
            self.console.close()

    def show_error(self, msg):
        self.error_label.set_markup("<b>%s</b>" % msg)
        self.box.set_current_page(1)

    def open_console(self):
        try:
            if not self.console.is_open():
                self.console.open(self.lookup_dev(), self.terminal)
            self.box.set_current_page(0)
            return True
        except Exception as e:
            logging.exception("Error opening serial console")
            self.show_error(_("Error connecting to text console: %s") % e)
            try:
                self.console.close()
            except Exception:
                pass

        return False

    def vm_status_changed(self, vm):
        if vm.status() in [libvirt.VIR_DOMAIN_RUNNING]:
            self.open_console()
        else:
            self.console.close()

    def lookup_dev(self):
        devs = self.vm.get_serial_devs()
        for dev in devs:
            port = dev.vmmindex
            path = dev.source_path

            if port == self.target_port:
                if path != self.lastpath:
                    logging.debug("Serial console '%s' path changed to %s",
                                  self.target_port, path)
                self.lastpath = path
                return dev

        logging.debug("No devices found for serial target port '%s'",
                      self.target_port)
        self.lastpath = None
        return None

    #######################
    # Popup menu handling #
    #######################

    def show_serial_rcpopup(self, src, event):
        if event.button != 3:
            return

        self.serial_popup.show_all()

        if src.get_has_selection():
            self.serial_copy.set_sensitive(True)
        else:
            self.serial_copy.set_sensitive(False)
        self.serial_popup.popup(None, None, None, None, 0, event.time)

    def serial_copy_text(self, src_ignore):
        self.terminal.copy_clipboard()

    def serial_paste_text(self, src_ignore):
        self.terminal.paste_clipboard()
