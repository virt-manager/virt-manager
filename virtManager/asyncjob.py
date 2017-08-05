#
# Copyright (C) 2006, 2013 Red Hat, Inc.
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

import threading
import traceback

from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Vte

import libvirt

import virtinst.progress

from .baseclass import vmmGObjectUI


class vmmMeter(virtinst.progress.BaseMeter):
    def __init__(self, cb_pulse, cb_fraction, cb_done):
        virtinst.progress.BaseMeter.__init__(self)
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
        fread = virtinst.progress.format_number(amount_read)
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
        fread = virtinst.progress.format_number(amount_read)
        if self.size is None:
            out = "    %5sB" % (fread)
            self._vmm_pulse(out, text)
        else:
            out = "%3i%% %5sB" % (100, fread)
            self._vmm_done(out, text)
        self.started = False


def cb_wrapper(callback, asyncjob, *args, **kwargs):
    try:
        callback(asyncjob, *args, **kwargs)
    except Exception as e:
        # If job is cancelled, don't report error to user.
        if (isinstance(e, libvirt.libvirtError) and
            asyncjob.can_cancel() and
            asyncjob.job_canceled):
            return

        asyncjob.set_error(str(e), "".join(traceback.format_exc()))


def _simple_async_done_cb(error, details,
                          parent, errorintro, errorcb, finish_cb):
    if error:
        if errorcb:
            errorcb(error, details)
        else:
            error = errorintro + ": " + error
            parent.err.show_err(error,
                                details=details)

    if finish_cb:
        finish_cb()


def _simple_async(callback, args, parent, title, text, errorintro,
                  show_progress, simplecb, errorcb, finish_cb):
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

    asyncjob = vmmAsyncJob(docb, args,
                           _simple_async_done_cb,
                           (parent, errorintro, errorcb, finish_cb),
                           title, text, parent.topwin,
                           show_progress=show_progress)
    asyncjob.run()


def idle_wrapper(fn):
    def wrapped(self, *args, **kwargs):
        return self.idle_add(fn, self, *args, **kwargs)
    return wrapped


class vmmAsyncJob(vmmGObjectUI):
    """
    Displays a progress bar while executing the "callback" method.
    """
    @staticmethod
    def simple_async(callback, args, parent, title, text, errorintro,
                     simplecb=True, errorcb=None, finish_cb=None):
        _simple_async(callback, args, parent,
                      title, text, errorintro, True,
                      simplecb, errorcb, finish_cb)

    @staticmethod
    def simple_async_noshow(callback, args, parent, errorintro,
                            simplecb=True, errorcb=None, finish_cb=None):
        _simple_async(callback, args, parent,
                      "", "", errorintro, False,
                      simplecb, errorcb, finish_cb)


    def __init__(self,
                 callback, args, finish_cb, finish_args,
                 title, text, parent,
                 show_progress=True, cancel_cb=None):
        """
        @show_progress: If False, don't actually show a progress dialog
        @cancel_cb: Cancel callback if operation supports it.
            (cb, arg1, arg2, ...)
        """
        vmmGObjectUI.__init__(self, "asyncjob.ui", "vmm-progress")
        self.topwin.set_transient_for(parent)

        self.show_progress = bool(show_progress)

        cancel_cb = cancel_cb or (None, [])
        self.cancel_cb = cancel_cb[0]
        self.cancel_args = [self] + list(cancel_cb[1:])
        self.job_canceled = False
        self._finish_cb = finish_cb
        self._finish_args = finish_args or ()

        self._timer = None
        self._error_info = None
        self._data = None

        self._details_widget = None
        self._details_update_cb = None

        self._is_pulsing = True
        self._meter = None

        self._bg_thread = threading.Thread(target=cb_wrapper,
                                           args=[callback, self] + args)
        self._bg_thread.daemon = True

        self.builder.connect_signals({
            "on_async_job_delete_event": self._on_window_delete,
            "on_async_job_cancel_clicked": self._on_cancel,
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


    ################
    # UI listeners #
    ################

    def _on_window_delete(self, ignore1=None, ignore2=None):
        return 1

    def _on_cancel(self, ignore1=None, ignore2=None):
        if not self.cancel_cb or not self._bg_thread.is_alive():
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

    def has_error(self):
        return bool(self._error_info)

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

    def _thread_finished(self):
        GLib.source_remove(self._timer)
        self.topwin.destroy()
        self.cleanup()

        error = None
        details = None
        if self._error_info:
            # pylint: disable=unpacking-non-sequence
            error, details = self._error_info
        self._finish_cb(error, details, *self._finish_args)

    def run(self):
        self._timer = GLib.timeout_add(100, self._exit_if_necessary)

        if self.show_progress:
            self.topwin.present()

        if not self.cancel_cb and self.show_progress:
            gdk_window = self.topwin.get_window()
            gdk_window.set_cursor(
                Gdk.Cursor.new_from_name(gdk_window.get_display(), "progress"))
        self._bg_thread.start()


    ####################################################################
    # All functions after this point are called from the timer loop or #
    # the worker thread, so anything that touches Gtk needs to be      #
    # dispatches with idle_add                                         #
    ####################################################################

    def _exit_if_necessary(self):
        if not self._bg_thread.is_alive():
            self._thread_finished()
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

    @idle_wrapper
    def details_enable(self):
        self._details_widget = Vte.Terminal()
        self.widget("details-box").add(self._details_widget)
        self._details_widget.set_visible(True)
        self.widget("details").set_visible(True)

    @idle_wrapper
    def details_update(self, data):
        self._details_widget.feed(data.replace("\n", "\r\n").encode())
