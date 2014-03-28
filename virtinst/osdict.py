#
# List of OS Specific data
#
# Copyright 2006-2008, 2013 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

_SENTINEL = -1234
_allvariants = {}
from datetime import datetime
from gi.repository import Libosinfo as libosinfo  # pylint: disable=E0611

_aliases = {
    "altlinux" : "altlinux1.0",
    "debianetch" : "debian4",
    "debianlenny" : "debian5",
    "debiansqueeze" : "debian6",
    "debianwheezy" : "debian7",
    "freebsd10" : "freebsd10.0",
    "freebsd6" : "freebsd6.0",
    "freebsd7" : "freebsd7.0",
    "freebsd8" : "freebsd8.0",
    "freebsd9" : "freebsd9.0",
    "mandriva2009" : "mandriva2009.0",
    "mandriva2010" : "mandriva2010.0",
    "mbs1" : "mbs1.0",
    "msdos" : "msdos6.22",
    "openbsd4" : "openbsd4.2",
    "opensolaris" : "opensolaris2009.06",
    "opensuse11" : "opensuse11.4",
    "opensuse12" : "opensuse12.3",
    "rhel4" : "rhel4.0",
    "rhel5" : "rhel5.0",
    "rhel6" : "rhel6.0",
    "rhel7" : "rhel7.0",
    "ubuntuhardy" : "ubuntu8.04",
    "ubuntuintrepid" : "ubuntu8.10",
    "ubuntujaunty" : "ubuntu9.04",
    "ubuntukarmic" : "ubuntu9.10",
    "ubuntulucid" : "ubuntu10.04",
    "ubuntumaverick" : "ubuntu10.10",
    "ubuntunatty" : "ubuntu11.04",
    "ubuntuoneiric" : "ubuntu11.10",
    "ubuntuprecise" : "ubuntu12.04",
    "ubuntuquantal" : "ubuntu12.10",
    "ubunturaring" : "ubuntu13.04",
    "ubuntusaucy" : "ubuntu13.10",
    "vista" : "winvista",
    "winxp64" : "winxp",
}


def _sort(tosort, sortpref=None):
    sortby_mappings = {}
    distro_mappings = {}
    retlist = []
    sortpref = sortpref or []

    # Make sure we are sorting by 'sortby' if specified, and group distros
    # by their 'distro' tag first and foremost
    for key, osinfo in tosort.items():
        sortby = osinfo.sortby or key
        # Hack to allow "sortby" duplicates.  Remove when this never happens
        # with libosinfo
        while sortby_mappings.get(sortby):
            sortby = sortby + ".1"
        sortby_mappings[sortby] = key

        distro = osinfo.urldistro or "zzzzzzz"
        if distro not in distro_mappings:
            distro_mappings[distro] = []
        distro_mappings[distro].append(sortby)

    # We want returned lists to be sorted descending by 'distro', so we get
    # debian5, debian4, fedora14, fedora13
    #   rather than
    # debian4, debian5, fedora13, fedora14
    for distro_list in distro_mappings.values():
        distro_list.sort()
        distro_list.reverse()

    sorted_distro_list = distro_mappings.keys()
    sorted_distro_list.sort()
    sortpref.reverse()
    for prefer in sortpref:
        if not prefer in sorted_distro_list:
            continue
        sorted_distro_list.remove(prefer)
        sorted_distro_list.insert(0, prefer)

    for distro in sorted_distro_list:
        distro_list = distro_mappings[distro]
        for key in distro_list:
            orig_key = sortby_mappings[key]
            retlist.append(tosort[orig_key])

    return retlist


class _OSVariant(object):
    """
    Object tracking guest OS specific configuration bits.

    @name: name of the object. This must be lowercase. This becomes part of
        the virt-install command line API so we cannot remove any existing
        name (we could probably add aliases though)
    @label: Pretty printed label. This is used in the virt-manager UI.
        We can tweak this.
    @is_type: virt-install historically had a distinction between an
        os 'type' (windows, linux, etc), and an os 'variant' (fedora18,
        winxp, etc). Back in 2009 we actually required the user to
        specify --os-type if specifying an --os-variant even though we
        could figure it out easily. This distinction isn't needed any
        more, though it's still baked into the virt-manager UI where
        it is still pretty useful, so we fake it here. New types should
        not be added often.
    @parent: Name of a pre-created variant that we want to extend. So
        fedoraFOO would have parent fedoraFOO-1. It's used for inheriting
        values.
    @typename: The family of the OS, e.g. "linux", "windows", "unix".
    @sortby: A different key to use for sorting the distro list. By default
        it's 'name', so this doesn't need to be specified.
    @urldistro: This is a distro class. It's wired up in urlfetcher to give
        us a shortcut when detecting OS type from a URL.
    @supported: If this distro is supported by it's owning organization,
        like is it still receiving updates. We use this to limit the
        distros we show in virt-manager by default, so old distros aren't
        squeezing out current ones.
    @three_stage_install: If True, this VM has a 3 stage install, AKA windows.
    @virtionet: If True, this OS supports virtionet out of the box
    @virtiodisk: If True, this OS supports virtiodisk out of the box
    @virtiommio: If True, this OS supports virtio-mmio out of the box,
        which provides virtio for certain ARM configurations
    @virtioconsole: If True, this OS supports virtio-console out of the box,
        and we should use it as the default console.
    @xen_disable_acpi: If True, disable acpi/apic for this OS if on old xen.
        This corresponds with the SUPPORT_CONN_CAN_DEFAULT_ACPI check
    @qemu_ga: If True, this distro has qemu_ga available by default

    The rest of the parameters are about setting device/guest defaults
    based on the OS. They should be self explanatory. See guest.py for
    their usage.
    """
    def __init__(self, name, label, is_type=False,
                 sortby=None, parent=_SENTINEL, typename=_SENTINEL,
                 urldistro=_SENTINEL, supported=_SENTINEL,
                 three_stage_install=_SENTINEL,
                 acpi=_SENTINEL, apic=_SENTINEL, clock=_SENTINEL,
                 netmodel=_SENTINEL, diskbus=_SENTINEL,
                 inputtype=_SENTINEL, inputbus=_SENTINEL,
                 videomodel=_SENTINEL, virtionet=_SENTINEL,
                 virtiodisk=_SENTINEL, virtiommio=_SENTINEL,
                 virtioconsole=_SENTINEL, xen_disable_acpi=_SENTINEL,
                 qemu_ga=_SENTINEL):
        if is_type:
            if parent != _SENTINEL:
                raise RuntimeError("OS types must not specify parent")
            parent = None
        elif parent == _SENTINEL:
            raise RuntimeError("Must specify explicit parent")
        else:
            parent = _allvariants[parent]

        def _get_default(name, val, default=_SENTINEL):
            if val == _SENTINEL:
                if not parent:
                    return default
                return getattr(parent, name)
            return val

        if name != name.lower():
            raise RuntimeError("OS dictionary wants lowercase name, not "
                               "'%s'" % name)

        self.name = name
        self.label = label
        self.sortby = sortby

        self.is_type = bool(is_type)

        self.typename = typename
        if typename == _SENTINEL:
            self.typename = _get_default("typename",
                                     self.is_type and self.name or _SENTINEL)

        # 'types' should rarely be altered, this check will make
        # doubly sure that a new type isn't accidentally added
        _approved_types = ["linux", "windows", "unix",
                           "solaris", "other"]
        if self.typename not in _approved_types:
            raise RuntimeError("type '%s' for variant '%s' not in list "
                               "of approved distro types %s" %
                               (self.typename, self.name, _approved_types))

        self.urldistro = _get_default("urldistro", urldistro, None)
        self.supported = _get_default("supported", supported, False)
        self.three_stage_install = _get_default("three_stage_install",
                                                three_stage_install)

        self.acpi = _get_default("acpi", acpi)
        self.apic = _get_default("apic", apic)
        self.clock = _get_default("clock", clock)

        self.netmodel = _get_default("netmodel", netmodel)
        self.videomodel = _get_default("videomodel", videomodel)
        self.diskbus = _get_default("diskbus", diskbus)
        self.inputtype = _get_default("inputtype", inputtype)
        self.inputbus = _get_default("inputbus", inputbus)

        self.xen_disable_acpi = _get_default("xen_disable_acpi",
                                             xen_disable_acpi)
        self.virtiodisk = _get_default("virtiodisk", virtiodisk)
        self.virtionet = _get_default("virtionet", virtionet)
        self.virtiommio = _get_default("virtiommio", virtiommio)
        self.virtioconsole = _get_default("virtioconsole", virtioconsole)
        self.qemu_ga = _get_default("qemu_ga", qemu_ga)

    def get_recommended_resources(self, arch):
        ignore1 = arch
        return None


def _add_type(*args, **kwargs):
    kwargs["is_type"] = True
    _t = _OSVariant(*args, **kwargs)
    _allvariants[_t.name] = _t


def _add_var(*args, **kwargs):
    v = _OSVariant(*args, **kwargs)
    _allvariants[v.name] = v


class _OsVariantOsInfo(_OSVariant):

    @staticmethod
    def is_windows(o):
        return o.get_family() in ['win9x', 'winnt', 'win16']

    def _is_three_stage_install(self):
        if _OsVariantOsInfo.is_windows(self._os):
            return True
        return _SENTINEL

    def _get_clock(self):
        if _OsVariantOsInfo.is_windows(self._os) or \
           self._os.get_family() in ['solaris']:
            return "localtime"
        return _SENTINEL

    def _is_acpi(self):
        if self._os.get_family() in ['msdos']:
            return False
        return _SENTINEL

    def _is_apic(self):
        if self._os.get_family() in ['msdos']:
            return False
        return _SENTINEL

    def _get_netmodel(self):
        if self._os.get_distro() == "fedora":
            return _SENTINEL

        fltr = libosinfo.Filter()
        fltr.add_constraint("class", "net")
        devs = self._os.get_all_devices(fltr)
        if devs.get_length():
            return devs.get_nth(0).get_name()
        return _SENTINEL

    def _get_videomodel(self):
        if self._os.get_short_id() in {"ubuntu13.10", "ubuntu13.04"}:
            return "vmvga"

        if _OsVariantOsInfo.is_windows(self._os):
            return "vga"

        if self._os.get_distro() == "fedora":
            return _SENTINEL

        fltr = libosinfo.Filter()
        fltr.add_constraint("class", "video")
        devs = self._os.get_all_devices(fltr)
        if devs.get_length():
            return devs.get_nth(0).get_name()
        return _SENTINEL

    def _get_inputtype(self):
        fltr = libosinfo.Filter()
        fltr.add_constraint("class", "input")
        devs = self._os.get_all_devices(fltr)
        if devs.get_length():
            return devs.get_nth(0).get_name()
        return _SENTINEL

    def get_inputbus(self):
        fltr = libosinfo.Filter()
        fltr.add_constraint("class", "input")
        devs = self._os.get_all_devices(fltr)
        if devs.get_length():
            return devs.get_nth(0).get_bus_type()
        return _SENTINEL

    def _get_diskbus(self):
        return _SENTINEL

    @staticmethod
    def is_os_related_to(o, related_os_list):
        if o.get_short_id() in related_os_list:
            return True
        related = o.get_related(libosinfo.ProductRelationship.DERIVES_FROM)
        clones = o.get_related(libosinfo.ProductRelationship.CLONES)
        for r in related.get_elements() + clones.get_elements():
            if r.get_short_id() in related_os_list or \
               _OsVariantOsInfo.is_os_related_to(r, related_os_list):
                return True

        return False

    def _get_xen_disable_acpi(self):
        if _OsVariantOsInfo.is_os_related_to(self._os, ["winxp", "win2k"]):
            return True
        return _SENTINEL

    def _is_virtiodisk(self):
        if self._os.get_distro() == "fedora":
            if self._os.get_version() == "unknown":
                return _SENTINEL
            return int(self._os.get_version() >= 10) or _SENTINEL

        fltr = libosinfo.Filter()
        fltr.add_constraint("class", "block")
        devs = self._os.get_all_devices(fltr)
        for dev in range(devs.get_length()):
            d = devs.get_nth(dev)
            if d.get_name() == "virtio-block":
                return True

        return _SENTINEL

    def _is_virtionet(self):
        if self._os.get_distro() == "fedora":
            if self._os.get_version() == "unknown":
                return _SENTINEL
            return int(self._os.get_version() >= 9) or _SENTINEL

        fltr = libosinfo.Filter()
        fltr.add_constraint("class", "net")
        devs = self._os.get_all_devices(fltr)
        for dev in range(devs.get_length()):
            d = devs.get_nth(dev)
            if d.get_name() == "virtio-net":
                return True
        return _SENTINEL

    def _is_virtioconsole(self):
        if self._os.get_distro() == "fedora":
            if self._os.get_version() == "unknown":
                return _SENTINEL
            return int(self._os.get_version()) >= 18 or _SENTINEL

        fltr = libosinfo.Filter()
        fltr.add_constraint("class", "console")
        devs = self._os.get_all_devices(fltr)
        for dev in range(devs.get_length()):
            d = devs.get_nth(dev)
            if d.get_name() == "virtio-console":
                return True
        return _SENTINEL

    def _is_virtiommio(self):
        if _OsVariantOsInfo.is_os_related_to(self._os, ["fedora19"]):
            return True
        return _SENTINEL

    def _is_qemu_ga(self):
        if self._os.get_distro() == "fedora":
            if self._os.get_version() == "unknown":
                return _SENTINEL
            return int(self._os.get_version()) >= 18 or _SENTINEL
        return _SENTINEL

    def _get_typename(self):
        if self._os.get_family() in ['linux']:
            return "linux"

        if self._os.get_family() in ['win9x', 'winnt', 'win16']:
            return "windows"

        if self._os.get_family() in ['solaris']:
            return "solaris"

        if self._os.get_family() in ['openbsd', 'freebsd', 'netbsd']:
            return "unix"

        return "other"

    def _get_sortby(self):
        version = self._os.get_version()
        try:
            t = version.split(".")
            t = t[:min(4, len(t))] + [0] * (4 - min(4, len(t)))
            new_version = ""
            for n in t:
                new_version = new_version + ("%.4i" % int(n))
            version = new_version
        except:
            pass

        distro = self._os.get_distro()
        return "%s-%s" % (distro, version)

    def _get_supported(self):
        d = self._os.get_eol_date_string()
        if self._os.get_distro() == "msdos":
            return False
        return d is None or datetime.strptime(d, "%Y-%m-%d") > datetime.now()

    def _get_urldistro(self):
        urldistro = self._os.get_distro()
        remap = {
            "opensuse" : "suse",
            "sles" : "suse",
            "mes" : "mandriva"
        }

        if remap.get(urldistro):
            return remap[urldistro]

        return urldistro

    def _get_name(self):
        return self._os.get_short_id()

    def get_label(self):
        return self._os.get_name()

    def __init__(self, o):
        self._os = o
        name = self._get_name()
        label = self.get_label()
        sortby = self._get_sortby()
        is_type = False
        typename = self._get_typename()
        urldistro = self._get_urldistro()
        supported = self._get_supported()
        three_stage_install = self._is_three_stage_install()
        acpi = self._is_acpi()
        apic = self._is_apic()
        clock = self._get_clock()
        netmodel = self._get_netmodel()
        videomodel = self._get_videomodel()
        diskbus = self._get_diskbus()
        inputtype = self._get_inputtype()
        inputbus = self.get_inputbus()
        xen_disable_acpi = self._get_xen_disable_acpi()
        virtiodisk = self._is_virtiodisk()
        virtionet = self._is_virtionet()
        virtiommio = self._is_virtiommio()
        virtioconsole = self._is_virtioconsole()
        qemu_ga = self._is_qemu_ga()
        _OSVariant.__init__(self, name=name, label=label, is_type=is_type,
                typename=typename, sortby=sortby, parent="generic",
                urldistro=urldistro, supported=supported,
                three_stage_install=three_stage_install, acpi=acpi, apic=apic,
                clock=clock, netmodel=netmodel, diskbus=diskbus,
                inputtype=inputtype, inputbus=inputbus, videomodel=videomodel,
                virtionet=virtionet, virtiodisk=virtiodisk,
                virtiommio=virtiommio, virtioconsole=virtioconsole,
                xen_disable_acpi=xen_disable_acpi, qemu_ga=qemu_ga)

    def get_recommended_resources(self, arch):
        ret = {}
        def read_resource(resources, arch):
            for i in range(resources.get_length()):
                r = resources.get_nth(i)
                if r.get_architecture() == arch:
                    ret["ram"] = r.get_ram()
                    ret["cpu"] = r.get_cpu()
                    ret["n-cpus"] = r.get_n_cpus()
                    ret["storage"] = r.get_storage()
                    break

        read_resource(self._os.get_recommended_resources(), "all")
        read_resource(self._os.get_recommended_resources(), arch)

        return ret

_add_type("linux", "Linux")
_add_type("windows", "Windows", clock="localtime", three_stage_install=True, inputtype="tablet", inputbus="usb", videomodel="vga")
_add_type("solaris", "Solaris", clock="localtime")
_add_type("unix", "UNIX")
_add_type("other", "Other")
_add_var("generic", "Generic", supported=True, parent="other")


_os_data_loaded = False
_os_loader = None


def _get_os_loader():
    global _os_loader
    if _os_loader:
        return _os_loader
    _os_loader = libosinfo.Loader()
    _os_loader.process_default_path()
    return _os_loader


def _load_os_data():
    global _os_data_loaded
    if _os_data_loaded:
        return
    loader = _get_os_loader()
    db = loader.get_db()
    oslist = db.get_os_list()
    for os in range(oslist.get_length()):
        osi = _OsVariantOsInfo(oslist.get_nth(os))
        _allvariants[osi.name] = osi
    _os_data_loaded = True


def lookup_os(key):
    _load_os_data()
    key = _aliases.get(key) or key
    ret = _allvariants.get(key)
    if ret is None:
        return ret
    return ret


def list_os(list_types=False, typename=None,
            filtervars=None, only_supported=False,
            **kwargs):
    _load_os_data()
    sortmap = {}
    filtervars = filtervars or []

    for key, osinfo in _allvariants.items():
        if list_types and not osinfo.is_type:
            continue
        if not list_types and osinfo.is_type:
            continue
        if typename and typename != osinfo.typename:
            continue
        if filtervars:
            filtervars = [lookup_os(x).name for x in filtervars]
            if osinfo.name not in filtervars:
                continue
        if only_supported and not osinfo.supported:
            continue
        sortmap[key] = osinfo
    return _sort(sortmap, **kwargs)


def lookup_osdict_key(variant, key, default):
    _load_os_data()
    val = _SENTINEL
    if variant is not None:
        if not hasattr(lookup_os(variant), key):
            raise ValueError("Unknown osdict property '%s'" % key)
        val = getattr(lookup_os(variant), key)
    if val == _SENTINEL:
        val = default
    return val


def get_recommended_resources(variant, arch):
    _load_os_data()
    v = _allvariants.get(variant)
    if v is None:
        return None

    return v.get_recommended_resources(arch)


def lookup_os_by_media(location):
    loader = _get_os_loader()
    media = libosinfo.Media.create_from_location(location, None)
    ret = loader.get_db().guess_os_from_media(media)
    if ret and len(ret) > 0:
        return ret[0].get_short_id()
    return None
