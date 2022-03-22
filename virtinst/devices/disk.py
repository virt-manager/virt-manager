#
# Classes for building disk device xml
#
# Copyright 2006-2008, 2012-2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from ..logger import log

from .. import diskbackend
from .. import progress
from .. import xmlutil
from .device import Device, DeviceAddress, DeviceSeclabel
from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


def _qemu_sanitize_drvtype(phystype, fmt):
    """
    Sanitize libvirt storage volume format to a valid qemu driver type
    """
    raw_list = ["iso"]

    if phystype == DeviceDisk.TYPE_BLOCK:
        return DeviceDisk.DRIVER_TYPE_RAW
    if fmt in raw_list:
        return DeviceDisk.DRIVER_TYPE_RAW
    return fmt


class _Host(XMLBuilder):
    _XML_PROP_ORDER = ["name", "port", "transport", "socket"]
    XML_NAME = "host"

    name = XMLProperty("./@name")
    port = XMLProperty("./@port", is_int=True)
    transport = XMLProperty("./@transport")
    socket = XMLProperty("./@socket")


class _DiskSourceAddress(DeviceAddress):
    pass


class _DiskSource(XMLBuilder):
    """
    Class representing disk <source> block, and various helpers
    that only operate on <source> contents
    """
    _XML_PROP_ORDER = [
        "file", "dev", "dir",
        "volume", "pool", "protocol", "name", "hosts",
        "type", "managed", "namespace", "address"]
    XML_NAME = "source"

    file = XMLProperty("./@file")
    dev = XMLProperty("./@dev")
    dir = XMLProperty("./@dir")

    pool = XMLProperty("./@pool")
    volume = XMLProperty("./@volume")

    hosts = XMLChildProperty(_Host)

    name = XMLProperty("./@name")
    protocol = XMLProperty("./@protocol")
    query = XMLProperty("./@query")

    type = XMLProperty("./@type")
    managed = XMLProperty("./@managed", is_yesno=True)
    namespace = XMLProperty("./@namespace", is_int=True)
    address = XMLChildProperty(_DiskSourceAddress, is_single=True)

    def set_from_url(self, uri):
        """
        For a passed in path URI like gluster:// or https://, split it
        up and set the <disk> properties directly
        """
        from ..uri import URI
        uriobj = URI(uri)

        if uriobj.scheme:
            self.protocol = uriobj.scheme
        if ((uriobj.hostname or uriobj.port or uriobj.transport) and
            not self.hosts):
            self.hosts.add_new()
        if uriobj.transport:
            self.hosts[0].transport = uriobj.transport
        if uriobj.hostname:
            self.hosts[0].name = uriobj.hostname
        if uriobj.port:
            self.hosts[0].port = uriobj.port
        if uriobj.path:
            if self.hosts and self.hosts[0].transport:
                self.hosts[0].socket = uriobj.path
            else:
                self.name = uriobj.path
                if self.name.startswith("/"):
                    self.name = self.name[1:]
        if uriobj.query:
            self.query = uriobj.query

    def build_url_from_network(self):
        """
        Build a URL from network contents of <source>
        """
        host = _Host(self.conn)
        if self.hosts:
            host = self.hosts[0]

        ret = self.protocol or "unknown"
        if host.transport:
            ret += "+%s" % host.transport
        ret += "://"
        if host.name:
            ret += host.name
            if host.port:
                ret += ":" + str(host.port)
        if self.name:
            if not self.name.startswith("/"):
                ret += "/"
            ret += self.name
        elif host.socket:
            if not host.socket.startswith("/"):
                ret += "/"
            ret += host.socket
        return ret

    def clear_source(self):
        """
        Unset all XML properties that describe the actual source media
        """
        self.file = None
        self.dev = None
        self.dir = None
        self.volume = None
        self.pool = None
        self.name = None
        self.protocol = None
        for h in self.hosts[:]:
            self.remove_child(h)

    def set_network_from_storage(self, volxml, poolxml):
        """
        For the passed pool + vol object combo representing a network
        volume, set the <source> elements directly
        """
        is_iscsi_direct = poolxml.type == "iscsi-direct"
        protocol = poolxml.type
        if is_iscsi_direct:
            protocol = "iscsi"

        self.protocol = protocol
        for idx, poolhost in enumerate(poolxml.hosts):
            if len(self.hosts) < (idx + 1):
                self.hosts.add_new()
            self.hosts[idx].name = poolhost.name
            self.hosts[idx].port = poolhost.port

        path = ""
        if is_iscsi_direct:
            # Vol path is like this:
            # ip-10.66.144.87:3260-iscsi-iqn.2017-12.com.virttest:emulated-iscsi-noauth.target2-lun-1
            # Always seems to have -iscsi- embedded in it
            if "-iscsi-iqn." in volxml.target_path:
                path = volxml.target_path.split("-iscsi-", 1)[-1]
        else:
            if poolxml.source_name:
                path += poolxml.source_name
                if poolxml.source_path:
                    path += poolxml.source_path
                if not path.endswith('/'):
                    path += "/"
            path += volxml.name
        self.name = path or None


class DeviceDisk(Device):
    XML_NAME = "disk"

    DRIVER_NAME_PHY = "phy"
    DRIVER_NAME_QEMU = "qemu"
    DRIVER_TYPE_RAW = "raw"

    CACHE_MODE_NONE = "none"
    CACHE_MODE_WRITETHROUGH = "writethrough"
    CACHE_MODE_WRITEBACK = "writeback"
    CACHE_MODE_DIRECTSYNC = "directsync"
    CACHE_MODE_UNSAFE = "unsafe"
    CACHE_MODES = [CACHE_MODE_NONE, CACHE_MODE_WRITETHROUGH,
        CACHE_MODE_WRITEBACK, CACHE_MODE_DIRECTSYNC, CACHE_MODE_UNSAFE]

    DISCARD_MODE_IGNORE = "ignore"
    DISCARD_MODE_UNMAP = "unmap"
    DISCARD_MODES = [DISCARD_MODE_IGNORE, DISCARD_MODE_UNMAP]

    DEVICE_DISK = "disk"
    DEVICE_LUN = "lun"
    DEVICE_CDROM = "cdrom"
    DEVICE_FLOPPY = "floppy"

    TYPE_FILE = "file"
    TYPE_BLOCK = "block"
    TYPE_DIR = "dir"
    TYPE_VOLUME = "volume"
    TYPE_NETWORK = "network"

    IO_MODE_NATIVE = "native"


    @staticmethod
    def path_definitely_exists(conn, path):
        """
        Check if path exists.

        return True if we are certain, False otherwise. Path may in fact
        exist if we return False, but we can't exhaustively know in all
        cases.

        (In fact if cached storage volume data is out of date, the volume
         may have disappeared behind our back, but that shouldn't have bad
         effects in practice.)
        """
        return diskbackend.path_definitely_exists(conn, path)

    @staticmethod
    def check_path_search(conn, path):
        """
        Check if the connection DAC user has search permissions for all the
        directories in the passed path.

        :returns: Class with:
            - List of the directories the user cannot search, or empty list
            - username we checked for or None if not applicable
            - uid we checked for or None if not application
        """
        log.debug("DeviceDisk.check_path_search path=%s", path)
        class SearchData(object):
            def __init__(self):
                self.user = None
                self.uid = None
                self.fixlist = []

        searchdata = SearchData()
        if not path:
            return searchdata

        if conn.is_remote():
            return searchdata
        if not conn.is_qemu_privileged():
            return searchdata
        if diskbackend.path_is_url(path):
            return searchdata
        if diskbackend.path_is_network_vol(conn, path):
            return searchdata
        path = os.path.abspath(path)

        user, uid = conn.caps.host.get_qemu_baselabel()
        if not user:
            return searchdata
        if uid == 0 and not xmlutil.in_testsuite():
            return searchdata  # pragma: no cover

        searchdata.user = user
        searchdata.uid = uid
        searchdata.fixlist = diskbackend.is_path_searchable(path, uid, user)
        searchdata.fixlist.reverse()
        return searchdata

    @staticmethod
    def fix_path_search(searchdata):
        """
        Try to fix any permission problems found by check_path_search

        :returns: Return a dictionary of entries {broken path : error msg}
        """
        errdict = diskbackend.set_dirs_searchable(
                searchdata.fixlist, searchdata.user)
        return errdict

    @staticmethod
    def path_in_use_by(conn, path, shareable=False, read_only=False):
        """
        Return a list of VM names that are using the passed path.

        :param conn: virConnect to check VMs
        :param path: Path to check for
        :param shareable: Path we are checking is marked shareable, so
            don't warn if it conflicts with another shareable source.
        :param read_only: Path we are checking is marked read_only, so
            don't warn if it conflicts with another read_only source.
        """
        if not path:
            return []

        # Find all volumes that have 'path' somewhere in their backing chain
        vols = []
        volmap = dict((vol.backing_store, vol)
                      for vol in conn.fetch_all_vols() if vol.backing_store)
        backpath = path
        while backpath in volmap:
            vol = volmap[backpath]
            if vol in vols:
                break  # pragma: no cover
            backpath = vol.target_path
            vols.append(backpath)

        ret = []
        vms = conn.fetch_all_domains()
        for vm in vms:
            if not read_only:
                if path in [vm.os.kernel, vm.os.initrd, vm.os.dtb]:
                    ret.append(vm.name)
                    continue

            for disk in vm.devices.disk:
                checkpath = disk.get_source_path()
                if checkpath in vols and vm.name not in ret:
                    # VM uses the path indirectly via backing store
                    ret.append(vm.name)
                    break

                if checkpath != path:
                    continue

                if shareable and disk.shareable:
                    continue
                if read_only and disk.read_only:
                    continue

                ret.append(vm.name)
                break

        return ret

    @staticmethod
    def build_vol_install(conn, volname, poolobj, size, sparse,
                          fmt=None, backing_store=None, backing_format=None):
        """
        Helper for building a StorageVolume instance to pass to DeviceDisk
        for eventual storage creation.

        :param volname: name of the volume to be created
        :param size: size in bytes
        """
        from ..storage import StorageVolume

        if size is None:
            raise ValueError(_("Size must be specified for non "
                               "existent volume '%s'" % volname))

        # This catches --disk /dev/idontexist,size=1 if /dev is unmanaged
        if not poolobj:
            raise RuntimeError(_("Don't know how to create storage for "
                "path '%s'. Use libvirt APIs to manage the parent directory "
                "as a pool first.") % volname)

        log.debug("Creating volume '%s' on pool '%s'",
                      volname, poolobj.name())

        cap = (size * 1024 * 1024 * 1024)
        if sparse:
            alloc = 0
        else:
            alloc = cap

        volinst = StorageVolume(conn)
        volinst.pool = poolobj
        volinst.name = volname
        volinst.capacity = cap
        volinst.allocation = alloc
        volinst.backing_store = backing_store
        volinst.backing_format = backing_format

        if fmt:
            if not volinst.supports_format():
                raise ValueError(_("Format attribute not supported for this "
                                   "volume type"))
            volinst.format = fmt

        return volinst

    @staticmethod
    def num_to_target(num):
        """
        Convert an index in range (1, 1024) to a disk /dev number
        (like hda, hdb, hdaa, etc.)
        """
        digits = []
        for factor in range(0, 3):
            amt = (num % (26 ** (factor + 1))) // (26 ** factor)
            if amt == 0 and num >= (26 ** (factor + 1)):
                amt = 26
            num -= amt
            digits.insert(0, amt)

        gen_t = ""
        for digit in digits:
            if digit == 0:
                continue
            gen_t += "%c" % (ord('a') + digit - 1)

        return gen_t


    @staticmethod
    def target_to_num(tgt):
        """
        Convert disk /dev number (like hda, hdb, hdaa, etc.) to an index
        """
        num = 0
        k = 0
        if tgt[0] == 'x':
            # This case is here for 'xvda'
            tgt = tgt[1:]
        for i, c in enumerate(reversed(tgt[2:])):
            if i != 0:
                k = 1
            num += (ord(c) - ord('a') + k) * (26 ** i)
        return num


    _XML_PROP_ORDER = [
        "_xmltype", "_device", "snapshot_policy",
        "driver_name", "driver_type",
        "driver_cache", "driver_discard", "driver_detect_zeroes",
        "driver_io", "driver_iothread", "driver_queues", "error_policy",
        "auth_username", "auth_secret_type", "auth_secret_uuid",
        "source",
        "target", "bus",
    ]

    def __init__(self, *args, **kwargs):
        Device.__init__(self, *args, **kwargs)

        self._source_volume_err = None
        self.storage_was_created = False

        self._storage_backend = diskbackend.StorageBackendStub(
            self.conn, self._get_xmlpath(), self._xmltype, self.driver_type)


    ##################
    # XML properties #
    ##################

    _xmltype = XMLProperty("./@type")
    _device = XMLProperty("./@device")

    driver_name = XMLProperty("./driver/@name")
    driver_type = XMLProperty("./driver/@type")

    source = XMLChildProperty(_DiskSource, is_single=True)

    auth_username = XMLProperty("./auth/@username")
    auth_secret_type = XMLProperty("./auth/secret/@type")
    auth_secret_uuid = XMLProperty("./auth/secret/@uuid")

    snapshot_policy = XMLProperty("./@snapshot")

    driver_copy_on_read = XMLProperty("./driver/@copy_on_read", is_onoff=True)

    sgio = XMLProperty("./@sgio")
    rawio = XMLProperty("./@rawio")

    bus = XMLProperty("./target/@bus")
    target = XMLProperty("./target/@dev")
    removable = XMLProperty("./target/@removable", is_onoff=True)
    rotation_rate = XMLProperty("./target/@rotation_rate", is_int=True)

    read_only = XMLProperty("./readonly", is_bool=True)
    shareable = XMLProperty("./shareable", is_bool=True)
    transient = XMLProperty("./transient", is_bool=True)
    transient_shareBacking = XMLProperty("./transient/@shareBacking", is_yesno=True)
    driver_cache = XMLProperty("./driver/@cache")
    driver_discard = XMLProperty("./driver/@discard")
    driver_detect_zeroes = XMLProperty("./driver/@detect_zeroes")
    driver_io = XMLProperty("./driver/@io")
    driver_iothread = XMLProperty("./driver/@iothread", is_int=True)
    driver_queues = XMLProperty("./driver/@queues", is_int=True)

    error_policy = XMLProperty("./driver/@error_policy")
    serial = XMLProperty("./serial")
    wwn = XMLProperty("./wwn")
    startup_policy = XMLProperty("./source/@startupPolicy")
    logical_block_size = XMLProperty("./blockio/@logical_block_size")
    physical_block_size = XMLProperty("./blockio/@physical_block_size")

    iotune_rbs = XMLProperty("./iotune/read_bytes_sec", is_int=True)
    iotune_ris = XMLProperty("./iotune/read_iops_sec", is_int=True)
    iotune_tbs = XMLProperty("./iotune/total_bytes_sec", is_int=True)
    iotune_tis = XMLProperty("./iotune/total_iops_sec", is_int=True)
    iotune_wbs = XMLProperty("./iotune/write_bytes_sec", is_int=True)
    iotune_wis = XMLProperty("./iotune/write_iops_sec", is_int=True)

    seclabels = XMLChildProperty(DeviceSeclabel, relative_xpath="./source")

    geometry_cyls = XMLProperty("./geometry/@cyls", is_int=True)
    geometry_heads = XMLProperty("./geometry/@heads", is_int=True)
    geometry_secs = XMLProperty("./geometry/@secs", is_int=True)
    geometry_trans = XMLProperty("./geometry/@trans")

    reservations_managed = XMLProperty("./source/reservations/@managed")
    reservations_source_type = XMLProperty("./source/reservations/source/@type")
    reservations_source_path = XMLProperty("./source/reservations/source/@path")
    reservations_source_mode = XMLProperty("./source/reservations/source/@mode")


    #############################
    # Internal defaults helpers #
    #############################

    def _get_default_type(self):
        if self.source.pool or self.source.volume:
            return DeviceDisk.TYPE_VOLUME
        if not self._storage_backend.is_stub():
            return self._storage_backend.get_dev_type()
        if self.source.protocol:
            return DeviceDisk.TYPE_NETWORK
        return self.TYPE_FILE

    def _get_default_driver_name(self):
        if self.is_empty():
            return None

        # Recommended xen defaults from here:
        # https://bugzilla.redhat.com/show_bug.cgi?id=1171550#c9
        # If type block, use name=phy. Otherwise do the same as qemu
        if self.conn.is_xen() and self.type == self.TYPE_BLOCK:
            return self.DRIVER_NAME_PHY
        if self.conn.support.conn_disk_driver_name_qemu():
            return self.DRIVER_NAME_QEMU
        return None

    def _get_default_driver_type(self):
        """
        Set driver type from passed parameters

        Where possible, we want to force /driver/@type = "raw" if installing
        a QEMU VM. Without telling QEMU to expect a raw file, the emulator
        is forced to autodetect, which has security implications:

        https://lists.gnu.org/archive/html/qemu-devel/2008-04/msg00675.html
        """
        if self.driver_name != self.DRIVER_NAME_QEMU:
            return None

        drvtype = self._storage_backend.get_driver_type()
        return _qemu_sanitize_drvtype(self.type, drvtype)

    def _get_type(self):
        if self._xmltype:
            return self._xmltype
        return self._get_default_type()
    def _set_type(self, val):
        self._xmltype = val
    type = property(_get_type, _set_type)

    def _get_device(self):
        if self._device:
            return self._device
        return self.DEVICE_DISK
    def _set_device(self, val):
        self._device = val
    device = property(_get_device, _set_device)


    ############################
    # Storage backend handling #
    ############################

    def _change_backend(self, path, vol_object, parent_pool):
        backend = diskbackend.StorageBackend(self.conn, path,
                                             vol_object, parent_pool)
        self._storage_backend = backend

    def set_backend_for_existing_path(self):
        # This is an entry point for parsexml Disk instances to request
        # a _storage_backend to be initialized from the XML path. That
        # will cause validate() to actually validate the path exists.
        # We need this so addhw XML editing will still validate the disk path
        if self._storage_backend.is_stub():
            self._resolve_storage_backend()

    def _resolve_storage_backend(self):
        """
        Convert the relevant <source> XML values into self._storage_backend
        """
        path = None
        vol_object = None
        parent_pool = None
        self._source_volume_err = None
        typ = self._get_default_type()

        if self.type == DeviceDisk.TYPE_NETWORK:
            # Fill in a completed URL for virt-manager UI, path comparison, etc
            path = self.source.build_url_from_network()

        if typ == DeviceDisk.TYPE_VOLUME:
            try:
                parent_pool = self.conn.storagePoolLookupByName(
                    self.source.pool)
                vol_object = parent_pool.storageVolLookupByName(
                    self.source.volume)
            except Exception as e:
                self._source_volume_err = str(e)
                log.debug("Error fetching source pool=%s vol=%s",
                    self.source.pool, self.source.volume, exc_info=True)

        if vol_object is None and path is None:
            path = self._get_xmlpath()

        if path and not vol_object and not parent_pool:
            (dummy, vol_object, parent_pool) = diskbackend.manage_path(
                    self.conn, path)

        self._change_backend(path, vol_object, parent_pool)

    def get_source_path(self):
        """
        Source path is a single string representation of the disk source
        storage. For regular storage this is a FS path. For type=network
        this is a reconstructed URL. In some cases like rbd:// this may
        be an entirely synthetic URL format
        """
        if (self._storage_backend.is_stub() and not
            self._storage_backend.get_path()):
            self._resolve_storage_backend()
        return self._storage_backend.get_path()

    def set_source_path(self, newpath):
        if self._storage_backend.will_create_storage():
            raise xmlutil.DevError(
                    "Can't change disk path if storage creation info "
                    "has been set.")

        # User explicitly changed 'path', so try to lookup its storage
        # object since we may need it
        (newpath, vol_object, parent_pool) = diskbackend.manage_path(
                self.conn, newpath)

        self._change_backend(newpath, vol_object, parent_pool)
        self._set_xmlpath(self.get_source_path())

    def set_vol_object(self, vol_object, parent_pool):
        log.debug("disk.set_vol_object: volxml=\n%s",
            vol_object.XMLDesc(0))
        log.debug("disk.set_vol_object: poolxml=\n%s",
            parent_pool.XMLDesc(0))
        self._change_backend(None, vol_object, parent_pool)
        self._set_xmlpath(self.get_source_path())

    def set_vol_install(self, vol_install):
        log.debug("disk.set_vol_install: name=%s poolxml=\n%s",
            vol_install.name, vol_install.pool.XMLDesc(0))
        self._storage_backend = diskbackend.ManagedStorageCreator(
            self.conn, vol_install)
        self._set_xmlpath(self.get_source_path())

    def get_vol_object(self):
        return self._storage_backend.get_vol_object()
    def get_vol_install(self):
        return self._storage_backend.get_vol_install()
    def get_parent_pool(self):
        return self._storage_backend.get_parent_pool()
    def get_size(self):
        return self._storage_backend.get_size()


    def _set_source_network_from_storage(self, volxml, poolxml):
        self.type = "network"
        if poolxml.auth_type:
            self.auth_username = poolxml.auth_username
            self.auth_secret_type = poolxml.auth_type
            self.auth_secret_uuid = poolxml.auth_secret_uuid

        self.source.set_network_from_storage(volxml, poolxml)

    def _set_network_source_from_backend(self):
        if (self._storage_backend.get_vol_object() or
            self._storage_backend.get_vol_install()):
            volxml = self._storage_backend.get_vol_xml()
            poolxml = self._storage_backend.get_parent_pool_xml()
            self._set_source_network_from_storage(volxml, poolxml)
        elif self._storage_backend.get_path():
            self.source.set_from_url(self._storage_backend.get_path())

    def _disk_type_to_object_prop_name(self):
        disk_type = self.type
        if disk_type == DeviceDisk.TYPE_BLOCK:
            return "dev"
        elif disk_type == DeviceDisk.TYPE_DIR:
            return "dir"
        elif disk_type == DeviceDisk.TYPE_FILE:
            return "file"
        return None


    # _xmlpath is an abstraction for source file/block/dir paths, since
    # they don't have any special properties aside from needing to match
    # 'type' value with the source property used.
    def _get_xmlpath(self):
        if self.source.file:
            return self.source.file
        if self.source.dev:
            return self.source.dev
        if self.source.dir:
            return self.source.dir
        return None

    def _set_xmlpath(self, val):
        self.source.clear_source()

        if self._storage_backend.get_dev_type() == "network":
            self._set_network_source_from_backend()
            return

        propname = self._disk_type_to_object_prop_name()
        if not propname:
            return
        return setattr(self.source, propname, val)

    def set_local_disk_to_clone(self, disk, sparse):
        """
        Set a path to manually clone (as in, not through libvirt)
        """
        self._storage_backend = diskbackend.CloneStorageCreator(self.conn,
            self.get_source_path(),
            disk.get_source_path(),
            disk.get_size(), sparse)


    #####################
    # Utility functions #
    #####################

    def is_empty(self):
        return not bool(self.get_source_path())

    def is_cdrom(self):
        return self.device == self.DEVICE_CDROM
    def is_floppy(self):
        return self.device == self.DEVICE_FLOPPY
    def is_disk(self):
        return self.device == self.DEVICE_DISK

    def can_be_empty(self):
        if self.is_floppy() or self.is_cdrom():
            return True
        if self.type in ["file", "block", "dir", "volume", "network"]:
            return False
        # Don't error for unknown types
        return True

    def wants_storage_creation(self):
        """
        If true, this disk needs storage creation parameters or things
        will error.
        """
        return not self._storage_backend.exists()


    ####################
    # Storage building #
    ####################

    def build_storage(self, meter):
        """
        Build storage (if required)

        If storage doesn't exist (a non-existent file 'path', or 'vol_install'
        was specified), we create it.
        """
        if not self._storage_backend.will_create_storage():
            return

        meter = progress.ensure_meter(meter)
        # pylint: disable=assignment-from-no-return
        vol_object = self._storage_backend.create(meter)
        self.storage_was_created = True
        if not vol_object:
            return

        parent_pool = self.get_vol_install().pool
        self._change_backend(None, vol_object, parent_pool)


    ######################
    # validation helpers #
    ######################

    def validate(self):
        if self.is_empty():
            if self._source_volume_err:
                raise RuntimeError(self._source_volume_err)

            if not self.can_be_empty():
                raise ValueError(_("Device type '%s' requires a path") %
                                 self.device)

            return

        if (not self._storage_backend.exists() and
            not self._storage_backend.will_create_storage()):
            raise ValueError(
                _("Must specify storage creation parameters for "
                  "non-existent path '%s'.") % self.get_source_path())

        self._storage_backend.validate()

    def is_size_conflict(self):
        """
        reports if disk size conflicts with available space

        returns a two element tuple:
            1. first element is True if fatal conflict occurs
            2. second element is a string description of the conflict or None
        Non fatal conflicts (sparse disk exceeds available space) will
        return (False, "description of collision")
        """
        return self._storage_backend.is_size_conflict()

    def is_conflict_disk(self):
        """
        check if specified storage is in use by any other VMs on passed
        connection.

        :returns: list of colliding VM names
        """
        ret = self.path_in_use_by(self.conn, self.get_source_path(),
                                  shareable=self.shareable,
                                  read_only=self.read_only)
        return ret


    ###########################
    # Misc functional helpers #
    ###########################

    def sync_path_props(self):
        """
        Fills in the values of type, driver_type, and driver_name for
        the associated backing storage. This needs to be manually called
        if changing an existing disk's media.
        """
        path = self._get_xmlpath()

        self.type = self._get_default_type()
        self.driver_name = self._get_default_driver_name()
        self.driver_type = self._get_default_driver_type()

        # Need to retrigger this if self.type changed
        if path:
            self._set_xmlpath(path)

    def get_target_prefix(self):
        """
        Returns the suggested disk target prefix (hd, xvd, sd ...) for the
        disk.
        :returns: str prefix, or None if no reasonable guess can be made
        """
        # The upper limits here aren't necessarily 1024, but let the HV
        # error as appropriate.
        def _return(prefix):
            nummap = {
                "vd": 1024,
                "xvd": 1024,
                "fd": 2,
                "hd": 4,
                "sd": 1024,
            }
            return prefix, nummap[prefix]

        if self.bus == "virtio":
            return _return("vd")
        elif self.bus == "xen":
            return _return("xvd")
        elif self.bus == "fdc" or self.is_floppy():
            return _return("fd")
        elif self.bus == "ide":
            return _return("hd")
        # sata, scsi, usb, sd
        return _return("sd")

    def generate_target(self, skip_targets):
        """
        Generate target device ('hda', 'sdb', etc..) for disk, excluding
        any targets in 'skip_targets'.
        Sets self.target, and returns the generated value.

        :param skip_targets: list of targets to exclude
        :returns: generated target
        """
        prefix, maxnode = self.get_target_prefix()
        skip_targets = [t for t in skip_targets if t and t.startswith(prefix)]
        skip_targets.sort()

        def get_target():
            first_found = None

            for i in range(maxnode):
                gen_t = prefix + self.num_to_target(i + 1)
                if gen_t in skip_targets:
                    skip_targets.remove(gen_t)
                    continue
                if not skip_targets:
                    return gen_t
                elif not first_found:
                    first_found = gen_t
            if first_found:
                return first_found

        ret = get_target()
        if ret:
            self.target = ret
            return ret

        raise ValueError(
            ngettext("Only %(number)s disk for bus '%(bus)s' are supported",
                     "Only %(number)s disks for bus '%(bus)s' are supported",
                     maxnode) %
            {"number": maxnode, "bus": self.bus})

    def change_bus(self, guest, newbus):
        """
        Change the bus value for an existing disk, which has some
        follow on side effects.
        """
        if self.bus == newbus:
            return

        oldprefix = self.get_target_prefix()[0]
        self.bus = newbus

        self.address.clear()

        if oldprefix == self.get_target_prefix()[0]:
            return

        used = [disk.target for disk in guest.devices.disk]

        if self.target:
            used.remove(self.target)

        self.target = None
        self.generate_target(used)


    #########################
    # set_defaults handling #
    #########################

    def _default_bus(self, guest):
        if self.is_floppy():
            return "fdc"
        if guest.os.is_xenpv():
            return "xen"
        if not guest.os.is_hvm():
            # This likely isn't correct, but it's kind of a catch all
            # for virt types we don't know how to handle.
            return "ide"
        if self.is_disk() and guest.supports_virtiodisk():
            return "virtio"
        if (self.is_cdrom() and
            guest.supports_virtioscsi() and
            not guest.os.is_x86()):
            # x86 long time default has been IDE CDROM, stick with that to
            # avoid churn, but every newer virt arch that supports virtio-scsi
            # should use it
            return "scsi"
        if guest.os.is_arm():
            return "sd"
        if guest.os.is_q35():
            return "sata"
        if self.conn.is_bhyve():
            # IDE bus is not supported by bhyve
            return "sata"
        return "ide"

    def set_defaults(self, guest):
        if not self._device:
            self._device = self._get_device()
        if not self._xmltype:
            self._xmltype = self._get_default_type()
        if not self.driver_name:
            self.driver_name = self._get_default_driver_name()
        if not self.driver_type:
            self.driver_type = self._get_default_driver_type()
        if not self.bus:
            self.bus = self._default_bus(guest)
        if self.is_cdrom():
            self.read_only = True

        discard_unmap = False
        if (self.conn.is_qemu() and
            self.is_disk() and
            self._storage_backend.will_create_storage() and
            self._storage_backend.get_vol_install() and
            self._storage_backend.get_vol_install().allocation == 0):
            discard_unmap = True

        if (self.conn.is_qemu() and
            self.is_disk() and
            self.type == self.TYPE_BLOCK):
            discard_unmap = True
            if not self.driver_cache:
                self.driver_cache = self.CACHE_MODE_NONE
            if not self.driver_io:
                self.driver_io = self.IO_MODE_NATIVE

        if discard_unmap:
            if not self.driver_discard:
                self.driver_discard = "unmap"

        if not self.target:
            used_targets = [d.target for d in guest.devices.disk if d.target]
            self.generate_target(used_targets)
