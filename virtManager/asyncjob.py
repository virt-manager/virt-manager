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

# pylint: disable=E0611
from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gtk
# pylint: enable=E0611

import libvirt
import urlgrabber

from virtManager.baseclass import vmmGObjectUI


class vmmMeter(urlgrabber.progress.BaseMeter):
    def __init__(self, cb_pulse, cb_fraction, cb_done):
        urlgrabber.progress.BaseMeter.__init__(self)
        self.started = False

        self._vmm_pulse = cb_pulse
        self._vmm_fraction = cb_fraction
        self._vmm_done = cb_done


    def _do_start(self, now=None):
        if self.text is not None:
            text = self.text
        else:
            text = self.basename
        if self.size is None:
            out = "    %5sB" % (0)
            self._vmm_pulse(out, text)
        else:
            out = "%3i%% %5sB" % (0, 0)
            self._vmm_fraction(0, out, text)
        self.started = True

    def _do_update(self, amount_read, now=None):
        if self.text is not None:
            text = self.text
        else:
            text = self.basename
        fread = urlgrabber.progress.format_number(amount_read)
        if self.size is None:
            out = "    %5sB" % (fread)
            self._vmm_pulse(out, text)
        else:
            frac = self.re.fraction_read()
            out = "%3i%% %5sB" % (frac * 100, fread)
            self._vmm_fraction(frac, out, text)

    def _do_end(self, amount_read, now=None):
        if self.text is not None:
            text = self.text
        else:
            text = self.basename
        fread = urlgrabber.progress.format_number(amount_read)
        if self.size is None:
            out = "    %5sB" % (fread)
            self._vmm_pulse(out, text)
        else:
            out = "%3i%% %5sB" % (100, fread)
            self._vmm_done(out, text)
        self.started = False


# This thin wrapper only exists so we can put debugging
# code in the run() method every now & then
class asyncJobWorker(threading.Thread):
    def __init__(self, callback, args):
        args = [callback] + args
        threading.Thread.__init__(self, target=cb_wrapper, args=args)
        self.daemon = True


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
                  show_progress, simplecb, errorcb):
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

    if errorcb:
        errorcb(error, details)
    else:
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
                     simplecb=True, errorcb=None):
        _simple_async(callback, args, title, text, parent, errorintro, True,
                      simplecb, errorcb)

    @staticmethod
    def simple_async_noshow(callback, args, parent, errorintro,
                            simplecb=True, errorcb=None):
        _simple_async(callback, args, "", "", parent, errorintro, False,
                      simplecb, errorcb)


    def __init__(self, callback, args, title, text, parent,
                 async=True, show_progress=True, cancel_cb=None):
        """
        @async: If False, run synchronously without a separate thread
        @show_progress: If False, don't actually show a progress dialog
        @cancel_cb: Cancel callback if operation supports it.
            (cb, arg1, arg2, ...)
        """
        vmmGObjectUI.__init__(self, "vmm-progress.ui", "vmm-progress")
        self.topwin.set_transient_for(parent)

        self.async = bool(async)
        self.show_progress = bool(show_progress)

        cancel_cb = cancel_cb or (None, [])
        self.cancel_cb = cancel_cb[0]
        self.cancel_args = [self] + list(cancel_cb[1:])
        self.job_canceled = False

        self._error_info = None
        self._data = None

        self._is_pulsing = True
        self._meter = None

        args = [self] + args
        self._bg_thread = asyncJobWorker(callback, args)
        logging.debug("Creating async job for function cb=%s", callback)

        self.builder.connect_signals({
            "on_async_job_delete_event" : self._on_window_delete,
            "on_async_job_cancel_clicked" : self._on_cancel,
        })

        # UI state
        self.topwin.set_title(title)
        self.widget("pbar-text").set_text(text)
        self.widget("cancel-async-job").set_visible(bool(self.cancel_cb))


    ####################
    # Internal helpers #
    ####################

    def _cleanup(self):
        self._bg_thread = None
        self.cancel_cb = None
        self.cancel_args = None
        self._meter = None

    def _set_stage_text(self, text, canceling=False):
        # This should be thread safe, since it's only ever called from
        # pbar idle callbacks and cancel routine which is invoked from the
        # main thread
        if self.job_canceled and not canceling:
            return
        self.widget("pbar-stage").set_text(text)

    def _hide_warning(self):
        self.widget("warning-box").hide()

    def _is_thread_active(self):
        return (self._bg_thread.isAlive() or not self.async)


    ################
    # UI listeners #
    ################

    def _on_window_delete(self, ignore1=None, ignore2=None):
        thread_active = (self._bg_thread.isAlive() or not self.async)
        if not self.cancel_cb or not thread_active:
            logging.debug("User closed progress window, but thread "
                          "still running and process isn't cancellable, "
                          "ignoring.")
            return 1

        res = self.err.warn_chkbox(
                text1=_("Cancel the job?"),
                buttons=Gtk.ButtonsType.YES_NO)
        if not res:
            logging.debug("User closed progress window, but chose not "
                          "cancel operation, ignoring.")
            return 1

        self._on_cancel()

    def _on_cancel(self, ignore1=None, ignore2=None):
        if not self.cancel_cb or not self._is_thread_active():
            return

        self.cancel_cb(*self.cancel_args)
        if self.job_canceled:
            self._hide_warning()
            self._set_stage_text(_("Cancelling job..."), canceling=True)


    ##############
    # Public API #
    ##############

    def get_meter(self):
        if not self._meter:
            self._meter = vmmMeter(self._pbar_pulse,
                                   self._pbar_fraction,
                                   self._pbar_done)
        return self._meter

    def set_error(self, error, details):
        self._error_info = (error, details)

    def set_extra_data(self, data):
        self._data = data
    def get_extra_data(self):
        return self._data

    def can_cancel(self):
        return bool(self.cancel_cb)

    def show_warning(self, summary):
        # This should only be called from cancel callbacks, not a the thread
        markup = "<small>%s</small>" % summary
        self.widget("warning-box").show()
        self.widget("warning-text").set_markup(markup)

    def run(self):
        timer = GLib.timeout_add(100, self._exit_if_necessary)

        if self.show_progress:
            self.topwin.present()

        if not self.cancel_cb and self.show_progress:
            self.topwin.get_window().set_cursor(
                            Gdk.Cursor.new(Gdk.CursorType.WATCH))

        if self.async:
            self._bg_thread.start()
            Gtk.main()
        else:
            self._bg_thread.run()

        self.topwin.destroy()
        self.cleanup()
        return self._error_info or (None, None)


    ####################################################################
    # All functions after this point are called from the timer loop or #
    # the worker thread, so anything that touches Gtk needs to be      #
    # dispatches with idle_add                                         #
    ####################################################################

    def _exit_if_necessary(self):
        if not self._is_thread_active():
            if self.async:
                Gtk.main_quit()
            return False

        if not self._is_pulsing or not self.show_progress:
            return True

        self._pbar_do_pulse()
        return True

    @idle_wrapper
    def _pbar_do_pulse(self):
        if not self.builder:
            return
        self.widget("pbar").pulse()

    @idle_wrapper
    def _pbar_pulse(self, progress="", stage=None):
        self._is_pulsing = True
        if not self.builder:
            return
        self.widget("pbar").set_text(progress)
        self._set_stage_text(stage or _("Processing..."))

    @idle_wrapper
    def _pbar_fraction(self, frac, progress, stage=None):
        self._is_pulsing = False
        if not self.builder:
            return
        self._set_stage_text(stage or _("Processing..."))
        self.widget("pbar").set_text(progress)

        if frac > 1:
            frac = 1.0
        if frac < 0:
            frac = 0
        self.widget("pbar").set_fraction(frac)

    @idle_wrapper
    def _pbar_done(self, progress, stage=None):
        self._is_pulsing = False
        if not self.builder:
            return
        self._set_stage_text(stage or _("Completed"))
        self.widget("pbar").set_text(progress)
        self.widget("pbar").set_fraction(1)
