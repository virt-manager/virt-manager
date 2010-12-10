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

import urlgrabber.progress as progress

class vmmCreateMeter(progress.BaseMeter):
    def __init__(self, asyncjob):
        # progress meter has to run asynchronously, so pass in the
        # async job to call back to with progress info
        progress.BaseMeter.__init__(self)
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
        fread = progress.format_number(amount_read)
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
        fread = progress.format_number(amount_read)
        if self.size is None:
            out = "    %5sB" % (fread)
            self.asyncjob.pulse_pbar(out, text)
        else:
            out = "%3i%% %5sB" % (100, fread)
            self.asyncjob.set_pbar_done(out, text)
        self.started = False
