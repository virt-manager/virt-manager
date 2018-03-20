#
# Copyright 2010, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _ClockTimer(XMLBuilder):
    _XML_ROOT_NAME = "timer"

    name = XMLProperty("./@name")
    present = XMLProperty("./@present", is_yesno=True)
    tickpolicy = XMLProperty("./@tickpolicy")


class DomainClock(XMLBuilder):
    _XML_ROOT_NAME = "clock"

    TIMER_NAMES = ["platform", "pit", "rtc", "hpet", "tsc", "kvmclock",
        "hypervclock"]

    offset = XMLProperty("./@offset")
    timers = XMLChildProperty(_ClockTimer)
