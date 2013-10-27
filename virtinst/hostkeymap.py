#
# Copyright 2006-2013 Red Hat, Inc.
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
import re


_ETC_VCONSOLE = "/etc/vconsole.conf"
_KEYBOARD_DIR = "/etc/sysconfig/keyboard"
_XORG_CONF = "/etc/X11/xorg.conf"
_CONSOLE_SETUP_CONF = "/etc/default/console-setup"
_KEYBOARD_DEFAULT = "/etc/default/keyboard"


def _find_xkblayout(f):
    """
    Reads a keyboard layout from a file that defines an XKBLAYOUT
    variable, e.g. /etc/default/{keyboard,console-setup}.
    The format of these files is such that they can be 'sourced'
    in a shell script.

    Used for both /etc/default/keyboard and /etc/default/console-setup.
    The former is used by Debian 6.0 (Squeeze) and later.  The latter is
    used by older versions of Debian, and Ubuntu.
    """
    kt = None
    keymap_re = re.compile(r'\s*XKBLAYOUT="(?P<kt>[a-z-]+)"')
    for line in f:
        m = keymap_re.match(line)
        if m:
            kt = m.group('kt')
            break
    return kt


def _xorg_keymap(f):
    """
    Look in /etc/X11/xorg.conf for the host machine's keymap, and attempt to
    map it to a keymap supported by qemu
    """
    kt = None
    keymap_re = re.compile(r'\s*Option\s+"XkbLayout"\s+"(?P<kt>[a-z-]+)"')
    for line in f:
        m = keymap_re.match(line)
        if m:
            kt = m.group('kt')
            break
    return kt


def _sysconfig_keyboard(f):
    kt = None
    while 1:
        s = f.readline()
        if s == "":
            break
        if (re.search("KEYMAP", s) is not None or
            re.search("KEYTABLE", s) is not None or
           (re.search("KEYBOARD", s) is not None and
            re.search("KEYBOARDTYPE", s) is None)):
            if s.count('"'):
                delim = '"'
            elif s.count('='):
                delim = '='
            else:
                continue
            kt = s.split(delim)[1].strip()
            break
    return kt


def _default_keymap():
    """
    Look in various config files for the host machine's keymap, and attempt
    to map it to a keymap supported by qemu
    """
    # Set keymap to same as hosts
    default = "en-us"
    keymap = None

    kt = None

    if "VIRTINST_TEST_SUITE" in os.environ:
        return default

    for path, cb in [
        (_ETC_VCONSOLE, _sysconfig_keyboard),
        (_KEYBOARD_DIR, _sysconfig_keyboard),
        (_XORG_CONF, _xorg_keymap),
        (_KEYBOARD_DEFAULT, _find_xkblayout),
        (_CONSOLE_SETUP_CONF, _find_xkblayout)]:
        if not os.path.exists(path):
            continue

        try:
            f = open(path, "r")
            kt = cb(f)
            f.close()
            if kt:
                logging.debug("Found keymap=%s in %s", kt, path)
                break
            logging.debug("Didn't find keymap in '%s'", path)
        except Exception, e:
            logging.debug("Error parsing '%s': %s", path, str(e))

    if kt is None:
        logging.debug("Did not parse any usable keymapping.")
        return default

    kt = kt.lower()
    keymap = sanitize_keymap(kt)
    if not keymap:
        logging.debug("Didn't match keymap '%s' in keytable!", kt)
        return default
    return keymap


##################
# Public helpers #
##################

# Host keytable entry : keymap name in qemu/xen
# Only use lower case entries: all lookups are .lower()'d
keytable = {
    "ar": "ar",
    "da": "da", "dk": "da",
    "de": "de",
    "de-ch": "de-ch",
    "en-gb": "en-gb", "gb": "en-gb", "uk": "en-gb",
    "en-us": "en-us", "us": "en-us",
    "es": "es",
    "et": "et",
    "fi": "fi", "se_fi": "fi",
    "fo": "fo",
    "fr": "fr",
    "fr-be": "fr-be", "be": "fr-be",
    "fr-ca": "fr-ca", "ca": "fr-ca",
    "fr-ch": "fr-ch", "fr_ch": "fr-ch",
    "hr": "hr",
    "hu": "hu",
    "is": "is",
    "it": "it",
    "ja": "ja", "jp106": "ja", "jp": "ja",
    "lt": "lt",
    "lv": "lv",
    "mk": "mk",
    "nl": "nl",
    "nl-be": "nl-be",
    "no": "no",
    "pl": "pl",
    "pt": "pt",
    "pt-br": "pt-br", "br": "pt-br", "br-abnt2": "pt-br",
    "ru": "ru",
    "sl": "sl",
    "sv": "sv",
    "th": "th",
    "tr": "tr",
}


_cached_keymap = None


def default_keymap():
    global _cached_keymap
    if _cached_keymap is None:
        _cached_keymap = _default_keymap()
    return _cached_keymap


def sanitize_keymap(kt):
    """
    Make sure the passed keymap roughly matches something in keytable
    """
    if kt.lower() in keytable:
        return keytable[kt]

    # Try a more intelligent lookup: strip out all '-' and '_', sort
    # the keytable keys putting the longest first, then compare
    # by string prefix
    def len_cmp(a, b):
        return len(b) - len(a)

    clean_kt = kt.replace("-", "").replace("_", "")
    sorted_keys = sorted(keytable.keys(), len_cmp)

    for key in sorted_keys:
        origkey = key
        key = key.replace("-", "").replace("_", "")

        if clean_kt.startswith(key):
            return keytable[origkey]

    return None
