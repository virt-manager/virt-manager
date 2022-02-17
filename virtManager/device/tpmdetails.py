# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from virtinst import DeviceTpm

from ..lib import uiutil
from ..baseclass import vmmGObjectUI


def _tpm_pretty_model(val):
    labels = {
        DeviceTpm.MODEL_TIS: _("TIS"),
        DeviceTpm.MODEL_CRB: _("CRB"),
        DeviceTpm.MODEL_SPAPR: _("SPAPR"),
    }
    return labels.get(val, val)


_EDIT_TPM_ENUM = range(1, 5)
(
    _EDIT_TPM_TYPE,
    _EDIT_TPM_DEVICE_PATH,
    _EDIT_TPM_MODEL,
    _EDIT_TPM_VERSION,
) = _EDIT_TPM_ENUM


class vmmTPMDetails(vmmGObjectUI):
    __gsignals__ = {
        "changed": (vmmGObjectUI.RUN_FIRST, None, []),
    }

    def __init__(self, vm, builder, topwin):
        super().__init__("tpmdetails.ui", None,
                         builder=builder, topwin=topwin)
        self.vm = vm
        self.conn = vm.conn

        self._active_edits = []

        def _e(edittype):
            def signal_cb(*args):
                self._change_cb(edittype)
            return signal_cb

        self.builder.connect_signals({
            "on_tpm_type_changed": _e(_EDIT_TPM_TYPE),
            "on_tpm_device_path_changed": _e(_EDIT_TPM_DEVICE_PATH),
            "on_tpm_model_changed": _e(_EDIT_TPM_MODEL),
            "on_tpm_version_changed": _e(_EDIT_TPM_VERSION),
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
        domcaps = self.vm.get_domain_capabilities()

        # We could check domcaps for this, but emulated is really the
        # preferred default here, so just let it fail
        rows = [
            [DeviceTpm.TYPE_EMULATOR, _("Emulated")],
            [DeviceTpm.TYPE_PASSTHROUGH, _("Passthrough")],
        ]
        uiutil.build_simple_combo(self.widget("tpm-type"), rows, sort=False)

        rows = [[None, _("Hypervisor default")]]
        if domcaps.devices.tpm.present:
            values = domcaps.devices.tpm.get_enum("model").get_values()
        else:
            values = [DeviceTpm.MODEL_CRB, DeviceTpm.MODEL_TIS]
        for v in values:
            rows.append([v, _tpm_pretty_model(v)])

        uiutil.build_simple_combo(self.widget("tpm-model"), rows, sort=False)

        rows = [
            [None, _("Hypervisor default")],
            [DeviceTpm.VERSION_2_0, DeviceTpm.VERSION_2_0],
            [DeviceTpm.VERSION_1_2, DeviceTpm.VERSION_1_2],
        ]
        uiutil.build_simple_combo(self.widget("tpm-version"), rows, sort=False)


    def _sync_ui(self):
        devtype = uiutil.get_list_selection(self.widget("tpm-type"))

        uiutil.set_grid_row_visible(self.widget("tpm-device-path"),
                devtype == DeviceTpm.TYPE_PASSTHROUGH)
        uiutil.set_grid_row_visible(self.widget("tpm-version"),
                devtype == DeviceTpm.TYPE_EMULATOR)


    ##################
    # Public UI APIs #
    ##################

    def reset_state(self):
        self.widget("tpm-device-path").set_text("/dev/tpm0")
        uiutil.set_list_selection(
                self.widget("tpm-type"), DeviceTpm.TYPE_EMULATOR)

        default_model = DeviceTpm.default_model(self.vm.xmlobj)
        uiutil.set_list_selection(
                self.widget("tpm-model"), default_model)
        uiutil.set_list_selection(
                self.widget("tpm-version"), None)


    def set_dev(self, dev):
        self.reset_state()

        uiutil.set_list_selection(
                self.widget("tpm-type"), dev.type)
        uiutil.set_list_selection(
                self.widget("tpm-model"), dev.model)
        uiutil.set_list_selection(
                self.widget("tpm-version"), dev.version)
        self.widget("tpm-device-path").set_text(dev.device_path or "")

        self._active_edits = []


    ########################
    # Device building APIs #
    ########################

    def _set_values(self, dev):
        typ = uiutil.get_list_selection(self.widget("tpm-type"))
        model = uiutil.get_list_selection(self.widget("tpm-model"))
        device_path = self.widget("tpm-device-path").get_text()
        version = uiutil.get_list_selection(self.widget("tpm-version"))

        if not self.widget("tpm-device-path").get_visible():
            device_path = None
        if not self.widget("tpm-version").get_visible():
            version = None

        if _EDIT_TPM_TYPE in self._active_edits:
            dev.type = typ
        if _EDIT_TPM_MODEL in self._active_edits:
            dev.model = model
        if _EDIT_TPM_DEVICE_PATH in self._active_edits:
            dev.device_path = device_path
        if _EDIT_TPM_VERSION in self._active_edits:
            dev.version = version

        return dev

    def build_device(self):
        self._active_edits = _EDIT_TPM_ENUM[:]

        conn = self.conn.get_backend()
        dev = DeviceTpm(conn)
        self._set_values(dev)

        dev.validate()
        return dev

    def update_device(self, dev):
        newdev = DeviceTpm(dev.conn, parsexml=dev.get_xml())
        self._set_values(newdev)
        return newdev


    #############
    # Listeners #
    #############

    def _change_cb(self, edittype):
        self._sync_ui()
        if edittype not in self._active_edits:
            self._active_edits.append(edittype)
        self.emit("changed")
