# Copyright (C) 2006, 2013 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import threading
import traceback

from gi.repository import GLib

import libvirt

import virtinst.progress

from .baseclass import vmmGObjectUI


class _vmmMeter(virtinst.progress.Meter):
    def __init__(self, pbar_pulse, pbar_fraction, pbar_done):
        virtinst.progress.Meter.__init__(self, quiet=True)

        self._pbar_pulse = pbar_pulse
        self._pbar_fraction = pbar_fraction
        self._pbar_done = pbar_done


    #################
    # Internal APIs #
    #################

    def _write(self):
        if self._size is None:
            self._pbar_pulse("", self._text)
        else:
            fread = virtinst.progress.Meter.format_number(self._total_read)
            rtime = virtinst.progress.Meter.format_time(
                    self._meter.re.remaining_time(), True)
            frac = self._meter.re.fraction_read()
            out = "%3i%% %5sB %s ETA" % (frac * 100, fread, rtime)
            self._pbar_fraction(frac, out, self._text)


    #############################################
    # Public APIs specific to virt-manager code #
    #############################################

    def is_started(self):
        return bool(self._meter.start_time)


    ###################
    # Meter overrides #
    ###################

    def start(self, *args, **kwargs):
        super().start(*args, **kwargs)
        self._write()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._write()

    def end(self, *args, **kwargs):
        super().end(*args, **kwargs)
        self._pbar_done()


def cb_wrapper(callback, asyncjob, *args, **kwargs):
    try:
        callback(asyncjob, *args, **kwargs)
    except Exception as e:
        # If job is cancelled, don't report error to user.
        if (isinstance(e, libvirt.libvirtError) and
            asyncjob.can_cancel() and
            asyncjob.job_canceled):
            return  # pragma: no cover

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
            return  # pragma: no cover
        self.widget("pbar-stage").set_text(text)



    ################
    # UI listeners #
    ################

    def _on_cancel(self, ignore1=None, ignore2=None):
        if not self.cancel_cb or not self._bg_thread.is_alive():
            return  # pragma: no cover

        self.cancel_cb(*self.cancel_args)
        if self.job_canceled:  # pragma: no cover
            self.widget("warning-box").hide()
            self._set_stage_text(_("Cancelling job..."), canceling=True)


    ##############
    # Public API #
    ##############

    def get_meter(self):
        if not self._meter:
            self._meter = _vmmMeter(self._pbar_pulse,
                                    self._pbar_fraction,
                                    self._pbar_done)
        return self._meter

    def set_error(self, error, details):
        self._error_info = (error, details)

    def has_error(self):
        return bool(self._error_info)

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
            self._set_cursor("progress")
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
            return  # pragma: no cover
        self.widget("pbar").pulse()

    @idle_wrapper
    def _pbar_pulse(self, progress="", stage=None):
        self._is_pulsing = True
        if not self.builder:
            return  # pragma: no cover
        self.widget("pbar").set_text(progress)
        self._set_stage_text(stage or _("Processing..."))

    @idle_wrapper
    def _pbar_fraction(self, frac, progress, stage=None):
        self._is_pulsing = False
        if not self.builder:
            return  # pragma: no cover
        self._set_stage_text(stage or _("Processing..."))
        self.widget("pbar").set_text(progress)

        frac = min(frac, 1)
        frac = max(frac, 0)
        self.widget("pbar").set_fraction(frac)

    @idle_wrapper
    def _pbar_done(self):
        self._is_pulsing = False

    @idle_wrapper
    def details_enable(self):
        from gi.repository import Vte
        self._details_widget = Vte.Terminal()
        self.widget("details-box").add(self._details_widget)
        self._details_widget.set_visible(True)
        self.widget("details").set_visible(True)

    @idle_wrapper
    def details_update(self, data):
        self._details_widget.feed(data.replace("\n", "\r\n").encode())
