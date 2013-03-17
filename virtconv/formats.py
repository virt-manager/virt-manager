#
# Copyright 2008 Sun Microsystems, Inc.  All rights reserved.
# Use is subject to license terms.
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

import os

from virtconv import _gettext as _

_parsers = [ ]

class parser(object):
    """
    Base class for particular config file format definitions of
    a VM instance.

    Warning: this interface is not (yet) considered stable and may
    change at will.
    """

    @staticmethod
    def identify_file(input_file):
        """
        Return True if the given file is of this format.
        """
        raise NotImplementedError

    @staticmethod
    def import_file(input_file):
        """
        Import a configuration file.  Raises if the file couldn't be
        opened, or parsing otherwise failed.
        """
        raise NotImplementedError

    @staticmethod
    def export(vm):
        """
        Export a configuration file as a string.
        @vm vm configuration instance

        Raises ValueError if configuration is not suitable.
        """
        raise NotImplementedError

def register_parser(new_parser):
    """
    Register a particular config format parser.  This should be called by each
    config plugin on import.
    """

    global _parsers
    _parsers += [ new_parser ]

def parser_by_name(name):
    """
    Return the parser of the given name.
    """
    parsers = [p for p in _parsers if p.name == name]
    if len(parsers):
        return parsers[0]

def find_parser_by_file(input_file):
    """
    Return the parser that is capable of comprehending the given file.
    """
    for p in _parsers:
        if p.identify_file(input_file):
            return p
    return None

def formats():
    """
    Return a list of supported formats.
    """
    return [p.name for p in _parsers]

def input_formats():
    """
    Return a list of supported input formats.
    """
    return [p.name for p in _parsers if p.can_import]

def output_formats():
    """
    Return a list of supported output formats.
    """
    return [p.name for p in _parsers if p.can_export]

def find_input(path, format=None):
    """
    Search for a configuration file automatically. If @format is given,
    then only search using a matching format parser.
    """

    if os.path.isdir(path):
        files = os.listdir(path)

    for p in _parsers:
        if not p.can_identify:
            continue
        if format and format != p.name:
            continue

        if os.path.isfile(path):
            if p.identify_file(path):
                return (path, p.name)
        elif os.path.isdir(path):
            for cfgfile in [ x for x in files if x.endswith(p.suffix) ]:
                if p.identify_file(os.path.join(path, cfgfile)):
                    return (os.path.join(path, cfgfile), p.name)

    raise StandardError(_("Unknown format"))
