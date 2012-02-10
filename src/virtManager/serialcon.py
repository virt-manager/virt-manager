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

import os
import termios
import tty
import pty
import fcntl
import logging

import gtk
import gobject

try:
    import vte
except ImportError:
    logging.debug("Could not import vte, no serial console support")
    vte = None

import libvirt

from virtManager.baseclass import vmmGObject

class ConsoleConnection(vmmGObject):
    def __init__(self, vm):
        vmmGObject.__init__(self)

        self.vm = vm
        self.conn = vm.conn

    def _cleanup(self):
        self.close()

        self.vm = None
        self.conn = None

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

    def open(self, dev, terminal):
        if self.fd != None:
            self.close()

        ipty = dev and dev.source_path or None
        logging.debug("Opening serial tty path: %s", ipty)
        if ipty == None:
            return

        self.fd = pty.slave_open(ipty)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, os.O_NONBLOCK)
        self.source = gobject.io_add_watch(self.fd,
                            gobject.IO_IN | gobject.IO_ERR | gobject.IO_HUP,
                            self.display_data, terminal)

        # Save term settings & set to raw mode
        self.origtermios = termios.tcgetattr(self.fd)
        tty.setraw(self.fd, termios.TCSANOW)

    def close(self):
        if self.fd == None:
            return

        # Restore term settings
        try:
            if self.origtermios:
                termios.tcsetattr(self.fd, termios.TCSANOW, self.origtermios)
        except:
            # domain may already have exited, destroying the pty, so ignore
            pass

        os.close(self.fd)
        self.fd = None

        gobject.source_remove(self.source)
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

        if cond != gobject.IO_IN:
            self.close()
            return False

        data = os.read(self.fd, 1024)
        terminal.feed(data, len(data))
        return True

class LibvirtConsoleConnection(ConsoleConnection):
    def __init__(self, vm):
        ConsoleConnection.__init__(self, vm)

        self.stream = None

        self.streamToTerminal = ""
        self.terminalToStream = ""

    def _event_on_stream(self, stream, events, opaque):
        ignore = stream
        terminal = opaque

        if (events & libvirt.VIR_EVENT_HANDLE_ERROR or
            events & libvirt.VIR_EVENT_HANDLE_HANGUP):
            logging.debug("Received stream ERROR/HANGUP, closing console")
            self.close()

        if events & libvirt.VIR_EVENT_HANDLE_READABLE:
            try:
                got = self.stream.recv(1024 * 100)
            except:
                logging.exception("Error receiving stream data")
                self.close()
                return

            if got == -2:
                return

            queued_text = bool(self.streamToTerminal)
            self.streamToTerminal += got
            if not queued_text:
                self.idle_add(self.display_data, terminal)

        if (events & libvirt.VIR_EVENT_HANDLE_WRITABLE and
            self.terminalToStream):

            try:
                done = self.stream.send(self.terminalToStream)
            except:
                logging.exception("Error sending stream data")
                self.close()
                return

            if done == -2:
                return

            self.terminalToStream = self.terminalToStream[done:]

        if not self.terminalToStream:
            self.stream.eventUpdateCallback(libvirt.VIR_STREAM_EVENT_READABLE |
                                            libvirt.VIR_STREAM_EVENT_ERROR |
                                            libvirt.VIR_STREAM_EVENT_HANGUP)


    def open(self, dev, terminal):
        if self.stream:
            self.close()

        name = dev and dev.alias.name or None
        logging.debug("Opening console stream for dev=%s alias=%s",
                      dev, name)
        if not name:
            raise RuntimeError(_("Cannot open a device with no alias name"))

        self.stream = self.conn.vmm.newStream(libvirt.VIR_STREAM_NONBLOCK)

        self.vm.open_console(name, self.stream)

        self.stream.eventAddCallback((libvirt.VIR_STREAM_EVENT_READABLE |
                                      libvirt.VIR_STREAM_EVENT_ERROR |
                                      libvirt.VIR_STREAM_EVENT_HANGUP),
                                     self._event_on_stream,
                                     terminal)

    def close(self):
        if self.stream:
            try:
                self.stream.eventRemoveCallback()
            except:
                logging.exception("Error removing stream callback")
            try:
                self.stream.finish()
            except:
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

        terminal.feed(self.streamToTerminal, len(self.streamToTerminal))
        self.streamToTerminal = ""

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

        ctype = dev.char_type
        path = dev.source_path
        is_remote = vm.conn.is_remote()
        support_tunnel = vmmSerialConsole.support_remote_console(vm)

        err = ""

        if is_remote:
            if not support_tunnel:
                err = _("Serial console not yet supported over remote "
                        "connection")
        elif not vm.is_active():
            err = _("Serial console not available for inactive guest")
        elif not ctype in usable_types:
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

        self.vm.connect("status-changed", self.vm_status_changed)

    def init_terminal(self):
        if not vte:
            return

        self.terminal = vte.Terminal()
        self.terminal.set_cursor_blinks(True)
        self.terminal.set_emulation("xterm")
        self.terminal.set_scrollback_lines(1000)
        self.terminal.set_audible_bell(False)
        self.terminal.set_visible_bell(True)
        # XXX python VTE binding has bug failing to register constants
        #self.terminal.set_backspace_binding(vte.ERASE_ASCII_BACKSPACE)
        self.terminal.set_backspace_binding(1)

        self.terminal.connect("button-press-event", self.show_serial_rcpopup)
        self.terminal.connect("commit", self.console.send_data, self.terminal)
        self.terminal.show()

    def init_popup(self):
        self.serial_popup = gtk.Menu()

        self.serial_copy = gtk.ImageMenuItem(gtk.STOCK_COPY)
        self.serial_popup.add(self.serial_copy)

        self.serial_paste = gtk.ImageMenuItem(gtk.STOCK_PASTE)
        self.serial_popup.add(self.serial_paste)

    def init_ui(self):
        self.box = gtk.Notebook()
        self.box.set_show_tabs(False)
        self.box.set_show_border(False)

        align = gtk.Alignment()
        align.set_padding(2, 2, 2, 2)
        evbox = gtk.EventBox()
        evbox.modify_bg(gtk.STATE_NORMAL, gtk.gdk.Color(0, 0, 0))
        terminalbox = gtk.HBox()
        scrollbar = gtk.VScrollbar()
        self.error_label = gtk.Label()
        self.error_label.set_width_chars(40)
        self.error_label.set_line_wrap(True)

        if self.terminal:
            scrollbar.set_adjustment(self.terminal.get_adjustment())
            align.add(self.terminal)

        evbox.add(align)
        terminalbox.pack_start(evbox)
        terminalbox.pack_start(scrollbar, expand=False, fill=False)

        self.box.append_page(terminalbox)
        self.box.append_page(self.error_label)
        self.box.show_all()

    def _cleanup(self):
        self.console.cleanup()
        self.console = None

        self.vm = None
        self.terminal = None
        self.box = None

    def show_error(self, msg):
        self.error_label.set_markup("<b>%s</b>" % msg)
        self.box.set_current_page(1)

    def open_console(self):
        try:
            if not vte:
                raise RuntimeError(
                        _("vte2 is required for text console support"))

            self.console.open(self.lookup_dev(), self.terminal)
            self.box.set_current_page(0)
            return True
        except Exception, e:
            logging.exception("Error opening serial console")
            self.show_error(_("Error connecting to text console: %s") % e)
            try:
                self.console.close()
            except:
                pass

        return False

    def vm_status_changed(self, src_ignore, oldstatus_ignore, status):
        if status in [libvirt.VIR_DOMAIN_RUNNING]:
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
        self.serial_copy.connect("activate", self.serial_copy_text, src)
        self.serial_paste.connect("activate", self.serial_paste_text, src)

        if src.get_has_selection():
            self.serial_copy.set_sensitive(True)
        else:
            self.serial_copy.set_sensitive(False)
        self.serial_popup.popup(None, None, None, 0, event.time)

    def serial_copy_text(self, src_ignore, terminal):
        terminal.copy_clipboard()

    def serial_paste_text(self, src_ignore, terminal):
        terminal.paste_clipboard()
