from ..xmlbuilder import XMLBuilder, XMLProperty


class DomainLaunchSecurity(XMLBuilder):
    """
    Class for generating <launchSecurity> XML element
    """

    XML_NAME = "launchSecurity"
    _XML_PROP_ORDER = ["type", "cbitpos", "reducedPhysBits", "policy",
            "session", "dhCert"]

    type = XMLProperty("./@type")
    cbitpos = XMLProperty("./cbitpos", is_int=True)
    reducedPhysBits = XMLProperty("./reducedPhysBits", is_int=True)
    policy = XMLProperty("./policy")
    session = XMLProperty("./session")
    dhCert = XMLProperty("./dhCert")

    def is_sev(self):
        return self.type == "sev"

    def validate(self):
        if not self.type:
            raise RuntimeError(_("Missing mandatory attribute 'type'"))

    def _set_defaults_sev(self, guest):
        # SeaBIOS doesn't have support for SEV. Q35 defaults to virtio 1.0,
        # which we need so let's not go through the 'virtio-transitional'
        # exercise for pc-i440fx to make SEV work, AMD recommends Q35 anyway
        # NOTE: at some point both of these platform checks should be put in
        # validate(), once that accepts the 'guest' instance
        if guest.os.is_q35() is False or guest.os.loader_type != "pflash":
            raise RuntimeError(_("SEV launch security requires a Q35 UEFI machine"))

        # libvirt or QEMU might not support SEV
        domcaps = guest.lookup_domcaps()
        if not domcaps.supports_sev_launch_security():
            raise RuntimeError(_("SEV launch security is not supported on this platform"))

        # 'policy' is a mandatory 4-byte argument for the SEV firmware,
        # if missing, let's use 0x03 which, according to the table at
        # https://libvirt.org/formatdomain.html#launchSecurity:
        # (bit 0) - disables the debugging mode
        # (bit 1) - disables encryption key sharing across multiple guests
        if self.policy is None:
            self.policy = "0x03"

        if self.cbitpos is None:
            self.cbitpos = domcaps.features.sev.cbitpos
        if self.reducedPhysBits is None:
            self.reducedPhysBits = domcaps.features.sev.reducedPhysBits

    def set_defaults(self, guest):
        if self.is_sev():
            return self._set_defaults_sev(guest)
