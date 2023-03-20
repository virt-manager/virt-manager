from virtinst import DeviceShMem

from ..lib import uiutil
from ..baseclass import vmmGObjectUI

_EDIT_SHMEM_ENUM = range(1, 3)
(
    _EDIT_SHMEM_NAME,
    _EDIT_SHMEM_SIZE,
) = _EDIT_SHMEM_ENUM


class vmmShmemDetails(vmmGObjectUI):
    __gsignals__ = {
        "changed": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    def __init__(self, vm, builder, topwin):
        super().__init__("shmem.ui", None, builder=builder, topwin=topwin)
        self.vm = vm
        self.conn = vm.conn

        self._active_edits = []

        def _e(edittype):
            def signal_cb(*args):
                self._change_cb(edittype)

            return signal_cb

        self.builder.connect_signals({
            "on_shmem_name_changed": _e(_EDIT_SHMEM_NAME),
            "on_shmem_size_changed": _e(_EDIT_SHMEM_SIZE),
        })

        self._init_ui()
        self.top_box = self.widget("top-box")

    def _cleanup(self):
        self.vm = None
        self.conn = None

    ##############
    # UI helpers #
    ##############

    def _init_ui(self):

        rows = []
        for i in (2 ** p for p in range(0, 20)):
            rows.append([i, _(str(i) + " MiB")])

        uiutil.build_simple_combo(self.widget("shmem-size"), rows, sort=False)

    def reset_state(self):
        uiutil.set_list_selection(self.widget("shmem-size"), 4)

    def set_dev(self, dev):
        self.reset_state()

        uiutil.set_list_selection(self.widget("shmem-size"), dev.size)

        self.widget("shmem-name").set_text(dev.name)

        self._active_edits = []

    def _set_values(self, dev):
        name = self.widget("shmem-name").get_text()
        size = uiutil.get_list_selection(self.widget("shmem-size"))

        if _EDIT_SHMEM_NAME in self._active_edits:
            dev.name = name
        if _EDIT_SHMEM_SIZE in self._active_edits:
            dev.size = size
        dev.size_unit = "M"
        dev.type = "ivshmem-plain"

        return dev

    def build_device(self):
        self._active_edits = _EDIT_SHMEM_ENUM[:]

        conn = self.conn.get_backend()
        dev = DeviceShMem(conn)
        self._set_values(dev)

        dev.validate()
        return dev

    def update_device(self, dev):
        newdev = DeviceShMem(dev.conn, parsexml=dev.get_xml())
        self._set_values(newdev)
        return newdev

    #############
    # Listeners #
    #############

    def _change_cb(self, edittype):
        if edittype not in self._active_edits:
            self._active_edits.append(edittype)
        self.emit("changed")
