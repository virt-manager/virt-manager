#
# Copyright 2008, 2013, 2015 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import threading

import libvirt

from . import generatename
from . import progress
from .logger import log
from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


_DEFAULT_DEV_TARGET = "/dev"
_DEFAULT_SCSI_TARGET = "/dev/disk/by-path"
_DEFAULT_MPATH_TARGET = "/dev/mapper"


class _StoragePermissions(XMLBuilder):
    XML_NAME = "permissions"
    _XML_PROP_ORDER = ["mode", "owner", "group", "label"]

    mode = XMLProperty("./mode")
    owner = XMLProperty("./owner")
    group = XMLProperty("./group")
    label = XMLProperty("./label")


class _StorageObject(XMLBuilder):
    """
    Base class for building any libvirt storage object.

    Meaningless to directly instantiate.
    """

    ##############
    # Properties #
    ##############

    name = XMLProperty("./name")
    permissions = XMLChildProperty(_StoragePermissions,
                                   relative_xpath="./target",
                                   is_single=True)


def _preferred_default_pool_path(conn):
    path = "/var/lib/libvirt/images"
    if conn.is_unprivileged():
        path = os.path.expanduser("~/.local/share/libvirt/images")
    return path


def _lookup_poolxml_by_path(conn, path):
    for poolxml in conn.fetch_all_pools():
        xml_path = poolxml.target_path
        if xml_path is not None and os.path.abspath(xml_path) == path:
            return poolxml
    return None


class _Host(XMLBuilder):
    _XML_PROP_ORDER = ["name", "port"]
    XML_NAME = "host"

    name = XMLProperty("./@name")
    port = XMLProperty("./@port", is_int=True)


class StoragePool(_StorageObject):
    """
    Base class for building and installing libvirt storage pool xml
    """
    TYPE_DIR     = "dir"
    TYPE_FS      = "fs"
    TYPE_NETFS   = "netfs"
    TYPE_LOGICAL = "logical"
    TYPE_DISK    = "disk"
    TYPE_ISCSI   = "iscsi"
    TYPE_SCSI    = "scsi"
    TYPE_MPATH   = "mpath"
    TYPE_GLUSTER = "gluster"
    TYPE_RBD     = "rbd"
    TYPE_SHEEPDOG = "sheepdog"
    TYPE_ZFS     = "zfs"

    @staticmethod
    def pool_list_from_sources(conn, pool_type):
        """
        Return a list of StoragePool instances built from libvirt's pool
        source enumeration (if supported).

        :param conn: Libvirt connection
        :param pool_type: Pool type string from I{Types}
        """
        source_xml = "<source/>"

        try:
            xml = conn.findStoragePoolSources(pool_type, source_xml, 0)
        except Exception as e:  # pragma: no cover
            if conn.support.is_error_nosupport(e):
                return []
            raise

        log.debug("Libvirt returned pool sources XML:\n%s", xml)

        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml)

        # We implicitly only support this for pool TYPE_LOGICAL
        ret = [e.text for e in root.findall("./source/name")]

        log.debug("Sources returning: %s", ret)
        return ret

    @staticmethod
    def lookup_default_pool(conn):
        """
        Helper to lookup the default pool. It will return one of
        * The pool named 'default'
        * If that doesn't exist, the pool pointing to the default path
        * Otherwise None
        """
        name = "default"
        path = _preferred_default_pool_path(conn)

        poolxml = None
        for trypool in conn.fetch_all_pools():
            if trypool.name == name:
                poolxml = trypool
                break
        else:
            poolxml = _lookup_poolxml_by_path(conn, path)

        if poolxml:
            log.debug("Found default pool name=%s target=%s",
                    poolxml.name, poolxml.target_path)
        return poolxml

    @staticmethod
    def build_default_pool(conn):
        """
        Attempt to lookup the 'default' pool, but if it doesn't exist,
        create it
        """
        poolxml = StoragePool.lookup_default_pool(conn)
        if poolxml:
            return poolxml

        try:
            name = "default"
            path = _preferred_default_pool_path(conn)
            log.debug("Attempting to build default pool with target '%s'",
                          path)
            defpool = StoragePool(conn)
            defpool.type = defpool.TYPE_DIR
            defpool.name = name
            defpool.target_path = path
            defpool.install(build=True, create=True, autostart=True)
            return defpool
        except Exception as e:  # pragma: no cover
            log.debug("Error building default pool", exc_info=True)
            msg = (_("Couldn't create default storage pool '%(path)s': %(error)s") %
                    {"path": path, "error": str(e)})
            raise RuntimeError(msg) from None

    @staticmethod
    def lookup_pool_by_path(conn, path):
        """
        Return the first pool with matching matching target path.
        return the first we find, active or inactive. This iterates over
        all pools and dumps their xml, so it is NOT quick.

        :returns: virStoragePool object if found, None otherwise
        """
        poolxml = _lookup_poolxml_by_path(conn, path)
        if not poolxml:
            return None
        return conn.storagePoolLookupByName(poolxml.name)

    @staticmethod
    def find_free_name(conn, basename, **kwargs):
        """
        Finds a name similar (or equal) to passed 'basename' that is not
        in use by another pool. Extra params are passed to generate_name
        """
        def cb(name):
            for pool in conn.fetch_all_pools():
                if pool.name == name:
                    return True
            return False
        return generatename.generate_name(basename, cb, **kwargs)

    @staticmethod
    def ensure_pool_is_running(pool_object, refresh=False):
        """
        If the passed vmmStoragePool isn't running, start it.

        :param pool_object: vmmStoragePool to check/start
        :param refresh: If True, run refresh() as well
        """
        if pool_object.info()[0] != libvirt.VIR_STORAGE_POOL_RUNNING:
            log.debug("starting pool=%s", pool_object.name())
            pool_object.create(0)
        if refresh:
            log.debug("refreshing pool=%s", pool_object.name())
            pool_object.refresh(0)


    ######################
    # Validation helpers #
    ######################

    @staticmethod
    def validate_name(conn, name):
        XMLBuilder.validate_generic_name(_("Storage object"), name)

        try:
            conn.storagePoolLookupByName(name)
        except libvirt.libvirtError:
            return
        raise ValueError(_("Name '%s' already in use by another pool." %
                         name))  # pragma: no cover

    def default_target_path(self):
        if not self.supports_target_path():
            return None
        if (self.type == self.TYPE_DIR or
            self.type == self.TYPE_NETFS or
            self.type == self.TYPE_FS):
            return os.path.join(
                    _preferred_default_pool_path(self.conn), self.name)
        if self.type == self.TYPE_ISCSI or self.type == self.TYPE_SCSI:
            return _DEFAULT_SCSI_TARGET
        if self.type == self.TYPE_MPATH:
            return _DEFAULT_MPATH_TARGET

    def _type_to_source_prop(self):
        if (self.type == self.TYPE_NETFS or
            self.type == self.TYPE_GLUSTER):
            return "_source_dir"
        elif self.type == self.TYPE_SCSI:
            return "_source_adapter"
        else:
            return "_source_device"

    def _get_source(self):
        return getattr(self, self._type_to_source_prop())
    def _set_source(self, val):
        return setattr(self, self._type_to_source_prop(), val)
    source_path = property(_get_source, _set_source)

    def default_source_name(self):
        if not self.supports_source_name():
            return None

        if self.type == StoragePool.TYPE_RBD:
            return "rbd"
        if self.type == StoragePool.TYPE_GLUSTER:
            return "gv0"


    ##############
    # Properties #
    ##############

    XML_NAME = "pool"
    _XML_PROP_ORDER = ["name", "type", "uuid",
                       "capacity", "allocation", "available",
                       "format", "hosts",
                       "_source_dir", "_source_adapter", "_source_device",
                       "source_name", "target_path",
                       "permissions",
                       "auth_type", "auth_username", "auth_secret_uuid"]


    _source_dir = XMLProperty("./source/dir/@path")
    _source_adapter = XMLProperty("./source/adapter/@name")
    _source_device = XMLProperty("./source/device/@path")

    type = XMLProperty("./@type")
    uuid = XMLProperty("./uuid")

    capacity = XMLProperty("./capacity", is_int=True)
    allocation = XMLProperty("./allocation", is_int=True)
    available = XMLProperty("./available", is_int=True)

    format = XMLProperty("./source/format/@type")
    iqn = XMLProperty("./source/initiator/iqn/@name")
    source_name = XMLProperty("./source/name")

    auth_type = XMLProperty("./source/auth/@type")
    auth_username = XMLProperty("./source/auth/@username")
    auth_secret_uuid = XMLProperty("./source/auth/secret/@uuid")

    target_path = XMLProperty("./target/path")

    hosts = XMLChildProperty(_Host, relative_xpath="./source")


    ######################
    # Public API helpers #
    ######################

    def supports_target_path(self):
        return self.type in [
                self.TYPE_DIR, self.TYPE_FS, self.TYPE_NETFS,
                self.TYPE_ISCSI,
                self.TYPE_SCSI, self.TYPE_MPATH]

    def supports_source_name(self):
        return self.type in [self.TYPE_LOGICAL, self.TYPE_GLUSTER,
            self.TYPE_RBD, self.TYPE_SHEEPDOG, self.TYPE_ZFS]


    def supports_source_path(self):
        return self.type in [
                self.TYPE_FS, self.TYPE_NETFS,
                self.TYPE_DISK, self.TYPE_ISCSI, self.TYPE_SCSI,
                self.TYPE_GLUSTER]

    def supports_hosts(self):
        return self.type in [
                self.TYPE_NETFS, self.TYPE_ISCSI, self.TYPE_GLUSTER,
                self.TYPE_RBD, self.TYPE_SHEEPDOG]

    def supports_format(self):
        return self.type in [self.TYPE_FS, self.TYPE_NETFS, self.TYPE_DISK]

    def supports_iqn(self):
        return self.type in [self.TYPE_ISCSI]

    def get_disk_type(self):
        if (self.type == StoragePool.TYPE_DISK or
            self.type == StoragePool.TYPE_LOGICAL or
            self.type == StoragePool.TYPE_SCSI or
            self.type == StoragePool.TYPE_MPATH or
            self.type == StoragePool.TYPE_ZFS):
            return StorageVolume.TYPE_BLOCK
        if (self.type == StoragePool.TYPE_GLUSTER or
            self.type == StoragePool.TYPE_RBD or
            self.type == StoragePool.TYPE_ISCSI or
            self.type == StoragePool.TYPE_SHEEPDOG):
            return StorageVolume.TYPE_NETWORK
        return StorageVolume.TYPE_FILE


    ##################
    # Build routines #
    ##################

    def validate(self):
        self.validate_name(self.conn, self.name)

        if not self.target_path:
            if self.type == self.TYPE_DISK:
                # disk is a bit special, in that it demands a target path,
                # but basically can't handle anything other than /dev
                self.target_path = _DEFAULT_DEV_TARGET
            else:
                self.target_path = self.default_target_path()
        if not self.source_name:
            self.source_name = self.default_source_name()
        if not self.format and self.supports_format():
            self.format = "auto"

        if (self.type == self.TYPE_DISK and self.format == "auto"):
            # There is no explicit "auto" type for disk pools, but leaving out
            # the format type seems to do the job for existing formatted disks
            self.format = None

    def install(self, meter=None, create=False, build=False, autostart=False):
        """
        Install storage pool xml.
        """
        xml = self.get_xml()
        log.debug("Creating storage pool '%s' with xml:\n%s",
                      self.name, xml)

        meter = progress.ensure_meter(meter)

        try:
            pool = self.conn.storagePoolDefineXML(xml, 0)
        except Exception as e:  # pragma: no cover
            msg = _("Could not define storage pool: %s") % str(e)
            raise RuntimeError(msg) from None

        errmsg = None
        if build:
            try:
                pool.build(libvirt.VIR_STORAGE_POOL_BUILD_NEW)
            except Exception as e:  # pragma: no cover
                errmsg = _("Could not build storage pool: %s") % str(e)

        if create and not errmsg:
            try:
                pool.create(0)
            except Exception as e:  # pragma: no cover
                errmsg = _("Could not start storage pool: %s") % str(e)

        if autostart and not errmsg:
            try:
                pool.setAutostart(True)
            except Exception as e:  # pragma: no cover
                errmsg = _("Could not set pool autostart flag: %s") % str(e)

        if errmsg:  # pragma: no cover
            # Try and clean up the leftover pool
            try:
                pool.undefine()
            except Exception as e:
                log.debug("Error cleaning up pool after failure: %s",
                              str(e))
            raise RuntimeError(errmsg)

        self.conn.cache_new_pool(pool)

        return pool


def _progress_thread(volname, pool, meter, event):
    vol = None
    if not meter:
        return  # pragma: no cover

    while True:
        try:
            if not vol:
                vol = pool.storageVolLookupByName(volname)
            vol.info()  # pragma: no cover
            break  # pragma: no cover
        except Exception:
            if event.wait(.2):
                break

    if vol is None:
        log.debug("Couldn't lookup storage volume in prog thread.")
        return

    while True:  # pragma: no cover
        dummy1, dummy2, alloc = vol.info()
        meter.update(alloc)
        if event.wait(1):
            break


class StorageVolume(_StorageObject):
    """
    Base class for building and installing libvirt storage volume xml
    """
    @staticmethod
    def get_file_extension_for_format(fmt):
        if not fmt:
            return ""
        if fmt == "raw":
            return ".img"
        return "." + fmt

    @staticmethod
    def find_free_name(conn, pool_object, basename, collideguest=None, **kwargs):
        """
        Finds a name similar (or equal) to passed 'basename' that is not
        in use by another volume. Extra params are passed to generate_name

        :param collideguest: Guest object. If specified, also check to
        ensure we don't collide with any disk paths there
        """
        collidelist = []
        if collideguest:
            pooltarget = None
            poolname = pool_object.name()
            for poolxml in conn.fetch_all_pools():
                if poolxml.name == poolname:
                    pooltarget = poolxml.target_path
                    break

            for disk in collideguest.devices.disk:
                checkpath = disk.get_source_path()
                if (pooltarget and checkpath and
                    os.path.dirname(checkpath) == pooltarget):
                    collidelist.append(os.path.basename(checkpath))

        def cb(tryname):
            if tryname in collidelist:
                return True
            return generatename.check_libvirt_collision(
                pool_object.storageVolLookupByName, tryname)

        StoragePool.ensure_pool_is_running(pool_object, refresh=True)
        return generatename.generate_name(basename, cb, **kwargs)

    TYPE_FILE = getattr(libvirt, "VIR_STORAGE_VOL_FILE", 0)
    TYPE_BLOCK = getattr(libvirt, "VIR_STORAGE_VOL_BLOCK", 1)
    TYPE_DIR = getattr(libvirt, "VIR_STORAGE_VOL_DIR", 2)
    TYPE_NETWORK = getattr(libvirt, "VIR_STORAGE_VOL_NETWORK", 3)
    TYPE_NETDIR = getattr(libvirt, "VIR_STORAGE_VOL_NETDIR", 4)


    def __init__(self, *args, **kwargs):
        _StorageObject.__init__(self, *args, **kwargs)

        self._input_vol = None
        self._pool = None
        self._pool_xml = None
        self._reflink = False


    ######################
    # Non XML properties #
    ######################

    def _get_pool(self):
        return self._pool
    def _set_pool(self, newpool):
        StoragePool.ensure_pool_is_running(newpool)
        self._pool = newpool
        self._pool_xml = StoragePool(self.conn,
            parsexml=self._pool.XMLDesc(0))
    pool = property(_get_pool, _set_pool)

    @property
    def input_vol(self):
        return self._input_vol
    def set_input_vol(self, vol):
        self._input_vol = vol
        parsevol = StorageVolume(self.conn,
                                 parsexml=self._input_vol.XMLDesc(0))

        self.format = parsevol.format
        self.capacity = parsevol.capacity
        self.allocation = parsevol.allocation
        if not self._pool:
            self.pool = self._input_vol.storagePoolLookupByVolume()

    def _get_reflink(self):
        return self._reflink
    def _set_reflink(self, reflink):
        self._reflink = reflink
    reflink = property(_get_reflink, _set_reflink)


    ##########################
    # XML validation helpers #
    ##########################

    @staticmethod
    def validate_name(pool, name):
        XMLBuilder.validate_generic_name(_("Storage object"), name)

        try:
            pool.storageVolLookupByName(name)
        except libvirt.libvirtError:
            return
        raise ValueError(_("Name '%s' already in use by another volume." %
                         name))  # pragma: no cover

    def _get_vol_type(self):
        if self.type:  # pragma: no cover
            if self.type == "file":
                return self.TYPE_FILE
            elif self.type == "block":
                return self.TYPE_BLOCK
            elif self.type == "dir":
                return self.TYPE_DIR
            elif self.type == "network":
                return self.TYPE_NETWORK
        return self._pool_xml.get_disk_type()
    file_type = property(_get_vol_type)


    ##################
    # XML properties #
    ##################

    XML_NAME = "volume"
    _XML_PROP_ORDER = ["name", "key", "capacity", "allocation", "format",
                       "target_path", "permissions"]

    type = XMLProperty("./@type")
    key = XMLProperty("./key")
    capacity = XMLProperty("./capacity", is_int=True)
    allocation = XMLProperty("./allocation", is_int=True)
    format = XMLProperty("./target/format/@type")
    target_path = XMLProperty("./target/path")
    backing_store = XMLProperty("./backingStore/path")
    backing_format = XMLProperty("./backingStore/format/@type")
    lazy_refcounts = XMLProperty(
            "./target/features/lazy_refcounts", is_bool=True)


    def _detect_backing_store_format(self):
        log.debug("Attempting to detect format for backing_store=%s",
                self.backing_store)
        from . import diskbackend
        vol, pool = diskbackend.manage_path(self.conn, self.backing_store)

        if not vol:  # pragma: no cover
            log.debug("Didn't find any volume for backing_store")
            return None

        # Only set backing format for volumes that support
        # the 'format' parameter as we know it, like qcow2 etc.
        volxml = StorageVolume(self.conn, vol.XMLDesc(0))
        volxml.pool = pool
        log.debug("Found backing store volume XML:\n%s",
                volxml.get_xml())

        if not volxml.supports_format():  # pragma: no cover
            log.debug("backing_store volume doesn't appear to have "
                "a file format we can specify, returning None")
            return None

        log.debug("Returning format=%s", volxml.format)
        return volxml.format


    ######################
    # Public API helpers #
    ######################

    def supports_format(self):
        return self.file_type == self.TYPE_FILE


    ##################
    # Build routines #
    ##################

    def validate(self):
        self.validate_name(self.pool, self.name)

        if not self.format and self.file_type == self.TYPE_FILE:
            self.format = "raw"
        if self._prop_is_unset("lazy_refcounts") and self.format == "qcow2":
            self.lazy_refcounts = self.conn.support.conn_qcow2_lazy_refcounts()

        if self._pool_xml.type == StoragePool.TYPE_LOGICAL:
            if self.allocation != self.capacity:
                log.warning(_("Sparse logical volumes are not supported, "
                               "setting allocation equal to capacity"))
                self.allocation = self.capacity

        isfatal, errmsg = self.is_size_conflict()
        if isfatal:
            raise ValueError(errmsg)
        if errmsg:
            log.warning(errmsg)

    def install(self, meter=None):
        """
        Build and install storage volume from xml
        """
        if self.backing_store and not self.backing_format:
            self.backing_format = self._detect_backing_store_format()

        xml = self.get_xml()
        log.debug("Creating storage volume '%s' with xml:\n%s",
                      self.name, xml)

        cloneflags = 0
        createflags = 0
        if (self.format == "qcow2" and
            not self.backing_store and
            self.conn.support.pool_metadata_prealloc(self.pool)):
            createflags |= libvirt.VIR_STORAGE_VOL_CREATE_PREALLOC_METADATA
            if self.capacity == self.allocation:
                # For cloning, this flag will make libvirt+qemu-img preallocate
                # the new disk image
                cloneflags |= libvirt.VIR_STORAGE_VOL_CREATE_PREALLOC_METADATA

        if self.reflink:
            cloneflags |= getattr(libvirt,
                "VIR_STORAGE_VOL_CREATE_REFLINK", 1)

        event = threading.Event()
        meter = progress.ensure_meter(meter)
        t = threading.Thread(target=_progress_thread,
                             name="Checking storage allocation",
                             args=(self.name, self.pool, meter, event))
        t.setDaemon(True)

        try:
            t.start()
            meter.start(size=self.capacity,
                        text=_("Allocating '%s'") % self.name)

            if self.conn.is_really_test():
                # Test suite doesn't support any flags, so reset them
                createflags = 0
                cloneflags = 0

            if self.input_vol:
                vol = self.pool.createXMLFrom(xml, self.input_vol, cloneflags)
            else:
                log.debug("Using vol create flags=%s", createflags)
                vol = self.pool.createXML(xml, createflags)

            meter.end(self.capacity)
            log.debug("Storage volume '%s' install complete.", self.name)
            return vol
        except Exception as e:
            log.debug("Error creating storage volume", exc_info=True)
            msg = ("Couldn't create storage volume '%s': '%s'" % (
                self.name, str(e)))
            raise RuntimeError(msg) from None
        finally:
            event.set()
            t.join()

    def is_size_conflict(self):
        """
        Report if requested size exceeds its pool's available amount

        :returns: 2 element tuple:
            1. True if collision is fatal, false otherwise
            2. String message if some collision was encountered.
        """
        if not self.pool:
            return (False, "")

        # pool info is [pool state, capacity, allocation, available]
        avail = self.pool.info()[3]
        if self.allocation > avail:
            msg = (_("There is not enough free space on the storage "
                    "pool to create the volume. (%(mem1)s M requested "
                    "allocation > %(mem2)s M available)") %
                    {"mem1": (self.allocation // (1024 * 1024)),
                     "mem2": (avail // (1024 * 1024))})
            return (True, msg)
        elif self.capacity > avail:
            msg = (_("The requested volume capacity will exceed the "
                     "available pool space when the volume is fully "
                     "allocated. (%(mem1)s M requested "
                     "capacity > %(mem2)s M available)") %
                     {"mem1": (self.capacity // (1024 * 1024)),
                      "mem2": (avail // (1024 * 1024))})
            return (False, msg)
        return (False, "")
