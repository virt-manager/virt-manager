#
# Helper functions for determining if libvirt supports certain features
#
# Copyright 2009  Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

import libvirt

from virtinst import util

# Flags for check_conn_support
(SUPPORT_CONN_STORAGE,
 SUPPORT_CONN_FINDPOOLSOURCES,
 SUPPORT_CONN_NODEDEV,
 SUPPORT_CONN_KEYMAP_AUTODETECT,
 SUPPORT_CONN_GETHOSTNAME,
 SUPPORT_CONN_DOMAIN_VIDEO,
 SUPPORT_CONN_NETWORK,
 SUPPORT_CONN_INTERFACE,
 SUPPORT_CONN_MAXVCPUS_XML,
 SUPPORT_CONN_STREAM,
 SUPPORT_CONN_GETVERSION,
 SUPPORT_CONN_LIBVERSION,
 SUPPORT_CONN_LISTALLDOMAINS,
 SUPPORT_CONN_LISTALLNETWORKS,
 SUPPORT_CONN_LISTALLSTORAGEPOOLS,
 SUPPORT_CONN_LISTALLINTERFACES) = range(1, 17)

# Flags for check_domain_support
(SUPPORT_DOMAIN_GETVCPUS,
 SUPPORT_DOMAIN_XML_SECURE,
 SUPPORT_DOMAIN_XML_INACTIVE,
 SUPPORT_DOMAIN_MANAGED_SAVE,
 SUPPORT_DOMAIN_MIGRATE_DOWNTIME,
 SUPPORT_DOMAIN_JOB_INFO,
 SUPPORT_DOMAIN_MAXVCPUS_XML,
 SUPPORT_DOMAIN_CONSOLE_STREAM,
 SUPPORT_DOMAIN_SET_METADATA,
 SUPPORT_DOMAIN_CPU_HOST_MODEL) = range(1000, 1010)

# Flags for check_pool_support
(SUPPORT_STORAGE_CREATEVOLFROM,
 SUPPORT_STORAGE_UPLOAD,
 SUPPORT_STORAGE_ISACTIVE) = range(2000, 2003)

# Flags for check_nodedev_support
(SUPPORT_NODEDEV_PCI_DETACH,) = range(3000, 3001)

# Flags for check_interface_support
(SUPPORT_INTERFACE_XML_INACTIVE,
 SUPPORT_INTERFACE_ISACTIVE) = range(4000, 4002)

# Flags for check_conn_hv_support
(SUPPORT_CONN_HV_VIRTIO,
 SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI,
 SUPPORT_CONN_HV_SOUND_AC97,
 SUPPORT_CONN_HV_SOUND_ICH6,
 SUPPORT_CONN_HV_GRAPHICS_SPICE,
 SUPPORT_CONN_HV_CHAR_SPICEVMC,
 SUPPORT_CONN_HV_DIRECT_INTERFACE,
 SUPPORT_CONN_HV_FILESYSTEM) = range(5000, 5008)

# Flags for check_stream_support
(SUPPORT_STREAM_UPLOAD,) = range(6000, 6001)

# Flags for check_net_support
(SUPPORT_NET_ISACTIVE,) = range(7000, 7001)


# Possible keys:
#
# "version" : Minimum libvirt version required for this feature. Not used
#             if 'args' provided
#
# "force_version" : Demand that version check is met for the checked
#                   libvirt version. Normally we will make a best effort
#                   attempt, because determining the daemon version depends
#                   on an api call from 2010. So for things like
#                   testing API availability (e.g. createXMLFrom) we won't
#                   force the check, but for things like XML options (AC97)
#                   we want to be ABSOLUTELY SURE it is supported so we
#                   don't enable it by default and break guest creation.
#                   This isn't required for versions after >= 0.7.3
#
# "function" : Function name to check exists. If object not specified,
#              function is checked against libvirt module.
#
# "args": Argument tuple to actually test object.function with.
#
# "flag": A flag to check exists. This will be appended to the argument
#         list if args are provided, otherwise we will only check against
#         the local libvirt version.
#
# "drv_version" : A list of tuples of the form
#                 (driver name (e.g qemu, xen, lxc), minimum supported version)
#                 If a hypervisor is not listed, it is assumed to be NOT
#                 SUPPORTED.
#
# "drv_libvirt_version" : List of tuples, similar to drv_version, but
#                         the version number is minimum supported _libvirt_
#                         version
# "hv_version" : A list of tuples of the same form as drv_version, however
#                listing the actual <domain type='%s'/> from the XML.
#                example: 'kvm'


_support_dict = {
    SUPPORT_CONN_STORAGE : {
        "function" : "virConnect.listStoragePools",
        "args" : (),
    },

    SUPPORT_CONN_NODEDEV : {
        "function" : "virConnect.listDevices",
        "args" : (None, 0),
    },

    SUPPORT_CONN_FINDPOOLSOURCES : {
        "function" : "virConnect.findStoragePoolSources",
    },

    SUPPORT_CONN_KEYMAP_AUTODETECT : {
        "drv_version" : [("qemu", 11000)],
    },

    SUPPORT_CONN_GETHOSTNAME : {
        "function" : "virConnect.getHostname()",
        "args" : (),
    },

    SUPPORT_CONN_DOMAIN_VIDEO : {
        "version" : 6005,
    },

    SUPPORT_CONN_NETWORK : {
        "function" : "virConnect.listNetworks",
        "args" : (),
    },

    SUPPORT_CONN_INTERFACE : {
        "function" : "virConnect.listInterfaces",
        "args" : (),
    },

    SUPPORT_CONN_MAXVCPUS_XML : {
        "version" : 8005,
    },

    SUPPORT_CONN_STREAM : {
        # Earliest version with working bindings
        "version" : 9003,
        "function" : "virConnect.newStream",
        "args" : (0,),
    },

    SUPPORT_CONN_GETVERSION : {
        "function": "virConnect.getVersion",
        "args": (),
    },

    SUPPORT_CONN_LIBVERSION : {
        "function": "virConnect.getLibVersion",
        "args": (),
    },

    SUPPORT_CONN_LISTALLDOMAINS : {
        "function": "virConnect.listAllDomains",
        "args": (),
    },
    SUPPORT_CONN_LISTALLNETWORKS : {
        "function": "virConnect.listAllNetworks",
        "args": (),
    },
    SUPPORT_CONN_LISTALLSTORAGEPOOLS : {
        "function": "virConnect.listAllStoragePools",
        "args": (),
    },
    SUPPORT_CONN_LISTALLINTERFACES : {
        "function": "virConnect.listAllInterfaces",
        "args": (),
    },


    #################
    # Domain checks #
    #################

    SUPPORT_DOMAIN_GETVCPUS : {
        "function" : "virDomain.vcpus",
        "args" : (),
    },

    SUPPORT_DOMAIN_XML_INACTIVE : {
        "function" : "virDomain.XMLDesc",
        "args" : (),
        "flag" : "VIR_DOMAIN_XML_INACTIVE",
    },

    SUPPORT_DOMAIN_XML_SECURE : {
        "function" : "virDomain.XMLDesc",
        "args" : (),
        "flag" : "VIR_DOMAIN_XML_SECURE",
    },

    SUPPORT_DOMAIN_MANAGED_SAVE : {
        "function" : "virDomain.hasManagedSaveImage",
        "args" : (0,),
    },

    SUPPORT_DOMAIN_MIGRATE_DOWNTIME : {
        "function" : "virDomain.migrateSetMaxDowntime",
        # Use a bogus flags value, so that we don't overwrite existing
        # downtime value
        "args" : (30, 12345678),
    },

    SUPPORT_DOMAIN_JOB_INFO : {
        "function" : "virDomain.jobInfo",
        "args" : (),
    },

    SUPPORT_DOMAIN_CONSOLE_STREAM : {
        "version" : 9003,
    },

    SUPPORT_DOMAIN_SET_METADATA : {
        "version" : 9010,
    },

    SUPPORT_DOMAIN_CPU_HOST_MODEL : {
        "version" : 9010,
    },


    ###############
    # Pool checks #
    ###############

    # This can't ever require a pool object for back compat reasons
    SUPPORT_STORAGE_CREATEVOLFROM : {
        "function" : "virStoragePool.createXMLFrom",
        "version" : 6004,
    },
    SUPPORT_STORAGE_ISACTIVE : {
        "function" : "virStoragePool.isActive",
        "args": (),
    },


    ##################
    # Nodedev checks #
    ##################

    # This can't ever require a nodedev object for back compat reasons
    SUPPORT_NODEDEV_PCI_DETACH : {
        "function" : "virNodeDevice.dettach",
        "version" : 6001,
    },


    ####################
    # Interface checks #
    ####################

    SUPPORT_INTERFACE_XML_INACTIVE : {
        "function" : "virInterface.XMLDesc",
        "args" : (),
        "flag" : "VIR_INTERFACE_XML_INACTIVE",
    },
    SUPPORT_INTERFACE_ISACTIVE : {
        "function" : "virInterface.isActive",
        "args": (),
    },


    ##################
    # Conn HV checks #
    ##################

    SUPPORT_CONN_HV_VIRTIO : {
        "drv_version": [("qemu", 0)],
        "hv_version" : [("kvm", 0)],
    },

    SUPPORT_CONN_HV_SKIP_DEFAULT_ACPI : {
        "drv_version" : [("xen", -3001000)],
    },

    SUPPORT_CONN_HV_SOUND_AC97 : {
        "version" : 6000,
        "force_version" : True,
        "drv_version" : [("qemu", 11000), ],
    },

    SUPPORT_CONN_HV_SOUND_ICH6 : {
        "version" : 8008,
        "drv_version" : [("qemu", 14000), ],
        "rhel6_drv_version" : [("qemu", 12001)],
        "rhel6_version" : 8007,
    },

    SUPPORT_CONN_HV_GRAPHICS_SPICE : {
        "version" : 8006,
        "drv_version" : [("qemu", 14000), ],
    },

    SUPPORT_CONN_HV_CHAR_SPICEVMC : {
        "version" : 8008,
        "drv_version" : [("qemu", 14000), ],
    },
    SUPPORT_CONN_HV_DIRECT_INTERFACE : {
        "version" : 8007,
        "drv_version" : [("qemu", 0), ],
    },
    SUPPORT_CONN_HV_FILESYSTEM : {
        "drv_version" : [("qemu", 13000),
                          ("lxc", 0),
                          ("openvz", 0),
                          ("test", 0)],
        "drv_libvirt_version" : [("qemu", 8005),
                                  ("lxc", 0),
                                  ("openvz", 0),
                                  ("test", 0)],
    },


    #################
    # Stream checks #
    #################

    SUPPORT_STREAM_UPLOAD : {
        # Latest I tested with, and since we will use it by default
        # for URL installs, want to be sure it works
        "version" : 9004,
    },


    ##################
    # Network checks #
    ##################

    SUPPORT_NET_ISACTIVE : {
        "function" : "virNetwork.isActive",
        "args": (),
    },
}

# RHEL6 has lots of feature backports, and since libvirt doesn't
# really offer any XML feature introspection, we have to use hacks to
# make sure we aren't generating bogus config on non RHEL
_rhel6 = False


def set_rhel6(val):
    global _rhel6
    _rhel6 = bool(val)


def get_rhel6():
    return _rhel6


# Check that command is present in the python bindings, and return the
# the requested function
def _get_command(funcname, objname=None, obj=None):
    if not obj:
        obj = libvirt

        if objname:
            if not hasattr(libvirt, objname):
                return None
            obj = getattr(libvirt, objname)

    if not hasattr(obj, funcname):
        return None

    return getattr(obj, funcname)


# Make sure libvirt object 'objname' has function 'funcname'
def _has_command(funcname, objname=None, obj=None):
    return bool(_get_command(funcname, objname, obj))


# Make sure libvirt object has flag 'flag_name'
def _get_flag(flag_name):
    return _get_command(flag_name)


# Try to call the passed function, and look for signs that libvirt or driver
# doesn't support it
def _try_command(func, args, check_all_error=False):
    try:
        func(*args)
    except libvirt.libvirtError, e:
        if util.is_error_nosupport(e):
            return False

        if check_all_error:
            return False
    except Exception:
        # Other python exceptions likely mean the bindings are horked
        return False
    return True


# Return the hypervisor version
def _split_function_name(function):
    if not function:
        return (None, None)

    output = function.split(".")
    if len(output) == 1:
        return (None, output[0])
    else:
        return (output[0], output[1])


def check_support(virtconn, feature, data=None):
    """
    Attempt to determine if a specific libvirt feature is support given
    the passed connection.

    @param conn: Libvirt connection to check feature on
    @param feature: Feature type to check support for
    @type  feature: One of the SUPPORT_* flags
    @param data: Option libvirt object to use in feature checking
    @type  data: Could be virDomain, virNetwork, virStoragePool,
                hv name, etc

    @returns: True if feature is supported, False otherwise
    """
    if "VirtualConnection" in repr(data):
        data = data.libvirtconn

    support_info = _support_dict[feature]
    key_list = support_info.keys()

    def get_value(key):
        if key in key_list:
            key_list.remove(key)
        return support_info.get(key)

    is_rhel6 = get_rhel6()
    force_version = get_value("force_version") or False

    minimum_libvirt_version = get_value("version") or 0
    rhel6_min = get_value("rhel6_version") or minimum_libvirt_version
    if is_rhel6:
        minimum_libvirt_version = rhel6_min

    drv_version = get_value("drv_version") or []
    rhel6_drv_version = get_value("rhel6_drv_version") or drv_version
    if is_rhel6:
        drv_version = rhel6_drv_version

    drv_libvirt_version = get_value("drv_libvirt_version") or []

    hv_version = get_value("hv_version") or []
    object_name, function_name = _split_function_name(get_value("function"))
    args = get_value("args")
    flag = get_value("flag")

    # Make sure there are no keys left in the key_list. This will
    # ensure we didn't mistype anything above, or in the support_dict
    if key_list:
        raise RuntimeError("Unknown keys in the support_dict: %s" % key_list)

    if function_name:
        # Make sure function is present in either libvirt module or
        # object_name class
        flag_tuple = ()

        if not _has_command(function_name, objname=object_name):
            return False

        if flag:
            found_flag = _get_flag(flag)
            if not bool(found_flag):
                return False
            flag_tuple = (found_flag,)

        if args is not None:
            classobj = None

            # If function requires an object, make sure the passed obj
            # is of the correct type
            if object_name:
                classobj = _get_command(object_name)
                if not isinstance(data, classobj):
                    raise ValueError(
                        "Passed obj %s with args must be of type %s, was %s" %
                        (data, str(classobj), type(data)))

            cmd = _get_command(function_name, obj=data)

            # Function with args specified is all the proof we need
            ret = _try_command(cmd, args + flag_tuple,
                               check_all_error=bool(flag_tuple))
            return ret

    # Do this after the function check, since there's an ordering issue
    # with VirtualConnection
    drv_type = virtconn.get_uri_driver()
    actual_lib_ver = virtconn.local_libvirt_version()
    actual_daemon_ver = virtconn.daemon_version()
    actual_drv_ver = virtconn.conn_version()
    if (actual_daemon_ver == 0 and not force_version):
        # This means the API may not be supported, but we don't care
        actual_daemon_ver = 1000000000

    # Check that local libvirt version is sufficient
    if minimum_libvirt_version > actual_lib_ver:
        return False

    # Check that daemon version is sufficient
    if minimum_libvirt_version > actual_daemon_ver:
        return False

    # If driver specific version info specified, try to verify
    if drv_version:
        found = False
        for drv, min_drv_ver in drv_version:
            if drv != drv_type:
                continue

            if min_drv_ver < 0:
                if actual_drv_ver <= -min_drv_ver:
                    found = True
                    break
            else:
                if actual_drv_ver >= min_drv_ver:
                    found = True
                    break

        if not found:
            return False

    if drv_libvirt_version:
        found = False
        for drv, min_lib_ver in drv_libvirt_version:
            if drv != drv_type:
                continue

            if min_lib_ver < 0:
                if actual_lib_ver <= -min_lib_ver:
                    found = True
                    break
            else:
                if actual_lib_ver >= min_lib_ver:
                    found = True
                    break

        if not found:
            return False

    if hv_version:
        found = False
        hv_type = data
        for hv, min_hv_ver in hv_version:
            if hv != hv_type:
                continue

            # No HV specific version info, just use driver version
            if min_hv_ver < 0:
                if actual_drv_ver <= -min_hv_ver:
                    found = True
                    break
            else:
                if actual_drv_ver >= min_hv_ver:
                    found = True
                    break

        if not found:
            return False

    return True
