# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

# This file is part of urlgrabber, a high-level cross-protocol url-grabber
# Copyright 2002-2004 Michael D. Stenner, Ryan Tomayko

# This code is all straight from python-urlgrabber, which we historically
# used the system installed version of. But since the project is in
# maintenance mode upstream, and eventually we want to switch to python3,
# we are just copying this for now.


import fcntl
import struct
import sys
import termios
import time


# Code from https://mail.python.org/pipermail/python-list/2000-May/033365.html
def terminal_width(fd=1):
    """ Get the real terminal width """
    try:
        buf = 'abcdefgh'
        buf = fcntl.ioctl(fd, termios.TIOCGWINSZ, buf)
        ret = struct.unpack('hhhh', buf)[1]  # pragma: no cover
        return ret or 80  # pragma: no cover
    except IOError:
        return 80


_term_width_val = None
_term_width_last = None


def terminal_width_cached(fd=1, cache_timeout=1.000):
    """ Get the real terminal width, but cache it for a bit. """
    global _term_width_val
    global _term_width_last

    now = time.time()
    if _term_width_val is None or (now - _term_width_last) > cache_timeout:
        _term_width_val = terminal_width(fd)
        _term_width_last = now
    return _term_width_val


class TerminalLine:
    """ Help create dynamic progress bars, uses terminal_width_cached(). """

    def __init__(self, min_rest=0, beg_len=None, fd=1, cache_timeout=1.000):
        if beg_len is None:
            beg_len = min_rest
        self._min_len = min_rest
        self.llen = max(terminal_width_cached(fd, cache_timeout), beg_len)
        self._fin = False

    def __len__(self):
        """ Usable length for elements. """
        return self.llen - self._min_len

    def rest_split(self, fixed, elements=2):
        """ After a fixed length, split the rest of the line length among
            a number of different elements (default=2). """
        return max(self.llen - fixed, 0) // elements

    def add(self, element, full_len=None):
        """ If there is room left in the line, above min_len, add element.
            Note that as soon as one add fails all the rest will fail too. """

        if full_len is None:
            full_len = len(element)
        if len(self) < full_len:
            self._fin = True
        if self._fin:
            return ''

        self.llen -= len(element)
        return element

    def rest(self):
        """ Current rest of line, same as .rest_split(fixed=0, elements=1). """
        return self.llen


class BaseMeter:
    def __init__(self):
        self.update_period = 0.3  # seconds

        self.text = None
        self.size = None
        self.start_time = None
        self.last_amount_read = 0
        self.last_update_time = None
        self.re = RateEstimator()

    def start(self, text, size):
        self.text = text
        self.size = size
        assert type(size) in [int, type(None)]
        assert self.text is not None

        now = time.time()
        self.start_time = now
        self.re.start(size, now)
        self.last_amount_read = 0
        self.last_update_time = now

    def update(self, amount_read):
        # for a real gui, you probably want to override and put a call
        # to your mainloop iteration function here
        assert type(amount_read) is int

        now = time.time()
        self.last_amount_read = amount_read
        self.re.update(amount_read, now)
        if (not self.last_update_time or
                (now >= self.last_update_time + self.update_period)):
            self.last_update_time = now
            self._do_update(amount_read)

    def _do_update(self, amount_read):
        pass

    def end(self):
        self._do_end()

    def _do_end(self):
        pass


#
#       update: No size (minimal: 17 chars)
#       -----------------------------------
# <text>                          <rate> | <current size> <elapsed time>
#  8-48                          1    8  3             6 1            9 5
#
# Order: 1. <text>+<current size> (17)
#        2. +<elapsed time>       (10, total: 27)
#        3. +                     ( 5, total: 32)
#        4. +<rate>               ( 9, total: 41)
#
#       update: Size, Single file
#       -------------------------
# <text>            <pc>  <bar> <rate> | <current size> <eta time> ETA
#  8-25            1 3-4 1 6-16 1   8  3             6 1        9 1  3 1
#
# Order: 1. <text>+<current size> (17)
#        2. +<eta time>           (10, total: 27)
#        3. +ETA                  ( 5, total: 32)
#        4. +<pc>                 ( 4, total: 36)
#        5. +<rate>               ( 9, total: 45)
#        6. +<bar>                ( 7, total: 52)
#
#       update: Size, All files
#       -----------------------
# <text> <total pc> <pc>  <bar> <rate> | <current size> <eta time> ETA
#  8-22 1      5-7 1 3-4 1 6-12 1   8  3             6 1        9 1  3 1
#
# Order: 1. <text>+<current size> (17)
#        2. +<eta time>           (10, total: 27)
#        3. +ETA                  ( 5, total: 32)
#        4. +<total pc>           ( 5, total: 37)
#        4. +<pc>                 ( 4, total: 41)
#        5. +<rate>               ( 9, total: 50)
#        6. +<bar>                ( 7, total: 57)
#
#       end
#       ---
# <text>                                 | <current size> <elapsed time>
#  8-56                                  3             6 1            9 5
#
# Order: 1. <text>                ( 8)
#        2. +<current size>       ( 9, total: 17)
#        3. +<elapsed time>       (10, total: 27)
#        4. +                     ( 5, total: 32)
#


def _term_add_bar(tl, bar_max_length, pc):
    bar_len = bar_max_length * pc
    ibar_len = int(bar_len)
    progressbar = '=' * ibar_len
    if (bar_len - ibar_len) >= 0.5:
        progressbar += '-'
    return tl.add(' [%-*.*s]' % (bar_max_length, bar_max_length,
                                 progressbar))


def _term_add_end(tl, osize, size):
    if osize:  # osize should be None or >0, but that's been broken.
        if size > osize:  # Is ??? better? Really need something to say < vs >.
            return tl.add(' !!! '), True
        elif size != osize:
            return tl.add(' ... '), True
    return tl.add(' ' * 5), False


class TextMeter(BaseMeter):
    def __init__(self, output=sys.stderr):
        BaseMeter.__init__(self)
        self.output = output

    def _do_update(self, amount_read):
        etime = self.re.elapsed_time()
        fread = format_number(amount_read)

        ave_dl = format_number(self.re.average_rate())

        # Include text + ui_rate in minimal
        tl = TerminalLine(8, 8 + 1 + 8)
        # For big screens, make it more readable.
        use_hours = bool(tl.llen > 80)
        ui_size = tl.add(' | %5sB' % fread)
        if self.size is None:
            ui_time = tl.add('  %s' % format_time(etime, use_hours))
            ui_end = tl.add(' ' * 5)
            ui_rate = tl.add(' %5sB/s' % ave_dl)
            out = '%-*.*s%s%s%s%s\r' % (tl.rest(), tl.rest(), self.text,
                                        ui_rate, ui_size, ui_time, ui_end)
        else:
            rtime = self.re.remaining_time()
            frtime = format_time(rtime, use_hours)
            frac = self.re.fraction_read()

            ui_time = tl.add('  %s' % frtime)
            ui_end = tl.add(' ETA ')

            ui_pc = tl.add(' %2i%%' % (frac * 100))
            ui_rate = tl.add(' %5sB/s' % ave_dl)
            # Make text grow a bit before we start growing the bar too
            blen = 4 + tl.rest_split(8 + 8 + 4)
            ui_bar = _term_add_bar(tl, blen, frac)
            out = '\r%-*.*s%s%s%s%s%s%s\r' % (
                tl.rest(), tl.rest(), self.text,
                ui_pc, ui_bar,
                ui_rate, ui_size, ui_time, ui_end
            )

        self.output.write(out)
        self.output.flush()

    def _do_end(self):
        amount_read = self.last_amount_read
        total_size = format_number(amount_read)

        tl = TerminalLine(8)
        # For big screens, make it more readable.
        use_hours = bool(tl.llen > 80)
        ui_time = tl.add('  %s' % format_time(self.re.elapsed_time(),
                                              use_hours))
        ui_end, not_done = _term_add_end(tl, self.size, amount_read)
        if not not_done and amount_read == 0:
            # Doesn't need to print total_size
            ui_size = tl.add(' | %5s ' % ' ')
        else:
            ui_size = tl.add(' | %5sB' % total_size)

        out = '\r%-*.*s%s%s%s\n' % (tl.rest(), tl.rest(), self.text,
                                    ui_size, ui_time, ui_end)
        self.output.write(out)
        self.output.flush()


######################################################################
# support classes and functions

class RateEstimator:
    def __init__(self, timescale=5.0):
        self.timescale = timescale
        self.total = None
        self.start_time = None
        self.last_update_time = None
        self.last_amount_read = 0
        self.ave_rate = None

    def start(self, total, now):
        self.total = total
        self.start_time = now
        self.last_update_time = now
        self.last_amount_read = 0
        self.ave_rate = None

    def update(self, amount_read, now):
        if amount_read == 0 or amount_read < self.last_amount_read:
            # if we just started this file, all bets are off
            self.last_update_time = now
            self.last_amount_read = amount_read
            self.ave_rate = None
            return

        time_diff = now - self.last_update_time
        read_diff = amount_read - self.last_amount_read
        # First update, on reget is the file size
        if self.last_amount_read:
            self.last_update_time = now
            self.ave_rate = self._temporal_rolling_ave(
                time_diff, read_diff, self.ave_rate, self.timescale)
        self.last_amount_read = amount_read

    #####################################################################
    # result methods
    def average_rate(self):
        "get the average transfer rate (in bytes/second)"
        return self.ave_rate

    def elapsed_time(self):
        "the time between the start of the transfer and the most recent update"
        return self.last_update_time - self.start_time

    def remaining_time(self):
        "estimated time remaining"
        if not self.ave_rate or not self.total:
            return None
        return (self.total - self.last_amount_read) / self.ave_rate

    def fraction_read(self):
        """the fraction of the data that has been read
        (can be None for unknown transfer size)"""
        if self.total is None:
            return None
        if self.total == 0:
            return 1.0  # pragma: no cover
        return float(self.last_amount_read) / self.total

    #########################################################################
    # support methods
    def _temporal_rolling_ave(self, time_diff, read_diff, last_ave, timescale):
        """a temporal rolling average performs smooth averaging even when
        updates come at irregular intervals.  This is performed by scaling
        the "epsilon" according to the time since the last update.
        Specifically, epsilon = time_diff / timescale

        As a general rule, the average will take on a completely new value
        after 'timescale' seconds."""
        epsilon = min(time_diff / timescale, 1.0)
        return self._rolling_ave(time_diff, read_diff, last_ave, epsilon)

    def _rolling_ave(self, time_diff, read_diff, last_ave, epsilon):
        """perform a "rolling average" iteration
        a rolling average "folds" new data into an existing average with
        some weight, epsilon.  epsilon must be between 0.0 and 1.0 (inclusive)
        a value of 0.0 means only the old value (initial value) counts,
        and a value of 1.0 means only the newest value is considered."""

        try:
            recent_rate = read_diff / time_diff
        except ZeroDivisionError:  # pragma: no cover
            recent_rate = None
        if last_ave is None:
            return recent_rate
        if recent_rate is None:
            return last_ave  # pragma: no cover

        # at this point, both last_ave and recent_rate are numbers
        return epsilon * recent_rate + (1 - epsilon) * last_ave


def format_time(seconds, use_hours=0):
    if seconds is None or seconds < 0:
        if use_hours:
            return '--:--:--'
        else:
            return '--:--'
    elif seconds == float('inf'):
        return 'Infinite'  # pragma: no cover
    else:
        seconds = int(seconds)
        minutes = seconds // 60
        seconds = seconds % 60
        if use_hours:
            hours = minutes // 60
            minutes = minutes % 60
            return '%02i:%02i:%02i' % (hours, minutes, seconds)
        else:
            return '%02i:%02i' % (minutes, seconds)


def format_number(number):
    """Turn numbers into human-readable metric-like numbers"""
    symbols = ['',  # (none)
               'k',  # kilo
               'M',  # mega
               'G',  # giga
               'T',  # tera
               'P',  # peta
               'E',  # exa
               'Z',  # zetta
               'Y']  # yotta

    step = 1024.0
    thresh = 999
    depth = 0
    max_depth = len(symbols) - 1
    number = number or 0

    # we want numbers between 0 and thresh, but don't exceed the length
    # of our list.  In that event, the formatting will be screwed up,
    # but it'll still show the right number.
    while number > thresh and depth < max_depth:
        depth = depth + 1
        number = number / step

    if isinstance(number, int):
        # it's an int or a long, which means it didn't get divided,
        # which means it's already short enough
        fmt = '%i%s%s'
    elif number < 9.95:
        # must use 9.95 for proper sizing.  For example, 9.99 will be
        # rounded to 10.0 with the .1f format string (which is too long)
        fmt = '%.1f%s%s'
    else:
        fmt = '%.0f%s%s'

    return fmt % (float(number or 0), " ", symbols[depth])
