# Copyright (C) 2018 VMware, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..lib import uiutil
from ..baseclass import vmmGObjectUI


class vmmVsockDetails(vmmGObjectUI):
    __gsignals__ = {
        "changed-auto-cid": (vmmGObjectUI.RUN_FIRST, None, []),
        "changed-cid": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    MIN_GUEST_CID = 3

    def __init__(self, vm, builder, topwin):
        super().__init__("vsockdetails.ui", None,
                         builder=builder, topwin=topwin)
        self.vm = vm
        self.conn = vm.conn

        self.builder.connect_signals({
            "on_vsock_auto_toggled": self._vsock_auto_toggled,
            "on_vsock_cid_changed": lambda ignore: self.emit("changed-cid"),
        })

        self.top_box = self.widget("vsock-box")

    def _cleanup(self):
        self.vm = None
        self.conn = None


    ##############
    # Public API #
    ##############

    def reset_state(self):
        self.widget("vsock-auto").set_active(True)
        self.widget("vsock-cid").set_value(self.MIN_GUEST_CID)
        self.widget("vsock-cid").set_visible(False)

    def get_values(self):
        auto_cid = self.widget("vsock-auto").get_active()
        cid = uiutil.spin_get_helper(self.widget("vsock-cid"))
        return auto_cid, cid

    def set_dev(self, dev):
        self.reset_state()

        is_auto = bool(dev.auto_cid)
        cid = int(dev.cid or self.MIN_GUEST_CID)

        label = self.widget("vsock-auto").get_label().split(" (")[0]
        if is_auto and self.vm.is_active():
            label += " (%s %s)" % (_("CID"), cid)
        self.widget("vsock-auto").set_label(label)

        self.widget("vsock-auto").set_active(is_auto)
        self.widget("vsock-cid").set_value(cid)
        self.widget("vsock-cid").set_visible(not is_auto)


    #############
    # Listeners #
    #############

    def _vsock_auto_toggled(self, ignore):
        is_auto = self.widget("vsock-auto").get_active()
        self.widget("vsock-cid").set_visible(not is_auto)
        self.emit("changed-auto-cid")
