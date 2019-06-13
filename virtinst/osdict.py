#
# List of OS Specific data
#
# Copyright 2006-2008, 2013-2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import datetime
import os
import re

from gi.repository import Libosinfo

from .logger import log


def _in_testsuite():
    return "VIRTINST_TEST_SUITE" in os.environ


###################
# Sorting helpers #
###################

def _sortby(osobj):
    """
    Combines distro+version to make a more sort friendly string. Examples

    fedora25    -> fedora-0025000000000000
    ubuntu17.04 -> ubuntu-0017000400000000
    win2k8r2    -> win-0006000100000000
    """
    if osobj.is_generic():
        # Sort generic at the end of the list
        return "zzzzzz-000000000000"

    version = osobj.version
    try:
        t = version.split(".")
        t = t[:min(4, len(t))] + [0] * (4 - min(4, len(t)))
        new_version = ""
        for n in t:
            new_version = new_version + ("%.4i" % int(n))
        version = new_version
    except Exception:
        pass

    return "%s-%s" % (osobj.distro, version)


def _sort(tosort):
    sortby_mappings = {}
    distro_mappings = {}
    retlist = []

    for key, osinfo in tosort.items():
        # Libosinfo has some duplicate version numbers here, so append .1
        # if there's a collision
        sortby = _sortby(osinfo)
        while sortby_mappings.get(sortby):
            sortby = sortby + ".1"
        sortby_mappings[sortby] = key

        # Group by distro first, so debian is clumped together, fedora, etc.
        distro = osinfo.distro
        if osinfo.is_generic():
            distro = "zzzzzz"
        if distro not in distro_mappings:
            distro_mappings[distro] = []
        distro_mappings[distro].append(sortby)

    # We want returned lists to be sorted descending by 'distro', so we get
    # debian5, debian4, fedora14, fedora13
    #   rather than
    # debian4, debian5, fedora13, fedora14
    for distro_list in list(distro_mappings.values()):
        distro_list.sort()
        distro_list.reverse()

    sorted_distro_list = list(distro_mappings.keys())
    sorted_distro_list.sort()

    # Build the final list of sorted os objects
    for distro in sorted_distro_list:
        distro_list = distro_mappings[distro]
        for key in distro_list:
            orig_key = sortby_mappings[key]
            retlist.append(tosort[orig_key])

    return retlist


class _OsinfoIter:
    """
    Helper to turn osinfo style get_length/get_nth lists into python
    iterables
    """
    def __init__(self, listobj):
        self.current = 0
        self.listobj = listobj
        self.high = -1
        if self.listobj:
            self.high = self.listobj.get_length() - 1

    def __iter__(self):
        return self
    def __next__(self):
        if self.current > self.high:
            raise StopIteration
        ret = self.listobj.get_nth(self.current)
        self.current += 1
        return ret


class _OSDB(object):
    """
    Entry point for the public API
    """
    def __init__(self):
        self.__os_loader = None
        self.__all_variants = None

    # This is only for back compatibility with pre-libosinfo support.
    # This should never change.
    _aliases = {
        "altlinux": "altlinux1.0",
        "debianetch": "debian4",
        "debianlenny": "debian5",
        "debiansqueeze": "debian6",
        "debianwheezy": "debian7",
        "freebsd10": "freebsd10.0",
        "freebsd6": "freebsd6.0",
        "freebsd7": "freebsd7.0",
        "freebsd8": "freebsd8.0",
        "freebsd9": "freebsd9.0",
        "mandriva2009": "mandriva2009.0",
        "mandriva2010": "mandriva2010.0",
        "mbs1": "mbs1.0",
        "msdos": "msdos6.22",
        "openbsd4": "openbsd4.2",
        "opensolaris": "opensolaris2009.06",
        "opensuse11": "opensuse11.4",
        "opensuse12": "opensuse12.3",
        "rhel4": "rhel4.0",
        "rhel5": "rhel5.0",
        "rhel6": "rhel6.0",
        "rhel7": "rhel7.0",
        "ubuntuhardy": "ubuntu8.04",
        "ubuntuintrepid": "ubuntu8.10",
        "ubuntujaunty": "ubuntu9.04",
        "ubuntukarmic": "ubuntu9.10",
        "ubuntulucid": "ubuntu10.04",
        "ubuntumaverick": "ubuntu10.10",
        "ubuntunatty": "ubuntu11.04",
        "ubuntuoneiric": "ubuntu11.10",
        "ubuntuprecise": "ubuntu12.04",
        "ubuntuquantal": "ubuntu12.10",
        "ubunturaring": "ubuntu13.04",
        "ubuntusaucy": "ubuntu13.10",
        "virtio26": "fedora10",
        "vista": "winvista",
        "winxp64": "winxp",

        # Old --os-type values
        "linux": "generic",
        "windows": "winxp",
        "solaris": "solaris10",
        "unix": "freebsd9.0",
        "other": "generic",
    }


    #################
    # Internal APIs #
    #################

    def _make_default_variants(self):
        ret = {}

        # Generic variant
        v = _OsVariant(None)
        ret[v.name] = v
        return ret

    @property
    def _os_loader(self):
        if not self.__os_loader:
            loader = Libosinfo.Loader()
            loader.process_default_path()

            self.__os_loader = loader
        return self.__os_loader

    @property
    def _all_variants(self):
        if not self.__all_variants:
            loader = self._os_loader
            allvariants = self._make_default_variants()
            db = loader.get_db()
            oslist = db.get_os_list()
            for o in _OsinfoIter(oslist):
                osi = _OsVariant(o)
                allvariants[osi.name] = osi

            self.__all_variants = allvariants
        return self.__all_variants


    ###############
    # Public APIs #
    ###############

    def lookup_os_by_full_id(self, full_id, raise_error=False):
        for osobj in self._all_variants.values():
            if osobj.full_id == full_id:
                return osobj
        if raise_error:
            raise ValueError(_("Unknown libosinfo ID '%s'") % full_id)

    def lookup_os(self, key, raise_error=False):
        if key in self._aliases:
            alias = self._aliases[key]
            # Added 2018-10-02. Maybe remove aliases in a year
            log.warning(
                _("OS name '%s' is deprecated, using '%s' instead. "
                  "This alias will be removed in the future."), key, alias)
            key = alias

        ret = self._all_variants.get(key)
        if ret is None and raise_error:
            raise ValueError(_("Unknown OS name '%s'. "
                    "See `osinfo-query os` for valid values.") % key)
        return ret

    def guess_os_by_iso(self, location):
        try:
            media = Libosinfo.Media.create_from_location(location, None)
        except Exception as e:
            log.debug("Error creating libosinfo media object: %s", str(e))
            return None

        if not self._os_loader.get_db().identify_media(media):
            return None  # pragma: no cover
        return media.get_os().get_short_id(), _OsMedia(media)

    def guess_os_by_tree(self, location):
        if location.startswith("/"):
            location = "file://" + location

        if _in_testsuite() and not location.startswith("file:"):
            # We have mock network tests, but we don't want to pass the
            # fake URL to libosinfo because it slows down the testcase
            return None

        try:
            tree = Libosinfo.Tree.create_from_location(location, None)
        except Exception as e:
            log.debug("Error creating libosinfo tree object for "
                "location=%s : %s", location, str(e))
            return None

        osobj, treeobj = self._os_loader.get_db().guess_os_from_tree(tree)
        if not osobj:
            return None  # pragma: no cover
        return osobj.get_short_id(), treeobj

    def list_os(self):
        """
        List all OSes in the DB
        """
        sortmap = {}

        for name, osobj in self._all_variants.items():
            sortmap[name] = osobj

        return _sort(sortmap)


OSDB = _OSDB()


#####################
# OsResources class #
#####################

class _OsResources:
    def __init__(self, minimum, recommended):
        self._minimum = self._convert_to_dict(minimum)
        self._recommended = self._convert_to_dict(recommended)

    def _convert_to_dict(self, resources):
        """
        Convert an OsResources object to a dictionary for easier
        lookups. Layout is: {arch: {strkey: value}}
        """
        ret = {}
        for r in _OsinfoIter(resources):
            vals = {}
            vals["ram"] = r.get_ram()
            vals["n-cpus"] = r.get_n_cpus()
            vals["storage"] = r.get_storage()
            ret[r.get_architecture()] = vals
        return ret

    def _get_key(self, resources, key, arch):
        for checkarch in [arch, "all"]:
            if checkarch in resources and key in resources[checkarch]:
                return resources[checkarch][key]

    def _get_minimum_key(self, key, arch):
        val = self._get_key(self._minimum, key, arch)
        if val and val > 0:
            return val

    def _get_recommended_key(self, key, arch):
        val = self._get_key(self._recommended, key, arch)
        if val and val > 0:
            return val
        # If we are looking for a recommended value, but the OS
        # DB only has minimum resources tracked, double the minimum
        # value as an approximation at a 'recommended' value
        val = self._get_minimum_key(key, arch)
        if val:
            log.debug("No recommended value found for key='%s', "
                    "using minimum=%s * 2", key, val)
            return val * 2
        return None

    def get_minimum_ram(self, arch):
        return self._get_minimum_key("ram", arch)

    def get_recommended_ram(self, arch):
        return self._get_recommended_key("ram", arch)

    def get_recommended_ncpus(self, arch):
        return self._get_recommended_key("n-cpus", arch)

    def get_recommended_storage(self, arch):
        return self._get_recommended_key("storage", arch)


#####################
# OsVariant classes #
#####################

class _OsVariant(object):
    def __init__(self, o):
        self._os = o
        self._family = self._os and self._os.get_family() or None

        self.full_id = self._os and self._os.get_id() or None
        self.name = self._os and self._os.get_short_id() or "generic"
        self.label = self._os and self._os.get_name() or "Generic default"
        self.codename = self._os and self._os.get_codename() or ""
        self.distro = self._os and self._os.get_distro() or ""
        self.version = self._os and self._os.get_version() or None

        self.eol = self._get_eol()

    def __repr__(self):
        return "<%s name=%s>" % (self.__class__.__name__, self.name)


    ########################
    # Internal helper APIs #
    ########################

    def _is_related_to(self, related_os_list, osobj=None,
            check_derives=True, check_upgrades=True, check_clones=True):
        osobj = osobj or self._os
        if not osobj:
            return False

        if osobj.get_short_id() in related_os_list:
            return True

        check_list = []
        def _extend(newl):
            for obj in newl:
                if obj not in check_list:
                    check_list.append(obj)

        if check_derives:
            _extend(osobj.get_related(
                Libosinfo.ProductRelationship.DERIVES_FROM).get_elements())
        if check_clones:
            _extend(osobj.get_related(
                Libosinfo.ProductRelationship.CLONES).get_elements())
        if check_upgrades:
            _extend(osobj.get_related(
                Libosinfo.ProductRelationship.UPGRADES).get_elements())

        for checkobj in check_list:
            if (checkobj.get_short_id() in related_os_list or
                self._is_related_to(related_os_list, osobj=checkobj,
                    check_upgrades=check_upgrades,
                    check_derives=check_derives,
                    check_clones=check_clones)):
                return True

        return False

    def _get_all_devices(self):
        if not self._os:
            return []
        return list(_OsinfoIter(self._os.get_all_devices()))

    def _device_filter(self, devids=None, cls=None):
        ret = []
        devids = devids or []
        for dev in self._get_all_devices():
            if devids and dev.get_id() not in devids:
                continue
            if cls and not re.match(cls, dev.get_class()):
                continue
            ret.append(dev.get_name())
        return ret


    ###############
    # Cached APIs #
    ###############

    def _get_eol(self):
        eol = self._os and self._os.get_eol_date() or None
        rel = self._os and self._os.get_release_date() or None

        # We can use os.get_release_status() & osinfo.ReleaseStatus.ROLLING
        # if we require libosinfo >= 1.4.0.
        release_status = self._os and self._os.get_param_value(
                Libosinfo.OS_PROP_RELEASE_STATUS) or None

        def _glib_to_datetime(glibdate):
            date = "%s-%s" % (glibdate.get_year(), glibdate.get_day_of_year())
            return datetime.datetime.strptime(date, "%Y-%j")

        now = datetime.datetime.today()
        if eol is not None:
            return now > _glib_to_datetime(eol)

        # Rolling distributions are never EOL.
        if release_status == "rolling":
            return False

        # If no EOL is present, assume EOL if release was > 5 years ago
        if rel is not None:
            rel5 = _glib_to_datetime(rel) + datetime.timedelta(days=365 * 5)
            return now > rel5
        return False


    ###############
    # Public APIs #
    ###############

    def get_handle(self):
        return self._os

    def is_generic(self):
        return self._os is None

    def is_windows(self):
        return self._family in ['win9x', 'winnt', 'win16']

    def broken_uefi_with_hyperv(self):
        # Some windows versions are broken with hyperv enlightenments + UEFI
        # https://bugzilla.redhat.com/show_bug.cgi?id=1185253
        # https://bugs.launchpad.net/qemu/+bug/1593605
        return self.name in ("win2k8r2", "win7")

    def get_clock(self):
        if self.is_windows() or self._family in ['solaris']:
            return "localtime"
        return "utc"

    def supported_netmodels(self):
        return self._device_filter(cls="net")

    def supports_usbtablet(self):
        # If no OS specified, still default to tablet
        if not self._os:
            return True

        devids = ["http://usb.org/usb/80ee/0021"]
        return bool(self._device_filter(devids=devids))

    def supports_virtiodisk(self):
        # virtio-block and virtio1.0-block
        devids = ["http://pcisig.com/pci/1af4/1001",
                  "http://pcisig.com/pci/1af4/1042"]
        return bool(self._device_filter(devids=devids))

    def supports_virtioscsi(self):
        # virtio-scsi and virtio1.0-scsi
        devids = ["http://pcisig.com/pci/1af4/1004",
                  "http://pcisig.com/pci/1af4/1048"]
        return bool(self._device_filter(devids=devids))

    def supports_virtionet(self):
        # virtio-net and virtio1.0-net
        devids = ["http://pcisig.com/pci/1af4/1000",
                  "http://pcisig.com/pci/1af4/1041"]
        return bool(self._device_filter(devids=devids))

    def supports_virtiorng(self):
        # virtio-rng and virtio1.0-rng
        devids = ["http://pcisig.com/pci/1af4/1005",
                  "http://pcisig.com/pci/1af4/1044"]
        return bool(self._device_filter(devids=devids))

    def supports_virtioballoon(self):
        # virtio-balloon and virtio1.0-balloon
        devids = ["http://pcisig.com/pci/1af4/1002",
                  "http://pcisig.com/pci/1af4/1045"]
        return bool(self._device_filter(devids=devids))

    def supports_virtioserial(self):
        devids = ["http://pcisig.com/pci/1af4/1003",
                  "http://pcisig.com/pci/1af4/1043"]
        if self._device_filter(devids=devids):
            return True
        # osinfo data was wrong for RHEL/centos here until Oct 2018
        # Remove this hack after 6 months or so
        return self._is_related_to("rhel6.0")

    def supports_virtioinput(self):
        # virtio1.0-input
        devids = ["http://pcisig.com/pci/1af4/1052"]
        return bool(self._device_filter(devids=devids))

    def supports_usb3(self):
        # qemu-xhci
        devids = ["http://pcisig.com/pci/1b36/0004"]
        return bool(self._device_filter(devids=devids))

    def supports_virtio1(self):
        # Use virtio1.0-net device as a proxy for virtio1.0 as a whole
        devids = ["http://pcisig.com/pci/1af4/1041"]
        return bool(self._device_filter(devids=devids))

    def supports_chipset_q35(self):
        # For our purposes, check for the union of q35 + virtio1.0 support
        if self.supports_virtionet() and not self.supports_virtio1():
            return False
        devids = ["http://qemu.org/chipset/x86/q35"]
        return bool(self._device_filter(devids=devids))

    def get_recommended_resources(self):
        minimum = self._os and self._os.get_minimum_resources() or None
        recommended = self._os and self._os.get_recommended_resources() or None
        return _OsResources(minimum, recommended)

    def get_network_install_required_ram(self, guest):
        if hasattr(self._os, "get_network_install_resources"):
            resources = self._os.get_network_install_resources()
            for r in _OsinfoIter(resources):
                arch = r.get_architecture()
                if arch == guest.os.arch or arch == "all":
                    return r.get_ram()

    def get_kernel_url_arg(self):
        """
        Kernel argument name the distro's installer uses to reference
        a network source, possibly bypassing some installer prompts
        """
        if not self._os:
            return None

        # SUSE distros
        if self.distro in ["caasp", "sle", "sled", "sles", "opensuse"]:
            return "install"

        if self.distro not in ["centos", "rhel", "fedora"]:
            return None

        # Red Hat distros
        try:
            if re.match(r"[0-9]+-unknown", self.version):
                version = float(self.version.split("-")[0])
            else:
                version = float(self.version)
        except Exception:
            # Can hit this for -rawhide or -unknown
            version = 999

        if self.distro in ["centos", "rhel"] and version < 7:
            return "method"

        if self.distro in ["fedora"] and version < 19:
            return "method"

        return "inst.repo"


    def get_location(self, arch):
        treelist = []
        if self._os:
            treelist = list(_OsinfoIter(self._os.get_tree_list()))

        if not treelist:
            raise RuntimeError(
                _("OS '%s' does not have a URL location") % self.name)

        # Some distros have more than one URL for a specific architecture,
        # which is the case for Fedora and different variants (Server,
        # Workstation). Later on, we'll have to differentiate that and return
        # the right one.
        for tree in treelist:
            if tree.get_architecture() == arch:
                return tree.get_url()

        raise RuntimeError(
            _("OS '%s' does not have a URL location for the %s architecture") %
            (self.name, arch))

    def get_install_script_list(self):
        if not self._os:
            return []  # pragma: no cover
        return list(_OsinfoIter(self._os.get_install_script_list()))


class _OsMedia(object):
    def __init__(self, osinfo_media):
        self._media = osinfo_media

    def get_kernel_path(self):
        return self._media.get_kernel_path()
    def get_initrd_path(self):
        return self._media.get_initrd_path()
    def supports_installer_script(self):
        return self._media.supports_installer_script()

    def is_netinst(self):
        variants = list(_OsinfoIter(self._media.get_os_variants()))
        for variant in variants:
            if "netinst" in variant.get_id():
                return True
        return False

    def get_install_script_list(self):
        return list(_OsinfoIter(self._media.get_install_script_list()))
