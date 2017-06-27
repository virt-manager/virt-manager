#
# Copyright 2006, 2013 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
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
#

import logging
import os
import random
import re
import sys

import libvirt


def listify(l):
    if l is None:
        return []
    elif type(l) != list:
        return [l]
    else:
        return l


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
                    "the form xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx or may "
                    "omit hyphens altogether."))

        else:   # UUID had no dashes, so add them in
            val = (val[0:8] + "-" + val[8:12] + "-" + val[12:16] +
                   "-" + val[16:20] + "-" + val[20:32])
    return val


def validate_name(name_type, val):
    # Rather than try and match libvirt's regex, just forbid things we
    # know don't work
    forbid = [" "]
    if not val:
        raise ValueError(
            _("A name must be specified for the %s") % name_type)
    for c in forbid:
        if c not in val:
            continue
        raise ValueError(
            _("%s name '%s' can not contain '%s' character.") %
            (name_type, val, c))


def validate_macaddr(val):
    if val is None:
        return

    if type(val) is not str:
        raise ValueError(_("MAC address must be a string."))

    form = re.match("^([0-9a-fA-F]{1,2}:){5}[0-9a-fA-F]{1,2}$", val)
    if form is None:
        raise ValueError(_("MAC address must be of the format "
                           "AA:BB:CC:DD:EE:FF, was '%s'") % val)


def generate_name(base, collision_cb, suffix="", lib_collision=True,
                  start_num=1, sep="-", force_num=False, collidelist=None):
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
    @param sep: The seperator to use between the basename and the
        generated number (default is "-")
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

    numrange = range(start_num, start_num + 100000)
    if not force_num:
        numrange = [None] + numrange

    for i in numrange:
        tryname = base
        if i is not None:
            tryname += ("%s%d" % (sep, i))
        tryname += suffix

        if not collide(tryname):
            return tryname

    raise ValueError(_("Name generation range exceeded."))



def generate_uuid(conn):
    for ignore in range(256):
        uuid = randomUUID(conn)
        if not vm_uuid_collision(conn, uuid):
            return uuid

    logging.error("Failed to generate non-conflicting UUID")



def randomUUID(conn):
    if conn.fake_conn_predictable():
        # Testing hack
        return "00000000-1111-2222-3333-444444444444"

    u = [random.randint(0, 255) for ignore in range(0, 16)]
    u[6] = (u[6] & 0x0F) | (4 << 4)
    u[8] = (u[8] & 0x3F) | (2 << 6)
    return "-".join(["%02x" * 4, "%02x" * 2, "%02x" * 2, "%02x" * 2,
                     "%02x" * 6]) % tuple(u)


def xml_escape(xml):
    """
    Replaces chars ' " < > & with xml safe counterparts
    """
    if xml is None:
        return None

    xml = xml.replace("&", "&amp;")
    xml = xml.replace("'", "&apos;")
    xml = xml.replace("\"", "&quot;")
    xml = xml.replace("<", "&lt;")
    xml = xml.replace(">", "&gt;")
    return xml


def is_error_nosupport(err):
    """
    Check if passed exception indicates that the called libvirt command isn't
    supported

    @param err: Exception raised from command call
    @returns: True if command isn't supported, False if we can't determine
    """
    if not isinstance(err, libvirt.libvirtError):
        return False

    if (err.get_error_code() == libvirt.VIR_ERR_RPC or
        err.get_error_code() == libvirt.VIR_ERR_NO_SUPPORT):
        return True

    return False


def exception_is_libvirt_error(e, error):
    return (hasattr(libvirt, error) and
            e.get_error_code() == getattr(libvirt, error))


def local_libvirt_version():
    """
    Lookup the local libvirt library version, but cache the value since
    it never changes.
    """
    key = "__virtinst_cached_getVersion"
    if not hasattr(libvirt, key):
        setattr(libvirt, key, libvirt.getVersion())
    return getattr(libvirt, key)


def get_system_scratchdir(hvtype):
    if "VIRTINST_TEST_SUITE" in os.environ:
        return os.getcwd()

    if hvtype == "test":
        return "/tmp"
    elif hvtype == "xen":
        return "/var/lib/xen"
    else:
        return "/var/lib/libvirt/boot"


def make_scratchdir(conn, hvtype):
    scratch = None
    if not conn.is_session_uri():
        scratch = get_system_scratchdir(hvtype)

    if (not scratch or
        not os.path.exists(scratch) or
        not os.access(scratch, os.W_OK)):
        scratch = os.path.join(get_cache_dir(), "boot")
        if not os.path.exists(scratch):
            os.makedirs(scratch, 0o751)

    return scratch


def pretty_mem(val):
    val = int(val)
    if val > (10 * 1024 * 1024):
        return "%2.2f GiB" % (val / (1024.0 * 1024.0))
    else:
        return "%2.0f MiB" % (val / 1024.0)


def pretty_bytes(val):
    val = int(val)
    if val > (1024 * 1024 * 1024):
        return "%2.2f GiB" % (val / (1024.0 * 1024.0 * 1024.0))
    else:
        return "%2.2f MiB" % (val / (1024.0 * 1024.0))


def get_cache_dir():
    ret = ""
    try:
        # We don't want to depend on glib for virt-install
        from gi.repository import GLib
        ret = GLib.get_user_cache_dir()
    except ImportError:
        pass

    if not ret:
        ret = os.environ.get("XDG_CACHE_HOME")
    if not ret:
        ret = os.path.expanduser("~/.cache")
    return os.path.join(ret, "virt-manager")


def register_libvirt_error_handler():
    """
    Ignore libvirt error reporting, we just use exceptions
    """
    def libvirt_callback(userdata, err):
        ignore = userdata
        ignore = err
    def libxml2_callback(userdata, err):
        ignore = userdata
        logging.debug("libxml2 callback error: %s", err)
    libvirt.registerErrorHandler(f=libvirt_callback, ctx=None)
    import libxml2
    libxml2.registerErrorHandler(f=libxml2_callback, ctx=None)


def ensure_meter(meter):
    if meter:
        return meter
    return make_meter(quiet=True)


def make_meter(quiet):
    from virtinst import progress
    if quiet:
        return progress.BaseMeter()
    return progress.TextMeter(fo=sys.stdout)
