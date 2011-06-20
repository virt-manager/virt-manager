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

import vte

import libvirt

from virtManager.baseclass import vmmGObject

class ConsoleConnection(vmmGObject):
    def __init__(self, vm):
        vmmGObject.__init__(self)

        self.vm = vm
        self.conn = vm.get_connection()

    def cleanup(self):
        vmmGObject.cleanup(self)
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

    def cleanup(self):
        ConsoleConnection.cleanup(self)

    def open(self, dev, terminal):
        if self.fd != None:
            self.close()

        ipty = dev and dev.source_path or None
        logging.debug("Opening serial tty path: %s" % ipty)
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
            termios.tcsetattr(self.fd, termios.TCSANOW, self.origtermios)
        except:
            # domain may already have exited, destroying the pty, so ignore
            pass

        os.close(self.fd)
        gobject.source_remove(self.source)
        self.fd = None
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




class vmmSerialConsole(vmmGObject):

    @staticmethod
    def can_connect(vm, dev):
        """
        Check if we think we can actually open passed console/serial dev
        """
        usable_types = ["pty"]

        ctype = dev.char_type
        path = dev.source_path

        err = ""

        if vm.get_connection().is_remote():
            err = _("Serial console not yet supported over remote "
                    "connection")
        elif not vm.is_active():
            err = _("Serial console not available for inactive guest")
        elif not ctype in usable_types:
            err = (_("Console for device type '%s' not yet supported") %
                     ctype)
        elif path and not os.access(path, os.R_OK | os.W_OK):
            err = _("Can not access console path '%s'") % str(path)

        return err

    def __init__(self, vm, target_port):
        vmmGObject.__init__(self)

        self.vm = vm
        self.target_port = target_port
        self.lastpath = None

        self.console = LocalConsoleConnection(self.vm)

        self.terminal = None
        self.init_terminal()

        self.box = None
        self.init_ui()

        self.box.connect("realize", self.handle_realize)
        self.box.connect("unrealize", self.handle_unrealize)
        self.vm.connect("status-changed", self.vm_status_changed)

    def init_terminal(self):
        self.terminal = vte.Terminal()
        self.terminal.set_cursor_blinks(True)
        self.terminal.set_emulation("xterm")
        self.terminal.set_font_from_string("fixed 10")
        self.terminal.set_scrollback_lines(1000)
        self.terminal.set_audible_bell(False)
        self.terminal.set_visible_bell(True)
        # XXX python VTE binding has bug failing to register constants
        #self.terminal.set_backspace_binding(vte.ERASE_ASCII_BACKSPACE)
        self.terminal.set_backspace_binding(1)

        self.terminal.connect("commit", self.console.send_data, self.terminal)
        self.terminal.show()

    def init_ui(self):
        self.box = gtk.HBox()
        scrollbar = gtk.VScrollbar()
        scrollbar.set_adjustment(self.terminal.get_adjustment())

        self.box.pack_start(self.terminal)
        self.box.pack_start(scrollbar, expand=False, fill=False)

    def cleanup(self):
        vmmGObject.cleanup(self)

        self.console.cleanup()
        self.console = None

        self.vm = None
        self.terminal = None
        self.box = None

    def handle_realize(self, ignore=None):
        self.console.open(self.lookup_dev(), self.terminal)

    def handle_unrealize(self, src_ignore=None, ignore=None):
        self.console.close()

    def vm_status_changed(self, src_ignore, oldstatus_ignore, status):
        if status in [libvirt.VIR_DOMAIN_RUNNING]:
            self.console.open(self.lookup_dev(), self.terminal)
        else:
            self.console.close()

    def lookup_dev(self):
        devs = self.vm.get_serial_devs()
        for dev in devs:
            port = dev.vmmindex
            path = dev.source_path

            if port == self.target_port:
                if path != self.lastpath:
                    logging.debug("Serial console '%s' path changed to %s."
                                  % (self.target_port, path))
                self.lastpath = path
                return dev

        logging.debug("No devices found for serial target port '%s'." %
                      self.target_port)
        self.lastpath = None
        return None
