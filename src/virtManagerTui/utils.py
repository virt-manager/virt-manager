# definedomain.py - Copyright (C) 2009 Red Hat, Inc.
# Written by Darryl L. Pierce <dpierce@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.  A copy of the GNU General Public License is
# also available at http://www.gnu.org/copyleft/gpl.html.

import re

def string_is_not_blank(value):
    if len(value) > 0: return True
    return False

def string_has_no_spaces(value):
    if re.match("^[a-zA-Z0-9_]*$", value):
        return True
    return False

def size_as_mb_or_gb(size):
    '''Takes a size value in bytes and returns it as either a
    value in megabytes or gigabytes.'''
    if size / 1024.0**3 < 1.0:
        result = "%0.2f MB" % (size / 1024.0**2)
    else:
        result = "%0.2f GB" % (size / 1024.0**3)
    return result
