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

import pkgutil
import imp
import os
import sys
import gettext

gettext.bindtextdomain("virtinst")
_gettext = lambda m: gettext.dgettext("virtinst", m)

try:
    import _config
except ImportError:
    print "virtconv: Please run 'python setup.py build' in the source"
    print "          directory before using the code."
    sys.exit(1)
__version__ = _config.__version__
__version_info__ = _config.__version_info__

parsers_path = [os.path.join(__path__[0], "parsers/")]

# iter_modules is only in Python 2.5, sadly
parser_names = [ "vmx", "virtimage", "ovf"]

if hasattr(pkgutil, "iter_modules"):
    parser_names = []
    for ignore, name, ignore in pkgutil.iter_modules(parsers_path):
        parser_names += [ name ]

for name in parser_names:
    filename, pathname, desc = imp.find_module(name, parsers_path)
    imp.load_module(name, filename, pathname, desc)
