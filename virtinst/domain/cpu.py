#
# Copyright 2010, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..logger import log

from ..xmlbuilder import XMLBuilder, XMLProperty, XMLChildProperty
from .. import xmlutil


###################################
# Misc child nodes for CPU domain #
###################################

class _CPUTopology(XMLBuilder):
    """
    Class for generating XML for <cpu> child node <topology>.
    """
    XML_NAME = "topology"
    _XML_PROP_ORDER = ["sockets", "dies", "cores", "threads"]

    sockets = XMLProperty("./@sockets", is_int=True)
    dies = XMLProperty("./@dies", is_int=True)
    cores = XMLProperty("./@cores", is_int=True)
    threads = XMLProperty("./@threads", is_int=True)

    # While `dies` is optional and defaults to 1 if omitted,
    # `sockets`, `cores`, and `threads` are mandatory.
    def set_defaults_from_vcpus(self, vcpus):
        # The hierarchy is sockets > dies > cores > threads.
        #
        # In real world silicon though it is rare to have
        # high socket/die counts, but common to have huge
        # core counts.
        #
        # Some OS will even refuse to use sockets over a
        # a certain count.
        #
        # Thus we prefer to expose cores to the guest rather
        # than sockets as the default for missing fields
        if not self.cores:
            self.cores = vcpus // self.total_vcpus()

        if not self.sockets:
            self.sockets = vcpus // self.total_vcpus()

        if not self.dies:
            self.dies = 1

        if not self.threads:
            self.threads = vcpus // self.total_vcpus()

        if self.total_vcpus() != vcpus:
            raise ValueError(_("Total CPUs implied by topology "
                               "(sockets=%(sockets)d * dies=%(dies)d * cores=%(cores)d * threads=%(threads)d == %(total)d) "
                               "does not match vCPU count %(vcpus)d") % {
                                   "sockets": self.sockets,
                                   "dies": self.dies,
                                   "cores": self.cores,
                                   "threads": self.threads,
                                   "total": self.total_vcpus(),
                                   "vcpus": vcpus,
                               })

        return

    def total_vcpus(self):
        """
        Determine the CPU count represented by topology
        """
        return ((self.sockets or 1) *
                (self.dies or 1) *
                (self.cores or 1) *
                (self.threads or 1))


# Note: CPU cache is weird. The documentation implies that multiples instances
# can be declared, one for each cache level one wishes to define. However,
# libvirt doesn't accept more than one <cache> element, so it's implemented
# with `is_single=True` for now (see actual CPU Domain below).
class _CPUCache(XMLBuilder):
    """
    Class for generating XML for <cpu> child node <cache>.
    """
    XML_NAME = "cache"
    _XML_PROP_ORDER = ["level", "mode"]

    level = XMLProperty("./@level", is_int=True)
    mode = XMLProperty("./@mode")


class _CPUFeature(XMLBuilder):
    """
    Class for generating XML for <cpu> child nodes <feature>.
    """
    XML_NAME = "feature"
    _XML_PROP_ORDER = ["policy", "name"]

    name = XMLProperty("./@name")
    policy = XMLProperty("./@policy")


##############
# NUMA cells #
##############

class _NUMACellSibling(XMLBuilder):
    """
    Class for generating XML for <cpu><numa><cell><distances> child nodes
    <sibling>, describing the distances to other NUMA cells.
    """
    XML_NAME = "sibling"
    _XML_PROP_ORDER = ["id", "value"]

    id = XMLProperty("./@id", is_int=True)
    value = XMLProperty("./@value", is_int=True)


class _NUMACellCache(XMLBuilder):
    """
    Class for generating XML for <cpu><numa><cell> child nodes <cache>,
    describing caches for NUMA cells.
    """
    XML_NAME = "cache"
    _XML_PROP_ORDER = ["level", "associativity", "policy",
            "size_value", "size_unit", "line_value", "line_unit"]

    level = XMLProperty("./@level", is_int=True)
    associativity = XMLProperty("./@associativity")
    policy = XMLProperty("./@policy")

    size_value = XMLProperty("./size/@value", is_int=True)
    size_unit = XMLProperty("./size/@unit")
    line_value = XMLProperty("./line/@value", is_int=True)
    line_unit = XMLProperty("./line/@unit")


class _NUMACell(XMLBuilder):
    """
    Class for generating XML for <cpu><numa> child nodes <cell> XML, describing
    NUMA cells.
    """
    XML_NAME = "cell"
    _XML_PROP_ORDER = ["id", "cpus", "memory", "unit", "memAccess", "discard",
            "siblings", "caches"]

    id = XMLProperty("./@id", is_int=True)
    cpus = XMLProperty("./@cpus")
    memory = XMLProperty("./@memory", is_int=True)
    unit = XMLProperty("./@unit")
    memAccess = XMLProperty("./@memAccess")
    discard = XMLProperty("./@discard", is_yesno=True)

    siblings = XMLChildProperty(_NUMACellSibling, relative_xpath="./distances")
    caches = XMLChildProperty(_NUMACellCache)


#######################################
# Interconnections between NUMA cells #
#######################################

class _NUMALatency(XMLBuilder):
    """
    Class for generating XML for <cpu><numa><cell><interconnects> child nodes
    <latency>, describing latency between two NUMA memory nodes.
    """
    XML_NAME = "latency"
    _XML_PROP_ORDER = ["initiator", "target", "cache", "type", "value", "unit"]

    # Note: While libvirt happily accepts XML with a unit= property, it is
    # currently ignored on <latency> nodes.
    initiator = XMLProperty("./@initiator", is_int=True)
    target = XMLProperty("./@target", is_int=True)
    cache = XMLProperty("./@cache", is_int=True)
    type = XMLProperty("./@type")
    value = XMLProperty("./@value", is_int=True)
    unit = XMLProperty("./@unit")


class _NUMABandwidth(XMLBuilder):
    """
    Class for generating XML for <cpu><numa><cell><interconnects> child nodes
    <bandwidth>, describing bandwidth between two NUMA memory nodes.
    """
    XML_NAME = "bandwidth"
    _XML_PROP_ORDER = ["initiator", "target", "cache", "type", "value", "unit"]

    # Note: The documentation only mentions <latency> nodes having a cache=
    # attribute, but <bandwidth> and <latency> nodes are otherwise identical
    # and libvirt will happily accept XML with a cache= attribute on
    # <bandwidth> nodes as well, so let's leave it here for now.
    initiator = XMLProperty("./@initiator", is_int=True)
    target = XMLProperty("./@target", is_int=True)
    cache = XMLProperty("./@cache", is_int=True)
    type = XMLProperty("./@type")
    value = XMLProperty("./@value", is_int=True)
    unit = XMLProperty("./@unit")


#####################
# Actual CPU domain #
#####################

class DomainCpu(XMLBuilder):
    """
    Class for generating <cpu> XML
    """
    XML_NAME = "cpu"
    _XML_PROP_ORDER = ["mode", "match", "check", "migratable",
            "model", "model_fallback", "model_vendor_id", "vendor",
            "topology", "cache", "features",
            "cells", "latencies", "bandwidths"]


    ##################
    # XML properties #
    ##################

    # Note: This is not a libvirt property. This is specific to the virt-*
    # tools and causes additional security features to be added to the VM.
    # See the security mitigation related functions below for more details.
    secure = True

    mode = XMLProperty("./@mode")
    match = XMLProperty("./@match")
    check = XMLProperty("./@check")
    migratable = XMLProperty("./@migratable", is_onoff=True)

    model = XMLProperty("./model")
    model_fallback = XMLProperty("./model/@fallback")
    model_vendor_id = XMLProperty("./model/@vendor_id")
    vendor = XMLProperty("./vendor")

    topology = XMLChildProperty(_CPUTopology, is_single=True)
    cache = XMLChildProperty(_CPUCache, is_single=True)
    features = XMLChildProperty(_CPUFeature)

    # NUMA related properties
    cells = XMLChildProperty(_NUMACell, relative_xpath="./numa")
    latencies = XMLChildProperty(_NUMALatency, relative_xpath="./numa/interconnects")
    bandwidths = XMLChildProperty(_NUMABandwidth, relative_xpath="./numa/interconnects")


    #############################
    # Special CPU mode handling #
    #############################

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

    def _get_app_default_mode(self, guest):
        # Depending on if libvirt+qemu is new enough, we prefer
        # host-passthrough, then host-model, and finally host-model-only
        domcaps = guest.lookup_domcaps()

        if domcaps.supports_safe_host_passthrough():
            return self.SPECIAL_MODE_HOST_PASSTHROUGH

        log.debug("Safe host-passthrough is not available")
        if domcaps.supports_safe_host_model():
            return self.SPECIAL_MODE_HOST_MODEL

        log.debug("Safe host-model is not available")
        return self.SPECIAL_MODE_HOST_MODEL_ONLY

    def set_special_mode(self, guest, val):
        if val == self.SPECIAL_MODE_APP_DEFAULT:
            val = self._get_app_default_mode(guest)
            log.debug("Using default cpu mode=%s", val)

        if (val == self.SPECIAL_MODE_HOST_MODEL or
            val == self.SPECIAL_MODE_HOST_PASSTHROUGH):
            self.model = None
            self.vendor = None
            self.model_fallback = None
            self.migratable = None
            self.check = None
            for f in self.features:
                self.remove_child(f)
            self.mode = val
        elif (val == self.SPECIAL_MODE_HV_DEFAULT or
              val == self.SPECIAL_MODE_CLEAR):
            self.clear()
        elif (val == self.SPECIAL_MODE_HOST_MODEL_ONLY or
              val == self.SPECIAL_MODE_HOST_COPY):
            if val == self.SPECIAL_MODE_HOST_COPY:
                log.warning("CPU mode=%s no longer supported, using mode=%s",
                        val, self.SPECIAL_MODE_HOST_MODEL_ONLY)
            if self.conn.caps.host.cpu.model:
                self.clear()
                self.set_model(guest, self.conn.caps.host.cpu.model)
        else:
            raise xmlutil.DevError("unknown special cpu mode '%s'" % val)

        self.special_mode_was_set = True


    ########################
    # Security mitigations #
    ########################

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


    ###########
    # Helpers #
    ###########

    def set_model(self, guest, val):
        log.debug("setting cpu model %s", val)
        self.migratable = None
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

    def vcpus_from_topology(self):
        """
        Determine the CPU count represented by topology, or 1 if
        no topology is set
        """
        return self.topology.total_vcpus()

    def has_topology(self):
        """
        Return True if any topology info is set
        """
        return bool(self.topology.get_xml())

    def set_topology_defaults(self, vcpus, create=False):
        """
        Fill in unset topology values, using the passed vcpus count.
        If @create is False, this will not set topology from scratch,
        just fill in missing topology values.
        If @create is True, this will create topology from scratch.
        """
        if not self.has_topology() and not create:
            return
        self.topology.set_defaults_from_vcpus(vcpus)


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
