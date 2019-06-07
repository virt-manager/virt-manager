#
# Copyright 2006, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
#

import os
import sys

import libvirt


def listify(l):
    if l is None:
        return []
    elif not isinstance(l, list):
        return [l]
    else:
        return l


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

    :param base: The base string to use for the name (e.g. "my-orig-vm-clone")
    :param collision_cb: A callback function to check for collision,
        receives the generated name as its only arg
    :param lib_collision: If true, the collision_cb is not a boolean function,
        and instead throws a libvirt error on failure
    :param start_num: The number to start at for generating non colliding names
    :param sep: The separator to use between the basename and the
        generated number (default is "-")
    :param force_num: Force the generated name to always end with a number
    :param collidelist: An extra list of names to check for collision
    """
    collidelist = collidelist or []
    base = str(base)

    def collide(n):
        if n in collidelist:
            return True
        if lib_collision:
            return libvirt_collision(collision_cb, tryname)
        else:
            return collision_cb(tryname)

    numrange = list(range(start_num, start_num + 100000))
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


def ensure_meter(meter):
    if meter:
        return meter
    return make_meter(quiet=True)


def make_meter(quiet):
    from virtinst import progress
    if quiet:
        return progress.BaseMeter()
    return progress.TextMeter(fo=sys.stdout)


def get_prop_path(obj, prop_path):
    """Return value of attribute identified by `prop_path`

    Look up the attribute of `obj` identified by `prop_path`
    (separated by "."). If any component along the path is missing an
    `AttributeError` is raised.

    """
    parent = obj
    pieces = prop_path.split(".")
    for piece in pieces[:-1]:
        parent = getattr(parent, piece)

    return getattr(parent, pieces[-1])


def set_prop_path(obj, prop_path, value):
    """Set value of attribute identified by `prop_path`

    Set the attribute of `obj` identified by `prop_path` (separated by
    ".") to `value`. If any component along the path is missing an
    `AttributeError` is raised.
    """
    parent = obj
    pieces = prop_path.split(".")
    for piece in pieces[:-1]:
        parent = getattr(parent, piece)

    return setattr(parent, pieces[-1], value)
