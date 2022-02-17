#
# Copyright 2011, 2013 Red Hat, Inc.
# Copyright 2013 IBM Corporation
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _ActivePCRBanks(XMLBuilder):
    XML_NAME = "active_pcr_banks"

    sha1 = XMLProperty("./sha1", is_bool=True)
    sha256 = XMLProperty("./sha256", is_bool=True)
    sha384 = XMLProperty("./sha384", is_bool=True)
    sha512 = XMLProperty("./sha512", is_bool=True)


class DeviceTpm(Device):
    XML_NAME = "tpm"

    VERSION_1_2 = "1.2"
    VERSION_2_0 = "2.0"
    VERSIONS = [VERSION_1_2, VERSION_2_0]

    TYPE_PASSTHROUGH = "passthrough"
    TYPE_EMULATOR = "emulator"
    TYPES = [TYPE_PASSTHROUGH, TYPE_EMULATOR]

    MODEL_TIS = "tpm-tis"
    MODEL_CRB = "tpm-crb"
    MODEL_SPAPR = "tpm-spapr"
    MODELS = [MODEL_TIS, MODEL_CRB, MODEL_SPAPR]

    type = XMLProperty("./backend/@type")
    version = XMLProperty("./backend/@version")
    model = XMLProperty("./@model")
    device_path = XMLProperty("./backend/device/@path")
    encryption_secret = XMLProperty("./backend/encryption/@secret")
    persistent_state = XMLProperty(
            "./backend/@persistent_state", is_yesno=True)

    active_pcr_banks = XMLChildProperty(_ActivePCRBanks, is_single=True)


    ##################
    # Default config #
    ##################

    @staticmethod
    def default_model(guest):
        domcaps = guest.lookup_domcaps()

        if not domcaps.devices.tpm.present and not guest.os.is_pseries():
            # Preserve the old default when domcaps is old
            return DeviceTpm.MODEL_CRB
        if domcaps.devices.tpm.get_enum("model").has_value(DeviceTpm.MODEL_CRB):
            # CRB is the modern version, and it implies version 2.0
            return DeviceTpm.MODEL_CRB

        # Let libvirt decide so we don't need to duplicate its arch logic
        return None

    def set_defaults(self, guest):
        if self.device_path and not self.type:
            self.type = self.TYPE_PASSTHROUGH
        if not self.type:
            # Libvirt requires a backend type to be specified. 'emulator'
            # may not be available if swtpm is not installed, but trying to
            # fallback to 'passthrough' in that case isn't really workable.
            # Instead we specify it unconditionally and let libvirt error.
            self.type = self.TYPE_EMULATOR

        # passthrough and model and version are all interconnected, so
        # don't try to set a default model if other bits are set
        if (self.type == self.TYPE_EMULATOR and
            not self.model and not self.version):
            self.model = self.default_model(guest)
