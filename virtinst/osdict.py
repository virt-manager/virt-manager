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

from . import xmlutil
from .logger import log


def _media_create_from_location(location):
    if not hasattr(Libosinfo.Media, "create_from_location_with_flags"):
        return Libosinfo.Media.create_from_location(location, None)  # pragma: no cover

    # We prefer this API, because by default it will not
    # reject non-bootable media, like debian s390x
    # pylint: disable=no-member
    return Libosinfo.Media.create_from_location_with_flags(location, None, 0)


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


#####################
# OVF OS hint maps  #
#####################

# The three maps below translate OVF/OVA vendor OS identifiers to libosinfo
# short IDs.  They are module-level constants referenced by
# OSDB.guess_os_from_ovf_hint() — update them here when new OS versions ship.

# VMware vmw:osType attribute values (OperatingSystemSection)
_OVF_VMW_OS_MAP = {
    # ── Windows Desktop ───────────────────────────────────────────────────
    "windows11_64Guest":          "win11",
    "windows10_64Guest":          "win10",
    "windows10Guest":             "win10",
    "windows9_64Guest":           "win10",
    "windows9Guest":              "win10",
    "windows8_64Guest":           "win8",
    "windows8Guest":              "win8",
    "windows7_64Guest":           "win7",
    "windows7Guest":              "win7",
    "windowsVistaGuest":          "winvista",
    "winvistaGuest":              "winvista",
    "windowsXPGuest":             "winxp",
    "winXPProGuest":              "winxp",
    "winXPPro64Guest":            "winxp",
    # ── Windows Server ────────────────────────────────────────────────────
    "windows2025srvNext_64Guest": "win2k25",
    "windows2022srvNext_64Guest": "win2k22",
    "windows2019srv_64Guest":     "win2k19",
    "windows2016srv_64Guest":     "win2k16",
    "windows2016srvNext_64Guest": "win2k16",
    "windows2012srv_64Guest":     "win2k12",
    "windows2012srvR2_64Guest":   "win2k12r2",
    "windows2008srvR2_64Guest":   "win2k8r2",
    "winNetEnterprise64Guest":    "win2k8",
    "longhorn64Guest":            "win2k8",
    "longhornGuest":              "win2k8",
    # ── RHEL / CentOS ─────────────────────────────────────────────────────
    "rhel9_64Guest":              "rhel9.0",
    "rhel8_64Guest":              "rhel8.0",
    "rhel7_64Guest":              "rhel7.0",
    "rhel6_64Guest":              "rhel6.0",
    "rhel5_64Guest":              "rhel5.0",
    "rhel4_64Guest":              "rhel4",
    "centos9_64Guest":            "centos-stream9",
    "centos8_64Guest":            "centos8",
    "centos7_64Guest":            "centos7.0",
    "centos64Guest":              "centos7.0",
    # ── Fedora ────────────────────────────────────────────────────────────
    "fedora64Guest":              "fedora38",
    "fedoraGuest":                "fedora38",
    # ── Debian ────────────────────────────────────────────────────────────
    "debian12_64Guest":           "debian12",
    "debian11_64Guest":           "debian11",
    "debian10_64Guest":           "debian10",
    "debian9_64Guest":            "debian9",
    # ── Ubuntu ────────────────────────────────────────────────────────────
    "ubuntu64Guest":              "ubuntu22.04",
    "ubuntuGuest":                "ubuntu22.04",
    # ── SUSE ─────────────────────────────────────────────────────────────
    "sles15_64Guest":             "sles15",
    "sles12_64Guest":             "sles12",
    "sles11_64Guest":             "sles11sp4",
    "opensuseNext64Guest":        "opensuse15.5",
    "opensuse64Guest":            "opensuse15.5",
    # ── FreeBSD ───────────────────────────────────────────────────────────
    "freebsd13_64Guest":          "freebsd13.0",
    "freebsd64Guest":             "freebsd13.0",
    "freebsdGuest":               "freebsd13.0",
}

# VirtualBox <vbox:OSType> child element values
_OVF_VBOX_OS_MAP = {
    # ── Windows Desktop ───────────────────────────────────────────────────
    "Windows11_64":    "win11",
    "Windows10_64":    "win10",
    "Windows10":       "win10",
    "Windows81_64":    "win8.1",
    "Windows81":       "win8.1",
    "Windows8_64":     "win8",
    "Windows8":        "win8",
    "Windows7_64":     "win7",
    "Windows7":        "win7",
    "WindowsVista_64": "winvista",
    "WindowsVista":    "winvista",
    "WindowsXP_64":    "winxp",
    "WindowsXP":       "winxp",
    "Windows2000":     "win2k",
    # ── Windows Server ────────────────────────────────────────────────────
    "Windows2022_64":  "win2k22",
    "Windows2019_64":  "win2k19",
    "Windows2016_64":  "win2k16",
    "Windows2012R2_64": "win2k12r2",
    "Windows2012_64":  "win2k12",
    "Windows2008R2_64": "win2k8r2",
    "Windows2008_64":  "win2k8",
    "Windows2008":     "win2k8",
    # ── RHEL / Oracle Linux ───────────────────────────────────────────────
    "RedHat_64":       "rhel9.0",
    "RedHat":          "rhel9.0",
    "Oracle_64":       "oraclelinux9",
    "Oracle":          "oraclelinux9",
    # ── Fedora ────────────────────────────────────────────────────────────
    "Fedora_64":       "fedora38",
    "Fedora":          "fedora38",
    # ── Debian ────────────────────────────────────────────────────────────
    "Debian_64":       "debian12",
    "Debian":          "debian12",
    # ── Ubuntu ────────────────────────────────────────────────────────────
    "Ubuntu_64":       "ubuntu22.04",
    "Ubuntu":          "ubuntu22.04",
    # ── SUSE ─────────────────────────────────────────────────────────────
    "OpenSUSE_64":     "opensuse15.5",
    "OpenSUSE":        "opensuse15.5",
    "SUSE_64":         "sles15",
    "SUSE":            "sles15",
    # ── ArchLinux ─────────────────────────────────────────────────────────
    "ArchLinux_64":    "archlinux",
    "ArchLinux":       "archlinux",
    # ── FreeBSD ───────────────────────────────────────────────────────────
    "FreeBSD_64":      "freebsd13.0",
    "FreeBSD":         "freebsd13.0",
}

# DMTF CIM OS type ID (ovf:id integer on OperatingSystemSection)
_OVF_CIM_OS_MAP = {
    36:  "linux2020",      # LINUX
    99:  "linux2020",      # Linux 2.6.x
    100: "linux2020",      # Linux 2.6.x 64-bit
    101: "linux2020",      # Linux 64-bit
    42:  "freebsd13.0",
    78:  "freebsd13.0",    # FreeBSD 64-bit
    58:  "win2k",          # Windows 2000
    67:  "winxp",          # Windows XP
    71:  "winxp",          # Windows XP 64-bit
    73:  "winvista",       # Windows Vista
    74:  "winvista",       # Windows Vista 64-bit
    105: "win7",           # Windows 7
    114: "win8",           # Windows 8
    115: "win8",           # Windows 8 64-bit
    69:  "win2k3",         # Windows Server 2003
    70:  "win2k3",         # Windows Server 2003 64-bit
    76:  "win2k8",         # Windows Server 2008
    77:  "win2k8",         # Windows Server 2008 64-bit
    103: "win2k8r2",       # Windows Server 2008 R2
    113: "win2k12",        # Windows Server 2012
    116: "win2k12r2",      # Windows Server 2012 R2
    79:  "rhel9.0",        # RHEL 32-bit
    80:  "rhel9.0",        # RHEL 64-bit
    106: "centos-stream9",  # CentOS 32-bit
    107: "centos-stream9",  # CentOS 64-bit
    93:  "ubuntu22.04",
    94:  "ubuntu22.04",    # Ubuntu 64-bit
    95:  "debian12",
    96:  "debian12",       # Debian 64-bit
    82:  "opensuse15.5",
    83:  "opensuse15.5",   # openSUSE 64-bit
    84:  "sles15",
    85:  "sles15",         # SLES 64-bit
}


class _OSDB:
    """
    Entry point for the public API
    """

    def __init__(self):
        self.__os_loader = None
        self.__os_generic = None

    #################
    # Internal APIs #
    #################

    @property
    def _os_generic(self):
        if not self.__os_generic:
            # Add our custom generic variant
            o = Libosinfo.Os()
            o.set_param("short-id", "generic")
            o.set_param("name", _("Generic or unknown OS. Usage is not recommended."))
            self.__os_generic = _OsVariant(o)
        return self.__os_generic

    @property
    def _os_loader(self):
        if not self.__os_loader:
            loader = Libosinfo.Loader()
            loader.process_default_path()

            self.__os_loader = loader
        return self.__os_loader

    @property
    def _os_db(self):
        return self._os_loader.get_db()

    ###############
    # Public APIs #
    ###############

    def lookup_os_by_full_id(self, full_id, raise_error=False):
        osobj = self._os_db.get_os(full_id)
        if osobj is None:
            if raise_error:
                raise ValueError(_("Unknown libosinfo ID '%s'") % full_id)
            return None
        return _OsVariant(osobj)

    def lookup_os(self, key, raise_error=False):
        if key == self._os_generic.name:
            return self._os_generic

        flt = Libosinfo.Filter()
        flt.add_constraint(Libosinfo.PRODUCT_PROP_SHORT_ID, key)
        oslist = self._os_db.get_os_list().new_filtered(flt).get_elements()
        if len(oslist) == 0:
            if raise_error:
                raise ValueError(
                    _("Unknown OS name '%s'. See `--osinfo list` for valid values.") % key
                )
            return None
        return _OsVariant(oslist[0])

    def guess_os_by_iso(self, location):
        try:
            media = _media_create_from_location(location)
        except Exception as e:
            log.debug("Error creating libosinfo media object: %s", str(e))
            return None

        if not self._os_db.identify_media(media):
            return None
        return media.get_os().get_short_id(), _OsMedia(media)

    def guess_os_by_tree(self, location):
        if location.startswith("/"):
            location = "file://" + location

        if xmlutil.in_testsuite() and not location.startswith("file:"):
            # We have mock network tests, but we don't want to pass the
            # fake URL to libosinfo because it slows down the testcase
            return None

        try:
            tree = Libosinfo.Tree.create_from_location(location, None)
        except Exception as e:
            log.debug("Error creating libosinfo tree object for location=%s : %s", location, str(e))
            return None

        if hasattr(self._os_db, "identify_tree"):
            # osinfo_db_identify_tree is part of libosinfo 1.6.0
            if not self._os_db.identify_tree(tree):
                return None  # pragma: no cover
            return tree.get_os().get_short_id(), _OsTree(tree)
        else:  # pragma: no cover
            osobj, treeobj = self._os_db.guess_os_from_tree(tree)
            if not osobj:
                return None  # pragma: no cover
            return osobj.get_short_id(), _OsTree(treeobj)

    def guess_os_from_ovf_hint(self, vmw_type=None, vbox_type=None, cim_id=None):
        """
        Return an :class:`_OsVariant` that best matches the OVF/OVA OS hints,
        or *None* if no match is found.

        Hints are tried in priority order:
          1. *vmw_type*  — VMware ``vmw:osType`` attribute string
          2. *vbox_type* — VirtualBox ``<vbox:OSType>`` element text
          3. *cim_id*    — DMTF CIM OS integer from OVF ``ovf:id``
        """
        short_id = None
        if vmw_type:
            short_id = _OVF_VMW_OS_MAP.get(vmw_type)
        if short_id is None and vbox_type:
            short_id = _OVF_VBOX_OS_MAP.get(vbox_type)
        if short_id is None and cim_id is not None:
            try:
                short_id = _OVF_CIM_OS_MAP.get(int(cim_id))
            except (ValueError, TypeError):
                pass
        if short_id is None:
            return None
        return self.lookup_os(short_id)

    def list_os(self, sortkey="name"):
        """
        List all OSes in the DB, sorting by the passes _OsVariant attribute
        """
        oslist = [_OsVariant(osent) for osent in self._os_db.get_os_list().get_elements()]
        oslist.append(self._os_generic)

        # human/natural sort, but with reverse sorted numbers
        def to_int(text):
            return (int(text) * -1) if text.isdigit() else text.lower()

        def alphanum_key(obj):
            val = getattr(obj, sortkey)
            return [to_int(c) for c in re.split("([0-9]+)", val)]

        return list(sorted(oslist, key=alphanum_key))


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
            val = resources.get(checkarch, {}).get(key, -1)
            if val != -1:
                return val

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
            log.debug("No recommended value found for key='%s', using minimum=%s * 2", key, val)
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


class _OsVariant:
    def __init__(self, o):
        self._os = o

        self._short_ids = [self._os.get_short_id()]
        if hasattr(self._os, "get_short_id_list"):
            self._short_ids = self._os.get_short_id_list()
        self.name = self._short_ids[0]
        self.all_names = list(sorted(set(self._short_ids)))

        self._family = self._os.get_family()
        self.full_id = self._os.get_id()
        self.label = self._os.get_name()
        self.codename = self._os.get_codename() or ""
        self.distro = self._os.get_distro() or ""
        self.version = self._os.get_version()

        self.eol = self._get_eol()

    def __repr__(self):
        return "<%s name=%s>" % (self.__class__.__name__, self.name)

    ########################
    # Internal helper APIs #
    ########################

    def _is_related_to(
        self,
        related_os_list,
        osobj=None,
        check_derives=True,
        check_upgrades=True,
        check_clones=True,
    ):
        osobj = osobj or self._os
        if osobj.get_short_id() in related_os_list:
            return True

        check_list = []

        def _extend(newl):
            for obj in newl:
                if obj not in check_list:
                    check_list.append(obj)

        if check_derives:
            _extend(osobj.get_related(Libosinfo.ProductRelationship.DERIVES_FROM).get_elements())
        if check_clones:
            _extend(osobj.get_related(Libosinfo.ProductRelationship.CLONES).get_elements())
        if check_upgrades:
            _extend(osobj.get_related(Libosinfo.ProductRelationship.UPGRADES).get_elements())

        for checkobj in check_list:
            if checkobj.get_short_id() in related_os_list or self._is_related_to(
                related_os_list,
                osobj=checkobj,
                check_upgrades=check_upgrades,
                check_derives=check_derives,
                check_clones=check_clones,
            ):
                return True

        return False

    def _get_all_devices(self):
        return list(_OsinfoIter(self._os.get_all_devices()))

    def _device_filter(self, devids=None, cls=None, extra_devs=None):
        ret = []
        devids = devids or []
        for dev in self._get_all_devices():
            if devids and dev.get_id() not in devids:
                continue
            if cls and not re.match(cls, dev.get_class()):
                continue
            ret.append(dev.get_name())

        extra_devs = extra_devs or []
        for dev in extra_devs:
            if dev.get_id() not in devids:
                continue
            ret.append(dev.get_name())

        return ret

    ###############
    # Cached APIs #
    ###############

    def _get_eol(self):
        eol = self._os.get_eol_date()
        rel = self._os.get_release_date()

        # We can use os.get_release_status() & osinfo.ReleaseStatus.ROLLING
        # if we require libosinfo >= 1.4.0.
        release_status = self._os.get_param_value(Libosinfo.OS_PROP_RELEASE_STATUS) or None

        def _glib_to_datetime(glibdate):
            date = "%s-%s" % (glibdate.get_year(), glibdate.get_day_of_year())
            return datetime.datetime.strptime(date, "%Y-%j")

        now = datetime.datetime.today()
        if eol is not None:
            return now > _glib_to_datetime(eol)

        # Rolling distributions are never EOL.
        if release_status == "rolling":
            return False

        # If no EOL is present, assume EOL if release was > 10 years ago
        if rel is not None:
            rel5 = _glib_to_datetime(rel) + datetime.timedelta(days=365 * 10)
            return now > rel5
        return False

    ###############
    # Public APIs #
    ###############

    def get_handle(self):
        return self._os

    def is_generic(self):
        return self.name == "generic"

    def is_linux_generic(self):
        return re.match(r"linux\d\d\d\d", self.name)

    def is_windows(self):
        return self._family in ["win9x", "winnt", "win16"]

    def get_clock(self):
        if self.is_windows() or self._family in ["solaris"]:
            return "localtime"
        return "utc"

    def supported_netmodels(self):
        return self._device_filter(cls="net")

    def supports_virtiodisk(self, extra_devs=None):
        # virtio-block and virtio1.0-block
        devids = ["http://pcisig.com/pci/1af4/1001", "http://pcisig.com/pci/1af4/1042"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def supports_virtioscsi(self, extra_devs=None):
        # virtio-scsi and virtio1.0-scsi
        devids = ["http://pcisig.com/pci/1af4/1004", "http://pcisig.com/pci/1af4/1048"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def supports_virtionet(self, extra_devs=None):
        # virtio-net and virtio1.0-net
        devids = ["http://pcisig.com/pci/1af4/1000", "http://pcisig.com/pci/1af4/1041"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def supports_virtiorng(self, extra_devs=None):
        # virtio-rng and virtio1.0-rng
        devids = ["http://pcisig.com/pci/1af4/1005", "http://pcisig.com/pci/1af4/1044"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def supports_virtiogpu(self, extra_devs=None):
        # virtio1.0-gpu and virtio1.0
        devids = ["http://pcisig.com/pci/1af4/1050"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def supports_virtioballoon(self, extra_devs=None):
        # virtio-balloon and virtio1.0-balloon
        devids = ["http://pcisig.com/pci/1af4/1002", "http://pcisig.com/pci/1af4/1045"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def supports_virtioserial(self, extra_devs=None):
        devids = ["http://pcisig.com/pci/1af4/1003", "http://pcisig.com/pci/1af4/1043"]
        if self._device_filter(devids=devids, extra_devs=extra_devs):
            return True
        # osinfo data was wrong for RHEL/centos here until Oct 2018
        # Remove this hack after 6 months or so
        return self._is_related_to("rhel6.0")

    def supports_virtioinput(self, extra_devs=None):
        # virtio1.0-input
        devids = ["http://pcisig.com/pci/1af4/1052"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def supports_usb3(self, extra_devs=None):
        # qemu-xhci
        devids = ["http://pcisig.com/pci/1b36/0004"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def supports_virtio1(self, extra_devs=None):
        # Use virtio1.0-net device as a proxy for virtio1.0 as a whole
        devids = ["http://pcisig.com/pci/1af4/1041"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def supports_chipset_q35(self, extra_devs=None):
        # For our purposes, check for the union of q35 + virtio1.0 support
        if self.supports_virtionet(extra_devs=extra_devs) and not self.supports_virtio1(
            extra_devs=extra_devs
        ):
            return False
        devids = ["http://qemu.org/chipset/x86/q35"]
        return bool(self._device_filter(devids=devids, extra_devs=extra_devs))

    def _get_firmware_list(self):
        if hasattr(self._os, "get_complete_firmware_list"):  # pragma: no cover
            return self._os.get_complete_firmware_list().get_elements()
        return []  # pragma: no cover

    def _supports_firmware_type(self, name, arch, default):
        firmwares = self._get_firmware_list()

        for firmware in firmwares:  # pragma: no cover
            if firmware.get_architecture() != arch:
                continue
            if firmware.get_firmware_type() == name:
                return firmware.is_supported()

        return default

    def requires_firmware_efi(self, arch):
        ret = False
        try:
            supports_efi = self._supports_firmware_type("efi", arch, False)
            supports_bios = self._supports_firmware_type("bios", arch, True)
            ret = supports_efi and not supports_bios
        except Exception:  # pragma: no cover
            log.debug("Error checking osinfo firmware support", exc_info=True)

        return ret

    def get_recommended_resources(self):
        minimum = self._os.get_minimum_resources()
        recommended = self._os.get_recommended_resources()
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
        # Let's ask the OS for its kernel argument for the source
        if hasattr(self._os, "get_kernel_url_argument"):
            osarg = self._os.get_kernel_url_argument()
            if osarg is not None:
                return osarg

        # SUSE distros
        if self.distro in ["caasp", "sle", "sled", "sles", "opensuse"]:
            return "install"

        if self.distro not in ["centos", "rhel", "fedora"]:
            return None

        # Default for RH distros, in case libosinfo data isn't complete
        return "inst.repo"  # pragma: no cover

    def _get_generic_location(self, treelist, arch, profile):
        if not hasattr(Libosinfo.Tree, "get_os_variants"):  # pragma: no cover
            for tree in treelist:
                if tree.get_architecture() == arch:
                    return tree.get_url()
            return None

        fallback_tree = None
        if profile == "jeos":
            profile = "Server"
        elif profile == "desktop":
            profile = "Workstation"
        elif not profile:
            profile = "Everything"

        for tree in treelist:
            if tree.get_architecture() != arch:
                continue

            variant_list = tree.get_os_variants()
            fallback_tree = tree
            for variant in _OsinfoIter(variant_list):
                if profile in variant.get_name():
                    return tree.get_url()

        if fallback_tree:
            return fallback_tree.get_url()
        return None

    def get_location(self, arch, profile=None):
        treelist = list(_OsinfoIter(self._os.get_tree_list()))

        if not treelist:
            raise RuntimeError(_("OS '%s' does not have a URL location") % self.name)

        # Some distros have more than one URL for a specific architecture,
        # which is the case for Fedora and different variants (Server,
        # Workstation). Later on, we'll have to differentiate that and return
        # the right one. However, for now, let's just rely on returning the
        # most generic tree possible.
        location = self._get_generic_location(treelist, arch, profile)
        if location:
            return location

        raise RuntimeError(
            _("OS '%(osname)s' does not have a URL location for the architecture '%(archname)s'")
            % {"osname": self.name, "archname": arch}
        )

    def get_install_script_list(self):
        return list(_OsinfoIter(self._os.get_install_script_list()))

    def _get_installable_drivers(self, arch):
        installable_drivers = []
        device_drivers = list(_OsinfoIter(self._os.get_device_drivers()))
        for device_driver in device_drivers:
            if arch != "all" and device_driver.get_architecture() != arch:
                continue

            installable_drivers.append(device_driver)
        return installable_drivers

    def _get_pre_installable_drivers(self, arch):
        installable_drivers = self._get_installable_drivers(arch)
        pre_inst_drivers = []
        for driver in installable_drivers:
            if driver.get_pre_installable():
                pre_inst_drivers.append(driver)
        return pre_inst_drivers

    def _get_drivers_location(self, drivers):
        locations = []
        for driver in drivers:
            filenames = driver.get_files()
            for filename in filenames:
                location = os.path.join(driver.get_location(), filename)
                locations.append(location)
        return locations

    def get_pre_installable_drivers_location(self, arch):
        pre_inst_drivers = self._get_pre_installable_drivers(arch)

        return self._get_drivers_location(pre_inst_drivers)

    def get_pre_installable_devices(self, arch):
        drivers = self._get_pre_installable_drivers(arch)
        devices = []
        for driver in drivers:
            devices += list(_OsinfoIter(driver.get_devices()))
        return devices

    def supports_unattended_drivers(self, arch):
        if self._get_pre_installable_drivers(arch):
            return True
        return False


class _OsMedia:
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
        return False  # pragma: no cover

    def get_install_script_list(self):
        return list(_OsinfoIter(self._media.get_install_script_list()))

    def get_osinfo_media(self):
        return self._media


class _OsTree:
    def __init__(self, osinfo_tree):
        self._tree = osinfo_tree

    def get_osinfo_tree(self):
        return self._tree
