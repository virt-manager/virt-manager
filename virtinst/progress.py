#
# Copyright 2021 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
#

import sys

from . import _progresspriv


class Meter:
    """
    Meter class that hides the internals of the backend implementation
    from virtinst and friends
    """
    # Used by virt-manager subclass
    format_number = _progresspriv.format_number
    format_time = _progresspriv.format_time

    def __init__(self, quiet=False):
        self._text = None
        self._size = None
        self._total_read = 0
        if quiet:
            self._meter = _progresspriv.BaseMeter()
        else:
            self._meter = _progresspriv.TextMeter(output=sys.stdout)

    def start(self, text, size):
        self._text = text
        self._size = size
        self._total_read = 0
        self._meter.start(text, size)

    def update(self, new_total):
        self._total_read = new_total
        self._meter.update(new_total)

    def end(self):
        self._meter.end()


def make_meter(quiet):
    return Meter(quiet=quiet)


def ensure_meter(meter):
    if meter:
        return meter
    return make_meter(quiet=True)
