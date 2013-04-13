#
# Copyright 2006-2013 Red Hat, Inc.
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

import logging
import re

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

KEYBOARD_DIR = "/etc/sysconfig/keyboard"
XORG_CONF = "/etc/X11/xorg.conf"
CONSOLE_SETUP_CONF = "/etc/default/console-setup"


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


def _find_keymap_from_etc_default():
    """
    Look under /etc/default for the host machine's keymap.

    This checks both /etc/default/keyboard and /etc/default/console-setup.
    The former is used by Debian 6.0 (Squeeze) and later.  The latter is
    used by older versions of Debian, and Ubuntu.
    """

    KEYBOARD_DEFAULT = "/etc/default/keyboard"
    paths = [KEYBOARD_DEFAULT, CONSOLE_SETUP_CONF]
    for path in paths:
        kt = find_xkblayout(path)
        if kt is not None:
            break
    return kt


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


def default_keymap():
    """
    Look in various config files for the host machine's keymap, and attempt
    to map it to a keymap supported by qemu
    """
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
            kt = _find_keymap_from_etc_default()
    else:
        while 1:
            s = f.readline()
            if s == "":
                break
            if re.search("KEYTABLE", s) is not None or \
               (re.search("KEYBOARD", s) is not None and
                re.search("KEYBOARDTYPE", s) is None):
                if s.count('"'):
                    delim = '"'
                elif s.count('='):
                    delim = '='
                else:
                    continue
                kt = s.split(delim)[1].strip()
        f.close()

    if kt is None:
        logging.debug("Did not parse any usable keymapping.")
        return default

    kt = kt.lower()

    keymap = sanitize_keymap(kt)

    if not keymap:
        logging.debug("Didn't match keymap '%s' in keytable!", kt)
        return default

    return keymap


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
