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

import gtk
import vte
import os
import gobject
import termios
import tty
import pty
import fcntl
import logging

import libvirt

class vmmSerialConsole(gtk.HBox):
    def __init__(self, vm, target_port):
        gtk.HBox.__init__(self)

        self.vm = vm
        self.target_port = target_port
        self.ttypath = None

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

        self.terminal.connect("commit", self.send_data)
        self.terminal.show()

        scrollbar = gtk.VScrollbar()
        scrollbar.set_adjustment(self.terminal.get_adjustment())

        self.pack_start(self.terminal)
        self.pack_start(scrollbar, expand=False, fill=False)

        self.ptyio = None
        self.ptysrc = None
        self.ptytermios = None

        self.connect("realize", self.handle_realize)
        self.connect("unrealize", self.handle_unrealize)
        self.vm.connect("config-changed", self.update_tty_path)
        self.vm.connect("status-changed", self.vm_status_changed)
        self.update_tty_path(self.vm)

    def handle_realize(self, ignore=None):
        self.opentty()

    def handle_unrealize(self, src_ignore=None, ignore=None):
        self.closetty()

    def vm_status_changed(self, src_ignore, oldstatus_ignore, status):
        if status in [ libvirt.VIR_DOMAIN_RUNNING ]:
            self.opentty()
        else:
            self.closetty()

    def update_tty_path(self, vm):
        serials = vm.get_serial_devs()
        for s in serials:
            port = s[3]
            path = s[2]
            if port == self.target_port:
                if path != self.ttypath:
                    logging.debug("Serial console '%s' path changed to %s."
                                   % (self.target_port, path))
                    self.ttypath = path
                    return

        logging.debug("No devices found for serial target port '%s'." %
                      self.target_port)
        self.ttypath = None

    def opentty(self):
        if self.ptyio != None:
            self.closetty()

        ipty = self.ttypath
        logging.debug("Opening serial tty path: %s" % self.ttypath)
        if ipty == None:
            return

        self.ptyio = pty.slave_open(ipty)
        fcntl.fcntl(self.ptyio, fcntl.F_SETFL, os.O_NONBLOCK)
        self.ptysrc = gobject.io_add_watch(self.ptyio,
                            gobject.IO_IN | gobject.IO_ERR | gobject.IO_HUP,
                            self.display_data)

        # Save term settings & set to raw mode
        self.ptytermios = termios.tcgetattr(self.ptyio)
        tty.setraw(self.ptyio, termios.TCSANOW)

    def closetty(self):
        if self.ptyio == None:
            return
        # Restore term settings
        try:
            termios.tcsetattr(self.ptyio, termios.TCSANOW, self.ptytermios)
        except:
            # The domain may already have exited, destroying the pty, so ignore
            pass
        os.close(self.ptyio)
        gobject.source_remove(self.ptysrc)
        self.ptyio = None
        self.ptysrc = None
        self.ptytermios = None

    def send_data(self, src_ignore, text, length_ignore):
        if self.ptyio != None:
            os.write(self.ptyio, text)

    def display_data(self, src_ignore, cond):
        if cond == gobject.IO_IN:
            data = os.read(self.ptyio, 1024)
            self.terminal.feed(data, len(data))
            return True
        else:
            self.closetty()
            return False

