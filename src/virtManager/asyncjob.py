#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
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
import threading
import gtk
import gtk.gdk
import gtk.glade
import gobject

# Displays a progress bar while executing the "callback" method.

class vmmAsyncJob(gobject.GObject):
    # This thin wrapper only exists so we can put debugging
    # code in the run() method every now & then
    class asyncJobWorker(threading.Thread):
        def __init__(self, callback, args):
            threading.Thread.__init__(self, target=callback, args=args)

        def run(self):
            threading.Thread.run(self)

    def __init__(self, config, callback, args=None,
                 text=_("Please wait a few moments..."),
                 title=_("Operation in progress")):
        self.__gobject_init__()
        self.config = config

        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-progress.glade", "vmm-progress", domain="virt-manager")
        self.window.get_widget("pbar-text").set_text(text)

        self.topwin = self.window.get_widget("vmm-progress")
        self.topwin.set_title(title)
        self.topwin.hide()

        # Callback sets this if there is an error
        self._error_info = None
        self.stage = self.window.get_widget("pbar-stage")
        self.pbar = self.window.get_widget("pbar")

        args.append(self)
        self.bg_thread = vmmAsyncJob.asyncJobWorker(callback, args)
        self.bg_thread.setDaemon(True)
        self.is_pulsing = True

    def run(self):
        timer = gobject.timeout_add (100, self.exit_if_necessary)
        self.topwin.present()
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))
        self.bg_thread.start()
        gtk.main()
        gobject.source_remove(timer)
        timer = 0

        if self.bg_thread.isAlive():
            # This can happen if the user closes the whole app while the
            # async dialog is running. This forces us to clean up properly
            # and not leave a dead process around.
            logging.debug("Forcing main_quit from async job.")
            self._exit_if_necessary(force_exit=True)

        self.topwin.destroy()

    def pulse_pbar(self, progress="", stage=None):
        gtk.gdk.threads_enter()
        try:
            self.is_pulsing = True
            self.pbar.set_text(progress)
            if stage is not None:
                self.stage.set_text(stage)
            else:
                self.stage.set_text(_("Processing..."))
        finally:
            gtk.gdk.threads_leave()


    def set_pbar_fraction(self, frac, progress, stage=None):
        # callback for progress meter when file size is known
        gtk.gdk.threads_enter()
        try:
            self.is_pulsing=False
            if stage is not None:
                self.stage.set_text(stage)
            else:
                self.stage.set_text(_("Processing..."))
            self.pbar.set_text(progress)
            self.pbar.set_fraction(frac)
        finally:
            gtk.gdk.threads_leave()


    def set_pbar_done(self, progress, stage=None):
        #callback for progress meter when progress is done
        gtk.gdk.threads_enter()
        try:
            self.is_pulsing=False
            if stage is not None:
                self.stage.set_text(stage)
            else:
                self.stage.set_text(_("Completed"))
            self.pbar.set_text(progress)
            self.pbar.set_fraction(1)
        finally:
            gtk.gdk.threads_leave()

    def set_error(self, error, details):
        self._error_info = (error, details)

    def get_error(self):
        if not self._error_info:
            return (None, None)
        return self._error_info

    def exit_if_necessary(self):
        gtk.gdk.threads_enter()
        try:
            return self._exit_if_necessary()
        finally:
            gtk.gdk.threads_leave()

    def _exit_if_necessary(self, force_exit=False):
        if self.bg_thread.isAlive() and not force_exit:
            if(self.is_pulsing):
                self.pbar.pulse()
            return True
        else:
            gtk.main_quit()
            return False

