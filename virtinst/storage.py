#
# Copyright 2008, 2013, 2015 Red Hat, Inc.
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

import os
import threading
import time
import logging

import libvirt

from .xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty
from . import util


_DEFAULT_DEV_TARGET = "/dev"
_DEFAULT_LVM_TARGET_BASE = "/dev/"
_DEFAULT_SCSI_TARGET = "/dev/disk/by-path"
_DEFAULT_MPATH_TARGET = "/dev/mapper"


class _StoragePermissions(XMLBuilder):
    _XML_ROOT_NAME = "permissions"
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

    ######################
    # Validation helpers #
    ######################

    def _check_name_collision(self, name):
        raise NotImplementedError()

    def _validate_name(self, name):
        if name == self.name:
            return
        util.validate_name(_("Storage object"), name)
        self._check_name_collision(name)
        return name


    ##############
    # Properties #
    ##############

    name = XMLProperty("./name", validate_cb=_validate_name,
                      doc=_("Name for the storage object."))
    permissions = XMLChildProperty(_StoragePermissions,
                                   relative_xpath="./target",
                                   is_single=True)


def _get_default_pool_path(conn):
    path = "/var/lib/libvirt/images"
    if conn.is_session_uri():
        path = os.path.expanduser("~/.local/share/libvirt/images")
    return path


class _Host(XMLBuilder):
    _XML_PROP_ORDER = ["name", "port"]
    _XML_ROOT_NAME = "host"

    name = XMLProperty("./@name")
    port = XMLProperty("./@port", is_int=True)


class StoragePool(_StorageObject):
    """
    Base class for building and installing libvirt storage pool xml
    """
    # @group Types: TYPE_*
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

    # Pool type descriptions for use in higher level programs
    _descs = {}
    _descs[TYPE_DIR]     = _("Filesystem Directory")
    _descs[TYPE_FS]      = _("Pre-Formatted Block Device")
    _descs[TYPE_NETFS]   = _("Network Exported Directory")
    _descs[TYPE_LOGICAL] = _("LVM Volume Group")
    _descs[TYPE_DISK]    = _("Physical Disk Device")
    _descs[TYPE_ISCSI]   = _("iSCSI Target")
    _descs[TYPE_SCSI]    = _("SCSI Host Adapter")
    _descs[TYPE_MPATH]   = _("Multipath Device Enumerator")
    _descs[TYPE_GLUSTER] = _("Gluster Filesystem")
    _descs[TYPE_RBD]     = _("RADOS Block Device/Ceph")
    _descs[TYPE_SHEEPDOG] = _("Sheepdog Filesystem")
    _descs[TYPE_ZFS]     = _("ZFS Pool")

    @staticmethod
    def get_pool_types():
        """
        Return list of appropriate pool types
        """
        return StoragePool._descs.keys()

    @staticmethod
    def get_pool_type_desc(pool_type):
        """
        Return human readable description for passed pool type
        """
        return StoragePool._descs.get(pool_type, "%s pool" % pool_type)

    @staticmethod
    def pool_list_from_sources(conn, pool_type, host=None):
        """
        Return a list of StoragePool instances built from libvirt's pool
        source enumeration (if supported).

        @param conn: Libvirt connection
        @param name: Name for the new pool
        @param pool_type: Pool type string from I{Types}
        @param host: Option host string to poll for sources
        """
        if not conn.check_support(conn.SUPPORT_CONN_FINDPOOLSOURCES):
            return []

        if host:
            source_xml = "<source><host name='%s'/></source>" % host
        else:
            source_xml = "<source/>"

        try:
            xml = conn.findStoragePoolSources(pool_type, source_xml, 0)
        except libvirt.libvirtError as e:
            if util.is_error_nosupport(e):
                return []
            raise

        class _EnumerateSource(XMLBuilder):
            _XML_ROOT_NAME = "source"
        class _EnumerateSources(XMLBuilder):
            _XML_ROOT_NAME = "sources"
            sources = XMLChildProperty(_EnumerateSource)


        ret = []
        sources = _EnumerateSources(conn, xml)
        for source in sources.sources:
            source_xml = source.get_xml_config()

            pool_xml = "<pool>\n%s\n</pool>" % (
                XMLBuilder.xml_indent(source_xml, 2))
            parseobj = StoragePool(conn, parsexml=pool_xml)
            parseobj.type = pool_type

            obj = StoragePool(conn)
            obj.type = pool_type
            obj.source_path = parseobj.source_path
            for h in parseobj.hosts:
                parseobj.remove_host(h)
                obj.add_host_obj(h)
            obj.source_name = parseobj.source_name
            obj.format = parseobj.format

            ret.append(obj)
        return ret

    @staticmethod
    def build_default_pool(conn):
        """
        Helper to build the 'default' storage pool
        """
        if not conn.check_support(conn.SUPPORT_CONN_STORAGE):
            return

        pool = None
        name = "default"
        path = _get_default_pool_path(conn)
        if conn.is_session_uri() and not os.path.exists(path):
            os.makedirs(path)

        try:
            pool = conn.storagePoolLookupByName(name)
        except libvirt.libvirtError:
            # Try default pool path when "default" name fails
            pool = StoragePool.lookup_pool_by_path(conn, path)

        if pool:
            # This is a libvirt pool object so create a StoragePool from it
            return StoragePool(conn, parsexml=pool.XMLDesc(0))

        try:
            logging.debug("Attempting to build default pool with target '%s'",
                          path)
            defpool = StoragePool(conn)
            defpool.type = defpool.TYPE_DIR
            defpool.name = name
            defpool.target_path = path
            defpool.install(build=True, create=True, autostart=True)
            return defpool
        except Exception as e:
            raise RuntimeError(
                _("Couldn't create default storage pool '%s': %s") %
                (path, str(e)))

    @staticmethod
    def manage_path(conn, path):
        """
        If the passed path is managed, lookup its storage objects.
        If the passed path isn't managed, attempt to manage it if
        we can.

        :returns: (vol, parent pool) tuple
        """
        from . import diskbackend
        return diskbackend.manage_path(conn, path)

    @staticmethod
    def get_default_dir(conn, build=False):
        """
        Return the default storage dir. If there's a 'default' pool,
        report that. If there's no default pool, return the dir we would
        use for the default.
        """
        path = _get_default_pool_path(conn)
        if (not conn.is_remote() and
            not conn.check_support(conn.SUPPORT_CONN_STORAGE)):
            if build and not os.path.exists(path):
                os.makedirs(path)
            return path

        try:
            for pool in conn.fetch_all_pools():
                if pool.name == "default":
                    return pool.target_path
        except Exception:
            pass

        if build:
            return StoragePool.build_default_pool(conn).target_path
        return _get_default_pool_path(conn)


    @staticmethod
    def lookup_pool_by_path(conn, path):
        """
        Return the first pool with matching matching target path.
        return the first we find, active or inactive. This iterates over
        all pools and dumps their xml, so it is NOT quick.

        @returns: virStoragePool object if found, None otherwise
        """
        if not conn.check_support(conn.SUPPORT_CONN_STORAGE):
            return None

        for pool in conn.fetch_all_pools():
            xml_path = pool.target_path
            if xml_path is not None and os.path.abspath(xml_path) == path:
                return conn.storagePoolLookupByName(pool.name)
        return None

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

        kwargs["lib_collision"] = False
        return util.generate_name(basename, cb, **kwargs)


    def __init__(self, *args, **kwargs):
        _StorageObject.__init__(self, *args, **kwargs)
        self._random_uuid = None


    ######################
    # Validation helpers #
    ######################

    def _check_name_collision(self, name):
        pool = None
        try:
            pool = self.conn.storagePoolLookupByName(name)
        except libvirt.libvirtError:
            pass
        if pool:
            raise ValueError(_("Name '%s' already in use by another pool." %
                                name))

    def _get_default_target_path(self):
        if not self.supports_property("target_path"):
            return None
        if (self.type == self.TYPE_DIR or
            self.type == self.TYPE_NETFS or
            self.type == self.TYPE_FS):
            return os.path.join(self.get_default_dir(self.conn), self.name)
        if self.type == self.TYPE_LOGICAL:
            name = self.name
            if self.source_name:
                name = self.source_name
            return _DEFAULT_LVM_TARGET_BASE + name
        if self.type == self.TYPE_DISK:
            return _DEFAULT_DEV_TARGET
        if self.type == self.TYPE_ISCSI or self.type == self.TYPE_SCSI:
            return _DEFAULT_SCSI_TARGET
        if self.type == self.TYPE_MPATH:
            return _DEFAULT_MPATH_TARGET
        raise RuntimeError("No default target_path for type=%s" % self.type)

    def _get_default_uuid(self):
        if self._random_uuid is None:
            self._random_uuid = util.generate_uuid(self.conn)
        return self._random_uuid

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

    def _default_source_name(self):
        srcname = None

        if not self.supports_property("source_name"):
            srcname = None
        elif self.type == StoragePool.TYPE_NETFS:
            srcname = self.name
        elif self.type == StoragePool.TYPE_RBD:
            srcname = "rbd"
        elif self.type == StoragePool.TYPE_GLUSTER:
            srcname = "gv0"
        elif ("target_path" in self._propstore and
            self.target_path and
            self.target_path.startswith(_DEFAULT_LVM_TARGET_BASE)):
            # If there is a target path, parse it for an expected VG
            # location, and pull the name from there
            vg = self.target_path[len(_DEFAULT_LVM_TARGET_BASE):]
            srcname = vg.split("/", 1)[0]

        return srcname

    def _default_format_cb(self):
        if not self.supports_property("format"):
            return None
        return "auto"


    ##############
    # Properties #
    ##############

    _XML_ROOT_NAME = "pool"
    _XML_PROP_ORDER = ["name", "type", "uuid",
                       "capacity", "allocation", "available",
                       "format", "hosts",
                       "_source_dir", "_source_adapter", "_source_device",
                       "source_name", "target_path",
                       "permissions"]


    _source_dir = XMLProperty("./source/dir/@path")
    _source_adapter = XMLProperty("./source/adapter/@name")
    _source_device = XMLProperty("./source/device/@path")

    type = XMLProperty("./@type",
        doc=_("Storage device type the pool will represent."))
    uuid = XMLProperty("./uuid",
                       validate_cb=lambda s, v: util.validate_uuid(v),
                       default_cb=_get_default_uuid)

    capacity = XMLProperty("./capacity", is_int=True)
    allocation = XMLProperty("./allocation", is_int=True)
    available = XMLProperty("./available", is_int=True)

    format = XMLProperty("./source/format/@type",
                         default_cb=_default_format_cb)
    iqn = XMLProperty("./source/initiator/iqn/@name",
                      doc=_("iSCSI initiator qualified name"))
    source_name = XMLProperty("./source/name",
                              default_cb=_default_source_name,
                              doc=_("Name of the Volume Group"))

    target_path = XMLProperty("./target/path",
                              default_cb=_get_default_target_path)

    def add_host_obj(self, obj):
        self.add_child(obj)
    def add_host(self, name, port=None):
        obj = _Host(self.conn)
        obj.name = name
        obj.port = port
        self.add_child(obj)
    def remove_host(self, obj):
        self.remove_child(obj)
    hosts = XMLChildProperty(_Host, relative_xpath="./source")


    ######################
    # Public API helpers #
    ######################

    def supports_property(self, propname):
        users = {
            "source_path": [self.TYPE_FS, self.TYPE_NETFS, self.TYPE_LOGICAL,
                            self.TYPE_DISK, self.TYPE_ISCSI, self.TYPE_SCSI,
                            self.TYPE_GLUSTER],
            "source_name": [self.TYPE_LOGICAL, self.TYPE_GLUSTER,
                            self.TYPE_RBD, self.TYPE_SHEEPDOG, self.TYPE_ZFS],
            "hosts": [self.TYPE_NETFS, self.TYPE_ISCSI, self.TYPE_GLUSTER,
                     self.TYPE_RBD, self.TYPE_SHEEPDOG],
            "format": [self.TYPE_FS, self.TYPE_NETFS, self.TYPE_DISK],
            "iqn": [self.TYPE_ISCSI],
            "target_path": [self.TYPE_DIR, self.TYPE_FS, self.TYPE_NETFS,
                             self.TYPE_LOGICAL, self.TYPE_DISK, self.TYPE_ISCSI,
                             self.TYPE_SCSI, self.TYPE_MPATH]
        }

        if users.get(propname):
            return self.type in users[propname]
        return hasattr(self, propname)

    def list_formats(self):
        if self.type == self.TYPE_FS:
            return ["auto", "ext2", "ext3", "ext4", "ufs", "iso9660", "udf",
                    "gfs", "gfs2", "vfat", "hfs+", "xfs"]
        if self.type == self.TYPE_NETFS:
            return ["auto", "nfs", "glusterfs"]
        if self.type == self.TYPE_DISK:
            return ["auto", "bsd", "dos", "dvh", "gpt", "mac", "pc98", "sun"]
        return []

    def supports_volume_creation(self):
        return self.type in [
            StoragePool.TYPE_DIR, StoragePool.TYPE_FS,
            StoragePool.TYPE_NETFS, StoragePool.TYPE_LOGICAL,
            StoragePool.TYPE_DISK,
            StoragePool.TYPE_RBD, StoragePool.TYPE_SHEEPDOG,
            StoragePool.TYPE_ZFS]

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
        if self.supports_property("host") and not self.hosts:
            raise RuntimeError(_("Hostname is required"))
        if (self.supports_property("source_path") and
            self.type != self.TYPE_LOGICAL and
            not self.source_path):
            raise RuntimeError(_("Source path is required"))

        if (self.type == self.TYPE_DISK and self.format == "auto"):
            # There is no explicit "auto" type for disk pools, but leaving out
            # the format type seems to do the job for existing formatted disks
            self.format = None

    def install(self, meter=None, create=False, build=False, autostart=False):
        """
        Install storage pool xml.
        """
        if (self.type == self.TYPE_LOGICAL and
            build and not self.source_path):
            raise ValueError(_("Must explicitly specify source path if "
                               "building pool"))
        if (self.type == self.TYPE_DISK and
            build and self.format == "auto"):
            raise ValueError(_("Must explicitly specify disk format if "
                               "formatting disk device."))

        xml = self.get_xml_config()
        logging.debug("Creating storage pool '%s' with xml:\n%s",
                      self.name, xml)

        meter = util.ensure_meter(meter)

        try:
            pool = self.conn.storagePoolDefineXML(xml, 0)
        except Exception as e:
            raise RuntimeError(_("Could not define storage pool: %s") % str(e))

        errmsg = None
        if build:
            try:
                pool.build(libvirt.VIR_STORAGE_POOL_BUILD_NEW)
            except Exception as e:
                errmsg = _("Could not build storage pool: %s") % str(e)

        if create and not errmsg:
            try:
                pool.create(0)
            except Exception as e:
                errmsg = _("Could not start storage pool: %s") % str(e)

        if autostart and not errmsg:
            try:
                pool.setAutostart(True)
            except Exception as e:
                errmsg = _("Could not set pool autostart flag: %s") % str(e)

        if errmsg:
            # Try and clean up the leftover pool
            try:
                pool.undefine()
            except Exception as e:
                logging.debug("Error cleaning up pool after failure: " +
                              "%s" % str(e))
            raise RuntimeError(errmsg)

        self.conn.cache_new_pool(pool)

        return pool



class StorageVolume(_StorageObject):
    """
    Base class for building and installing libvirt storage volume xml
    """
    ALL_FORMATS = ["raw", "bochs", "cloop", "dmg", "iso", "qcow",
                   "qcow2", "qed", "vmdk", "vpc", "fat", "vhd", "vdi"]

    @staticmethod
    def get_file_extension_for_format(fmt):
        if not fmt:
            return ""
        if fmt == "raw":
            return ".img"
        return "." + fmt

    @staticmethod
    def find_free_name(pool_object, basename, **kwargs):
        """
        Finds a name similar (or equal) to passed 'basename' that is not
        in use by another volume. Extra params are passed to generate_name
        """
        pool_object.refresh(0)
        return util.generate_name(basename,
                                  pool_object.storageVolLookupByName,
                                  **kwargs)

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

        # Indicate that the volume installation has finished. Used to
        # definitively tell the storage progress thread to stop polling.
        self._install_finished = True


    ######################
    # Non XML properties #
    ######################

    def _get_pool(self):
        return self._pool
    def _set_pool(self, newpool):
        if newpool.info()[0] != libvirt.VIR_STORAGE_POOL_RUNNING:
            raise ValueError(_("pool '%s' must be active.") % newpool.name())
        self._pool = newpool
        self._pool_xml = StoragePool(self.conn,
            parsexml=self._pool.XMLDesc(0))
    pool = property(_get_pool, _set_pool)

    def _get_input_vol(self):
        return self._input_vol
    def _set_input_vol(self, vol):
        if vol is None:
            self._input_vol = None
            return

        if not isinstance(vol, libvirt.virStorageVol):
            raise ValueError(_("input_vol must be a virStorageVol"))

        if not self.conn.check_support(
            self.conn.SUPPORT_POOL_CREATEVOLFROM, self.pool):
            raise ValueError(_("Creating storage from an existing volume is"
                               " not supported by this libvirt version."))

        self._input_vol = vol
    input_vol = property(_get_input_vol, _set_input_vol,
                         doc=_("virStorageVolume pointer to clone/use as "
                               "input."))

    def _get_reflink(self):
        return self._reflink
    def _set_reflink(self, reflink):
        if (reflink and not
            self.conn.check_support(self.conn.SUPPORT_POOL_REFLINK)):
            raise ValueError(_("Creating storage by btrfs COW copy is"
                " not supported by this libvirt version."))

        self._reflink = reflink
    reflink = property(_get_reflink, _set_reflink,
            doc="flags for VIR_STORAGE_VOL_CREATE_REFLINK")

    def sync_input_vol(self, only_format=False):
        # Pull parameters from input vol into this class
        parsevol = StorageVolume(self.conn,
                                 parsexml=self._input_vol.XMLDesc(0))

        self.format = parsevol.format
        self.capacity = parsevol.capacity
        self.allocation = parsevol.allocation
        if only_format:
            return
        self.pool = self._input_vol.storagePoolLookupByVolume()


    ##########################
    # XML validation helpers #
    ##########################

    def _check_name_collision(self, name):
        vol = None
        try:
            vol = self.pool.storageVolLookupByName(name)
        except libvirt.libvirtError:
            pass
        if vol:
            raise ValueError(_("Name '%s' already in use by another volume." %
                                name))

    def _default_format(self):
        if self.file_type == self.TYPE_FILE:
            return "raw"
        return None

    def _get_vol_type(self):
        if self.type:
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

    _XML_ROOT_NAME = "volume"
    _XML_PROP_ORDER = ["name", "key", "capacity", "allocation", "format",
                       "target_path", "permissions"]

    type = XMLProperty("./@type")
    key = XMLProperty("./key")
    capacity = XMLProperty("./capacity", is_int=True)
    allocation = XMLProperty("./allocation", is_int=True)
    format = XMLProperty("./target/format/@type", default_cb=_default_format)
    target_path = XMLProperty("./target/path")
    backing_store = XMLProperty("./backingStore/path")
    backing_format = XMLProperty("./backingStore/format/@type")

    def _lazy_refcounts_default_cb(self):
        if self.format != "qcow2":
            return False
        return self.conn.check_support(
            self.conn.SUPPORT_CONN_QCOW2_LAZY_REFCOUNTS)
    lazy_refcounts = XMLProperty("./target/features/lazy_refcounts",
        is_bool=True, default_cb=_lazy_refcounts_default_cb)


    def _detect_backing_store_format(self):
        logging.debug("Attempting to detect format for backing_store=%s",
                self.backing_store)
        vol, pool = StoragePool.manage_path(self.conn, self.backing_store)

        if not vol:
            logging.debug("Didn't find any volume for backing_store")
            return None

        # Only set backing format for volumes that support
        # the 'format' parameter as we know it, like qcow2 etc.
        volxml = StorageVolume(self.conn, vol.XMLDesc(0))
        volxml.pool = pool
        logging.debug("Found backing store volume XML:\n%s",
                volxml.get_xml_config())

        if volxml.supports_property("format"):
            logging.debug("Returning format=%s", volxml.format)
            return volxml.format

        logging.debug("backing_store volume doesn't appear to have "
            "a file format we can specify, returning None")
        return None


    ######################
    # Public API helpers #
    ######################

    def _supports_format(self):
        if self.file_type == self.TYPE_FILE:
            return True
        if self._pool_xml.type == StoragePool.TYPE_GLUSTER:
            return True
        return False

    def supports_property(self, propname):
        if propname == "format":
            return self._supports_format()
        return hasattr(self, propname)

    def list_formats(self):
        if self._supports_format():
            return self.ALL_FORMATS
        return []

    def list_create_formats(self):
        if self._supports_format():
            return ["raw", "qcow", "qcow2", "qed", "vmdk", "vpc", "vdi"]
        return None


    ##################
    # Build routines #
    ##################

    def validate(self):
        if self._pool_xml.type == StoragePool.TYPE_LOGICAL:
            if self.allocation != self.capacity:
                logging.warning(_("Sparse logical volumes are not supported, "
                               "setting allocation equal to capacity"))
                self.allocation = self.capacity

        isfatal, errmsg = self.is_size_conflict()
        if isfatal:
            raise ValueError(errmsg)
        if errmsg:
            logging.warning(errmsg)

    def install(self, meter=None):
        """
        Build and install storage volume from xml
        """
        if self.backing_store and not self.backing_format:
            self.backing_format = self._detect_backing_store_format()

        xml = self.get_xml_config()
        logging.debug("Creating storage volume '%s' with xml:\n%s",
                      self.name, xml)

        t = threading.Thread(target=self._progress_thread,
                             name="Checking storage allocation",
                             args=(meter,))
        t.setDaemon(True)

        meter = util.ensure_meter(meter)

        cloneflags = 0
        createflags = 0
        if (self.format == "qcow2" and
            not self.backing_store and
            not self.conn.is_really_test() and
            self.conn.check_support(
                self.conn.SUPPORT_POOL_METADATA_PREALLOC, self.pool)):
            createflags |= libvirt.VIR_STORAGE_VOL_CREATE_PREALLOC_METADATA

        if self.reflink:
            cloneflags |= getattr(libvirt,
                "VIR_STORAGE_VOL_CREATE_REFLINK", 1)

        try:
            self._install_finished = False
            t.start()
            meter.start(size=self.capacity,
                        text=_("Allocating '%s'") % self.name)

            if self.input_vol:
                vol = self.pool.createXMLFrom(xml, self.input_vol, cloneflags)
            else:
                logging.debug("Using vol create flags=%s", createflags)
                vol = self.pool.createXML(xml, createflags)

            self._install_finished = True
            t.join()
            meter.end(self.capacity)
            logging.debug("Storage volume '%s' install complete.",
                          self.name)
            return vol
        except Exception as e:
            logging.debug("Error creating storage volume", exc_info=True)
            raise RuntimeError("Couldn't create storage volume "
                               "'%s': '%s'" % (self.name, str(e)))

    def _progress_thread(self, meter):
        vol = None
        if not meter:
            return

        while True:
            try:
                if not vol:
                    vol = self.pool.storageVolLookupByName(self.name)
                vol.info()
                break
            except Exception:
                if time:  # pylint: disable=using-constant-test
                    # This 'if' check saves some noise from the test suite
                    time.sleep(.2)
                if self._install_finished:
                    break

        if vol is None:
            logging.debug("Couldn't lookup storage volume in prog thread.")
            return

        while not self._install_finished:
            ignore, ignore, alloc = vol.info()
            meter.update(alloc)
            time.sleep(1)


    def is_size_conflict(self):
        """
        Report if requested size exceeds its pool's available amount

        @returns: 2 element tuple:
            1. True if collision is fatal, false otherwise
            2. String message if some collision was encountered.
        @rtype: 2 element C{tuple}: (C{bool}, C{str})
        """
        if not self.pool:
            return (False, "")

        # pool info is [pool state, capacity, allocation, available]
        avail = self.pool.info()[3]
        if self.allocation > avail:
            return (True, _("There is not enough free space on the storage "
                            "pool to create the volume. "
                            "(%d M requested allocation > %d M available)") %
                            ((self.allocation / (1024 * 1024)),
                             (avail / (1024 * 1024))))
        elif self.capacity > avail:
            return (False, _("The requested volume capacity will exceed the "
                             "available pool space when the volume is fully "
                             "allocated. "
                             "(%d M requested capacity > %d M available)") %
                             ((self.capacity / (1024 * 1024)),
                              (avail / (1024 * 1024))))
        return (False, "")
