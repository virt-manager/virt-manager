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
from virtinst.VirtualDevice import VirtualDevice

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
    "model_type": [
        (HV_ALL, "vga"),
   ]
}

DEFAULTS = {
    "acpi":             True,
    "apic":             True,
    "clock":            "utc",
    "continue":         False,
    "distro":           None,
    "label":            None,
    "pv_cdrom_install": False,
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
            "model_type": [
                (HV_ALL, "cirrus"),
           ]
       },
   }
}


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
                support_ret = support.check_conn_hv_support(conn,
                                                            support_key,
                                                            hv_type)

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


def lookup_osdict_key(conn, hv_type, os_type, var, key):

    defaults = DEFAULTS[key]
    dictval = defaults
    if os_type:
        if var and key in OS_TYPES[os_type]["variants"][var]:
            dictval = OS_TYPES[os_type]["variants"][var][key]
        elif key in OS_TYPES[os_type]:
            dictval = OS_TYPES[os_type][key]

    return parse_key_entry(conn, hv_type, dictval, defaults)


def lookup_device_param(conn, hv_type, os_type, var, device_key, param):

    os_devs = lookup_osdict_key(conn, hv_type, os_type, var, "devices")
    defaults = DEFAULTS["devices"]

    for devs in [os_devs, defaults]:
        if device_key not in devs:
            continue

        return parse_key_entry(conn, hv_type, devs[device_key][param],
                               defaults.get(param))

    raise RuntimeError(_("Invalid dictionary entry for device '%s %s'" %
                       (device_key, param)))


# NOTE: keep variant keys using only lowercase so we can do case
#       insensitive checks on user passed input
OS_TYPES = {
"linux": {
    "label": "Linux",
    "variants": {

    "rhel2.1": {
        "label": "Red Hat Enterprise Linux 2.1",
        "distro": "rhel"
   },
    "rhel3": {
        "label": "Red Hat Enterprise Linux 3",
        "distro": "rhel"
   },
    "rhel4": {
        "label": "Red Hat Enterprise Linux 4",
        "distro": "rhel",
        "supported": True,
   },
    "rhel5": {
        "label": "Red Hat Enterprise Linux 5",
        "distro": "rhel",
   },
    "rhel5.4": {
        "label": "Red Hat Enterprise Linux 5.4 or later",
        "distro": "rhel",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "rhel6": {
        "label": "Red Hat Enterprise Linux 6",
        "distro": "rhel",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },
    "rhel7": {
        "label": "Red Hat Enterprise Linux 7",
        "distro": "rhel",
        "supported": False,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },

    "fedora5": {
        "sortby": "fedora05",
        "label": "Fedora Core 5",
        "distro": "fedora"
   },
    "fedora6": {
        "sortby": "fedora06",
        "label": "Fedora Core 6",
        "distro": "fedora"
   },
    "fedora7": {
        "sortby": "fedora07",
        "label": "Fedora 7",
        "distro": "fedora"
   },
    "fedora8": {
        "sortby": "fedora08",
        "label": "Fedora 8",
        "distro": "fedora"
   },
    "fedora9": {
        "sortby":  "fedora09",
        "label": "Fedora 9",
        "distro": "fedora",
        "devices" : {
            # Apparently F9 has selinux errors when installing with virtio:
            # https://bugzilla.redhat.com/show_bug.cgi?id=470386
            # DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       }
   },
    "fedora10": {
        "label": "Fedora 10",
        "distro": "fedora",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       }
   },
    "fedora11": {
        "label": "Fedora 11",
        "distro": "fedora",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },
    "fedora12": {
        "label": "Fedora 12",
        "distro": "fedora",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },
    "fedora13": {
        "label": "Fedora 13", "distro": "fedora",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },
    "fedora14": {
        "label": "Fedora 14",
        "distro": "fedora",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },
    "fedora15": {
        "label": "Fedora 15",
        "distro": "fedora",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },
    "fedora16": {
        "label": "Fedora 16",
        "distro": "fedora",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },
    "fedora17": {
        "label": "Fedora 17",
        "distro": "fedora",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },
    "fedora18": {
        "label": "Fedora 18",
        "distro": "fedora",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },

    "opensuse11": {
        "label": "openSuse 11",
        "distro": "suse",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "opensuse12": {
        "label": "openSuse 12",
        "distro": "suse",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },

    "sles10": {
        "label": "Suse Linux Enterprise Server",
        "distro": "suse",
        "supported": True,
   },
    "sles11": {
        "label": "Suse Linux Enterprise Server 11",
        "distro": "suse",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },

    "mandriva2009": {
        "label": "Mandriva Linux 2009 and earlier",
        "distro": "mandriva"
   },
    "mandriva2010": {
        "label": "Mandriva Linux 2010 and later",
        "distro": "mandriva",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },

    "mes5": {
        "label": "Mandriva Enterprise Server 5.0",
        "distro": "mandriva",
   },
    "mes5.1": {
        "label": "Mandriva Enterprise Server 5.1 and later",
        "distro": "mandriva",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },

    "mageia1": {
        "label": "Mageia 1 and later",
        "distro": "mageia",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       },
   },


    "debianetch": {
        "label": "Debian Etch",
        "distro": "debian",
        "sortby": "debian4",
   },
    "debianlenny": {
        "label": "Debian Lenny",
        "distro": "debian",
        "sortby": "debian5",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "debiansqueeze": {
        "label": "Debian Squeeze",
        "distro": "debian",
        "sortby": "debian6",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
            INPUT: USB_TABLET,
       }
   },
    "debianwheezy": {
        "label": "Debian Wheezy",
        "distro": "debian",
        "sortby": "debian7",
        "supported": True,
        "devices" : {
                   DISK : VIRTIO_DISK,
                   NET  : VIRTIO_NET,
                   INPUT: USB_TABLET,
       }
   },

    "ubuntuhardy": {
        "label": "Ubuntu 8.04 LTS (Hardy Heron)",
        "distro": "ubuntu",
        "supported": True,
        "devices" : {
            NET  : VIRTIO_NET,
       },
   },
    "ubuntuintrepid": {
        "label": "Ubuntu 8.10 (Intrepid Ibex)",
        "distro": "ubuntu",
        "devices" : {
            NET  : VIRTIO_NET,
       },
   },
    "ubuntujaunty": {
        "label": "Ubuntu 9.04 (Jaunty Jackalope)",
        "distro": "ubuntu",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "ubuntukarmic": {
        "label": "Ubuntu 9.10 (Karmic Koala)",
        "distro": "ubuntu",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "ubuntulucid": {
        "label": "Ubuntu 10.04 LTS (Lucid Lynx)",
        "distro": "ubuntu",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "ubuntumaverick": {
        "label": "Ubuntu 10.10 (Maverick Meerkat)",
        "distro": "ubuntu",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "ubuntunatty": {
        "label": "Ubuntu 11.04 (Natty Narwhal)",
        "distro": "ubuntu",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "ubuntuoneiric": {
        "label": "Ubuntu 11.10 (Oneiric Ocelot)",
        "distro": "ubuntu",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "ubuntuprecise": {
        "label": "Ubuntu 12.04 LTS (Precise Pangolin)",
        "distro": "ubuntu",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },
    "ubuntuquantal": {
        "label": "Ubuntu 12.10 (Quantal Quetzal)",
        "distro": "ubuntu",
        "supported": True,
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },

    "generic24": {
        "label": "Generic 2.4.x kernel"
   },
    "generic26": {
        "label": "Generic 2.6.x kernel"
   },
    "virtio26": {
        "sortby": "genericvirtio26",
        "label": "Generic 2.6.25 or later kernel with virtio",
        "devices" : {
            DISK : VIRTIO_DISK,
            NET  : VIRTIO_NET,
       },
   },

   },
},

"windows": {
    "label": "Windows",
    "clock": "localtime",
    "continue": True,
    "devices" : {
        INPUT : USB_TABLET,
        VIDEO : VGA_VIDEO,
   },

    "variants": {

    "winxp": {
        "label": "Microsoft Windows XP",
        "sortby": "mswin5",
        "distro" : "win",
        "supported": True,
        "acpi": [(support.SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI, False)],
        "apic": [(support.SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI, False)],
   },
    "winxp64": {
        "label": "Microsoft Windows XP (x86_64)",
        "supported": True,
        "sortby": "mswin564",
        "distro": "win",
   },
    "win2k": {
        "label": "Microsoft Windows 2000",
        "sortby" : "mswin4",
        "distro": "win",
        "acpi": [(support.SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI, False)],
        "apic": [(support.SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI, False)],
   },
    "win2k3": {
        "label": "Microsoft Windows Server 2003",
        "supported": True,
        "sortby" : "mswinserv2003",
        "distro": "winserv",
   },
    "win2k8": {
        "label": "Microsoft Windows Server 2008",
        "supported": True,
        "sortby": "mswinserv2008",
        "distro": "winserv",
   },
    "vista": {
        "label": "Microsoft Windows Vista",
        "supported": True,
        "sortby": "mswin6",
        "distro": "win",
   },
    "win7": {
        "label": "Microsoft Windows 7",
        "supported": True,
        "sortby": "mswin7",
        "distro": "win",
   },

   },
},

"solaris": {
    "label": "Solaris",
    "clock": "localtime",
    "pv_cdrom_install": True,
    "variants": {

    "solaris9": {
        "label": "Sun Solaris 9",
   },
    "solaris10": {
        "label": "Sun Solaris 10",
        "devices" : {
            INPUT : USB_TABLET,
       },
   },
    "opensolaris": {
        "label": "Sun OpenSolaris",
        "devices" : {
            INPUT : USB_TABLET,
       },
   },

   },
},

"unix": {
    "label": "UNIX",
    "variants": {

    "freebsd6": {
        "label": "FreeBSD 6.x" ,
        # http://www.nabble.com/Re%3A-Qemu%3A-bridging-on-FreeBSD-7.0-STABLE-p15919603.html
        "devices" : {
            NET : {"model" : [(HV_ALL, "ne2k_pci")]}
       },
   },
    "freebsd7": {
        "label": "FreeBSD 7.x" ,
        "devices" : {
            NET : {"model" : [(HV_ALL, "ne2k_pci")]}
       },
   },
    "freebsd8": {
        "label": "FreeBSD 8.x" ,
        "supported": True,
        "devices" : {
            NET : {"model" : [(HV_ALL, "e1000")]}
       },
   },

    "openbsd4": {
        "label": "OpenBSD 4.x" ,
        # http://calamari.reverse-dns.net:980/cgi-bin/moin.cgi/OpenbsdOnQemu
        # https://www.redhat.com/archives/et-mgmt-tools/2008-June/msg00018.html
        "devices" : {
            NET  : {"model" : [(HV_ALL, "pcnet")]}
       },
   },

   },
},

"other": {
    "label": "Other",
    "variants": {

    "msdos": {
        "label": "MS-DOS",
        "acpi": False,
        "apic": False,
   },

    "netware4": {
        "label": "Novell Netware 4",
   },
    "netware5": {
        "label": "Novell Netware 5",
   },
    "netware6": {
        "label": "Novell Netware 6",
        "pv_cdrom_install": True,
   },

    "generic": {
        "supported": True,
        "label": "Generic"
   },

   },
}
}

# Back compatibility entries
solaris_compat = OS_TYPES["unix"]["variants"]

solaris_compat["solaris9"] = OS_TYPES["solaris"]["variants"]["solaris9"].copy()
solaris_compat["solaris9"]["skip"] = True

solaris_compat["solaris10"] = OS_TYPES["solaris"]["variants"]["solaris10"].copy()
solaris_compat["solaris10"]["skip"] = True
