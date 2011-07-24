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
import traceback

import gtk
import gobject

import libvirt

from virtManager.baseclass import vmmGObjectUI

# This thin wrapper only exists so we can put debugging
# code in the run() method every now & then
class asyncJobWorker(threading.Thread):
    def __init__(self, callback, args):
        args = [callback] + args
        threading.Thread.__init__(self, target=cb_wrapper, args=args)

    def run(self):
        threading.Thread.run(self)

def cb_wrapper(callback, asyncjob, *args, **kwargs):
    try:
        callback(asyncjob, *args, **kwargs)
    except Exception, e:
        # If job is cancelled, don't report error to user.
        if (isinstance(e, libvirt.libvirtError) and
            asyncjob.can_cancel() and
            asyncjob.job_canceled):
            return

        asyncjob.set_error(str(e), "".join(traceback.format_exc()))

def _simple_async(callback, args, title, text, parent, errorintro,
                  show_progress, simplecb):
    """
    @show_progress: Whether to actually show a progress dialog
    @simplecb: If true, build a callback wrapper that ignores the asyncjob
               param that's passed to every cb by default
    """
    docb = callback
    if simplecb:
        def tmpcb(job, *args, **kwargs):
            ignore = job
            callback(*args, **kwargs)
        docb = tmpcb

    asyncjob = vmmAsyncJob(docb, args, title, text, parent.topwin,
                           show_progress=show_progress,
                           run_main=parent.config.support_threading)
    error, details = asyncjob.run()
    if error is None:
        return

    error = errorintro + ": " + error
    parent.err.show_err(error,
                        details=details)

# Displays a progress bar while executing the "callback" method.
class vmmAsyncJob(vmmGObjectUI):

    @staticmethod
    def simple_async(callback, args, title, text, parent, errorintro,
                     simplecb=True):
        _simple_async(callback, args, title, text, parent, errorintro, True,
                      simplecb)

    @staticmethod
    def simple_async_noshow(callback, args, parent, errorintro, simplecb=True):
        _simple_async(callback, args, "", "", parent, errorintro, False,
                      simplecb)


    def __init__(self, callback, args, title, text, parent,
                 run_main=True, show_progress=True,
                 cancel_back=None, cancel_args=None):
        """
        @run_main: If False, run synchronously without a separate thread
        @show_progress: If False, don't actually show a progress dialog
        @cancel_back: If operation supports cancelling, call this function
                      when cancel button is clicked
        @cancel_args: Arguments for optional cancel_back
        """
        vmmGObjectUI.__init__(self, "vmm-progress.glade", "vmm-progress")

        self.run_main = bool(run_main)
        self.show_progress = bool(show_progress)
        self.cancel_job = cancel_back
        self.cancel_args = cancel_args or []
        self.cancel_args = [self] + self.cancel_args
        if self.cancel_job:
            self.widget("cancel-async-job").show()
        else:
            self.widget("cancel-async-job").hide()
        self.job_canceled = False

        self._error_info = None
        self._data = None

        self.stage = self.widget("pbar-stage")
        self.pbar = self.widget("pbar")
        self.widget("pbar-text").set_text(text)
        self.topwin.set_transient_for(parent)

        args = [self] + args
        self.bg_thread = asyncJobWorker(callback, args)
        self.bg_thread.setDaemon(True)
        self.is_pulsing = True

        self.window.signal_autoconnect({
            "on_async_job_delete_event" : self.delete,
            "on_async_job_cancel_clicked" : self.cancel,
        })

        self.topwin.set_title(title)

    def run(self):
        timer = self.safe_timeout_add(100, self.exit_if_necessary)

        if self.show_progress:
            self.topwin.present()

        if not self.cancel_job:
            self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        if self.run_main:
            self.bg_thread.start()
            gtk.main()
        else:
            self.bg_thread.run()

        gobject.source_remove(timer)
        timer = 0

        if self.bg_thread.isAlive():
            # This can happen if the user closes the whole app while the
            # async dialog is running. This forces us to clean up properly
            # and not leave a dead process around.
            logging.debug("Forcing main_quit from async job.")
            self.exit_if_necessary(force_exit=True)

        self.topwin.destroy()
        self.cleanup()
        return self._get_error()

    def _cleanup(self):
        self.bg_thread = None
        self.cancel_job = None
        self.cancel_args = None

    def delete(self, ignore1=None, ignore2=None):
        thread_active = (self.bg_thread.isAlive() or not self.run_main)
        if self.cancel_job and thread_active:
            res = self.err.warn_chkbox(
                    text1=_("Cancel the job before closing window?"),
                    buttons=gtk.BUTTONS_YES_NO)
            if res:
                # The job may end after we click 'Yes', so check whether the
                # thread is active again
                thread_active = (self.bg_thread.isAlive() or not self.run_main)
                if thread_active:
                    self.cancel()

    def set_stage_text(self, text, canceling=False):
        if self.job_canceled and not canceling:
            return
        self.stage.set_text(text)

    def hide_warning(self):
        self.widget("warning-box").hide()

    def show_warning(self, summary):
        markup = "<small>%s</small>" % summary
        self.widget("warning-box").show()
        self.widget("warning-text").set_markup(markup)

    def can_cancel(self):
        return bool(self.cancel_job)

    def cancel(self, ignore1=None, ignore2=None):
        if not self.cancel_job:
            return

        self.cancel_job(*self.cancel_args)
        if self.job_canceled:
            self.hide_warning()
            self.set_stage_text(_("Cancelling job..."), canceling=True)

    def pulse_pbar(self, progress="", stage=None):
        gtk.gdk.threads_enter()
        try:
            self.is_pulsing = True
            self.pbar.set_text(progress)
            self.set_stage_text(stage or _("Processing..."))
        finally:
            gtk.gdk.threads_leave()


    def set_pbar_fraction(self, frac, progress, stage=None):
        # callback for progress meter when file size is known
        gtk.gdk.threads_enter()
        try:
            self.is_pulsing = False
            self.set_stage_text(stage or _("Processing..."))
            self.pbar.set_text(progress)

            if frac > 1:
                frac = 1.0
            if frac < 0:
                frac = 0
            self.pbar.set_fraction(frac)
        finally:
            gtk.gdk.threads_leave()


    def set_pbar_done(self, progress, stage=None):
        #callback for progress meter when progress is done
        gtk.gdk.threads_enter()
        try:
            self.is_pulsing = False
            self.set_stage_text(stage or _("Completed"))
            self.pbar.set_text(progress)
            self.pbar.set_fraction(1)
        finally:
            gtk.gdk.threads_leave()

    def set_error(self, error, details):
        self._error_info = (error, details)

    def _get_error(self):
        if not self._error_info:
            return (None, None)
        return self._error_info

    def set_data(self, data):
        self._data = data
    def get_data(self):
        return self._data

    def exit_if_necessary(self, force_exit=False):
        thread_active = (self.bg_thread.isAlive() or not self.run_main)

        if thread_active and not force_exit:
            if (self.is_pulsing):
                # Don't call pulse_pbar: this function is thread wrapped
                self.pbar.pulse()
            return True
        else:
            if self.run_main:
                gtk.main_quit()
            return False
