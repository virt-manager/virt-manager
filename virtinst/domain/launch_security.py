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
    guestVisibleWorkarounds = XMLProperty("./guestVisibleWorkarounds")
    idBlock = XMLProperty("./idBlock")
    idAuth = XMLProperty("./idAuth")
    hostData = XMLProperty("./hostData")
    kernelHashes = XMLProperty("./@kernelHashes", is_yesno=True)
    authorKey = XMLProperty("./@authorKey", is_yesno=True)
    vcek = XMLProperty("./@vcek", is_yesno=True)

    def _set_defaults_sev(self, guest):
        if not guest.os.is_q35() or not guest.is_uefi():
            raise RuntimeError(_("SEV launch security requires a Q35 UEFI machine"))

        # The 'policy' is a mandatory 4-byte argument for the SEV firmware.
        # If missing, we use 0x03 for the original SEV implementation and
        # 0x07 for SEV-ES.
        # Reference: https://libvirt.org/formatdomain.html#launch-security
        if self.policy is None:
            domcaps = guest.lookup_domcaps()
            self.policy = "0x03"
            if domcaps.supports_sev_launch_security(check_es=True):
                self.policy = "0x07"

    def _set_defaults_sev_snp(self, guest):
        if not guest.os.is_q35() or not guest.is_uefi():
            raise RuntimeError(_("SEV-SNP launch security requires a Q35 UEFI machine"))

    def set_defaults(self, guest):
        if self.type == "sev":
            return self._set_defaults_sev(guest)
        elif self.type == "sev-snp":
            return self._set_defaults_sev_snp(guest)
