#
# List of OS Specific data
#
# Copyright 2006-2008  Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
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

from virtinst import support
from virtinst import VirtualDevice

HV_ALL = "all"

# Default values for OS_TYPES keys. Can be overwritten at os_type or
# variant level

NET   = VirtualDevice.VIRTUAL_DEV_NET
DISK  = VirtualDevice.VIRTUAL_DEV_DISK
INPUT = VirtualDevice.VIRTUAL_DEV_INPUT
SOUND = VirtualDevice.VIRTUAL_DEV_AUDIO
VIDEO = VirtualDevice.VIRTUAL_DEV_VIDEO

VIRTIO_DISK = {
    "bus" : [
        (support.SUPPORT_CONN_HV_VIRTIO, "virtio"),
   ]
}

VIRTIO_NET = {
    "model" : [
        (support.SUPPORT_CONN_HV_VIRTIO, "virtio"),
   ]
}

USB_TABLET = {
    "type" : [
        (HV_ALL, "tablet"),
   ],
    "bus"  : [
        (HV_ALL, "usb"),
   ]
}

VGA_VIDEO = {
    "model": [
        (HV_ALL, "vga"),
   ]
}

VMVGA_VIDEO = {
    "model": [
        (HV_ALL, "vmvga"),
    ]
}

DEFAULTS = {
    "acpi":             True,
    "apic":             True,
    "clock":            "utc",
    "cont":         False,
    "distro":           None,
    "label":            None,
    "supported":        False,

    "devices" : {
        #  "devname" : {"attribute" : [(["applicable", "hv-type", list"],
        #                               "recommended value for hv-types"),]},
        INPUT   : {
            "type" : [
                (HV_ALL, "mouse")
            ],
            "bus"  : [
                (HV_ALL, "ps2")
           ],
       },

        DISK    : {
            "bus"  : [
                (HV_ALL, None)
           ],
       },

        NET     : {
            "model": [
                (HV_ALL, None)
           ],
       },

        SOUND : {
            "model": [
                (support.SUPPORT_CONN_HV_SOUND_ICH6, "ich6"),
                (support.SUPPORT_CONN_HV_SOUND_AC97, "ac97"),
                (HV_ALL, "es1370"),
           ]
       },

        VIDEO : {
            "model": [
                (HV_ALL, "cirrus"),
           ]
       },
   }
}

_SENTINEL = -1234
OS_TYPES = {}
_allvariants = {}


def lookup_os(key):
    ret = _allvariants.get(key)
    if ret is None:
        return ret
    return ret


def sort_helper(tosort, sortpref=None):
    """
    Helps properly sorting os dictionary entires
    """
    sortby_mappings = {}
    distro_mappings = {}
    retlist = []
    sortpref = sortpref or []

    # Make sure we are sorting by 'sortby' if specified, and group distros
    # by their 'distro' tag first and foremost
    for key, osinfo in tosort.items():
        if osinfo.get("skip"):
            continue

        sortby = osinfo.get("sortby")
        if not sortby:
            sortby = key
        sortby_mappings[sortby] = key

        distro = osinfo.get("distro") or "zzzzzzz"
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
            retlist.append(orig_key)

    return retlist


def parse_key_entry(conn, hv_type, key_entry, defaults):
    ret = None
    found = False
    if type(key_entry) == list:

        # List of tuples with (support -> value) mappings
        for tup in key_entry:

            support_key = tup[0]
            value = tup[1]

            # HV_ALL means don't check for support, just return the value
            if support_key != HV_ALL:
                support_ret = conn.check_conn_hv_support(support_key, hv_type)

                if support_ret is not True:
                    continue

            found = True
            ret = value
            break
    else:
        found = True
        ret = key_entry

    if not found and defaults:
        ret = parse_key_entry(conn, hv_type, defaults, None)

    return ret


def lookup_osdict_key(conn, hv_type, var, key):
    defaults = DEFAULTS[key]
    dictval = defaults

    if var is not None:
        vardict = _allvariants[var].to_dict()
        if key in vardict:
            dictval = vardict[key]

    return parse_key_entry(conn, hv_type, dictval, defaults)


def lookup_device_param(conn, hv_type, var, device_key, param):
    os_devs = lookup_osdict_key(conn, hv_type, var, "devices")
    defaults = DEFAULTS["devices"]

    for devs in [os_devs, defaults]:
        if device_key not in devs:
            continue

        return parse_key_entry(conn, hv_type, devs[device_key][param],
                               defaults.get(param))

    raise RuntimeError(_("Invalid dictionary entry for device '%s %s'" %
                       (device_key, param)))


# 'types' should rarely be altered, this check will make
# doubly sure that a new type isn't accidentally added
_approved_types = ["linux", "windows", "unix", "solaris", "other"]


def _add_type(*args, **kwargs):
    kwargs["is_type"] = True
    _t = _OSVariant(*args, **kwargs)

    if _t.name not in _approved_types:
        raise RuntimeError("type '%s' not in list of approved distro types %s"
                           % (t.name, _approved_types))

    OS_TYPES[_t.name] = _t.to_dict()
    OS_TYPES[_t.name]["variants"] = {}
    _allvariants[_t.name] = _t
    return _t


class _OSVariant(object):
    def __init__(self, name, label, is_type=False,
                 sortby=None, parent=_SENTINEL,
                 distro=_SENTINEL, cont=_SENTINEL, supported=_SENTINEL,
                 devices=_SENTINEL, acpi=_SENTINEL,
                 apic=_SENTINEL, clock=_SENTINEL):
        if parent == _SENTINEL:
            raise RuntimeError("Must specify explicit parent")
        elif parent is None:
            if not is_type:
                raise RuntimeError("Only OS types can have parent=None")
        else:
            parent = _allvariants[parent]

        def _get_default(name, val, default):
            if val == _SENTINEL:
                if parent:
                    return getattr(parent, name)
                return default
            return val

        self.name = name.lower()
        self.label = label
        self.sortby = sortby

        self.is_type = bool(is_type)
        self.typename = _get_default("typename", _SENTINEL, self.name)

        if self.typename not in _approved_types:
            raise RuntimeError("type '%s' for variant '%s' not in list "
                               "of approved distro types %s" %
                               (self.typename, self.name, _approved_types))

        self.distro = _get_default("distro", distro, None)
        self.supported = bool(_get_default("supported", supported, False))
        self.cont = bool(_get_default("cont", cont, False))

        self.devices = _get_default("devices", devices, None)
        self.acpi = _get_default("acpi", acpi, None)
        self.apic = _get_default("apic", apic, None)
        self.clock = _get_default("clock", clock, None)

    def to_dict(self):
        ret = {}
        allparams = ["label", "distro", "sortby", "supported",
                     "cont", "devices", "apic", "acpi", "clock"]
        canfalse = ["apic", "acpi"]
        for param in allparams:
            val = getattr(self, param)
            if param in canfalse and val is False:
                pass
            elif not val:
                continue
            ret[param] = val
        return ret

    def add(self, *args, **kwargs):
        v = _OSVariant(*args, **kwargs)
        OS_TYPES[self.name]["variants"][v.name] = v.to_dict()
        _allvariants[v.name] = v

t = _add_type("linux", "Linux", parent=None)
t.add("rhel2.1", "Red Hat Enterprise Linux 2.1", distro="rhel", parent="linux")
t.add("rhel3", "Red Hat Enterprise Linux 3", parent="rhel2.1")
t.add("rhel4", "Red Hat Enterprise Linux 4", supported=True, parent="rhel3")
t.add("rhel5", "Red Hat Enterprise Linux 5", supported=False, parent="rhel4")
t.add("rhel5.4", "Red Hat Enterprise Linux 5.4 or later", supported=True, devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="rhel5")
t.add("rhel6", "Red Hat Enterprise Linux 6", devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET, INPUT: USB_TABLET}, parent="rhel5.4")
t.add("rhel7", "Red Hat Enterprise Linux 7", supported=False, parent="rhel6")

t.add("fedora5", "Fedora Core 5", sortby="fedora05", distro="fedora", parent="linux")
t.add("fedora6", "Fedora Core 6", sortby="fedora06", parent="fedora5")
t.add("fedora7", "Fedora 7", sortby="fedora07", parent="fedora6")
t.add("fedora8", "Fedora 8", sortby="fedora08", parent="fedora7")
# Apparently F9 has selinux errors when installing with virtio:
# https: //bugzilla.redhat.com/show_bug.cgi?id=470386
t.add("fedora9", "Fedora 9", sortby="fedora09", devices={NET: VIRTIO_NET}, parent="fedora8")
t.add("fedora10", "Fedora 10", devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="fedora9")
t.add("fedora11", "Fedora 11", devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET, INPUT: USB_TABLET}, parent="fedora10")
t.add("fedora12", "Fedora 12", parent="fedora11")
t.add("fedora13", "Fedora 13", parent="fedora12")
t.add("fedora14", "Fedora 14", parent="fedora13")
t.add("fedora15", "Fedora 15", parent="fedora14")
t.add("fedora16", "Fedora 16", parent="fedora15")
t.add("fedora17", "Fedora 17", supported=True, parent="fedora16")
t.add("fedora18", "Fedora 18", parent="fedora17")
t.add("fedora19", "Fedora 19", parent="fedora18")

t.add("opensuse11", "openSuse 11", distro="suse", supported=True, devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="linux")
t.add("opensuse12", "openSuse 12", parent="opensuse11")

t.add("sles10", "Suse Linux Enterprise Server", distro="suse", supported=True, parent="linux")
t.add("sles11", "Suse Linux Enterprise Server 11", supported=True, devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="sles10")

t.add("mandriva2009", "Mandriva Linux 2009 and earlier", distro="mandriva", parent="linux")
t.add("mandriva2010", "Mandriva Linux 2010 and later", devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="mandriva2009")

t.add("mes5", "Mandriva Enterprise Server 5.0", distro="mandriva", parent="linux")
t.add("mes5.1", "Mandriva Enterprise Server 5.1 and later", supported=True, devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="mes5")

t.add("mageia1", "Mageia 1 and later", distro="mageia", supported=True, devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET, INPUT: USB_TABLET}, parent="linux")

t.add("altlinux", "ALT Linux", distro="altlinux", supported=True, devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET, INPUT: USB_TABLET}, parent="linux")

t.add("debianetch", "Debian Etch", distro="debian", sortby="debian4", parent="linux")
t.add("debianlenny", "Debian Lenny", sortby="debian5", supported=True, devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="debianetch")
t.add("debiansqueeze", "Debian Squeeze", sortby="debian6", devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET, INPUT: USB_TABLET}, parent="debianlenny")
t.add("debianwheezy", "Debian Wheezy", sortby="debian7", parent="debiansqueeze")

t.add("ubuntuhardy", "Ubuntu 8.04 LTS (Hardy Heron)", distro="ubuntu", devices={NET: VIRTIO_NET}, parent="linux")
t.add("ubuntuintrepid", "Ubuntu 8.10 (Intrepid Ibex)", parent="ubuntuhardy")
t.add("ubuntujaunty", "Ubuntu 9.04 (Jaunty Jackalope)", devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="ubuntuintrepid")
t.add("ubuntukarmic", "Ubuntu 9.10 (Karmic Koala)", parent="ubuntujaunty")
t.add("ubuntulucid", "Ubuntu 10.04 LTS (Lucid Lynx)", supported=True, parent="ubuntukarmic")
t.add("ubuntumaverick", "Ubuntu 10.10 (Maverick Meerkat)", supported=False, parent="ubuntulucid")
t.add("ubuntunatty", "Ubuntu 11.04 (Natty Narwhal)", parent="ubuntumaverick")
t.add("ubuntuoneiric", "Ubuntu 11.10 (Oneiric Ocelot)", parent="ubuntunatty")
t.add("ubuntuprecise", "Ubuntu 12.04 LTS (Precise Pangolin)", supported=True, parent="ubuntuoneiric")
t.add("ubuntuquantal", "Ubuntu 12.10 (Quantal Quetzal)", parent="ubuntuprecise")
t.add("ubunturaring", "Ubuntu 13.04 (Raring Ringtail)", devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET, VIDEO: VMVGA_VIDEO}, parent="ubuntuquantal")
t.add("ubuntusaucy", "Ubuntu 13.10 (Saucy Salamander)", parent="ubunturaring")

t.add("generic24", "Generic 2.4.x kernel", parent="linux")
t.add("generic26", "Generic 2.6.x kernel", parent="generic24")
t.add("virtio26", "Generic 2.6.25 or later kernel with virtio", sortby="genericvirtio26", devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="generic26")



t = _add_type("windows", "Windows", clock="localtime", cont=True, devices={INPUT: USB_TABLET, VIDEO: VGA_VIDEO}, parent=None)
t.add("win2k", "Microsoft Windows 2000", sortby="mswin4",  acpi=[(support.SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI, False)], apic=[(support.SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI, False)], parent="windows")
t.add("winxp", "Microsoft Windows XP", sortby="mswin5", supported=True, acpi=[(support.SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI, False)], apic=[(support.SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI, False)], parent="windows")
t.add("winxp64", "Microsoft Windows XP (x86_64)", supported=True, sortby="mswin564", parent="windows")
t.add("win2k3", "Microsoft Windows Server 2003", supported=True, sortby="mswinserv2003", parent="windows")
t.add("win2k8", "Microsoft Windows Server 2008", supported=True, sortby="mswinserv2008", parent="windows")
t.add("vista", "Microsoft Windows Vista", supported=True, sortby="mswin6", parent="windows")
t.add("win7", "Microsoft Windows 7", supported=True, sortby="mswin7", parent="windows")


t = _add_type("solaris", "Solaris", clock="localtime", parent=None)
t.add("solaris9", "Sun Solaris 9", parent="solaris")
t.add("solaris10", "Sun Solaris 10", devices={INPUT: USB_TABLET}, parent="solaris")
t.add("opensolaris", "Sun OpenSolaris", devices={INPUT: USB_TABLET}, parent="solaris")


t = _add_type("unix", "UNIX", parent=None)
# http: //www.nabble.com/Re%3A-Qemu%3A-bridging-on-FreeBSD-7.0-STABLE-p15919603.html
t.add("freebsd6", "FreeBSD 6.x", devices={NET: {"model": [(HV_ALL, "ne2k_pci")]}}, parent="unix")
t.add("freebsd7", "FreeBSD 7.x", parent="freebsd6")
t.add("freebsd8", "FreeBSD 8.x", supported=True, devices={NET: {"model": [(HV_ALL, "e1000")]}}, parent="freebsd7")
t.add("freebsd9", "FreeBSD 9.x", parent="freebsd8")
t.add("freebsd10", "FreeBSD 10.x", supported=False, devices={DISK: VIRTIO_DISK, NET: VIRTIO_NET}, parent="freebsd9")

# http: //calamari.reverse-dns.net: 980/cgi-bin/moin.cgi/OpenbsdOnQemu
# https: //www.redhat.com/archives/et-mgmt-tools/2008-June/msg00018.html
t.add("openbsd4", "OpenBSD 4.x", devices={NET: {"model": [(HV_ALL, "pcnet")]}}, parent="unix")



t = _add_type("other", "Other", parent=None)
t.add("msdos", "MS-DOS", acpi=False, apic=False, parent="other")
t.add("netware4", "Novell Netware 4", parent="other")
t.add("netware5", "Novell Netware 5", parent="other")
t.add("netware6", "Novell Netware 6", parent="other")
t.add("generic", "Generic", supported=True, parent="other")
