#
# Copyright (C) 2011 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
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
import logging

import gobject

import libvirt

class GlobalState(object):
    def __init__(self):
        self.lock = threading.Lock()

        self.nextwatch = 1
        self.watches = []

        self.nexttimer = 1
        self.timers = []

class EventWatch(object):
    def __init__(self):
        self.watch = -1
        self.fd = -1
        self.events = 0
        self.source = 0

        self.cb = None
        self.opaque = None

    def clear(self):
        if self.source:
            gobject.source_remove(self.source)

        self.source = 0
        self.events = 0

class EventTimer(object):
    def __init__(self):
        self.timer = -1
        self.interval = -1
        self.source = 0

        self.cb = None
        self.opaque = None

    def clear(self):
        if self.source:
            gobject.source_remove(self.source)

        self.source = 0
        self.interval = -1

state = GlobalState()

def find_timer(timer):
    for t in state.timers:
        if t.timer == timer:
            return t
    return None

def find_watch(watch):
    for w in state.watches:
        if w.watch == watch:
            return w
    return None



def glib_event_handle_dispatch(source, cond, opaque):
    ignore = source
    data = opaque
    events = 0

    if cond & gobject.IO_IN:
        events |= libvirt.VIR_EVENT_HANDLE_READABLE
    if cond & gobject.IO_OUT:
        events |= libvirt.VIR_EVENT_HANDLE_WRITABLE
    if cond & gobject.IO_HUP:
        events |= libvirt.VIR_EVENT_HANDLE_HANGUP
    if cond & gobject.IO_ERR:
        events |= libvirt.VIR_EVENT_HANDLE_ERROR

    data.cb(data.watch, data.fd, events, data.opaque)
    return True

def glib_event_handle_add(fd, events, cb, opaque):
    data = EventWatch()
    cond = 0

    state.lock.acquire()
    try:
        if events & libvirt.VIR_EVENT_HANDLE_READABLE:
            cond |= gobject.IO_IN
        if events & libvirt.VIR_EVENT_HANDLE_WRITABLE:
            cond |= gobject.IO_OUT

        data.watch = state.nextwatch
        state.nextwatch += 1
        data.fd = fd
        data.events = events
        data.cb = cb
        data.opaque = opaque

        data.source = gobject.io_add_watch(data.fd,
                                           cond,
                                           glib_event_handle_dispatch,
                                           data)
        state.watches.append(data)
        return data.watch
    finally:
        state.lock.release()

def glib_event_handle_update(watch, events):
    state.lock.acquire()
    try:
        data = find_watch(watch)
        if not data:
            return

        if events:
            cond = 0
            if events == data.events:
                # Nothing to update
                return

            data.clear()

            cond |= gobject.IO_HUP
            if events & libvirt.VIR_EVENT_HANDLE_READABLE:
                cond |= gobject.IO_IN
            if events & libvirt.VIR_EVENT_HANDLE_WRITABLE:
                cond |= gobject.IO_OUT

            data.source = gobject.io_add_watch(data.fd,
                                               cond,
                                               glib_event_handle_dispatch,
                                               data)
            data.events = events

        else:
            data.clear()
    finally:
        state.lock.release()

def glib_event_handle_remove(watch):
    state.lock.acquire()
    try:
        data = find_watch(watch)
        if not data:
            return

        data.clear()
        state.watches.remove(data)
        return 0
    finally:
        state.lock.release()



def glib_event_timeout_dispatch(opaque):
    data = opaque
    data.cb(data.timer, data.opaque)

    return True

def glib_event_timeout_add(interval, cb, opaque):
    data = EventTimer()

    state.lock.acquire()
    try:
        data.timer = state.nexttimer
        state.nexttimer += 1
        data.interval = interval
        data.cb = cb
        data.opaque = opaque

        if interval >= 0:
            data.source = gobject.timeout_add(interval,
                                              glib_event_timeout_dispatch,
                                              data)

        state.timers.append(data)
        return data.timer
    finally:
        state.lock.release()

def glib_event_timeout_update(timer, interval):
    state.lock.acquire()
    try:
        data = find_timer(timer)
        if not data:
            return

        if interval >= 0:
            if data.source:
                return

            data.interval = interval
            data.source = gobject.timeout_add(data.interval,
                                              glib_event_timeout_dispatch,
                                              data)

        else:
            data.clear()
    finally:
        state.lock.release()

def glib_event_timeout_remove(timer):
    state.lock.acquire()
    try:
        data = find_timer(timer)
        if not data:
            return

        data.clear()
        state.timers.remove(data)
        return 0
    finally:
        state.lock.release()

def register_event_impl():
    if (hasattr(libvirt, "eventInvokeHandleCallback") and
        not hasattr(libvirt, "_eventInvokeHandleCallback")):
        logging.debug("Libvirt version is not new enough for our event loop "
                      "impl. Skipping registration.")
        return
    libvirt.virEventRegisterImpl(glib_event_handle_add,
                                 glib_event_handle_update,
                                 glib_event_handle_remove,
                                 glib_event_timeout_add,
                                 glib_event_timeout_update,
                                 glib_event_timeout_remove)
