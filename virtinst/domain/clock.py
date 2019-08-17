#
# Copyright 2010, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _ClockTimer(XMLBuilder):
    XML_NAME = "timer"

    name = XMLProperty("./@name")
    present = XMLProperty("./@present", is_yesno=True)
    tickpolicy = XMLProperty("./@tickpolicy")
    track = XMLProperty("./@track")
    mode = XMLProperty("./@mode")
    frequency = XMLProperty("./@frequency", is_int=True)
    threshold = XMLProperty("./catchup/@threshold", is_int=True)
    slew = XMLProperty("./catchup/@slew", is_int=True)
    limit = XMLProperty("./catchup/@limit", is_int=True)


class DomainClock(XMLBuilder):
    XML_NAME = "clock"

    offset = XMLProperty("./@offset")
    timers = XMLChildProperty(_ClockTimer)


    ##################
    # Default config #
    ##################

    def set_defaults(self, guest):
        if not guest.os.is_hvm():
            return

        if self.offset is None:
            self.offset = guest.osinfo.get_clock()

        if self.timers:
            return
        if not guest.os.is_x86():
            return
        if not self.conn.is_qemu():
            return

        # Set clock policy that maps to qemu options:
        #   -no-hpet -no-kvm-pit-reinjection -rtc driftfix=slew
        #
        # hpet: Is unneeded and has a performance penalty
        # pit: While it has no effect on windows, it doesn't hurt and
        #   is beneficial for linux
        #
        # If libvirt/qemu supports it and using a windows VM, also
        # specify hypervclock.
        #
        # This is what has been recommended by the RH qemu guys :)
        rtc = self.timers.add_new()
        rtc.name = "rtc"
        rtc.tickpolicy = "catchup"

        pit = self.timers.add_new()
        pit.name = "pit"
        pit.tickpolicy = "delay"

        hpet = self.timers.add_new()
        hpet.name = "hpet"
        hpet.present = False

        if (guest.hyperv_supported() and
            self.conn.support.conn_hyperv_clock()):
            hyperv = self.timers.add_new()
            hyperv.name = "hypervclock"
            hyperv.present = True
