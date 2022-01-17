#
# Helper functions for determining if libvirt supports certain features
#
# Copyright 2009, 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import libvirt

from . import xmlutil


def _check_function(function, flag, run_args, data):
    """
    Make sure function and option flag is present in the libvirt module.
    If run_args specified, try actually running the function against
    the passed 'data' object
    """
    object_name, function_name = function.split(".")
    classobj = getattr(libvirt, object_name, None)
    if not classobj:
        return False
    if not getattr(classobj, function_name, None):
        return False

    flag_tuple = None
    if flag:
        found_flag = getattr(libvirt, flag, None)
        if found_flag is None:
            return False
        flag_tuple = (found_flag,)

    if run_args is None:
        return None

    # If function requires an object, make sure the passed obj
    # is of the correct type
    if not isinstance(data, classobj):
        raise ValueError(
            "Passed obj %s with args must be of type %s, was %s" %
            (data, str(classobj), type(data)))

    use_args = run_args
    if flag_tuple:
        use_args += flag_tuple

    try:
        getattr(data, function_name)(*run_args)
    except libvirt.libvirtError as e:
        if SupportCache.is_error_nosupport(e):
            return False
        if bool(flag_tuple):  # pragma: no cover
            return False
    except Exception:  # pragma: no cover
        # Other python exceptions likely mean the bindings are horked
        return False
    return True


def _version_str_to_int(verstr):
    if verstr is None:
        return None
    if verstr == 0:
        return 0

    if verstr.count(".") != 2:
        raise xmlutil.DevError(
                "version string '%s' needs two '.' in it." % verstr)

    return ((int(verstr.split(".")[0]) * 1000000) +
            (int(verstr.split(".")[1]) * 1000) + (int(verstr.split(".")[2])))


class _SupportCheck(object):
    """
    @version: Minimum libvirt version required for this feature. Not used
        if 'args' provided.

    @function: Function name to check exists. Expected to be of the
        format $obj.$func. Like virDomain.isActive

    @run_args: Argument tuple to actually test 'function' with, and check
        for an 'unsupported' error from libvirt.

    @flag: A flag to check exists. This will be appended to the argument
        :list if run_args are provided, otherwise we will only check against
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

        if self.function:
            assert len(function.split(".")) == 2

        versions = ([self.version] + list(self.hv_libvirt_version.values()))
        for vstr in versions:
            v = _version_str_to_int(vstr)
            if vstr is not None and v != 0 and v < 7003:
                raise xmlutil.DevError(
                    "Cannot enforce "
                    "support checks for libvirt versions less than 0.7.3, "
                    "since required APIs were not available. ver=%s" % vstr)

    def __call__(self, virtconn, data=None):
        """
        Attempt to determine if a specific libvirt feature is support given
        the passed connection.

        :param virtconn: VirtinstConnection to check feature on
        :param feature: Feature type to check support for
        :type feature: One of the SUPPORT_* flags
        :param data: Option libvirt object to use in feature checking
        :type data: Could be virDomain, virNetwork, virStoragePool, hv name, etc

        :returns: True if feature is supported, False otherwise
        """
        if "VirtinstConnection" in repr(data):
            data = data.get_conn_for_api_arg()

        if self.function:
            ret = _check_function(
                    self.function, self.flag, self.run_args, data)
            if ret is not None:
                return ret

        # Do this after the function check, since there's an ordering issue
        # with VirtinstConnection
        hv_type = virtconn.get_uri_driver()
        actual_libvirt_version = virtconn.daemon_version()
        actual_hv_version = virtconn.conn_version()

        # Check that local libvirt version is sufficient
        v = _version_str_to_int(self.version)
        if v and (v > actual_libvirt_version):
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
                if "all" not in self.hv_libvirt_version:
                    return False
            elif (actual_libvirt_version <
                  _version_str_to_int(self.hv_libvirt_version[hv_type])):
                return False

        return True


def _make(*args, **kwargs):
    """
    Create a _SupportCheck from the passed args, then turn it into a
    SupportCache method which captures and caches the returned support
    value in self._cache
    """
    # pylint: disable=protected-access
    support_obj = _SupportCheck(*args, **kwargs)

    def cache_wrapper(self, data=None):
        if support_obj not in self._cache:
            support_ret = support_obj(self._virtconn, data or self._virtconn)
            self._cache[support_obj] = support_ret
        return self._cache[support_obj]

    return cache_wrapper


class SupportCache:
    """
    Class containing all support checks and access APIs, and support for
    caching returned results
    """

    @staticmethod
    def is_libvirt_error_no_domain(err):
        """
        Small helper to check if the passed exception is a libvirt error
        with code VIR_ERR_NO_DOMAIN
        """
        if not isinstance(err, libvirt.libvirtError):
            return False  # pragma: no cover
        return err.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN

    @staticmethod
    def is_error_nosupport(err):
        """
        Check if passed exception indicates that the called libvirt command isn't
        supported

        :param err: Exception raised from command call
        :returns: True if command isn't supported, False if we can't determine
        """
        if not isinstance(err, libvirt.libvirtError):
            return False  # pragma: no cover

        if (err.get_error_code() == libvirt.VIR_ERR_RPC or
            err.get_error_code() == libvirt.VIR_ERR_NO_SUPPORT):
            return True

        return False  # pragma: no cover


    def __init__(self, virtconn):
        self._cache = {}
        self._virtconn = virtconn

    conn_domain = _make(
        function="virConnect.listAllDomains", run_args=())
    conn_storage = _make(
        function="virConnect.listAllStoragePools", run_args=())
    conn_nodedev = _make(
        function="virConnect.listDevices", run_args=(None, 0))
    conn_network = _make(
        function="virConnect.listNetworks", run_args=())

    conn_stream = _make(function="virConnect.newStream", run_args=(0,))
    conn_working_xen_events = _make(hv_version={"xen": "4.0.0", "all": 0})
    # This is an arbitrary check to say whether it's a good idea to
    # default to qcow2. It might be fine for xen or qemu older than the versions
    # here, but until someone tests things I'm going to be a bit conservative.
    conn_default_qcow2 = _make(hv_version={"qemu": "1.2.0", "test": 0})
    conn_autosocket = _make(hv_libvirt_version={"qemu": "1.0.6"})
    conn_pm_disable = _make(hv_version={"qemu": "1.2.0", "test": 0})
    conn_qcow2_lazy_refcounts = _make(
        version="1.1.0", hv_version={"qemu": "1.2.0", "test": 0})
    conn_hyperv_vapic = _make(
        version="1.1.0", hv_version={"qemu": "1.1.0", "test": 0})
    conn_hyperv_clock = _make(
        version="1.2.2", hv_version={"qemu": "1.5.3", "test": 0})
    conn_domain_capabilities = _make(
        function="virConnect.getDomainCapabilities",
        run_args=(None, None, None, None))
    conn_vmport = _make(
        version="1.2.16", hv_version={"qemu": "2.2.0", "test": 0})
    conn_mem_stats_period = _make(
        function="virDomain.setMemoryStatsPeriod",
        version="1.1.1", hv_version={"qemu": 0, "test": "5.6.0"})
    # spice GL is actually enabled with libvirt 1.3.3, but 3.1.0 is the
    # first version that sorts out the qemu:///system + cgroup issues
    conn_graphics_listen_none = _make(version="2.0.0")
    conn_rng_urandom = _make(version="1.3.4")
    conn_usb3_ports = _make(version="1.3.5")
    conn_machvirt_pci_default = _make(version="3.0.0")
    conn_qemu_xhci = _make(version="3.3.0", hv_version={"qemu": "2.9.0"})
    conn_vnc_none_auth = _make(hv_version={"qemu": "2.9.0"})
    conn_device_boot_order = _make(hv_version={"qemu": 0, "test": 0})
    conn_riscv_virt_pci_default = _make(version="5.3.0", hv_version={"qemu": "4.0.0"})

    # We choose qemu 2.11.0 as the first version to target for q35 default.
    # That's not really based on anything except reasonably modern at the
    # time of these patches.
    qemu_q35_default = _make(hv_version={"qemu": "2.11.0", "test": "0"})

    # This is for disk <driver name=qemu>. xen supports this, but it's
    # limited to arbitrary new enough xen, since I know libxl can handle it
    # but I don't think the old xend driver does.
    conn_disk_driver_name_qemu = _make(
        hv_version={"qemu": 0, "xen": "4.2.0"},
        hv_libvirt_version={"qemu": 0, "xen": "1.1.0"})

    # Domain checks
    domain_xml_inactive = _make(function="virDomain.XMLDesc", run_args=(),
        flag="VIR_DOMAIN_XML_INACTIVE")
    domain_xml_secure = _make(function="virDomain.XMLDesc", run_args=(),
        flag="VIR_DOMAIN_XML_SECURE")
    domain_managed_save = _make(
        function="virDomain.hasManagedSaveImage",
        run_args=(0,))
    domain_job_info = _make(function="virDomain.jobInfo", run_args=())
    domain_list_snapshots = _make(
        function="virDomain.listAllSnapshots", run_args=())
    domain_memory_stats = _make(
        function="virDomain.memoryStats", run_args=())
    domain_state = _make(function="virDomain.state", run_args=())
    domain_open_graphics = _make(function="virDomain.openGraphicsFD",
        version="1.2.8", hv_version={"qemu": 0})

    # Pool checks
    pool_metadata_prealloc = _make(
        flag="VIR_STORAGE_VOL_CREATE_PREALLOC_METADATA",
        version="1.0.1")

    # Nodedev checks
    # Added in libvirt 7.8.0 mid 2021
    nodedev_isactive = _make(
        function="virNodeDevice.isActive", run_args=())


    def _check_version(self, version):
        """
        Check libvirt version. Useful for the test suite so we don't need
        to keep adding new support checks.
        """
        sobj = _SupportCheck(version=version)
        return sobj(self._virtconn, None)
