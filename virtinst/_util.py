#
# Copyright 2006  Red Hat, Inc.
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
#

#
# Internal utility functions. These do NOT form part of the API and must
# not be used by clients.
#

import stat
import os
import re
import commands
import logging
import platform
import subprocess

import libxml2
import libvirt

import virtinst.util as util

try:
    import selinux
except ImportError:
    selinux = None

def listify(l):
    if l is None:
        return []
    elif type(l) != list:
        return [ l ]
    else:
        return l

def is_vdisk(path):
    if not os.path.exists("/usr/sbin/vdiskadm"):
        return False
    if not os.path.exists(path):
        return True
    if os.path.isdir(path) and \
       os.path.exists(path + "/vdisk.xml"):
        return True
    return False

def stat_disk(path):
    """Returns the tuple (isreg, size)."""
    if not os.path.exists(path):
        return True, 0

    if is_vdisk(path):
        size = int(commands.getoutput(
            "vdiskadm prop-get -p max-size " + path))
        return True, size

    mode = os.stat(path)[stat.ST_MODE]

    # os.path.getsize('/dev/..') can be zero on some platforms
    if stat.S_ISBLK(mode):
        try:
            fd = os.open(path, os.O_RDONLY)
            # os.SEEK_END is not present on all systems
            size = os.lseek(fd, 0, 2)
            os.close(fd)
        except:
            size = 0
        return False, size
    elif stat.S_ISREG(mode):
        return True, os.path.getsize(path)

    return True, 0

def blkdev_size(path):
    """Return the size of the block device.  We can't use os.stat() as
    that returns zero on many platforms."""
    fd = os.open(path, os.O_RDONLY)
    # os.SEEK_END is not present on all systems
    size = os.lseek(fd, 0, 2)
    os.close(fd)
    return size

def sanitize_arch(arch):
    """Ensure passed architecture string is the format we expect it.
       Returns the sanitized result"""
    if not arch:
        return arch
    tmparch = arch.lower().strip()
    if re.match(r'i[3-9]86', tmparch):
        return "i686"
    elif tmparch == "amd64":
        return "x86_64"
    return arch

def vm_uuid_collision(conn, uuid):
    """
    Check if passed UUID string is in use by another guest of the connection
    Returns true/false
    """
    return libvirt_collision(conn.lookupByUUIDString, uuid)

def libvirt_collision(collision_cb, val):
    """
    Run the passed collision function with val as the only argument:
    If libvirtError is raised, return False
    If no libvirtError raised, return True
    """
    check = False
    if val is not None:
        try:
            if collision_cb(val) is not None:
                check = True
        except libvirt.libvirtError:
            pass
    return check

def validate_uuid(val):
    if type(val) is not str:
        raise ValueError(_("UUID must be a string."))

    form = re.match("[a-fA-F0-9]{8}[-]([a-fA-F0-9]{4}[-]){3}[a-fA-F0-9]{12}$",
                    val)
    if form is None:
        form = re.match("[a-fA-F0-9]{32}$", val)
        if form is None:
            raise ValueError(
                  _("UUID must be a 32-digit hexadecimal number. It may take "
                    "the form XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX or may omit "
                    "hyphens altogether."))

        else:   # UUID had no dashes, so add them in
            val = (val[0:8] + "-" + val[8:12] + "-" + val[12:16] +
                   "-" + val[16:20] + "-" + val[20:32])
    return val

def validate_name(name_type, val, lencheck=False):
    if type(val) is not str or len(val) == 0:
        raise ValueError(_("%s name must be a string") % name_type)

    if lencheck:
        if len(val) > 50:
            raise ValueError(_("%s name must be less than 50 characters") %
                             name_type)
    if re.match("^[0-9]+$", val):
        raise ValueError(_("%s name can not be only numeric characters") %
                          name_type)
    if re.match("^[a-zA-Z0-9._-]+$", val) == None:
        raise ValueError(_("%s name can only contain alphanumeric, '_', '.', "
                           "or '-' characters") % name_type)

def validate_macaddr(val):
    if val is None:
        return

    if type(val) is not str:
        raise ValueError(_("MAC address must be a string."))

    form = re.match("^([0-9a-fA-F]{1,2}:){5}[0-9a-fA-F]{1,2}$", val)
    if form is None:
        raise ValueError(_("MAC address must be of the format "
                           "AA:BB:CC:DD:EE:FF"))
def xml_append(orig, new):
    """
    Little function that helps generate consistent xml
    """
    if not new:
        return orig
    if orig:
        orig += "\n"
    return orig + new

def fetch_all_guests(conn):
    """
    Return 2 lists: ([all_running_vms], [all_nonrunning_vms])
    """
    active = []
    inactive = []

    # Get all active VMs
    ids = conn.listDomainsID()
    for i in ids:
        try:
            vm = conn.lookupByID(i)
            active.append(vm)
        except libvirt.libvirtError:
            # guest probably in process of dieing
            logging.warn("Failed to lookup active domain id %d", i)

    # Get all inactive VMs
    names = conn.listDefinedDomains()
    for name in names:
        try:
            vm = conn.lookupByName(name)
            inactive.append(vm)
        except:
            # guest probably in process of dieing
            logging.warn("Failed to lookup inactive domain %d", name)

    return (active, inactive)

def set_xml_path(xml, path, newval):
    """
    Set the passed xml xpath to the new value
    """
    doc = None
    ctx = None
    result = None

    try:
        doc = libxml2.parseDoc(xml)
        ctx = doc.xpathNewContext()

        ret = ctx.xpathEval(path)
        if ret != None:
            if type(ret) == list:
                if len(ret) == 1:
                    ret[0].setContent(newval)
            else:
                ret.setContent(newval)

        result = doc.serialize()
    finally:
        if doc:
            doc.freeDoc()
        if ctx:
            ctx.xpathFreeContext()
    return result


def generate_name(base, collision_cb, suffix="", lib_collision=True,
                  start_num=0, sep="-", force_num=False, collidelist=None):
    """
    Generate a new name from the passed base string, verifying it doesn't
    collide with the collision callback.

    This can be used to generate disk path names from the parent VM or pool
    name. Names generated look like 'base-#suffix', ex:

    If foobar, and foobar-1.img already exist, and:
    base   = "foobar"
    suffix = ".img"

    output = "foobar-2.img"

    @param base: The base string to use for the name (e.g. "my-orig-vm-clone")
    @param collision_cb: A callback function to check for collision,
                         receives the generated name as its only arg
    @param lib_collision: If true, the collision_cb is not a boolean function,
                          and instead throws a libvirt error on failure
    @param start_num: The number to start at for generating non colliding names
    @param sep: The seperator to use between the basename and the generated number
                (default is "-")
    @param force_num: Force the generated name to always end with a number
    @param collidelist: An extra list of names to check for collision
    """
    collidelist = collidelist or []

    def collide(n):
        if n in collidelist:
            return True
        if lib_collision:
            return libvirt_collision(collision_cb, tryname)
        else:
            return collision_cb(tryname)

    for i in range(start_num, start_num + 100000):
        tryname = base
        if i != 0 or force_num:
            tryname += ("%s%d" % (sep, i))
        tryname += suffix

        if not collide(tryname):
            return tryname

    raise ValueError(_("Name generation range exceeded."))

# Selinux helpers
def have_selinux():
    return bool(selinux) and bool(selinux.is_selinux_enabled())

def selinux_restorecon(path):
    if have_selinux() and hasattr(selinux, "restorecon"):
        try:
            selinux.restorecon(path)
        except Exception, e:
            logging.debug("Restoring context for '%s' failed: %s",
                          path, str(e))
def selinux_getfilecon(path):
    if have_selinux():
        return selinux.getfilecon(path)[1]
    return None

def selinux_setfilecon(storage, label):
    """
    Wrapper for selinux.setfilecon. Libvirt may be able to relabel existing
    storage someday, we can fold that into this.
    """
    if have_selinux():
        selinux.setfilecon(storage, label)

def selinux_is_label_valid(label):
    """
    Check if the passed label is an actually valid selinux context label
    Returns False if selinux support is not present
    """
    return bool(have_selinux() and (not hasattr(selinux, "context_new") or
                                    selinux.context_new(label)))

def selinux_rw_label():
    """
    Expected SELinux label for read/write disks
    """
    con = "system_u:object_r:virt_image_t:s0"

    if not selinux_is_label_valid(con):
        con = ""
    return con

def selinux_readonly_label():
    """
    Expected SELinux label for things like readonly installation media
    """
    con = "system_u:object_r:virt_content_t:s0"

    if not selinux_is_label_valid(con):
        # The RW label is newer than the RO one, so see if that exists
        con = selinux_rw_label()
    return con

def default_nic():
    """
    Return the default NIC to use, if one is specified.
    """

    dev = ''

    if platform.system() != 'SunOS':
        return dev

    # XXX: fails without PRIV_XVM_CONTROL
    proc = subprocess.Popen(['/usr/lib/xen/bin/xenstore-read',
        'device-misc/vif/default-nic'], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    out = proc.stdout.readlines()
    if len(out) > 0:
        dev = out[0].rstrip()

    return dev

def default_bridge2(conn=None):
    if platform.system() == 'SunOS':
        return ["bridge", default_nic()]

    dev = util.default_route()

    if (dev is not None and
        (not conn or not is_uri_remote(conn.getURI(), conn=conn))):
        # New style peth0 == phys dev, eth0 == bridge, eth0 == default route
        if os.path.exists("/sys/class/net/%s/bridge" % dev):
            return ["bridge", dev]

        # Old style, peth0 == phys dev, eth0 == netloop, xenbr0 == bridge,
        # vif0.0 == netloop enslaved, eth0 == default route
        try:
            defn = int(dev[-1])
        except:
            defn = -1

        if (defn >= 0 and
            os.path.exists("/sys/class/net/peth%d/brport" % defn) and
            os.path.exists("/sys/class/net/xenbr%d/bridge" % defn)):
            return ["bridge", "xenbr%d" % defn]

    return None

def _get_uri_to_split(conn, uri):
    if not conn and not uri:
        return None

    if type(conn) is str:
        uri = conn
    elif uri is None:
        uri = conn.getURI()
    return uri

def is_qemu_system(conn, uri=None):
    uri = _get_uri_to_split(conn, uri)
    if not uri:
        return False

    (scheme, ignore, ignore,
     path, ignore, ignore) = uri_split(uri)
    if path == "/system" and scheme.startswith("qemu"):
        return True
    return False

def is_session_uri(conn, uri=None):
    uri = _get_uri_to_split(conn, uri)
    if not uri:
        return False

    (ignore, ignore, ignore,
     path, ignore, ignore) = uri_split(uri)
    return bool(path and path == "/session")

def is_qemu(conn, uri=None):
    uri = _get_uri_to_split(conn, uri)
    if not uri:
        return False

    scheme = uri_split(uri)[0]
    return scheme.startswith("qemu")

def is_xen(conn, uri=None):
    uri = _get_uri_to_split(conn, uri)
    if not uri:
        return False

    scheme = uri_split(uri)[0]
    return scheme.startswith("xen")

def parse_node_helper(xml, root_name, callback, exec_class=ValueError):
    """
    Parse the passed XML, expecting root as root_name, and pass the
    root node to callback
    """
    class ErrorHandler:
        def __init__(self):
            self.msg = ""
        def handler(self, ignore, s):
            self.msg += s
    error = ErrorHandler()
    libxml2.registerErrorHandler(error.handler, None)

    try:
        try:
            doc = libxml2.readMemory(xml, len(xml),
                                     None, None,
                                     libxml2.XML_PARSE_NOBLANKS)
        except (libxml2.parserError, libxml2.treeError), e:
            raise exec_class("%s\n%s" % (e, error.msg))
    finally:
        libxml2.registerErrorHandler(None, None)

    ret = None
    try:
        root = doc.getRootElement()
        if root.name != root_name:
            raise ValueError("Root element is not '%s'" % root_name)

        ret = callback(root)
    finally:
        doc.freeDoc()

    return ret

def find_xkblayout(path):
    """
    Reads a keyboard layout from a file that defines an XKBLAYOUT
    variable, e.g. /etc/default/{keyboard,console-setup}.
    The format of these files is such that they can be 'sourced'
    in a shell script.
    """

    kt = None
    try:
        f = open(path, "r")
    except IOError, e:
        logging.debug('Could not open "%s": %s ', path, str(e))
    else:
        keymap_re = re.compile(r'\s*XKBLAYOUT="(?P<kt>[a-z-]+)"')
        for line in f:
            m = keymap_re.match(line)
            if m:
                kt = m.group('kt')
                break
        else:
            logging.debug("Didn't find keymap in '%s'!", path)
        f.close()
    return kt

def find_keymap_from_etc_default():
    """
    Look under /etc/default for the host machine's keymap.

    This checks both /etc/default/keyboard and /etc/default/console-setup.
    The former is used by Debian 6.0 (Squeeze) and later.  The latter is
    used by older versions of Debian, and Ubuntu.
    """

    KEYBOARD_DEFAULT = "/etc/default/keyboard"
    paths = [ KEYBOARD_DEFAULT, util.CONSOLE_SETUP_CONF ]
    for path in paths:
        kt = find_xkblayout(path)
        if kt != None:
            break
    return kt

def generate_uuid(conn):
    for ignore in range(256):
        uuid = uuidToString(randomUUID(), conn=conn)
        if not vm_uuid_collision(conn, uuid):
            return uuid

    logging.error("Failed to generate non-conflicting UUID")

#
# These functions accidentally ended up in the API under virtinst.util
#
default_route = util.default_route
default_bridge = util.default_bridge
default_network = util.default_network
default_connection = util.default_connection
get_cpu_flags = util.get_cpu_flags
is_pae_capable = util.is_pae_capable
is_blktap_capable = util.is_blktap_capable
get_default_arch = util.get_default_arch
randomMAC = util.randomMAC
randomUUID = util.randomUUID
uuidToString = util.uuidToString
uuidFromString = util.uuidFromString
get_host_network_devices = util.get_host_network_devices
get_max_vcpus = util.get_max_vcpus
get_phy_cpus = util.get_phy_cpus
xml_escape = util.xml_escape
compareMAC = util.compareMAC
default_keymap = util.default_keymap
pygrub_path = util.pygrub_path
uri_split = util.uri_split
is_uri_remote = util.is_uri_remote
get_uri_hostname = util.get_uri_hostname
get_uri_transport = util.get_uri_transport
get_uri_driver = util.get_uri_driver
is_storage_capable = util.is_storage_capable
get_xml_path = util.get_xml_path
lookup_pool_by_path = util.lookup_pool_by_path
check_keytable = util.check_keytable
