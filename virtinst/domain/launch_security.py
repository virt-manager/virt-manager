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
    kernelHashes = XMLProperty("./@kernelHashes", is_yesno=True)

    def _set_defaults_sev(self, guest):
        if not guest.os.is_q35() or not guest.is_uefi():
            raise RuntimeError(_("SEV launch security requires a Q35 UEFI machine"))

        # 'policy' is a mandatory 4-byte argument for the SEV firmware,
        # if missing, let's use 0x03 which, according to the table at
        # https://libvirt.org/formatdomain.html#launchSecurity:
        # (bit 0) - disables the debugging mode
        # (bit 1) - disables encryption key sharing across multiple guests
        if self.policy is None:
            self.policy = "0x03"

    def set_defaults(self, guest):
        if self.type == "sev":
            return self._set_defaults_sev(guest)
