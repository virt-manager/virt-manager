#
# Helper functions for determining if libvirt supports certain features
#
# Copyright 2009, 2013, 2014 Red Hat, Inc.
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

from . import util


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
def _try_command(func, run_args, check_all_error=False):
    try:
        func(*run_args)
    except libvirt.libvirtError as e:
        if util.is_error_nosupport(e):
            return False

        if check_all_error:
            return False
    except Exception as e:
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


def _check_function(function, flag, run_args, data):
    object_name, function_name = _split_function_name(function)
    if not function_name:
        return None

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

    if run_args is None:
        return None

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
    return _try_command(cmd, run_args + flag_tuple,
                        check_all_error=bool(flag_tuple))


def _version_str_to_int(verstr):
    if verstr is None:
        return None
    if verstr == 0:
        return 0

    if verstr.count(".") != 2:
        raise RuntimeError("programming error: version string '%s' needs "
            "two '.' in it.")

    return ((int(verstr.split(".")[0]) * 1000000) +
            (int(verstr.split(".")[1]) * 1000) + (int(verstr.split(".")[2])))


class _SupportCheck(object):
    """
    @version: Minimum libvirt version required for this feature. Not used
        if 'args' provided.

    @function: Function name to check exists. If object not specified,
        function is checked against libvirt module. If run_args is specified,
        this function will actually be called, so beware.

    @run_args: Argument tuple to actually test 'function' with, and check
        for an 'unsupported' error from libvirt.

    @flag: A flag to check exists. This will be appended to the argument
        list if run_args are provided, otherwise we will only check against
        that the flag is present in the python bindings.

    @hv_version: A dictionary with hypervisor names for keys, and
        hypervisor versions as values. This is for saying 'this feature
        is only supported with qemu version 1.5.0' or similar. If the
        version is 0, then perform no version check.

    @hv_libvirt_version: Similar to hv_version, but this will check
        the version of libvirt for a specific hv key. Use this to say
        'this feature is supported with qemu and libvirt version 1.0.0,
         and xen with libvirt version 1.1.0'
    """
    def __init__(self,
                 function=None, run_args=None, flag=None,
                 version=None, hv_version=None, hv_libvirt_version=None):
        self.function = function
        self.run_args = run_args
        self.flag = flag
        self.version = version
        self.hv_version = hv_version or {}
        self.hv_libvirt_version = hv_libvirt_version or {}

        versions = ([self.version] + self.hv_libvirt_version.values())
        for vstr in versions:
            v = _version_str_to_int(vstr)
            if vstr is not None and v != 0 and v < 7009:
                raise RuntimeError("programming error: Cannot enforce "
                    "support checks for libvirt versions less than 0.7.9, "
                    "since required APIs were not available. ver=%s" % vstr)

    def check_support(self, conn, data):
        ret = _check_function(self.function, self.flag, self.run_args, data)
        if ret is not None:
            return ret

        # Do this after the function check, since there's an ordering issue
        # with VirtualConnection
        hv_type = conn.get_uri_driver()
        actual_libvirt_version = conn.daemon_version()
        actual_hv_version = conn.conn_version()

        # Check that local libvirt version is sufficient
        if _version_str_to_int(self.version) > actual_libvirt_version:
            return False

        if self.hv_version:
            if hv_type not in self.hv_version:
                if "all" not in self.hv_version:
                    return False
            elif (actual_hv_version <
                  _version_str_to_int(self.hv_version[hv_type])):
                return False

        if self.hv_libvirt_version:
            if hv_type not in self.hv_libvirt_version:
                if "all" not in self.hv_version:
                    return False
            elif (actual_libvirt_version <
                  _version_str_to_int(self.hv_libvirt_version[hv_type])):
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



SUPPORT_CONN_STORAGE = _make(
    function="virConnect.listStoragePools", run_args=())
SUPPORT_CONN_NODEDEV = _make(
    function="virConnect.listDevices", run_args=(None, 0))
SUPPORT_CONN_FINDPOOLSOURCES = _make(
    function="virConnect.findStoragePoolSources")
SUPPORT_CONN_KEYMAP_AUTODETECT = _make(hv_version={"qemu": "0.11.0"})
SUPPORT_CONN_GETHOSTNAME = _make(
    function="virConnect.getHostname", run_args=())
SUPPORT_CONN_NETWORK = _make(function="virConnect.listNetworks", run_args=())
SUPPORT_CONN_INTERFACE = _make(
    function="virConnect.listInterfaces", run_args=())
SUPPORT_CONN_MAXVCPUS_XML = _make(version="0.8.5")
# Earliest version with working bindings
SUPPORT_CONN_STREAM = _make(
    version="0.9.3", function="virConnect.newStream", run_args=(0,))
SUPPORT_CONN_GETVERSION = _make(function="virConnect.getVersion", run_args=())
SUPPORT_CONN_LIBVERSION = _make(
    function="virConnect.getLibVersion", run_args=())
SUPPORT_CONN_LISTALLDOMAINS = _make(
    function="virConnect.listAllDomains", run_args=())
SUPPORT_CONN_LISTALLNETWORKS = _make(
    function="virConnect.listAllNetworks", run_args=())
SUPPORT_CONN_LISTALLSTORAGEPOOLS = _make(
    function="virConnect.listAllStoragePools", run_args=())
SUPPORT_CONN_LISTALLINTERFACES = _make(
    function="virConnect.listAllInterfaces", run_args=())
SUPPORT_CONN_LISTALLDEVICES = _make(
    function="virConnect.listAllDevices", run_args=())
SUPPORT_CONN_VIRTIO_MMIO = _make(
    version="1.1.2", hv_version={"qemu": "1.6.0"})
SUPPORT_CONN_DISK_SD = _make(version="1.1.2")
# This is an arbitrary check to say whether it's a good idea to
# default to qcow2. It might be fine for xen or qemu older than the versions
# here, but until someone tests things I'm going to be a bit conservative.
SUPPORT_CONN_DEFAULT_QCOW2 = _make(
    version="0.8.0", hv_version={"qemu": "1.2.0", "test": 0})
SUPPORT_CONN_DEFAULT_USB2 = _make(
    version="0.9.7", hv_version={"qemu": "1.0.0", "test": 0})
SUPPORT_CONN_CAN_ACPI = _make(hv_version={"xen": "3.1.0", "all": 0})
SUPPORT_CONN_WORKING_XEN_EVENTS = _make(hv_version={"xen": "4.0.0", "all": 0})
SUPPORT_CONN_SOUND_AC97 = _make(
    version="0.8.0", hv_version={"qemu": "0.11.0"})
SUPPORT_CONN_SOUND_ICH6 = _make(
    version="0.8.8", hv_version={"qemu": "0.14.0"})
SUPPORT_CONN_GRAPHICS_SPICE = _make(
    version="0.8.6", hv_version={"qemu": "0.14.0"})
SUPPORT_CONN_CHAR_SPICEVMC = _make(
    version="0.8.8", hv_version={"qemu": "0.14.0"})
SUPPORT_CONN_DIRECT_INTERFACE = _make(
    version="0.8.7", hv_version={"qemu": 0, "test": 0})
SUPPORT_CONN_FILESYSTEM = _make(
    hv_version={"qemu": "0.13.0", "lxc": 0, "openvz": 0, "test": 0},
    hv_libvirt_version={"qemu": "0.8.5", "lxc": 0, "openvz": 0, "test": 0})
SUPPORT_CONN_AUTOSOCKET = _make(hv_libvirt_version={"qemu": "1.0.6"})
SUPPORT_CONN_ADVANCED_CLOCK = _make(hv_libvirt_version={"qemu": "0.8.0"})
SUPPORT_CONN_VIRTIO_CONSOLE = _make(hv_libvirt_version={"qemu": "0.8.3"})
SUPPORT_CONN_PANIC_DEVICE = _make(
    version="1.2.1", hv_version={"qemu": "1.5.0", "test": 0})
SUPPORT_CONN_PM_DISABLE = _make(
    version="0.10.2", hv_version={"qemu": "1.2.0", "test": 0})
SUPPORT_CONN_QCOW2_LAZY_REFCOUNTS = _make(
    version="1.1.0", hv_version={"qemu": "1.2.0", "test": 0})
SUPPORT_CONN_USBREDIR = _make(
    version="0.9.5", hv_version={"qemu": "1.3.0", "test": 0})
SUPPORT_CONN_DEVICE_BOOTORDER = _make(
    version="0.8.8", hv_version={"qemu": 0, "test": 0})
SUPPORT_CONN_POOL_GLUSTERFS = _make(version="1.2.0")
SUPPORT_CONN_CPU_MODEL_NAMES = _make(function="virConnect.getCPUModelNames",
                                     run_args=("x86_64", 0))
SUPPORT_CONN_HYPERV_VAPIC = _make(
    version="1.1.0", hv_version={"qemu": "1.1.0", "test": 0})
SUPPORT_CONN_HYPERV_CLOCK = _make(
    version="1.2.2", hv_version={"qemu": "2.0.0", "test": 0})
SUPPORT_CONN_HYPERV_CLOCK_RHEL = _make(
    version="1.2.2", hv_version={"qemu": "1.5.3", "test": 0})
SUPPORT_CONN_LOADER_ROM = _make(version="1.2.9")
SUPPORT_CONN_DOMAIN_CAPABILITIES = _make(
    function="virConnect.getDomainCapabilities",
    run_args=(None, None, None, None))
SUPPORT_CONN_DOMAIN_RESET = _make(version="0.9.7", hv_version={"qemu": 0})
SUPPORT_CONN_SPICE_COMPRESSION = _make(version="0.9.1")
SUPPORT_CONN_VMPORT = _make(
    version="1.2.16", hv_version={"qemu": "2.2.0", "test": 0})
SUPPORT_CONN_VCPU_PLACEMENT = _make(
    version="0.9.11", hv_version={"qemu": 0, "test": 0})
SUPPORT_CONN_MEM_STATS_PERIOD = _make(
    function="virDomain.setMemoryStatsPeriod",
    version="1.1.1", hv_version={"qemu": 0})
# spice GL is actually enabled with libvirt 1.3.3, but 3.1.0 is the
# first version that sorts out the qemu:///system + cgroup issues
SUPPORT_CONN_SPICE_GL = _make(version="3.1.0",
    hv_version={"qemu": "2.6.0", "test": 0})
SUPPORT_CONN_SPICE_RENDERNODE = _make(version="3.1.0",
    hv_version={"qemu": "2.9.0", "test": 0})
SUPPORT_CONN_VIDEO_VIRTIO_ACCEL3D = _make(version="1.3.0",
    hv_version={"qemu": "2.5.0", "test": 0})
SUPPORT_CONN_GRAPHICS_LISTEN_NONE = _make(version="2.0.0")
SUPPORT_CONN_RNG_URANDOM = _make(version="1.3.4")
SUPPORT_CONN_USB3_PORTS = _make(version="1.3.5")
SUPPORT_CONN_MACHVIRT_PCI_DEFAULT = _make(version="3.0.0")
SUPPORT_CONN_QEMU_XHCI = _make(version="3.3.0")


# This is for disk <driver name=qemu>. xen supports this, but it's
# limited to arbitrary new enough xen, since I know libxl can handle it
# but I don't think the old xend driver does.
SUPPORT_CONN_DISK_DRIVER_NAME_QEMU = _make(
    hv_version={"qemu": 0, "xen": "4.2.0"},
    hv_libvirt_version={"qemu": 0, "xen": "1.1.0"})


#################
# Domain checks #
#################

SUPPORT_DOMAIN_GETVCPUS = _make(function="virDomain.vcpus", run_args=())
SUPPORT_DOMAIN_XML_INACTIVE = _make(function="virDomain.XMLDesc", run_args=(),
    flag="VIR_DOMAIN_XML_INACTIVE")
SUPPORT_DOMAIN_XML_SECURE = _make(function="virDomain.XMLDesc", run_args=(),
    flag="VIR_DOMAIN_XML_SECURE")
SUPPORT_DOMAIN_MANAGED_SAVE = _make(
    function="virDomain.hasManagedSaveImage",
    run_args=(0,))
SUPPORT_DOMAIN_MIGRATE_DOWNTIME = _make(
    function="virDomain.migrateSetMaxDowntime",
    # Use a bogus flags value, so that we don't overwrite existing
    # downtime value
    run_args=(30, 12345678))
SUPPORT_DOMAIN_JOB_INFO = _make(function="virDomain.jobInfo", run_args=())
SUPPORT_DOMAIN_CONSOLE_STREAM = _make(version="0.8.6")
SUPPORT_DOMAIN_SET_METADATA = _make(version="0.9.10")
SUPPORT_DOMAIN_CPU_HOST_MODEL = _make(version="0.9.10")
SUPPORT_DOMAIN_LIST_SNAPSHOTS = _make(
    function="virDomain.listAllSnapshots", run_args=())
SUPPORT_DOMAIN_GET_METADATA = _make(function="virDomain.metadata",
    run_args=(getattr(libvirt, "VIR_DOMAIN_METADATA_TITLE", 1), None, 0))
SUPPORT_DOMAIN_MEMORY_STATS = _make(
    function="virDomain.memoryStats", run_args=())
SUPPORT_DOMAIN_STATE = _make(function="virDomain.state", run_args=())
SUPPORT_DOMAIN_OPEN_GRAPHICS = _make(function="virDomain.openGraphicsFD",
    version="1.2.8", hv_version={"qemu": 0})
SUPPORT_DOMAIN_FEATURE_SMM = _make(version="2.1.0")
SUPPORT_DOMAIN_LOADER_SECURE = _make(version="2.1.0")


###############
# Pool checks #
###############

SUPPORT_POOL_CREATEVOLFROM = _make(
    function="virStoragePool.createXMLFrom", version="0.8.0")
SUPPORT_POOL_ISACTIVE = _make(function="virStoragePool.isActive", run_args=())
SUPPORT_POOL_LISTALLVOLUMES = _make(
    function="virStoragePool.listAllVolumes", run_args=())
SUPPORT_POOL_METADATA_PREALLOC = _make(
    flag="VIR_STORAGE_VOL_CREATE_PREALLOC_METADATA",
    version="1.0.1")
SUPPORT_POOL_REFLINK = _make(
    flag="VIR_STORAGE_VOL_CREATE_REFLINK",
    version="1.2.13")


####################
# Interface checks #
####################

SUPPORT_INTERFACE_XML_INACTIVE = _make(function="virInterface.XMLDesc",
    flag="VIR_INTERFACE_XML_INACTIVE",
    run_args=())
SUPPORT_INTERFACE_ISACTIVE = _make(
    function="virInterface.isActive", run_args=())


#################
# Stream checks #
#################

# Latest I tested with, and since we will use it by default
# for URL installs, want to be sure it works
SUPPORT_STREAM_UPLOAD = _make(version="0.9.4")


##################
# Network checks #
##################

SUPPORT_NET_ISACTIVE = _make(function="virNetwork.isActive", run_args=())


def check_support(virtconn, feature, data=None):
    """
    Attempt to determine if a specific libvirt feature is support given
    the passed connection.

    @param virtconn: Libvirt connection to check feature on
    @param feature: Feature type to check support for
    @type  feature: One of the SUPPORT_* flags
    @param data: Option libvirt object to use in feature checking
    @type  data: Could be virDomain, virNetwork, virStoragePool,
                hv name, etc

    @returns: True if feature is supported, False otherwise
    """
    if "VirtualConnection" in repr(data):
        data = data.get_conn_for_api_arg()

    sobj = _support_objs[feature - 1]
    return sobj.check_support(virtconn, data)


def _check_version(virtconn, version):
    """
    Check libvirt version. Useful for the test suite so we don't need
    to keep adding new support checks.
    """
    sobj = _SupportCheck(version=version)
    return sobj.check_support(virtconn, None)
