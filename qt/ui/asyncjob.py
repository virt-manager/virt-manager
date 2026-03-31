import threading
import traceback

from PyQt6.QtCore import QThread, Qt
from PyQt6.QtWidgets import QProgressDialog, QLabel, QVBoxLayout, QPushButton

import libvirt

from virtinst import progress as virtinst_progress

from .lib.i18n import _


class _vmmMeter(virtinst_progress.Meter):
    def __init__(self, pbar_pulse, pbar_fraction, pbar_done):
        virtinst_progress.Meter.__init__(self, quiet=True)

        self._pbar_pulse = pbar_pulse
        self._pbar_fraction = pbar_fraction
        self._pbar_done = pbar_done

    def _write(self):
        if self._size is None:
            self._pbar_pulse("", self._text)
        else:
            fread = virtinst_progress.Meter.format_number(self._total_read)
            rtime = virtinst_progress.Meter.format_time(self._meter.re.remaining_time(), True)
            frac = self._meter.re.fraction_read()
            out = "%3i%% %5sB %s ETA" % (frac * 100, fread, rtime)
            self._pbar_fraction(frac, out, self._text)

    def is_started(self):
        return bool(self._meter.start_time)

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
        if isinstance(e, libvirt.libvirtError) and asyncjob.can_cancel() and asyncjob.job_canceled:
            return
        asyncjob.set_error(str(e), "".join(traceback.format_exc()))


def _simple_async_done_cb(error, details, parent, errorintro, errorcb, finish_cb):
    if error:
        if errorcb:
            errorcb(error, details)
        else:
            error = errorintro + ": " + error
            parent.err.show_err(error, details=details)
    if finish_cb:
        finish_cb()


def _simple_async(callback, args, parent, title, text, errorintro, show_progress, simplecb, errorcb, finish_cb):
    docb = callback
    if simplecb:
        def tmpcb(job, *args, **kwargs):
            callback(*args, **kwargs)
        docb = tmpcb

    asyncjob = vmmAsyncJob(
        docb,
        args,
        _simple_async_done_cb,
        (parent, errorintro, errorcb, finish_cb),
        title,
        text,
        parent,
        show_progress=show_progress,
    )
    asyncjob.run()


class _AsyncJobThread(QThread):
    def __init__(self, callback, asyncjob, args):
        super().__init__()
        self._callback = callback
        self._asyncjob = asyncjob
        self._args = args

    def run(self):
        cb_wrapper(self._callback, self._asyncjob, *self._args)


class vmmAsyncJob:
    @staticmethod
    def simple_async(callback, args, parent, title, text, errorintro, simplecb=True, errorcb=None, finish_cb=None):
        _simple_async(callback, args, parent, title, text, errorintro, True, simplecb, errorcb, finish_cb)

    @staticmethod
    def simple_async_noshow(callback, args, parent, errorintro, simplecb=True, errorcb=None, finish_cb=None):
        _simple_async(callback, args, parent, "", "", errorintro, False, simplecb, errorcb, finish_cb)

    def __init__(self, callback, args, finish_cb, finish_args, title, text, parent, show_progress=True, cancel_cb=None):
        self._callback = callback
        self._args = args
        self._finish_cb = finish_cb
        self._finish_args = finish_args or ()
        self._title = title
        self._text = text
        self._parent = parent
        self._show_progress = bool(show_progress)
        
        self.cancel_cb = cancel_cb[0] if cancel_cb else None
        self.cancel_args = [self] + list(cancel_cb[1] if cancel_cb else [])
        self.job_canceled = False
        
        self._error_info = None
        self._meter = None
        self._thread = None
        self._dialog = None
        
        self._is_pulsing = True

    def get_meter(self):
        if not self._meter:
            self._meter = _vmmMeter(self._pbar_pulse, self._pbar_fraction, self._pbar_done)
        return self._meter

    def set_error(self, error, details):
        self._error_info = (error, details)

    def has_error(self):
        return bool(self._error_info)

    def can_cancel(self):
        return bool(self.cancel_cb)

    def show_warning(self, summary):
        if self._dialog:
            self._dialog.setLabelText(_("Warning: %s") % summary)

    def _pbar_pulse(self, progress="", stage=None):
        self._is_pulsing = True
        if self._dialog:
            self._dialog.setLabelText(stage or progress or _("Processing..."))

    def _pbar_fraction(self, frac, progress, stage=None):
        self._is_pulsing = False
        if self._dialog:
            self._dialog.setLabelText(stage or _("Processing..."))
            self._dialog.setLabelText(progress)
            frac = min(frac, 1)
            frac = max(frac, 0)
            self._dialog.setValue(int(frac * 100))

    def _pbar_done(self):
        self._is_pulsing = False

    def _on_cancel(self):
        if not self.cancel_cb or not self._thread.isFinished():
            return
        self.cancel_cb(*self.cancel_args)
        if self.job_canceled:
            self._dialog.setLabelText(_("Cancelling job..."))

    def _thread_finished(self):
        if self._dialog:
            self._dialog.hide()
            self._dialog.deleteLater()
            self._dialog = None

        error = None
        details = None
        if self._error_info:
            error, details = self._error_info
        self._finish_cb(error, details, *self._finish_args)

    def run(self):
        if self._show_progress:
            self._dialog = QProgressDialog(self._text, _("Cancel") if self.cancel_cb else None, 0, 100, self._parent)
            self._dialog.setWindowTitle(self._title)
            self._dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self._dialog.setAutoClose(True)
            self._dialog.canceled.connect(self._on_cancel)
            self._dialog.show()
        else:
            self._dialog = None

        self._thread = _AsyncJobThread(self._callback, self, self._args)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()
