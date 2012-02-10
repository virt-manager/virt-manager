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
import urlgrabber

from virtManager.baseclass import vmmGObjectUI

class vmmCreateMeter(urlgrabber.progress.BaseMeter):
    def __init__(self, asyncjob):
        # progress meter has to run asynchronously, so pass in the
        # async job to call back to with progress info
        urlgrabber.progress.BaseMeter.__init__(self)
        self.asyncjob = asyncjob
        self.started = False

    def _do_start(self, now=None):
        if self.text is not None:
            text = self.text
        else:
            text = self.basename
        if self.size is None:
            out = "    %5sB" % (0)
            self.asyncjob.pulse_pbar(out, text)
        else:
            out = "%3i%% %5sB" % (0, 0)
            self.asyncjob.set_pbar_fraction(0, out, text)
        self.started = True

    def _do_update(self, amount_read, now=None):
        if self.text is not None:
            text = self.text
        else:
            text = self.basename
        fread = urlgrabber.progress.format_number(amount_read)
        if self.size is None:
            out = "    %5sB" % (fread)
            self.asyncjob.pulse_pbar(out, text)
        else:
            frac = self.re.fraction_read()
            out = "%3i%% %5sB" % (frac * 100, fread)
            self.asyncjob.set_pbar_fraction(frac, out, text)

    def _do_end(self, amount_read, now=None):
        if self.text is not None:
            text = self.text
        else:
            text = self.basename
        fread = urlgrabber.progress.format_number(amount_read)
        if self.size is None:
            out = "    %5sB" % (fread)
            self.asyncjob.pulse_pbar(out, text)
        else:
            out = "%3i%% %5sB" % (100, fread)
            self.asyncjob.set_pbar_done(out, text)
        self.started = False


# This thin wrapper only exists so we can put debugging
# code in the run() method every now & then
class asyncJobWorker(threading.Thread):
    def __init__(self, callback, args):
        args = [callback] + args
        threading.Thread.__init__(self, target=cb_wrapper, args=args)
        self.setDaemon(True)

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
                           async=parent.config.support_threading)
    error, details = asyncjob.run()
    if error is None:
        return

    error = errorintro + ": " + error
    parent.err.show_err(error,
                        details=details)

def idle_wrapper(fn):
    def wrapped(self, *args, **kwargs):
        return self.idle_add(fn, self, *args, **kwargs)
    return wrapped

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
                 async=True, show_progress=True,
                 cancel_back=None, cancel_args=None):
        """
        @async: If False, run synchronously without a separate thread
        @show_progress: If False, don't actually show a progress dialog
        @cancel_back: If operation supports cancelling, call this function
                      when cancel button is clicked
        @cancel_args: Arguments for optional cancel_back
        """
        vmmGObjectUI.__init__(self, "vmm-progress.ui", "vmm-progress")
        self.topwin.set_transient_for(parent)

        self.async = bool(async)
        self.show_progress = bool(show_progress)
        self.cancel_job = cancel_back
        self.cancel_args = cancel_args or []
        self.cancel_args = [self] + self.cancel_args
        self.job_canceled = False

        self._error_info = None
        self._data = None

        self.stage = self.widget("pbar-stage")
        self.pbar = self.widget("pbar")
        self.is_pulsing = True
        self._meter = None

        args = [self] + args
        self.bg_thread = asyncJobWorker(callback, args)
        logging.debug("Creating async job for function cb=%s", callback)

        self.window.connect_signals({
            "on_async_job_delete_event" : self.delete,
            "on_async_job_cancel_clicked" : self.cancel,
        })

        # UI state
        self.topwin.set_title(title)
        self.widget("pbar-text").set_text(text)
        if self.cancel_job:
            self.widget("cancel-async-job").show()
        else:
            self.widget("cancel-async-job").hide()


    #############
    # Accessors #
    #############

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

    def get_meter(self):
        if not self._meter:
            self._meter = vmmCreateMeter(self)
        return self._meter

    def can_cancel(self):
        return bool(self.cancel_job)

    def _cleanup(self):
        self.bg_thread = None
        self.cancel_job = None
        self.cancel_args = None
        self._meter = None

    ####################
    # Internal helpers #
    ####################

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


    ###########
    # Actions #
    ###########

    def run(self):
        timer = gobject.timeout_add(100, self.exit_if_necessary)

        if self.show_progress:
            self.topwin.present()

        if not self.cancel_job and self.show_progress:
            self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        if self.async:
            self.bg_thread.start()
            gtk.main()
        else:
            self.bg_thread.run()

        gobject.source_remove(timer)

        if self.bg_thread.isAlive():
            # This can happen if the user closes the whole app while the
            # async dialog is running. This forces us to clean up properly
            # and not leave a dead process around.
            logging.debug("Forcing main_quit from async job.")
            self.exit_if_necessary(force_exit=True)

        self.topwin.destroy()
        self.cleanup()
        return self._get_error()

    def delete(self, ignore1=None, ignore2=None):
        thread_active = (self.bg_thread.isAlive() or not self.async)
        if not self.cancel_job or not thread_active:
            return

        res = self.err.warn_chkbox(
                text1=_("Cancel the job before closing window?"),
                buttons=gtk.BUTTONS_YES_NO)
        if not res:
            return

        # The job may end after we click 'Yes', so check whether the
        # thread is active again
        thread_active = (self.bg_thread.isAlive() or not self.async)
        if thread_active:
            self.cancel()


    def cancel(self, ignore1=None, ignore2=None):
        if not self.cancel_job:
            return

        self.cancel_job(*self.cancel_args)
        if self.job_canceled:
            self.hide_warning()
            self.set_stage_text(_("Cancelling job..."), canceling=True)


    # All functions after this point are called from the timer loop
    # which means we need to be careful and lock threads before doing
    # any UI bits
    def exit_if_necessary(self, force_exit=False):
        thread_active = (self.bg_thread.isAlive() or not self.async)

        if not thread_active or force_exit:
            if self.async:
                gtk.main_quit()
            return False

        if not self.is_pulsing or not self.show_progress:
            return True

        self.idle_add(self.pbar.pulse)
        return True

    @idle_wrapper
    def pulse_pbar(self, progress="", stage=None):
        self.is_pulsing = True
        self.pbar.set_text(progress)
        self.set_stage_text(stage or _("Processing..."))

    @idle_wrapper
    def set_pbar_fraction(self, frac, progress, stage=None):
        self.is_pulsing = False
        self.set_stage_text(stage or _("Processing..."))
        self.pbar.set_text(progress)

        if frac > 1:
            frac = 1.0
        if frac < 0:
            frac = 0
        self.pbar.set_fraction(frac)

    @idle_wrapper
    def set_pbar_done(self, progress, stage=None):
        self.is_pulsing = False
        self.set_stage_text(stage or _("Completed"))
        self.pbar.set_text(progress)
        self.pbar.set_fraction(1)
