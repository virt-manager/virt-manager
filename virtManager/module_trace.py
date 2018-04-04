# Copyright (C) 2011, 2013 Red Hat, Inc.
# Copyright (C) 2011 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

# This module provides a simple way to trace any activity on a specific
# python class or module. The trace output is logged using the regular
# logging infrastructure. Invoke this with virt-manager --trace-libvirt

import logging
import re
import threading
import time
import traceback

from types import FunctionType
from types import MethodType


def generate_wrapper(origfunc, name):
    # This could be used as generic infrastructure, but it has hacks for
    # identifying places where libvirt hits the network from the main thread,
    # which causes UI blocking on slow network connections.

    def newfunc(*args, **kwargs):
        threadname = threading.current_thread().name
        is_main_thread = (threading.current_thread().name == "MainThread")

        # These APIs don't hit the network, so we might not want to see them.
        is_non_network_libvirt_call = (name.endswith(".name") or
            name.endswith(".UUIDString") or
            name.endswith(".__init__") or
            name.endswith(".__del__") or
            name.endswith(".connect") or
            name.startswith("libvirtError"))

        if not is_non_network_libvirt_call and is_main_thread:
            tb = ""
            if is_main_thread:
                tb = "\n%s" % "".join(traceback.format_stack())
            logging.debug("TRACE %s: thread=%s: %s %s %s%s",
                          time.time(), threadname, name, args, kwargs, tb)
        return origfunc(*args, **kwargs)

    return newfunc


def wrap_func(module, funcobj):
    name = funcobj.__name__
    logging.debug("wrapfunc %s %s", funcobj, name)

    newfunc = generate_wrapper(funcobj, name)
    setattr(module, name, newfunc)


def wrap_method(classobj, methodobj):
    name = methodobj.__name__
    fullname = classobj.__name__ + "." + name
    logging.debug("wrapmeth %s", fullname)

    newfunc = generate_wrapper(methodobj, fullname)
    setattr(classobj, name, newfunc)


def wrap_class(classobj):
    logging.debug("wrapclas %s %s", classobj, classobj.__name__)

    for name in dir(classobj):
        obj = getattr(classobj, name)
        if isinstance(obj, MethodType):
            wrap_method(classobj, obj)


def wrap_module(module, regex=None):
    for name in dir(module):
        if regex and not re.match(regex, name):
            continue
        obj = getattr(module, name)
        if isinstance(obj, FunctionType):
            wrap_func(module, obj)
        if isinstance(obj, type):
            wrap_class(obj)
