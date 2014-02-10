#
# Helper functions for determining if libvirt supports certain features
#
# Copyright 2009, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
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

import libvirt

from virtinst import util


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


class _SupportCheck(object):
    """
    @version: Minimum libvirt version required for this feature. Not used
        if 'args' provided
    @force_version: Demand that version check is met for the checked
        libvirt version. Normally we will make a best effort
        attempt, because determining the daemon version depends
        on an api call from 2010. So for things like
        testing API availability (e.g. createXMLFrom) we won't
        force the check, but for things like XML options (AC97)
        we want to be ABSOLUTELY SURE it is supported so we
        don't enable it by default and break guest creation.
        This isn't required for versions after >= 0.7.3
    @function: Function name to check exists. If object not specified,
        function is checked against libvirt module.
    @args: Argument tuple to actually test object.function with.
    @flag: A flag to check exists. This will be appended to the argument
        list if args are provided, otherwise we will only check against
        the local libvirt version.
    @drv_version: A list of tuples of the form
        (driver name (e.g qemu, xen, lxc), minimum supported version)
        If a hypervisor is not listed, it is assumed to be NOT SUPPORTED.
        If the special value 'all' is a key, assume any driver not listed
        is explicitly supported.
    @drv_libvirt_version: List of tuples, similar to drv_version, but
        the version number is minimum supported _libvirt_ version
    """
    def __init__(self,
                 function=None, args=None, flag=None,
                 version=None, force_version=None,
                 drv_version=None, drv_libvirt_version=None):
        self.function = function
        self.args = args
        self.flag = flag
        self.version = version and int(version) or 0
        self.force_version = bool(force_version)
        self.drv_version = drv_version or {}
        self.drv_libvirt_version = drv_libvirt_version or {}

    def check_support(self, conn, data):
        minimum_libvirt_version = self.version

        object_name, function_name = _split_function_name(self.function)

        if function_name:
            # Make sure function is present in either libvirt module or
            # object_name class
            flag_tuple = ()

            if not _has_command(function_name, objname=object_name):
                return False

            if self.flag:
                found_flag = _get_flag(self.flag)
                if not bool(found_flag):
                    return False
                flag_tuple = (found_flag,)

            if self.args is not None:
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
                ret = _try_command(cmd, self.args + flag_tuple,
                                   check_all_error=bool(flag_tuple))
                return ret

        # Do this after the function check, since there's an ordering issue
        # with VirtualConnection
        drv_type = conn.get_uri_driver()
        actual_lib_ver = conn.local_libvirt_version()
        actual_daemon_ver = conn.daemon_version()
        actual_drv_ver = conn.conn_version()
        if actual_daemon_ver == 0 and not self.force_version:
            # This means the API may not be supported, but we don't care
            actual_daemon_ver = 1000000000
        if actual_daemon_ver != 0:
            actual_lib_ver = actual_daemon_ver

        # Check that local libvirt version is sufficient
        if minimum_libvirt_version > actual_lib_ver:
            return False

        if self.drv_version:
            if drv_type not in self.drv_version:
                if "all" not in self.drv_version:
                    return False
            elif actual_drv_ver < self.drv_version[drv_type]:
                return False

        if self.drv_libvirt_version:
            if drv_type not in self.drv_libvirt_version:
                if "all" not in self.drv_version:
                    return False
            elif actual_lib_ver < self.drv_libvirt_version[drv_type]:
                return False

        return True


_support_id = 0
_support_objs = []


def _make(*args, **kwargs):
    global _support_id
    _support_id += 1
    obj = _SupportCheck(*args, **kwargs)
    _support_objs.append(obj)
    return _support_id



SUPPORT_CONN_STORAGE = _make(function="virConnect.listStoragePools",
                             args=())
SUPPORT_CONN_NODEDEV = _make(function="virConnect.listDevices", args=(None, 0))
SUPPORT_CONN_FINDPOOLSOURCES = _make(
                        function="virConnect.findStoragePoolSources")
SUPPORT_CONN_KEYMAP_AUTODETECT = _make(drv_version={"qemu": 11000})
SUPPORT_CONN_GETHOSTNAME = _make(function="virConnect.getHostname", args=())
SUPPORT_CONN_DOMAIN_VIDEO = _make(version=6005)
SUPPORT_CONN_NETWORK = _make(function="virConnect.listNetworks", args=())
SUPPORT_CONN_INTERFACE = _make(function="virConnect.listInterfaces", args=())
SUPPORT_CONN_MAXVCPUS_XML = _make(version=8005)
# Earliest version with working bindings
SUPPORT_CONN_STREAM = _make(version=9003,
                            function="virConnect.newStream",
                            args=(0,))
SUPPORT_CONN_GETVERSION = _make(function="virConnect.getVersion", args=())
SUPPORT_CONN_LIBVERSION = _make(function="virConnect.getLibVersion", args=())
SUPPORT_CONN_LISTALLDOMAINS = _make(function="virConnect.listAllDomains",
                                    args=())
SUPPORT_CONN_LISTALLNETWORKS = _make(function="virConnect.listAllNetworks",
                                     args=())
SUPPORT_CONN_LISTALLSTORAGEPOOLS = _make(
                                function="virConnect.listAllStoragePools",
                                args=())
SUPPORT_CONN_LISTALLINTERFACES = _make(function="virConnect.listAllInterfaces",
                                args=())
SUPPORT_CONN_LISTALLDEVICES = _make(function="virConnect.listAllDevices",
                                    args=())
SUPPORT_CONN_VIRTIO_MMIO = _make(version=1001002,
    drv_version={"qemu": 1006000})
SUPPORT_CONN_DISK_SD = _make(version=1001002)
# This is an arbitrary check to say whether it's a good idea to
# default to qcow2. It might be fine for xen or qemu older than the versions
# here, but until someone tests things I'm going to be a bit conservative.
SUPPORT_CONN_DEFAULT_QCOW2 = _make(version=8000,
    drv_version={"qemu": 1002000, "test": 0})
SUPPORT_CONN_DEFAULT_USB2 = _make(version=9007,
    drv_version={"qemu": 1000000, "test": 0})
SUPPORT_CONN_CAN_ACPI = _make(drv_version={"xen": 3001000, "all": 0})
SUPPORT_CONN_SOUND_AC97 = _make(version=6000, force_version=True,
    drv_version={"qemu": 11000})
SUPPORT_CONN_SOUND_ICH6 = _make(version=8008, drv_version={"qemu": 14000})
SUPPORT_CONN_GRAPHICS_SPICE = _make(version=8006, drv_version={"qemu": 14000})
SUPPORT_CONN_CHAR_SPICEVMC = _make(version=8008, drv_version={"qemu": 14000})
SUPPORT_CONN_DIRECT_INTERFACE = _make(version=8007,
    drv_version={"qemu": 0, "test": 0})
SUPPORT_CONN_FILESYSTEM = _make(
    drv_version={"qemu": 13000, "lxc": 0, "openvz": 0, "test": 0},
    drv_libvirt_version={"qemu": 8005, "lxc": 0, "openvz": 0, "test": 0})
SUPPORT_CONN_AUTOSOCKET = _make(drv_libvirt_version={"qemu": 1000006})
SUPPORT_CONN_ADVANCED_CLOCK = _make(
    drv_libvirt_version={"qemu": 8000})
SUPPORT_CONN_VIRTIO_CONSOLE = _make(drv_libvirt_version={"qemu": 8003})
SUPPORT_CONN_PANIC_DEVICE = _make(version=1002001,
    drv_version={"qemu": 1005000, "test": 0})
SUPPORT_CONN_PM_DISABLE = _make(version="10002",
    drv_version={"qemu": 1002000, "test": 0})
SUPPORT_CONN_QCOW2_LAZY_REFCOUNTS = _make(version="1001000",
    drv_version={"qemu": 1002000, "test": 0})
SUPPORT_CONN_USBREDIR = _make(version="9005",
    drv_version={"qemu": 1003000, "test": 0})
SUPPORT_CONN_DEVICE_BOOTORDER = _make(version="8008",
    drv_version={"qemu": 0, "test": 0})


# Domain checks
SUPPORT_DOMAIN_GETVCPUS = _make(function="virDomain.vcpus", args=())
SUPPORT_DOMAIN_XML_INACTIVE = _make(function="virDomain.XMLDesc", args=(),
                                    flag="VIR_DOMAIN_XML_INACTIVE")
SUPPORT_DOMAIN_XML_SECURE = _make(function="virDomain.XMLDesc", args=(),
                                  flag="VIR_DOMAIN_XML_SECURE")
SUPPORT_DOMAIN_MANAGED_SAVE = _make(function="virDomain.hasManagedSaveImage",
                                    args=(0,))
SUPPORT_DOMAIN_MIGRATE_DOWNTIME = _make(
        function="virDomain.migrateSetMaxDowntime",
        # Use a bogus flags value, so that we don't overwrite existing
        # downtime value
        args=(30, 12345678))
SUPPORT_DOMAIN_JOB_INFO = _make(function="virDomain.jobInfo", args=())
SUPPORT_DOMAIN_CONSOLE_STREAM = _make(version=8006)
SUPPORT_DOMAIN_SET_METADATA = _make(version=9010)
SUPPORT_DOMAIN_CPU_HOST_MODEL = _make(version=9010)
SUPPORT_DOMAIN_LIST_SNAPSHOTS = _make(function="virDomain.listAllSnapshots",
                                      args=())
SUPPORT_DOMAIN_GET_METADATA = _make(function="virDomain.metadata",
            args=(getattr(libvirt, "VIR_DOMAIN_METADATA_TITLE", 1), None, 0))
SUPPORT_DOMAIN_MEMORY_STATS = _make(function="virDomain.memoryStats", args=())


# Pool checks
SUPPORT_POOL_CREATEVOLFROM = _make(function="virStoragePool.createXMLFrom",
                                      version=6004)
SUPPORT_POOL_ISACTIVE = _make(function="virStoragePool.isActive", args=())
SUPPORT_POOL_LISTALLVOLUMES = _make(function="virStoragePool.listAllVolumes",
                                    args=())
SUPPORT_POOL_METADATA_PREALLOC = _make(
    flag="VIR_STORAGE_VOL_CREATE_PREALLOC_METADATA",
    version="1000001")


# Interface checks
SUPPORT_INTERFACE_XML_INACTIVE = _make(function="virInterface.XMLDesc",
                                       flag="VIR_INTERFACE_XML_INACTIVE",
                                       args=())
SUPPORT_INTERFACE_ISACTIVE = _make(function="virInterface.isActive", args=())


# Stream checks
# Latest I tested with, and since we will use it by default
# for URL installs, want to be sure it works
SUPPORT_STREAM_UPLOAD = _make(version=9004)

# Network checks
SUPPORT_NET_ISACTIVE = _make(function="virNetwork.isActive", args=())


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

    sobj = _support_objs[feature - 1]
    return sobj.check_support(virtconn, data)
