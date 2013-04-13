#
# Copyright (C) 2011 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
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

# This module provides a simple way to trace any activity on a specific
# python class or module. The trace output is logged using the regular
# logging infrastructure. Invoke this with virt-manager --trace-libvirt

import logging
import time
import re
import traceback

from types import FunctionType
from types import ClassType
from types import MethodType


def generate_wrapper(origfunc, name, do_tb):
    def newfunc(*args, **kwargs):
        tb = do_tb and ("\n%s" % "".join(traceback.format_stack())) or ""
        logging.debug("TRACE %s: %s %s %s%s",
                      time.time(), name, args, kwargs, tb)
        return origfunc(*args, **kwargs)

    return newfunc


def wrap_func(module, funcobj, tb):
    name = funcobj.__name__
    logging.debug("wrapfunc %s %s", funcobj, name)

    newfunc = generate_wrapper(funcobj, name, tb)
    setattr(module, name, newfunc)


def wrap_method(classobj, methodobj, tb):
    name = methodobj.__name__
    fullname = classobj.__name__ + "." + name
    logging.debug("wrapmeth %s", fullname)

    newfunc = generate_wrapper(methodobj, fullname, tb)
    setattr(classobj, name, newfunc)


def wrap_class(classobj, tb):
    logging.debug("wrapclas %s %s", classobj, classobj.__name__)

    for name in dir(classobj):
        obj = getattr(classobj, name)
        if type(obj) is MethodType:
            wrap_method(classobj, obj, tb)


def wrap_module(module, regex=None, tb=False):
    for name in dir(module):
        if regex and not re.match(regex, name):
            continue
        obj = getattr(module, name)
        if type(obj) is FunctionType:
            wrap_func(module, obj, tb)
        if type(obj) is ClassType:
            wrap_class(obj, tb)
