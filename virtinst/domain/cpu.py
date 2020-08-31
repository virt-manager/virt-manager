#
# Copyright 2010, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..logger import log

from ..xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty
from .. import xmlutil


class _CPUCellSibling(XMLBuilder):
    """
    Class for generating <distances> <sibling> nodes
    """
    XML_NAME = "sibling"
    _XML_PROP_ORDER = ["id", "value"]

    id = XMLProperty("./@id", is_int=True)
    value = XMLProperty("./@value", is_int=True)


class _CPUCell(XMLBuilder):
    """
    Class for generating <cpu><numa> child <cell> XML
    """
    XML_NAME = "cell"
    _XML_PROP_ORDER = ["id", "cpus", "memory", "memAccess", "discard"]

    id = XMLProperty("./@id", is_int=True)
    cpus = XMLProperty("./@cpus")
    memory = XMLProperty("./@memory", is_int=True)
    memAccess = XMLProperty("./@memAccess")
    discard = XMLProperty("./@discard")
    siblings = XMLChildProperty(_CPUCellSibling, relative_xpath="./distances")


class _CPUCache(XMLBuilder):
    """
    Class for generating <cpu> child <cache> XML
    """

    XML_NAME = "cache"
    _XML_PROP_ORDER = ["mode", "level"]

    mode = XMLProperty("./@mode")
    level = XMLProperty("./@level", is_int=True)


class _CPUFeature(XMLBuilder):
    """
    Class for generating <cpu> child <feature> XML
    """
    XML_NAME = "feature"
    _XML_PROP_ORDER = ["policy", "name"]

    name = XMLProperty("./@name")
    policy = XMLProperty("./@policy")


class _CPUTopology(XMLBuilder):
    """
    Class for generating <cpu> <topology> XML
    """
    XML_NAME = "topology"
    _XML_PROP_ORDER = ["sockets", "cores", "threads"]

    sockets = XMLProperty("./@sockets", is_int=True)
    cores = XMLProperty("./@cores", is_int=True)
    threads = XMLProperty("./@threads", is_int=True)

    def set_defaults_from_vcpus(self, vcpus):
        if not self.sockets:
            if not self.cores:
                self.sockets = vcpus // self.threads
            else:
                self.sockets = vcpus // self.cores

        if not self.cores:
            if not self.threads:
                self.cores = vcpus // self.sockets
            else:
                self.cores = vcpus // (self.sockets * self.threads)

        if not self.threads:
            self.threads = vcpus // (self.sockets * self.cores)

        return


class DomainCpu(XMLBuilder):
    """
    Class for generating <cpu> XML
    """
    XML_NAME = "cpu"
    _XML_PROP_ORDER = ["mode", "match", "model", "vendor",
            "topology", "features"]

    secure = True

    special_mode_was_set = False
    # These values are exposed on the command line, so are stable API
    SPECIAL_MODE_HOST_MODEL_ONLY = "host-model-only"
    SPECIAL_MODE_HV_DEFAULT = "hv-default"
    SPECIAL_MODE_HOST_COPY = "host-copy"
    SPECIAL_MODE_HOST_MODEL = "host-model"
    SPECIAL_MODE_HOST_PASSTHROUGH = "host-passthrough"
    SPECIAL_MODE_CLEAR = "clear"
    SPECIAL_MODE_APP_DEFAULT = "default"
    SPECIAL_MODES = [SPECIAL_MODE_HOST_MODEL_ONLY, SPECIAL_MODE_HV_DEFAULT,
                     SPECIAL_MODE_HOST_COPY, SPECIAL_MODE_HOST_MODEL,
                     SPECIAL_MODE_HOST_PASSTHROUGH, SPECIAL_MODE_CLEAR,
                     SPECIAL_MODE_APP_DEFAULT]
    def set_special_mode(self, guest, val):
        if val == self.SPECIAL_MODE_APP_DEFAULT:
            # If libvirt is new enough to support reliable mode=host-model
            # then use it, otherwise use previous default HOST_MODEL_ONLY
            domcaps = guest.lookup_domcaps()
            val = self.SPECIAL_MODE_HOST_MODEL_ONLY
            if domcaps.supports_safe_host_model():
                val = self.SPECIAL_MODE_HOST_MODEL

        if (val == self.SPECIAL_MODE_HOST_MODEL or
            val == self.SPECIAL_MODE_HOST_PASSTHROUGH):
            self.model = None
            self.vendor = None
            self.model_fallback = None
            for f in self.features:
                self.remove_child(f)
            self.mode = val
        elif val == self.SPECIAL_MODE_HOST_COPY:
            self.copy_host_cpu(guest)
        elif (val == self.SPECIAL_MODE_HV_DEFAULT or
              val == self.SPECIAL_MODE_CLEAR):
            self.clear()
        elif val == self.SPECIAL_MODE_HOST_MODEL_ONLY:
            if self.conn.caps.host.cpu.model:
                self.clear()
                self.set_model(guest, self.conn.caps.host.cpu.model)
        else:
            raise xmlutil.DevError("unknown special cpu mode '%s'" % val)

        self.special_mode_was_set = True

    def _add_security_features(self, guest):
        domcaps = guest.lookup_domcaps()
        for feature in domcaps.get_cpu_security_features():
            exists = False
            for f in self.features:
                if f.name == feature:
                    exists = True
                    break
            if not exists:
                self.add_feature(feature)

    def check_security_features(self, guest):
        """
        Since 'secure' property is not exported into the domain XML
        we might need to refresh its state.
        """
        domcaps = guest.lookup_domcaps()
        features = domcaps.get_cpu_security_features()
        if len(features) == 0:
            self.secure = False
            return

        guestFeatures = [f.name for f in self.features if f.policy == "require"]
        if self.model:
            if self.model.endswith("IBRS"):
                guestFeatures.append("spec-ctrl")
            if self.model.endswith("IBPB"):
                guestFeatures.append("ibpb")

        self.secure = set(features) <= set(guestFeatures)

    def _remove_security_features(self, guest):
        domcaps = guest.lookup_domcaps()
        for feature in domcaps.get_cpu_security_features():
            for f in self.features:
                if f.name == feature and f.policy == "require":
                    self.remove_child(f)
                    break

    def set_model(self, guest, val):
        log.debug("setting cpu model %s", val)
        if val:
            self.mode = "custom"
            if not self.match:
                self.match = "exact"
            if self.secure:
                self._add_security_features(guest)
            else:
                self._remove_security_features(guest)
        self.model = val

    def add_feature(self, name, policy="require"):
        feature = self.features.add_new()
        feature.name = name
        feature.policy = policy
    features = XMLChildProperty(_CPUFeature)

    cells = XMLChildProperty(_CPUCell, relative_xpath="./numa")
    cache = XMLChildProperty(_CPUCache, is_single=True)

    def copy_host_cpu(self, guest):
        """
        Try to manually mimic host-model, copying all the info
        preferably out of domcapabilities, but capabilities as fallback.
        """
        domcaps = guest.lookup_domcaps()
        if domcaps.supports_safe_host_model():
            log.debug("Using domcaps for host-copy")
            cpu = domcaps.cpu.get_mode("host-model")
            model = cpu.models[0].model
            fallback = cpu.models[0].fallback
        else:
            cpu = self.conn.caps.host.cpu
            model = cpu.model
            fallback = None
            if not model:  # pragma: no cover
                raise ValueError(_("No host CPU reported in capabilities"))

        self.mode = "custom"
        self.match = "exact"
        self.set_model(guest, model)
        if fallback:
            self.model_fallback = fallback
        self.vendor = cpu.vendor

        for feature in self.features:
            self.remove_child(feature)
        for feature in cpu.features:
            policy = getattr(feature, "policy", "require")
            self.add_feature(feature.name, policy)

    def vcpus_from_topology(self):
        """
        Determine the CPU count represented by topology, or 1 if
        no topology is set
        """
        return ((self.topology.sockets or 1) *
                (self.topology.cores or 1) *
                (self.topology.threads or 1))

    def has_topology(self):
        """
        Return True if any topology info is set
        """
        return bool(self.topology.get_xml())

    def set_topology_defaults(self, vcpus):
        """
        Fill in unset topology values, using the passed vcpus count.
        Will not set topology from scratch, this just fills in missing
        topology values.
        """
        if not self.has_topology():
            return
        self.topology.set_defaults_from_vcpus(vcpus)


    ##################
    # XML properties #
    ##################

    topology = XMLChildProperty(_CPUTopology, is_single=True)

    model = XMLProperty("./model")
    model_fallback = XMLProperty("./model/@fallback")

    match = XMLProperty("./@match")
    vendor = XMLProperty("./vendor")
    mode = XMLProperty("./@mode")


    ##################
    # Default config #
    ##################

    def _validate_default_host_model_only(self, guest):
        # It's possible that the value HOST_MODEL_ONLY gets from
        # <capabilities> is not actually supported by qemu/kvm
        # combo which will be reported in <domainCapabilities>
        if not self.model:
            return  # pragma: no cover

        domcaps = guest.lookup_domcaps()
        domcaps_mode = domcaps.cpu.get_mode("custom")
        if not domcaps_mode:
            return  # pragma: no cover

        cpu_model = domcaps_mode.get_model(self.model)
        if cpu_model and cpu_model.usable != "no":
            return

        log.debug("Host capabilities CPU '%s' is not supported "
            "according to domain capabilities. Unsetting CPU model",
            self.model)
        self.model = None

    def _set_cpu_x86_kvm_default(self, guest):
        if guest.os.arch != self.conn.caps.host.cpu.arch:
            return

        mode = guest.x86_cpu_default

        self.set_special_mode(guest, mode)
        if mode == self.SPECIAL_MODE_HOST_MODEL_ONLY:
            self._validate_default_host_model_only(guest)

    def set_defaults(self, guest):
        if not self.conn.is_test() and not self.conn.is_qemu():
            return
        if (self.get_xml().strip() or
            self.special_mode_was_set):
            # User already configured CPU
            return

        if guest.os.is_arm_machvirt() and guest.type == "kvm":
            self.mode = self.SPECIAL_MODE_HOST_PASSTHROUGH

        elif guest.os.is_arm64() and guest.os.is_arm_machvirt():
            # -M virt defaults to a 32bit CPU, even if using aarch64
            self.set_model(guest, "cortex-a57")

        elif guest.os.is_x86() and guest.type == "kvm":
            self._set_cpu_x86_kvm_default(guest)
