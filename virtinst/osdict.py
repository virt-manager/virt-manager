#
# List of OS Specific data
#
# Copyright 2006-2008, 2013-2014 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import datetime
import logging
import re
import time

import gi
gi.require_version('Libosinfo', '1.0')
from gi.repository import Libosinfo as libosinfo
from gi.repository import GLib


###################
# Sorting helpers #
###################

def _sort(tosort):
    sortby_mappings = {}
    distro_mappings = {}
    retlist = []

    for key, osinfo in tosort.items():
        # Libosinfo has some duplicate version numbers here, so append .1
        # if there's a collision
        sortby = osinfo.sortby
        while sortby_mappings.get(sortby):
            sortby = sortby + ".1"
        sortby_mappings[sortby] = key

        # Group distros by their urldistro value first, so debian is clumped
        # together, and fedora, etc.
        distro = osinfo.urldistro or "zzzzzzz"
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
            loader = libosinfo.Loader()
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
            for os in range(oslist.get_length()):
                osi = _OsVariant(oslist.get_nth(os))
                allvariants[osi.name] = osi

            self.__all_variants = allvariants
        return self.__all_variants


    ###############
    # Public APIs #
    ###############

    def lookup_os(self, key):
        key = self._aliases.get(key) or key
        return self._all_variants.get(key)

    def lookup_os_by_media(self, location):
        media = libosinfo.Media.create_from_location(location, None)
        ret = self._os_loader.get_db().guess_os_from_media(media)
        if not (ret and len(ret) > 0 and ret[0]):
            return None

        osname = ret[0].get_short_id()
        if osname == "fedora-unknown":
            osname = self.latest_fedora_version()
            logging.debug("Detected location=%s as os=fedora-unknown. "
                "Converting that to the latest fedora OS version=%s",
                location, osname)

        return osname

    def list_types(self):
        approved_types = ["linux", "windows", "bsd", "macos",
            "solaris", "other", "generic"]
        return approved_types

    def list_os(self):
        """
        List all OSes in the DB
        """
        sortmap = {}

        for name, osobj in self._all_variants.items():
            sortmap[name] = osobj

        return _sort(sortmap)

    def latest_regex(self, regex):
        """
        Return the latest distro name that matches the passed regex
        """
        oses = [o.name for o in self.list_os() if re.match(regex, o.name)]
        if not oses:
            return None
        return oses[0]

    def latest_fedora_version(self):
        return self.latest_regex("fedora[0-9]+")


#####################
# OsVariant classes #
#####################

class _OsVariant(object):
    def __init__(self, o):
        self._os = o
        self._family = self._os and self._os.get_family() or None

        self.name = self._os and self._os.get_short_id() or "generic"
        self.label = self._os and self._os.get_name() or "Generic"
        self.codename = self._os and self._os.get_codename() or ""
        self.distro = self._os and self._os.get_distro() or ""
        self.eol = False

        eol = self._os and self._os.get_eol_date() or None
        rel = self._os and self._os.get_release_date() or None

        # End of life if an EOL date is present and has past,
        # or if the release date is present and was 5 years or more
        if eol is not None:
            now = GLib.Date()
            now.set_time_t(time.time())
            if eol.compare(now) < 0:
                self.eol = True
        elif rel is not None:
            then = GLib.Date()
            then.set_time_t(time.time())
            then.subtract_years(5)
            if rel.compare(then) < 0:
                self.eol = True

        self.sortby = self._get_sortby()
        self.urldistro = self._get_urldistro()
        self._supported = None


    ########################
    # Internal helper APIs #
    ########################

    def _is_related_to(self, related_os_list, os=None,
            check_derives=True, check_upgrades=True, check_clones=True):
        os = os or self._os
        if not os:
            return False

        if os.get_short_id() in related_os_list:
            return True

        check_list = []
        def _extend(newl):
            for obj in newl:
                if obj not in check_list:
                    check_list.append(obj)

        if check_derives:
            _extend(os.get_related(
                libosinfo.ProductRelationship.DERIVES_FROM).get_elements())
        if check_clones:
            _extend(os.get_related(
                libosinfo.ProductRelationship.CLONES).get_elements())
        if check_upgrades:
            _extend(os.get_related(
                libosinfo.ProductRelationship.UPGRADES).get_elements())

        for checkobj in check_list:
            if (checkobj.get_short_id() in related_os_list or
                self._is_related_to(related_os_list, os=checkobj,
                    check_upgrades=check_upgrades,
                    check_derives=check_derives,
                    check_clones=check_clones)):
                return True

        return False


    ###############
    # Cached APIs #
    ###############

    def _get_sortby(self):
        if not self._os:
            return "1"

        version = self._os.get_version()
        try:
            t = version.split(".")
            t = t[:min(4, len(t))] + [0] * (4 - min(4, len(t)))
            new_version = ""
            for n in t:
                new_version = new_version + ("%.4i" % int(n))
            version = new_version
        except Exception:
            pass

        return "%s-%s" % (self.distro, version)

    def _get_supported(self):
        if not self._os:
            return True

        eol_date = self._os.get_eol_date_string()

        if eol_date:
            return (datetime.datetime.strptime(eol_date, "%Y-%m-%d") >
                    datetime.datetime.now())

        if self.name == "fedora-unknown":
            return False

        # As of libosinfo 2.11, many clearly EOL distros don't have an
        # EOL date. So assume None == EOL, add some manual work arounds.
        # We should fix this in a new libosinfo version, and then drop
        # this hack
        if self._is_related_to(["fedora24", "rhel7.0", "debian6",
            "ubuntu13.04", "win8", "win2k12", "mageia5", "centos7.0"],
            check_clones=False, check_derives=False):
            return True
        return False

    def _get_urldistro(self):
        if not self._os:
            return None
        urldistro = self.distro
        remap = {
            "opensuse": "suse",
            "sles": "suse",
            "mes": "mandriva"
        }

        if remap.get(urldistro):
            return remap[urldistro]

        return urldistro


    ###############
    # Public APIs #
    ###############

    def get_supported(self):
        if self._supported is None:
            self._supported = self._get_supported()
        return self._supported

    def get_typename(self):
        """
        Streamline the family name for use in the virt-manager UI
        """
        if not self._os:
            return "generic"

        if self._family in ['linux']:
            return "linux"

        if self._family in ['win9x', 'winnt', 'win16']:
            return "windows"

        if self._family in ['solaris']:
            return "solaris"

        if self._family in ['openbsd', 'freebsd', 'netbsd']:
            return "bsd"

        if self._family in ['darwin']:
            return "macos"

        return "other"

    def is_windows(self):
        return self.get_typename() == "windows"

    def need_old_xen_disable_acpi(self):
        return self._is_related_to(["winxp", "win2k"], check_upgrades=False)

    def broken_x2apic(self):
        # x2apic breaks networking in solaris10
        # https://bugs.launchpad.net/bugs/1395217
        return self.name in ('solaris10', 'solaris11')

    def get_clock(self):
        if self.is_windows() or self._family in ['solaris']:
            return "localtime"
        return "utc"

    def supports_virtiommio(self):
        return self._is_related_to(["fedora19"])

    def default_netmodel(self):
        """
        Default non-virtio net-model, since we check for that separately
        """
        if not self._os:
            return None

        fltr = libosinfo.Filter()
        fltr.add_constraint("class", "net")
        devs = self._os.get_all_devices(fltr)
        for idx in range(devs.get_length()):
            devname = devs.get_nth(idx).get_name()
            if devname in ["pcnet", "ne2k_pci", "rtl8139", "e1000"]:
                return devname
        return None

    def supports_usbtablet(self):
        if not self._os:
            return False

        fltr = libosinfo.Filter()
        fltr.add_constraint("class", "input")
        fltr.add_constraint("name", "tablet")
        devs = self._os.get_all_devices(fltr)
        for idx in range(devs.get_length()):
            if devs.get_nth(idx).get_bus_type() == "usb":
                return True
        return False

    def supports_virtiodisk(self):
        if self._os:
            fltr = libosinfo.Filter()
            fltr.add_constraint("class", "block")
            devs = self._os.get_all_devices(fltr)
            for dev in range(devs.get_length()):
                d = devs.get_nth(dev)
                if d.get_name() == "virtio-block":
                    return True

        return False

    def supports_virtionet(self):
        if self._os:
            fltr = libosinfo.Filter()
            fltr.add_constraint("class", "net")
            devs = self._os.get_all_devices(fltr)
            for dev in range(devs.get_length()):
                d = devs.get_nth(dev)
                if d.get_name() == "virtio-net":
                    return True

        return False

    def supports_virtiorng(self):
        if self._os:
            fltr = libosinfo.Filter()
            fltr.add_constraint("class", "rng")
            devs = self._os.get_all_devices(fltr)
            for dev in range(devs.get_length()):
                d = devs.get_nth(dev)
                if d.get_name() == "virtio-rng":
                    return True

        return False

    def supports_qemu_ga(self):
        return self._is_related_to(["debian8", "fedora18", "rhel6.0", "sles11sp4"])

    def default_videomodel(self, guest):
        if guest.os.is_pseries():
            return "vga"

        if guest.has_spice() and guest.os.is_x86():
            if guest.has_gl():
                return "virtio"
            else:
                return "qxl"

        if self.is_windows():
            return "vga"

        return None

    def get_recommended_resources(self, guest):
        ret = {}
        if not self._os:
            return ret

        def read_resource(resources, minimum, arch):
            # If we are reading the "minimum" block, allocate more
            # resources.
            ram_scale = minimum and 2 or 1
            n_cpus_scale = minimum and 2 or 1
            storage_scale = minimum and 2 or 1
            for i in range(resources.get_length()):
                r = resources.get_nth(i)
                if r.get_architecture() == arch:
                    ret["ram"] = r.get_ram() * ram_scale
                    ret["cpu"] = r.get_cpu()
                    ret["n-cpus"] = r.get_n_cpus() * n_cpus_scale
                    ret["storage"] = r.get_storage() * storage_scale
                    break

        # libosinfo may miss the recommended resources block for some OS,
        # in this case read first the minimum resources (if present)
        # and use them.
        read_resource(self._os.get_minimum_resources(), True, "all")
        read_resource(self._os.get_minimum_resources(), True, guest.os.arch)
        read_resource(self._os.get_recommended_resources(), False, "all")
        read_resource(self._os.get_recommended_resources(),
            False, guest.os.arch)

        # QEMU TCG doesn't gain anything by having extra VCPUs
        if guest.type == "qemu":
            ret["n-cpus"] = 1

        return ret

OSDB = _OSDB()
