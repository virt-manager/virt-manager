#
# Copyright 2021 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
#

import tqdm


class _fakewriter:
    def write(self, msg):
        pass
    def flush(self):
        pass


class Meter:
    """
    Compat API that matches what urlgrabber used to provide, so our
    internal callers don't need to adapter
    """
    def __init__(self, quiet=False, bar_format=None):
        self._text = None
        self._size = None
        self._total_read = 0
        self._tqdm = None
        self._quiet = quiet
        self._bar_format = bar_format

    def start(self, text, size):
        self._text = text
        self._size = size
        self._total_read = 0

        if self._quiet:
            fileobj = _fakewriter()
        else:
            fileobj = None

        self._tqdm = tqdm.tqdm(
                desc=self._text, total=self._size,
                unit='B', unit_scale=True, unit_divisor=1024,
                miniters=0, mininterval=0.25, leave=True, file=fileobj,
                # Set bar_format to only print the text to start. We
                # don't want it to print bytes info until first data comes in
                bar_format="{desc}",
        )

    def update(self, new_total):
        update_amount = new_total - self._total_read
        self._total_read = new_total
        # Data came in, use our requested bar_format
        self._tqdm.bar_format = self._bar_format
        self._tqdm.update(update_amount)

    def end(self):
        if self._tqdm is not None:
            self._tqdm.close()
        self._tqdm = None


def make_meter(quiet):
    return Meter(quiet=quiet)


def ensure_meter(meter):
    if meter:
        return meter
    return make_meter(quiet=True)
