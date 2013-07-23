#
# Copyright 2008, 2013 Red Hat, Inc.
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
"""
Classes for building and installing libvirt storage xml

General workflow for the different storage objects:

    1. Storage Pool:

    Pool type options can be exposed to a user via the static function
    L{StoragePool.get_pool_types}. Any selection can be fed back into
    L{StoragePool.get_pool_class} to get the particular volume class to
    instantiate. From here, values can be set at init time or via
    properties post init.

    Different pool types have different options and
    requirements, so using getattr() is probably the best way to check
    for parameter availability.

    2) Storage Volume:

    There are a few options for determining what pool volume class to use:
        - Pass the pools type for L{StoragePool.get_volume_for_pool}
        - Pass the pool object or name to L{StorageVolume.get_volume_for_pool}

    These will give back the appropriate class to instantiate. For most cases,
    all that's needed is a name and capacity, the rest will be filled in.

@see: U{http://libvirt.org/storage.html}
"""

import os
import threading
import time
import logging

import libvirt
import urlgrabber

from virtinst.util import xml_escape as escape
from virtinst import util


DEFAULT_DEV_TARGET = "/dev"
DEFAULT_LVM_TARGET_BASE = "/dev/"
DEFAULT_DIR_TARGET_BASE = "/var/lib/libvirt/images/"
DEFAULT_SCSI_TARGET = "/dev/disk/by-path"
DEFAULT_MPATH_TARGET = "/dev/mapper"

# Pulled from libvirt, used for building on older versions
VIR_STORAGE_VOL_FILE = 0
VIR_STORAGE_VOL_BLOCK = 1


def _parse_pool_source_list(source_xml):
    def source_parser(node):
        ret_list = []

        child = node.children
        while child:
            if child.name == "source":
                val_dict = {}
                source = child.children

                while source:
                    if source.name == "name":
                        val_dict["source_name"] = source.content
                    elif source.name == "host":
                        val_dict["host"] = source.prop("name")
                    elif source.name == "format":
                        val_dict["format"] = source.prop("type")
                    elif source.name in ["device", "dir"]:
                        val_dict["source_path"] = source.prop("path")
                    source = source.next

                ret_list.append(val_dict)

            child = child.next

        for val_dict in ret_list:
            if (val_dict.get("format") == "lvm2" and
                val_dict.get("source_name") and
                not val_dict.get("target_path")):
                val_dict["target_path"] = (DEFAULT_LVM_TARGET_BASE +
                                           val_dict["source_name"])

        return ret_list

    return util.parse_node_helper(source_xml, "sources", source_parser)


class StorageObject(object):
    """
    Base class for building any libvirt storage object.

    Mostly meaningless to directly instantiate.
    """

    TYPE_POOL   = "pool"
    TYPE_VOLUME = "volume"

    def __init__(self, conn, object_type, name):
        """
        Initialize storage object parameters
        """
        if object_type not in [self.TYPE_POOL, self.TYPE_VOLUME]:
            raise ValueError(_("Unknown storage object type: %s") % type)
        self._object_type = object_type
        self._conn = conn
        self._name = None

        self.name = name

        # Initialize all optional properties
        self._perms = None


    ## Properties
    def get_object_type(self):
        # 'pool' or 'volume'
        return self._object_type
    object_type = property(get_object_type)

    def _get_conn(self):
        return self._conn
    conn = property(_get_conn)

    def get_name(self):
        return self._name
    def set_name(self, val):
        util.validate_name(_("Storage object"), val)

        # Check that name doesn't collide with other storage objects
        self._check_name_collision(val)
        self._name = val
    name = property(get_name, set_name, doc=_("Name for the storage object."))

    # Get/Set methods for use by some objects. Will register where applicable
    def get_perms(self):
        return self._perms
    def set_perms(self, val):
        if type(val) is not dict:
            raise ValueError(_("Permissions must be passed as a dict object"))
        for key in ["mode", "owner", "group"]:
            if not key in val:
                raise ValueError(_("Permissions must contain 'mode', 'owner' and 'group' keys."))
        self._perms = val


    # Validation helper functions
    def _validate_path(self, path):
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError(_("'%s' is not an absolute path." % path))

    def _check_name_collision(self, name):
        ignore = name
        raise NotImplementedError()

    # XML Building
    def _get_storage_xml(self):
        """
        Returns the pool/volume specific xml blob
        """
        raise NotImplementedError()

    def _get_perms_xml(self):
        perms = self.get_perms()
        if not perms:
            return ""
        xml = "    <permissions>\n" + \
              "      <mode>0%o</mode>\n" % perms["mode"] + \
              "      <owner>%d</owner>\n" % perms["owner"] + \
              "      <group>%d</group>\n" % perms["group"]

        if "label" in perms:
            xml += "      <label>%s</label>\n" % perms["label"]

        xml += "    </permissions>\n"
        return xml


    def get_xml_config(self):
        """
        Construct the xml description of the storage object

        @returns: xml description
        @rtype: C{str}
        """
        if not hasattr(self, "type"):
            root_xml = "<%s>\n" % self.object_type
        else:
            _type = getattr(self, "type")
            root_xml = "<%s type='%s'>\n" % (self.object_type, _type)

        xml = "%s" % (root_xml) + \
              """  <name>%s</name>\n""" % (self.name) + \
              """%(stor_xml)s""" % {"stor_xml" : self._get_storage_xml()} + \
              """</%s>\n""" % (self.object_type)
        return xml




class StoragePool(StorageObject):
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

    # Pool type descriptions for use in higher level programs
    _types = {}
    _types[TYPE_DIR]     = _("Filesystem Directory")
    _types[TYPE_FS]      = _("Pre-Formatted Block Device")
    _types[TYPE_NETFS]   = _("Network Exported Directory")
    _types[TYPE_LOGICAL] = _("LVM Volume Group")
    _types[TYPE_DISK]    = _("Physical Disk Device")
    _types[TYPE_ISCSI]   = _("iSCSI Target")
    _types[TYPE_SCSI]    = _("SCSI Host Adapter")
    _types[TYPE_MPATH]   = _("Multipath Device Enumerator")

    def get_pool_class(ptype):
        """
        Return class associated with passed pool type.

        @param ptype: Pool type
        @type ptype: member of I{Types}
        """
        if ptype not in StoragePool._types:
            raise ValueError(_("Unknown storage pool type: %s" % ptype))
        if ptype == StoragePool.TYPE_DIR:
            return DirectoryPool
        if ptype == StoragePool.TYPE_FS:
            return FilesystemPool
        if ptype == StoragePool.TYPE_NETFS:
            return NetworkFilesystemPool
        if ptype == StoragePool.TYPE_LOGICAL:
            return LogicalPool
        if ptype == StoragePool.TYPE_DISK:
            return DiskPool
        if ptype == StoragePool.TYPE_ISCSI:
            return iSCSIPool
        if ptype == StoragePool.TYPE_SCSI:
            return SCSIPool
        if ptype == StoragePool.TYPE_MPATH:
            return MultipathPool
    get_pool_class = staticmethod(get_pool_class)

    def get_volume_for_pool(pool_type):
        """Convenience method, returns volume class associated with pool_type"""
        pool_class = StoragePool.get_pool_class(pool_type)
        return pool_class.get_volume_class()
    get_volume_for_pool = staticmethod(get_volume_for_pool)

    def get_pool_types():
        """Return list of appropriate pool types"""
        return StoragePool._types.keys()
    get_pool_types = staticmethod(get_pool_types)

    def get_pool_type_desc(pool_type):
        """Return human readable description for passed pool type"""
        if pool_type in StoragePool._types:
            return StoragePool._types[pool_type]
        else:
            return "%s pool" % pool_type
    get_pool_type_desc = staticmethod(get_pool_type_desc)

    def pool_list_from_sources(conn, name, pool_type, host=None):
        """
        Return a list of StoragePool instances built from libvirt's pool
        source enumeration (if supported).

        @param conn: Libvirt connection
        @param name: Name for the new pool
        @param pool_type: Pool type string from I{Types}
        @param host: Option host string to poll for sources
        """
        if not conn.check_conn_support(conn.SUPPORT_CONN_FINDPOOLSOURCES):
            return []

        pool_class = StoragePool.get_pool_class(pool_type)
        pool_inst = pool_class(conn=conn, name=name)

        if host:
            source_xml = "<source><host name='%s'/></source>" % host
        else:
            source_xml = "<source/>"

        try:
            xml = conn.findStoragePoolSources(pool_type, source_xml, 0)
        except libvirt.libvirtError, e:
            if util.is_error_nosupport(e):
                return []
            raise

        retlist = []
        source_list = _parse_pool_source_list(xml)
        for source in source_list:
            pool_inst = pool_class(conn=conn, name=name)
            for key, val in source.items():

                if not hasattr(pool_inst, key):
                    continue

                setattr(pool_inst, key, val)

            retlist.append(pool_inst)

        return retlist
    pool_list_from_sources = staticmethod(pool_list_from_sources)

    def __init__(self, conn, name, type, target_path=None, uuid=None):
        # pylint: disable=W0622
        # Redefining built-in 'type', but it matches the XML so keep it

        StorageObject.__init__(self, object_type=StorageObject.TYPE_POOL,
                               name=name, conn=conn)

        if type not in self.get_pool_types():
            raise ValueError(_("Unknown storage pool type: %s" % type))
        self._type = type
        self._target_path = None
        self._host = None
        self._format = None
        self._source_path = None
        self._uuid = None

        if target_path is None:
            target_path = self._get_default_target_path()
        self.target_path = target_path

        if uuid:
            self.uuid = uuid

        # Initialize all optional properties
        self._host = None
        self._source_path = None
        self._random_uuid = util.generate_uuid(self.conn)

    # Properties used by all pools
    def get_type(self):
        return self._type
    type = property(get_type,
                    doc=_("Storage device type the pool will represent."))

    def get_target_path(self):
        return self._target_path
    def set_target_path(self, val):
        self._validate_path(val)
        self._target_path = os.path.abspath(val)

    # Get/Set methods for use by some pools. Will be registered when applicable
    def get_source_path(self):
        return self._source_path
    def set_source_path(self, val):
        self._validate_path(val)
        self._source_path = os.path.abspath(val)

    def get_host(self):
        return self._host
    def set_host(self, val):
        if not isinstance(val, str):
            raise ValueError(_("Host name must be a string"))
        self._host = val

    # uuid: uuid of the storage object. optional: generated if not set
    def get_uuid(self):
        return self._uuid
    def set_uuid(self, val):
        val = util.validate_uuid(val)
        self._uuid = val
    uuid = property(get_uuid, set_uuid)

    # Validation functions
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
        raise NotImplementedError()

    # XML Building
    def _get_target_xml(self):
        raise NotImplementedError()

    def _get_source_xml(self):
        raise NotImplementedError()

    def _get_storage_xml(self):
        src_xml = ""
        if self._get_source_xml() != "":
            src_xml = "  <source>\n" + \
                      "%s" % (self._get_source_xml()) + \
                      "  </source>\n"
        tar_xml = "  <target>\n" + \
                  "%s" % (self._get_target_xml()) + \
                  "  </target>\n"

        return "  <uuid>%s</uuid>\n" % (self.uuid or self._random_uuid) + \
               "%s" % src_xml + \
               "%s" % tar_xml

    def install(self, meter=None, create=False, build=False, autostart=False):
        """
        Install storage pool xml.
        """
        xml = self.get_xml_config()
        logging.debug("Creating storage pool '%s' with xml:\n%s",
                      self.name, xml)

        if not meter:
            meter = urlgrabber.progress.BaseMeter()

        try:
            pool = self.conn.storagePoolDefineXML(xml, 0)
        except Exception, e:
            raise RuntimeError(_("Could not define storage pool: %s" % str(e)))

        errmsg = None
        if build:
            try:
                pool.build(libvirt.VIR_STORAGE_POOL_BUILD_NEW)
            except Exception, e:
                errmsg = _("Could not build storage pool: %s" % str(e))

        if create and not errmsg:
            try:
                pool.create(0)
            except Exception, e:
                errmsg = _("Could not start storage pool: %s" % str(e))

        if autostart and not errmsg:
            try:
                pool.setAutostart(True)
            except Exception, e:
                errmsg = _("Could not set pool autostart flag: %s" % str(e))

        if errmsg:
            # Try and clean up the leftover pool
            try:
                pool.undefine()
            except Exception, e:
                logging.debug("Error cleaning up pool after failure: " +
                              "%s" % str(e))
            raise RuntimeError(errmsg)

        return pool


class DirectoryPool(StoragePool):
    """
    Create a directory based storage pool
    """

    def get_volume_class():
        return FileVolume
    get_volume_class = staticmethod(get_volume_class)

    # Register applicable property methods from parent class
    perms = property(StorageObject.get_perms, StorageObject.set_perms)
    target_path = property(StoragePool.get_target_path,
                           StoragePool.set_target_path,
                           doc=_("Directory to use for the storage pool."))

    def __init__(self, conn, name, target_path=None, uuid=None, perms=None):
        StoragePool.__init__(self, name=name, type=StoragePool.TYPE_DIR,
                             target_path=target_path, uuid=uuid, conn=conn)
        if perms:
            self.perms = perms

    def _get_default_target_path(self):
        path = (DEFAULT_DIR_TARGET_BASE + self.name)
        return path

    def _get_target_xml(self):
        xml = "    <path>%s</path>\n" % escape(self.target_path) + \
              "%s" % self._get_perms_xml()
        return xml

    def _get_source_xml(self):
        return ""


class FilesystemPool(StoragePool):
    """
    Create a formatted partition based storage pool
    """

    def get_volume_class():
        return FileVolume
    get_volume_class = staticmethod(get_volume_class)

    formats = ["auto", "ext2", "ext3", "ext4", "ufs", "iso9660", "udf",
                "gfs", "gfs2", "vfat", "hfs+", "xfs"]

    # Register applicable property methods from parent class
    perms = property(StorageObject.get_perms, StorageObject.set_perms)
    source_path = property(StoragePool.get_source_path,
                           StoragePool.set_source_path,
                           doc=_("The existing device to mount for the pool."))
    target_path = property(StoragePool.get_target_path,
                           StoragePool.set_target_path,
                           doc=_("Location to mount the source device."))

    def __init__(self, conn, name, source_path=None, target_path=None,
                 format="auto", uuid=None, perms=None):
        # pylint: disable=W0622
        # Redefining built-in 'format', but it matches the XML so keep it

        StoragePool.__init__(self, name=name, type=StoragePool.TYPE_FS,
                             target_path=target_path, uuid=uuid, conn=conn)

        self.format = format

        if source_path:
            self.source_path = source_path
        if perms:
            self.perms = perms

    def get_format(self):
        return self._format
    def set_format(self, val):
        if not val in self.formats:
            raise ValueError(_("Unknown Filesystem format: %s" % val))
        self._format = val
    format = property(get_format, set_format,
                      doc=_("Filesystem type of the source device."))

    def _get_default_target_path(self):
        path = (DEFAULT_DIR_TARGET_BASE + self.name)
        return path

    def _get_target_xml(self):
        xml = "    <path>%s</path>\n" % escape(self.target_path) + \
              "%s" % self._get_perms_xml()
        return xml

    def _get_source_xml(self):
        if not self.source_path:
            raise RuntimeError(_("Device path is required"))
        xml = "    <format type='%s'/>\n" % self.format + \
              "    <device path='%s'/>\n" % escape(self.source_path)
        return xml


class NetworkFilesystemPool(StoragePool):
    """
    Create a network mounted filesystem storage pool
    """

    def get_volume_class():
        return FileVolume
    get_volume_class = staticmethod(get_volume_class)

    formats = ["auto", "nfs", "glusterfs"]

    # Register applicable property methods from parent class
    source_path = property(StoragePool.get_source_path,
                           StoragePool.set_source_path,
                           doc=_("Path on the host that is being shared."))
    host = property(StoragePool.get_host, StoragePool.set_host,
                    doc=_("Name of the host sharing the storage."))
    target_path = property(StoragePool.get_target_path,
                           StoragePool.set_target_path,
                           doc=_("Location to mount the source device."))

    def __init__(self, conn, name, source_path=None, host=None,
                 target_path=None, format="auto", uuid=None):
        # pylint: disable=W0622
        # Redefining built-in 'format', but it matches the XML so keep it

        StoragePool.__init__(self, name=name, type=StoragePool.TYPE_NETFS,
                             uuid=uuid, target_path=target_path, conn=conn)

        self.format = format

        if source_path:
            self.source_path = source_path
        if host:
            self.host = host

    def get_format(self):
        return self._format
    def set_format(self, val):
        if not val in self.formats:
            raise ValueError(_("Unknown Network Filesystem format: %s" % val))
        self._format = val
    format = property(get_format, set_format,
                      doc=_("Type of network filesystem."))

    def _get_default_target_path(self):
        path = (DEFAULT_DIR_TARGET_BASE + self.name)
        return path

    def _get_target_xml(self):
        xml = "    <path>%s</path>\n" % escape(self.target_path)
        return xml

    def _get_source_xml(self):
        if not self.host:
            raise RuntimeError(_("Hostname is required"))
        if not self.source_path:
            raise RuntimeError(_("Host path is required"))
        xml = """    <format type="%s"/>\n""" % self.format + \
              """    <host name="%s"/>\n""" % self.host + \
              """    <dir path="%s"/>\n""" % escape(self.source_path)
        return xml


class LogicalPool(StoragePool):
    """
    Create a logical (lvm volume group) storage pool
    """
    def get_volume_class():
        return LogicalVolume
    get_volume_class = staticmethod(get_volume_class)

    # Register applicable property methods from parent class
    perms = property(StorageObject.get_perms, StorageObject.set_perms)
    target_path = property(StoragePool.get_target_path,
                           StoragePool.set_target_path,
                           doc=_("Location of the existing LVM volume group."))

    def __init__(self, conn, name, target_path=None, uuid=None, perms=None,
                 source_path=None, source_name=None):
        StoragePool.__init__(self, name=name, type=StoragePool.TYPE_LOGICAL,
                             target_path=target_path, uuid=uuid, conn=conn)

        self._source_name = None

        if perms:
            self.perms = perms
        if source_path:
            self.source_path = source_path
        if source_name:
            self.source_name = source_name

    # Need to overwrite storage path checks, since this optionally be a list
    # of devices
    def get_source_path(self):
        return self._source_path
    def set_source_path(self, val):
        if not val:
            self._source_path = None
            return

        if type(val) != list:
            StoragePool.set_source_path(self, val)
        else:
            self._source_path = val
    source_path = property(get_source_path, set_source_path,
                           doc=_("Optional device(s) to build new LVM volume "
                                 "on."))

    def get_source_name(self):
        if self._source_name:
            return self._source_name

        # If a source name isn't explictly set, try to determine it from
        # existing parameters
        srcname = self.name

        if (self.target_path and
            self.target_path.startswith(DEFAULT_LVM_TARGET_BASE)):
            # If there is a target path, parse it for an expected VG
            # location, and pull the name from there
            vg = self.target_path[len(DEFAULT_LVM_TARGET_BASE):]
            srcname = vg.split("/", 1)[0]

        return srcname

    def set_source_name(self, val):
        self._source_name = val
    source_name = property(get_source_name, set_source_name,
                           doc=_("Name of the Volume Group"))

    def _make_source_name(self):
        srcname = self.name

        if self.source_path:
            # Building a pool, so just use pool name
            return srcname

    def _get_default_target_path(self):
        return DEFAULT_LVM_TARGET_BASE + self.name

    def _get_target_xml(self):
        xml = "    <path>%s</path>\n" % escape(self.target_path) + \
              "%s" % self._get_perms_xml()
        return xml

    def _get_source_xml(self):
        sources = self.source_path
        if type(sources) != list:
            sources = sources and [sources] or []

        xml = ""
        for s in sources:
            xml += "    <device path='%s'/>\n" % s
        if self.source_name:
            xml += "    <name>%s</name>\n" % self.source_name
        return xml

    def install(self, meter=None, create=False, build=False, autostart=False):
        if build and not self.source_path:
            raise ValueError(_("Must explicitly specify source path if "
                               "building pool"))
        return StoragePool.install(self, meter=meter, create=create,
                                   build=build, autostart=autostart)


class DiskPool(StoragePool):
    """
    Create a storage pool from a physical disk
    """
    def get_volume_class():
        return DiskVolume
    get_volume_class = staticmethod(get_volume_class)

    # Register applicable property methods from parent class
    source_path = property(StoragePool.get_source_path,
                           StoragePool.set_source_path,
                           doc=_("Path to the existing disk device."))
    target_path = property(StoragePool.get_target_path,
                           StoragePool.set_target_path,
                           doc=_("Root location for identifying new storage"
                                 " volumes."))

    formats = ["auto", "bsd", "dos", "dvh", "gpt", "mac", "pc98", "sun"]

    def __init__(self, conn, name, source_path=None, target_path=None,
                 format="auto", uuid=None):
        # pylint: disable=W0622
        # Redefining built-in 'format', but it matches the XML so keep it

        StoragePool.__init__(self, name=name, type=StoragePool.TYPE_DISK,
                             uuid=uuid, target_path=target_path, conn=conn)
        self.format = format
        if source_path:
            self.source_path = source_path

    def get_format(self):
        return self._format
    def set_format(self, val):
        if not val in self.formats:
            raise ValueError(_("Unknown Disk format: %s" % val))
        self._format = val
    format = property(get_format, set_format,
                      doc=_("Format of the source device's partition table."))

    def _get_default_target_path(self):
        return DEFAULT_DEV_TARGET

    def _get_target_xml(self):
        xml = "   <path>%s</path>\n" % escape(self.target_path)
        return xml

    def _get_source_xml(self):
        if not self.source_path:
            raise RuntimeError(_("Host path is required"))

        xml = ""
        # There is no explicit "auto" type for disk pools, but leaving out
        # the format type seems to do the job for existing formatted disks
        if self.format != "auto":
            xml = """    <format type="%s"/>\n""" % self.format
        xml += """    <device path="%s"/>\n""" % escape(self.source_path)
        return xml

    def install(self, meter=None, create=False, build=False, autostart=False):
        if self.format == "auto" and build:
            raise ValueError(_("Must explicitly specify disk format if "
                               "formatting disk device."))
        return StoragePool.install(self, meter=meter, create=create,
                                   build=build, autostart=autostart)


class iSCSIPool(StoragePool):
    """
    Create an iSCSI based storage pool
    """

    host = property(StoragePool.get_host, StoragePool.set_host,
                    doc=_("Name of the host sharing the storage."))
    target_path = property(StoragePool.get_target_path,
                           StoragePool.set_target_path,
                           doc=_("Root location for identifying new storage"
                                 " volumes."))

    def get_volume_class():
        raise NotImplementedError(_("iSCSI volume creation is not supported."))
    get_volume_class = staticmethod(get_volume_class)

    def __init__(self, conn, name, source_path=None, host=None,
                 target_path=None, uuid=None):
        StoragePool.__init__(self, name=name, type=StoragePool.TYPE_ISCSI,
                             uuid=uuid, target_path=target_path, conn=conn)

        if source_path:
            self.source_path = source_path
        if host:
            self.host = host

        self._iqn = None

    # Need to overwrite pool *_source_path since iscsi device isn't
    # a fully qualified path
    def get_source_path(self):
        return self._source_path
    def set_source_path(self, val):
        self._source_path = val
    source_path = property(get_source_path, set_source_path,
                           doc=_("Path on the host that is being shared."))

    def _get_iqn(self):
        return self._iqn
    def _set_iqn(self, val):
        self._iqn = val
    iqn = property(_get_iqn, _set_iqn,
                        doc=_("iSCSI initiator qualified name"))

    def _get_default_target_path(self):
        return DEFAULT_SCSI_TARGET

    def _get_target_xml(self):
        xml = "    <path>%s</path>\n" % escape(self.target_path)
        return xml

    def _get_source_xml(self):
        if not self.host:
            raise RuntimeError(_("Hostname is required"))
        if not self.source_path:
            raise RuntimeError(_("Host path is required"))

        iqn_xml = ""
        if self.iqn:
            iqn_xml += """    <initiator>\n"""
            iqn_xml += """      <iqn name="%s"/>\n""" % escape(self.iqn)
            iqn_xml += """    </initiator>\n"""

        xml  = """    <host name="%s"/>\n""" % self.host
        xml += """    <device path="%s"/>\n""" % escape(self.source_path)
        xml += iqn_xml

        return xml


class SCSIPool(StoragePool):
    """
    Create a SCSI based storage pool
    """

    target_path = property(StoragePool.get_target_path,
                           StoragePool.set_target_path,
                           doc=_("Root location for identifying new storage"
                                 " volumes."))

    def get_volume_class():
        raise NotImplementedError(_("SCSI volume creation is not supported."))
    get_volume_class = staticmethod(get_volume_class)

    def __init__(self, conn, name, source_path=None,
                 target_path=None, uuid=None):
        StoragePool.__init__(self, name=name, type=StoragePool.TYPE_SCSI,
                             uuid=uuid, target_path=target_path, conn=conn)

        if source_path:
            self.source_path = source_path

    # Need to overwrite pool *_source_path since iscsi device isn't
    # a fully qualified path
    def get_source_path(self):
        return self._source_path
    def set_source_path(self, val):
        self._source_path = val
    source_path = property(get_source_path, set_source_path,
                           doc=_("Name of the scsi adapter (ex. host2)"))

    def _get_default_target_path(self):
        return DEFAULT_SCSI_TARGET

    def _get_target_xml(self):
        xml = "    <path>%s</path>\n" % escape(self.target_path)
        return xml

    def _get_source_xml(self):
        if not self.source_path:
            raise RuntimeError(_("Adapter name is required"))
        xml = """    <adapter name="%s"/>\n""" % escape(self.source_path)
        return xml


class MultipathPool(StoragePool):
    """
    Create a Multipath based storage pool
    """

    target_path = property(StoragePool.get_target_path,
                           StoragePool.set_target_path,
                           doc=_("Root location for identifying new storage"
                                 " volumes."))

    def get_volume_class():
        raise NotImplementedError(_("Multipath volume creation is not "
                                    "supported."))
    get_volume_class = staticmethod(get_volume_class)

    def __init__(self, conn, name, target_path=None, uuid=None):
        StoragePool.__init__(self, name=name, type=StoragePool.TYPE_MPATH,
                             uuid=uuid, target_path=target_path, conn=conn)

    def _get_default_target_path(self):
        return DEFAULT_MPATH_TARGET

    def _get_target_xml(self):
        xml = "    <path>%s</path>\n" % escape(self.target_path)
        return xml

    def _get_source_xml(self):
        return ""


##########################
# Storage Volume classes #
##########################

class StorageVolume(StorageObject):
    """
    Base class for building and installing libvirt storage volume xml
    """

    formats = []

    # File vs. Block for the Volume class
    _file_type = None

    def __init__(self, conn, name, capacity, pool_name=None, pool=None,
                 allocation=0):
        """
        @param name: Name for the new storage volume
        @param capacity: Total size of the new volume (in bytes)
        @param conn: optional connection instance to lookup pool_name on
        @param pool_name: optional pool_name to install on
        @param pool: virStoragePool object to install on
        @param allocation: amount of storage to actually allocate (default 0)
        """
        if pool is None:
            if pool_name is None:
                raise ValueError(_("One of pool or pool_name must be "
                                   "specified."))
            pool = StorageVolume.lookup_pool_by_name(pool_name=pool_name,
                                                     conn=conn)
        self._pool = None
        self.pool = pool

        StorageObject.__init__(self, conn,
                               object_type=StorageObject.TYPE_VOLUME,
                               name=name)
        self._allocation = None
        self._capacity = None
        self._format = None
        self._input_vol = None

        self.allocation = allocation
        self.capacity = capacity

        # Indicate that the volume installation has finished. Used to
        # definitively tell the storage progress thread to stop polling.
        self._install_finished = True

    def get_volume_for_pool(pool_object=None, pool_name=None, conn=None):
        """
        Returns volume class associated with passed pool_object/name
        """
        pool_object = StorageVolume.lookup_pool_by_name(pool_object=pool_object,
                                                        pool_name=pool_name,
                                                        conn=conn)
        return StoragePool.get_volume_for_pool(util.xpath(
            pool_object.XMLDesc(0), "/pool/@type"))
    get_volume_for_pool = staticmethod(get_volume_for_pool)

    def find_free_name(name, pool_object=None, pool_name=None, conn=None,
                       suffix="", collidelist=None, start_num=0):
        """
        Finds a name similar (or equal) to passed 'name' that is not in use
        by another pool

        This function scans the list of existing Volumes on the passed or
        looked up pool object for a collision with the passed name. If the
        name is in use, it append "-1" to the name and tries again, then "-2",
        continuing to 100000 (which will hopefully never be reached.") If
        suffix is specified, attach it to the (potentially incremented) name
        before checking for collision.

        Ex name="test", suffix=".img" -> name-3.img

        @param collidelist: An extra list of names to check for collision
        @type collidelist: C{list}
        @returns: A free name
        @rtype: C{str}
        """
        collidelist = collidelist or []
        pool_object = StorageVolume.lookup_pool_by_name(
                                                    pool_object=pool_object,
                                                    pool_name=pool_name,
                                                    conn=conn)
        pool_object.refresh(0)

        return util.generate_name(name, pool_object.storageVolLookupByName,
                                   suffix, collidelist=collidelist,
                                   start_num=start_num)
    find_free_name = staticmethod(find_free_name)

    def lookup_pool_by_name(pool_object=None, pool_name=None, conn=None):
        """
        Returns pool object determined from passed parameters.

        Largely a convenience function for the other static functions.
        """
        if pool_object is None and pool_name is None:
            raise ValueError(_("Must specify pool_object or pool_name"))

        if pool_name is not None and pool_object is None:
            if conn is None:
                raise ValueError(_("'conn' must be specified with 'pool_name'"))
            if not conn.check_conn_support(conn.SUPPORT_CONN_STORAGE):
                raise ValueError(_("Connection does not support storage "
                                   "management."))
            try:
                pool_object = conn.storagePoolLookupByName(pool_name)
            except Exception, e:
                raise ValueError(_("Couldn't find storage pool '%s': %s" %
                                   (pool_name, str(e))))

        if not isinstance(pool_object, libvirt.virStoragePool):
            raise ValueError(_("pool_object must be a virStoragePool"))

        return pool_object
    lookup_pool_by_name = staticmethod(lookup_pool_by_name)

    # Properties used by all volumes
    def get_file_type(self):
        return self._file_type
    file_type = property(get_file_type)

    def get_capacity(self):
        return self._capacity
    def set_capacity(self, val):
        if type(val) not in (int, float, long) or val < 0:
            raise ValueError(_("Capacity must be a positive number"))
        newcap = int(val)
        origcap = self.capacity
        origall = self.allocation
        self._capacity = newcap
        if self.allocation is not None and (newcap < self.allocation):
            self._allocation = newcap

        ret = self.is_size_conflict()
        if ret[0]:
            self._capacity = origcap
            self._allocation = origall
            raise ValueError(ret[1])
        elif ret[1]:
            logging.warn(ret[1])
    capacity = property(get_capacity, set_capacity)

    def get_allocation(self):
        return self._allocation
    def set_allocation(self, val):
        if type(val) not in (int, float, long) or val < 0:
            raise ValueError(_("Allocation must be a non-negative number"))
        newall = int(val)
        if self.capacity is not None and newall > self.capacity:
            logging.debug("Capping allocation at capacity.")
            newall = self.capacity
        origall = self._allocation
        self._allocation = newall

        ret = self.is_size_conflict()
        if ret[0]:
            self._allocation = origall
            raise ValueError(ret[1])
        elif ret[1]:
            logging.warn(ret[1])
    allocation = property(get_allocation, set_allocation)

    def get_pool(self):
        return self._pool
    def set_pool(self, newpool):
        if not isinstance(newpool, libvirt.virStoragePool):
            raise ValueError(_("'pool' must be a virStoragePool instance."))
        if newpool.info()[0] != libvirt.VIR_STORAGE_POOL_RUNNING:
            raise ValueError(_("pool '%s' must be active." % newpool.name()))
        self._pool = newpool
    pool = property(get_pool, set_pool)

    def get_input_vol(self):
        return self._input_vol
    def set_input_vol(self, vol):
        if vol is None:
            self._input_vol = None
            return

        if not isinstance(vol, libvirt.virStorageVol):
            raise ValueError(_("input_vol must be a virStorageVol"))

        if not self.conn.check_pool_support(self.conn,
                    self.conn.SUPPORT_STORAGE_CREATEVOLFROM):
            raise ValueError(_("Creating storage from an existing volume is"
                               " not supported by this libvirt version."))
        self._input_vol = vol
    input_vol = property(get_input_vol, set_input_vol,
                         doc=_("virStorageVolume pointer to clone/use as "
                               "input."))

    # Property functions used by more than one child class
    def get_format(self):
        return self._format
    def set_format(self, val):
        if val not in self.formats:
            raise ValueError(_("'%s' is not a valid format.") % val)
        self._format = val

    def _check_name_collision(self, name):
        vol = None
        try:
            vol = self.pool.storageVolLookupByName(name)
        except libvirt.libvirtError:
            pass
        if vol:
            raise ValueError(_("Name '%s' already in use by another volume." %
                                name))

    def _check_target_collision(self, path):
        col = None
        try:
            col = self.conn.storageVolLookupByPath(path)
        except libvirt.libvirtError:
            pass
        if col:
            return True
        return False

    # xml building functions
    def _get_target_xml(self):
        raise NotImplementedError()

    def _get_source_xml(self):
        raise NotImplementedError()

    def _get_storage_xml(self):
        src_xml = ""
        if self._get_source_xml() != "":
            src_xml = "  <source>\n" + \
                      "%s" % (self._get_source_xml()) + \
                      "  </source>\n"
        tar_xml = "  <target>\n" + \
                  "%s" % (self._get_target_xml()) + \
                  "  </target>\n"
        return "  <capacity>%d</capacity>\n" % self.capacity + \
               "  <allocation>%d</allocation>\n" % self.allocation + \
               "%s" % src_xml + \
               "%s" % tar_xml

    def install(self, meter=None):
        """
        Build and install storage volume from xml
        """
        xml = self.get_xml_config()
        logging.debug("Creating storage volume '%s' with xml:\n%s",
                      self.name, xml)

        t = threading.Thread(target=self._progress_thread,
                             name="Checking storage allocation",
                             args=(meter,))
        t.setDaemon(True)

        if not meter:
            meter = urlgrabber.progress.BaseMeter()

        try:
            self._install_finished = False
            t.start()
            meter.start(size=self.capacity,
                        text=_("Allocating '%s'") % self.name)

            if self.input_vol:
                vol = self.pool.createXMLFrom(xml, self.input_vol, 0)
            else:
                vol = self.pool.createXML(xml, 0)

            self._install_finished = True
            t.join()
            meter.end(self.capacity)
            logging.debug("Storage volume '%s' install complete.",
                          self.name)
            return vol
        except libvirt.libvirtError, e:
            if util.is_error_nosupport(e):
                raise RuntimeError("Libvirt version does not support "
                                   "storage cloning.")
            raise
        except Exception, e:
            raise RuntimeError("Couldn't create storage volume "
                               "'%s': '%s'" % (self.name, str(e)))

    def _progress_thread(self, meter):
        lookup_attempts = 10
        vol = None

        if not meter:
            return

        while lookup_attempts > 0:
            try:
                vol = self.pool.storageVolLookupByName(self.name)
                break
            except:
                lookup_attempts -= 1
                time.sleep(.2)
                if self._install_finished:
                    break
                else:
                    continue
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
        # pool info is [pool state, capacity, allocation, available]
        avail = self.pool.info()[3]
        if self.allocation > avail:
            return (True, _("There is not enough free space on the storage "
                            "pool to create the volume. "
                            "(%d M requested allocation > %d M available)" %
                            ((self.allocation / (1024 * 1024)),
                             (avail / (1024 * 1024)))))
        elif self.capacity > avail:
            return (False, _("The requested volume capacity will exceed the "
                             "available pool space when the volume is fully "
                             "allocated. "
                             "(%d M requested capacity > %d M available)" %
                             ((self.capacity / (1024 * 1024)),
                              (avail / (1024 * 1024)))))
        return (False, "")


class FileVolume(StorageVolume):
    """
    Build and install xml for use on pools which use file based storage
    """
    _file_type = VIR_STORAGE_VOL_FILE

    formats = ["raw", "bochs", "cloop", "cow", "dmg", "iso", "qcow",
               "qcow2", "qed", "vmdk", "vpc"]
    create_formats = ["raw", "cow", "qcow", "qcow2", "qed", "vmdk", "vpc"]

    # Register applicable property methods from parent class
    perms = property(StorageObject.get_perms, StorageObject.set_perms)
    format = property(StorageVolume.get_format, StorageVolume.set_format)

    def __init__(self, conn, name, capacity,
                 pool=None, pool_name=None,
                 format="raw", allocation=None, perms=None):
        # pylint: disable=W0622
        # Redefining built-in 'format', but it matches the XML so keep it

        StorageVolume.__init__(self, conn, name=name,
                               pool=pool, pool_name=pool_name,
                               allocation=allocation, capacity=capacity)
        self.format = format
        if perms:
            self.perms = perms

    def _get_target_xml(self):
        return "    <format type='%s'/>\n" % self.format + \
               "%s" % self._get_perms_xml()

    def _get_source_xml(self):
        return ""


class DiskVolume(StorageVolume):
    """
    Build and install xml volumes for use on physical disk pools
    """
    _file_type = VIR_STORAGE_VOL_BLOCK

    # Register applicable property methods from parent class
    perms = property(StorageObject.get_perms, StorageObject.set_perms)

    def __init__(self, conn, name, capacity,
                  pool=None, pool_name=None,
                 allocation=None, perms=None):
        StorageVolume.__init__(self, conn, name=name,
                               pool=pool, pool_name=pool_name,
                               allocation=allocation, capacity=capacity)
        if perms:
            self.perms = perms

    def _get_target_xml(self):
        return "%s" % self._get_perms_xml()

    def _get_source_xml(self):
        return ""


class LogicalVolume(StorageVolume):
    """
    Build and install logical volumes for lvm pools
    """
    _file_type = VIR_STORAGE_VOL_BLOCK

    # Register applicable property methods from parent class
    perms = property(StorageObject.get_perms, StorageObject.set_perms)

    def __init__(self, conn,
                 name, capacity, pool=None, pool_name=None,
                 allocation=None, perms=None):
        if allocation and allocation != capacity:
            logging.warn(_("Sparse logical volumes are not supported, "
                           "setting allocation equal to capacity"))
        StorageVolume.__init__(self, conn, name=name,
                               pool=pool, pool_name=pool_name,
                               allocation=capacity, capacity=capacity)
        if perms:
            self.perms = perms

    def set_capacity(self, capacity):
        super(LogicalVolume, self).set_capacity(capacity)
        self.allocation = capacity
    capacity = property(StorageVolume.get_capacity, set_capacity)

    def set_allocation(self, allocation):
        if allocation != self.capacity:
            logging.warn(_("Sparse logical volumes are not supported, "
                           "setting allocation equal to capacity"))
        super(LogicalVolume, self).set_allocation(self.capacity)
    capacity = property(StorageVolume.get_allocation, set_allocation)


    def _get_target_xml(self):
        return "%s" % self._get_perms_xml()

    def _get_source_xml(self):
        return ""


class CloneVolume(StorageVolume):
    """
    Build and install a volume that is a clone of an existing volume
    """

    format = property(StorageVolume.get_format, StorageVolume.set_format)

    def __init__(self, conn, name, input_vol):
        if not isinstance(input_vol, libvirt.virStorageVol):
            raise ValueError(_("input_vol must be a virStorageVol"))

        pool = input_vol.storagePoolLookupByVolume()

        # Populate some basic info
        xml  = input_vol.XMLDesc(0)
        typ  = input_vol.info()[0]
        cap  = int(util.xpath(xml, "/volume/capacity"))
        alc  = int(util.xpath(xml, "/volume/allocation"))
        fmt  = util.xpath(xml, "/volume/target/format/@type")

        StorageVolume.__init__(self, conn, name=name, pool=pool,
                               pool_name=pool.name(),
                               allocation=alc, capacity=cap)

        self.input_vol = input_vol
        self._file_type = typ
        self._format = fmt

    def _get_target_xml(self):
        return ""
    def _get_source_xml(self):
        return ""

    def get_xml_config(self):
        xml  = self.input_vol.XMLDesc(0)
        newxml = util.set_xml_path(xml, "/volume/name", self.name)
        return newxml

# class iSCSIVolume(StorageVolume):
#    """
#    Build and install xml for use on iSCSI device pools
#    """
#    _file_type = VIR_STORAGE_VOL_BLOCK
#
#    def __init__(self, *args, **kwargs):
#        raise NotImplementedError
