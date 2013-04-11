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

import commands
import logging
import os
import platform
import random
import re
import stat
import subprocess

import libvirt
import libxml2


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

def default_bridge(conn=None):
    if platform.system() == 'SunOS':
        return ["bridge", default_nic()]

    dev = default_route()

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
    paths = [ KEYBOARD_DEFAULT, CONSOLE_SETUP_CONF ]
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

KEYBOARD_DIR = "/etc/sysconfig/keyboard"
XORG_CONF = "/etc/X11/xorg.conf"
CONSOLE_SETUP_CONF = "/etc/default/console-setup"

def default_route(nic=None):
    if platform.system() == 'SunOS':
        cmd = [ '/usr/bin/netstat', '-rn' ]
        if nic:
            cmd += [ '-I', nic ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        for line in proc.stdout.readlines():
            vals = line.split()
            if len(vals) > 1 and vals[0] == 'default':
                return vals[1]
        return None

    route_file = "/proc/net/route"
    d = file(route_file)

    defn = 0
    for line in d.xreadlines():
        info = line.split()
        if (len(info) != 11): # 11 = typical num of fields in the file
            logging.warn(_("Invalid line length while parsing %s."),
                         route_file)
            logging.warn(_("Defaulting bridge to xenbr%d"), defn)
            break
        try:
            route = int(info[1], 16)
            if route == 0:
                return info[0]
        except ValueError:
            continue
    return None


def default_network(conn):
    ret = default_bridge(conn)
    if not ret:
        # FIXME: Check that this exists
        ret = ["network", "default"]

    return ret

def default_connection():
    if os.path.exists('/var/lib/xend'):
        if os.path.exists('/dev/xen/evtchn'):
            return 'xen'
        if os.path.exists("/proc/xen"):
            return 'xen'

    from virtinst import User

    if os.path.exists("/usr/bin/qemu") or \
        os.path.exists("/usr/bin/qemu-kvm") or \
        os.path.exists("/usr/bin/kvm") or \
        os.path.exists("/usr/bin/xenner"):
        if User.current().has_priv(User.PRIV_QEMU_SYSTEM):
            return "qemu:///system"
        else:
            return "qemu:///session"
    return None


def is_blktap_capable():
    if platform.system() == 'SunOS':
        return False

    #return os.path.exists("/dev/xen/blktapctrl")
    f = open("/proc/modules")
    lines = f.readlines()
    f.close()
    for line in lines:
        if line.startswith("blktap ") or line.startswith("xenblktap "):
            return True
    return False


# this function is directly from xend/server/netif.py and is thus
# available under the LGPL,
# Copyright 2004, 2005 Mike Wray <mike.wray@hp.com>
# Copyright 2005 XenSource Ltd
def randomMAC(type="xen", conn=None):
    """Generate a random MAC address.

    00-16-3E allocated to xensource
    52-54-00 used by qemu/kvm

    The OUI list is available at http://standards.ieee.org/regauth/oui/oui.txt.

    The remaining 3 fields are random, with the first bit of the first
    random field set 0.

    >>> randomMAC().startswith("00:16:3E")
    True
    >>> randomMAC("foobar").startswith("00:16:3E")
    True
    >>> randomMAC("xen").startswith("00:16:3E")
    True
    >>> randomMAC("qemu").startswith("52:54:00")
    True

    @return: MAC address string
    """
    if conn and hasattr(conn, "_virtinst__fake_conn_predictable"):
        # Testing hack
        return "00:11:22:33:44:55"

    ouis = { 'xen': [ 0x00, 0x16, 0x3E ], 'qemu': [ 0x52, 0x54, 0x00 ] }

    try:
        oui = ouis[type]
    except KeyError:
        oui = ouis['xen']

    mac = oui + [
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff)]
    return ':'.join(map(lambda x: "%02x" % x, mac))


# the following three functions are from xend/uuid.py and are thus
# available under the LGPL,
# Copyright 2005 Mike Wray <mike.wray@hp.com>
# Copyright 2005 XenSource Ltd
def randomUUID():
    """Generate a random UUID."""

    return [ random.randint(0, 255) for dummy in range(0, 16) ]

def uuidToString(u, conn=None):
    if conn and hasattr(conn, "_virtinst__fake_conn_predictable"):
        # Testing hack
        return "00000000-1111-2222-3333-444444444444"

    return "-".join(["%02x" * 4, "%02x" * 2, "%02x" * 2, "%02x" * 2,
                     "%02x" * 6]) % tuple(u)


def get_max_vcpus(conn, type=None):
    """@param conn: libvirt connection to poll for max possible vcpus
       @type type: optional guest type (kvm, etc.)"""
    if type is None:
        type = conn.getType()
    try:
        m = conn.getMaxVcpus(type.lower())
    except libvirt.libvirtError:
        m = 32
    return m


def xml_escape(str):
    """Replaces chars ' " < > & with xml safe counterparts"""
    if str is None:
        return None

    str = str.replace("&", "&amp;")
    str = str.replace("'", "&apos;")
    str = str.replace("\"", "&quot;")
    str = str.replace("<", "&lt;")
    str = str.replace(">", "&gt;")
    return str


def _xorg_keymap():
    """Look in /etc/X11/xorg.conf for the host machine's keymap, and attempt to
       map it to a keymap supported by qemu"""

    kt = None
    try:
        f = open(XORG_CONF, "r")
    except IOError, e:
        logging.debug('Could not open "%s": %s ', XORG_CONF, str(e))
    else:
        keymap_re = re.compile(r'\s*Option\s+"XkbLayout"\s+"(?P<kt>[a-z-]+)"')
        for line in f:
            m = keymap_re.match(line)
            if m:
                kt = m.group('kt')
                break
        else:
            logging.debug("Didn't find keymap in '%s'!", XORG_CONF)
        f.close()
    return kt

def _console_setup_keymap():
    """Look in /etc/default/console-setup for the host machine's keymap, and attempt to
       map it to a keymap supported by qemu"""
    return find_xkblayout(CONSOLE_SETUP_CONF)

def default_keymap():
    """Look in /etc/sysconfig for the host machine's keymap, and attempt to
       map it to a keymap supported by qemu"""

    # Set keymap to same as hosts
    default = "en-us"
    keymap = None

    kt = None
    try:
        f = open(KEYBOARD_DIR, "r")
    except IOError, e:
        logging.debug('Could not open "/etc/sysconfig/keyboard" ' + str(e))
        kt = _xorg_keymap()
        if not kt:
            kt = find_keymap_from_etc_default()
    else:
        while 1:
            s = f.readline()
            if s == "":
                break
            if re.search("KEYTABLE", s) != None or \
               (re.search("KEYBOARD", s) != None and
                re.search("KEYBOARDTYPE", s) == None):
                if s.count('"'):
                    delim = '"'
                elif s.count('='):
                    delim = '='
                else:
                    continue
                kt = s.split(delim)[1].strip()
        f.close()

    if kt == None:
        logging.debug("Did not parse any usable keymapping.")
        return default

    kt = kt.lower()

    keymap = check_keytable(kt)

    if not keymap:
        logging.debug("Didn't match keymap '%s' in keytable!", kt)
        return default

    return keymap


def uri_split(uri):
    """
    Parse a libvirt hypervisor uri into it's individual parts
    @returns: tuple of the form (scheme (ex. 'qemu', 'xen+ssh'), username,
                                 hostname, path (ex. '/system'), query,
                                 fragment)
    """
    def splitnetloc(url, start=0):
        for c in '/?#': # the order is important!
            delim = url.find(c, start)
            if delim >= 0:
                break
        else:
            delim = len(url)
        return url[start:delim], url[delim:]

    username = netloc = query = fragment = ''
    i = uri.find(":")
    if i > 0:
        scheme, uri = uri[:i].lower(), uri[i + 1:]
        if uri[:2] == '//':
            netloc, uri = splitnetloc(uri, 2)
            offset = netloc.find("@")
            if offset > 0:
                username = netloc[0:offset]
                netloc = netloc[offset + 1:]
        if '#' in uri:
            uri, fragment = uri.split('#', 1)
        if '?' in uri:
            uri, query = uri.split('?', 1)
    else:
        scheme = uri.lower()
    return scheme, username, netloc, uri, query, fragment


def is_uri_remote(uri, conn=None):
    if conn and hasattr(conn, "_virtinst__fake_conn_remote"):
        # Testing hack
        return True

    try:
        split_uri = uri_split(uri)
        netloc = split_uri[2]

        if netloc == "":
            return False
        return True
    except Exception, e:
        logging.exception("Error parsing URI in is_remote: %s", e)
        return True

def get_uri_hostname(uri):
    try:
        split_uri = uri_split(uri)
        netloc = split_uri[2]

        if netloc != "":
            return netloc
    except Exception, e:
        logging.warning("Cannot parse URI %s: %s", uri, str(e))
    return "localhost"

def get_uri_transport(uri):
    try:
        split_uri = uri_split(uri)
        scheme = split_uri[0]
        username = split_uri[1]

        if scheme:
            offset = scheme.index("+")
            if offset > 0:
                return [scheme[offset + 1:], username]
    except:
        pass
    return [None, None]

def get_uri_driver(uri):
    try:
        split_uri = uri_split(uri)
        scheme = split_uri[0]

        if scheme:
            offset = scheme.find("+")
            if offset > 0:
                return scheme[:offset]
            return scheme
    except Exception:
        pass
    return "xen"

def is_storage_capable(conn):
    """check if virConnectPtr passed has storage API support"""
    import support

    return support.check_conn_support(conn, support.SUPPORT_CONN_STORAGE)

def get_xml_path(xml, path=None, func=None):
    """
    Return the content from the passed xml xpath, or return the result
    of a passed function (receives xpathContext as its only arg)
    """
    doc = None
    ctx = None
    result = None

    try:
        doc = libxml2.parseDoc(xml)
        ctx = doc.xpathNewContext()

        if path:
            ret = ctx.xpathEval(path)
            if ret != None:
                if type(ret) == list:
                    if len(ret) >= 1:
                        result = ret[0].content
                else:
                    result = ret

        elif func:
            result = func(ctx)

        else:
            raise ValueError(_("'path' or 'func' is required."))
    finally:
        if doc:
            doc.freeDoc()
        if ctx:
            ctx.xpathFreeContext()
    return result

def lookup_pool_by_path(conn, path):
    """
    Return the first pool with matching matching target path.
    return the first we find, active or inactive. This iterates over
    all pools and dumps their xml, so it is NOT quick.
    Favor running pools over inactive pools.
    @returns: virStoragePool object if found, None otherwise
    """
    if not is_storage_capable(conn):
        return None

    def check_pool(poolname, path):
        pool = conn.storagePoolLookupByName(poolname)
        xml_path = get_xml_path(pool.XMLDesc(0), "/pool/target/path")
        if xml_path is not None and os.path.abspath(xml_path) == path:
            return pool

    running_list = conn.listStoragePools()
    inactive_list = conn.listDefinedStoragePools()
    for plist in [running_list, inactive_list]:
        for name in plist:
            p = check_pool(name, path)
            if p:
                return p
    return None

def check_keytable(kt):
    import keytable
    keymap = None
    # Try a simple lookup in the keytable
    if kt.lower() in keytable.keytable:
        return keytable.keytable[kt]
    else:
        # Try a more intelligent lookup: strip out all '-' and '_', sort
        # the keytable keys putting the longest first, then compare
        # by string prefix
        def len_cmp(a, b):
            return len(b) - len(a)

        clean_kt = kt.replace("-", "").replace("_", "")
        sorted_keys = sorted(keytable.keytable.keys(), len_cmp)

        for key in sorted_keys:
            origkey = key
            key = key.replace("-", "").replace("_", "")

            if clean_kt.startswith(key):
                return keytable.keytable[origkey]

    return keymap

def _test():
    import doctest
    doctest.testmod()

if __name__ == "__main__":
    _test()
