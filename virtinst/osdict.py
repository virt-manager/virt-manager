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

import gi
gi.require_version('Libosinfo', '1.0')
from gi.repository import Libosinfo as libosinfo


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

        # Group by distro first, so debian is clumped together, fedora, etc.
        distro = osinfo.distro
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

    def lookup_os_by_full_id(self, full_id):
        for osobj in self._all_variants.values():
            if osobj.full_id == full_id:
                return osobj

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

        self.full_id = self._os and self._os.get_id() or None
        self.name = self._os and self._os.get_short_id() or "generic"
        self.label = self._os and self._os.get_name() or "Generic"
        self.codename = self._os and self._os.get_codename() or ""
        self.distro = self._os and self._os.get_distro() or ""

        self.eol = self._get_eol()
        self.sortby = self._get_sortby()


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

    def _get_all_devices(self):
        if not self._os:
            return []
        devlist = self._os.get_all_devices()
        return [devlist.get_nth(i) for i in range(devlist.get_length())]

    def _device_filter(self, name=None, cls=None, bus=None):
        ret = []
        for dev in self._get_all_devices():
            if name and not re.match(name, dev.get_name()):
                continue
            if cls and not re.match(cls, dev.get_class()):
                continue
            if bus and not re.match(bus, dev.get_bus_type()):
                continue
            ret.append(dev.get_name())
        return ret


    ###############
    # Cached APIs #
    ###############

    def _get_eol(self):
        eol = self._os and self._os.get_eol_date() or None
        rel = self._os and self._os.get_release_date() or None

        def _glib_to_datetime(glibdate):
            date = "%s-%s" % (glibdate.get_year(), glibdate.get_day_of_year())
            return datetime.datetime.strptime(date, "%Y-%j")

        now = datetime.datetime.today()
        if eol is not None:
            return now > _glib_to_datetime(eol)

        # If no EOL is present, assume EOL if release was > 5 years ago
        if rel is not None:
            rel5 = _glib_to_datetime(rel) + datetime.timedelta(days=365 * 5)
            return now > rel5
        return False

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


    ###############
    # Public APIs #
    ###############

    def is_windows(self):
        return self._family in ['win9x', 'winnt', 'win16']

    def broken_x2apic(self):
        # x2apic breaks networking in solaris10
        # https://bugs.launchpad.net/bugs/1395217
        return self.name in ('solaris10', 'solaris11')

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
        return bool(self._device_filter(cls="input", name="tablet", bus="usb"))

    def supports_virtiodisk(self):
        return bool(self._device_filter(cls="block", name="virtio.*-block"))

    def supports_virtionet(self):
        return bool(self._device_filter(cls="net", name="virtio.*-net"))

    def supports_virtiorng(self):
        return bool(self._device_filter(cls="rng", name="virtio.*-rng"))

    def supports_virtioserial(self):
        if self._device_filter(cls="console", name="virtio.*-console"):
            return True
        # 2018-09-01: osinfo data is wrong for RHEL/centos here
        return self._is_related_to("rhel6.0")

    def supports_chipset_q35(self):
        return False

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
