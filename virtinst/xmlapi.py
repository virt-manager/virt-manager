#
# XML API wrappers
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

from .logger import log
from .xmletree import ETreeAPI
from .xmllibxml2 import Libxml2API

_backend = os.environ.get("VIRTINST_XML_BACKEND")
log.debug("VIRTINST_XML_BACKEND=%s", _backend)


def _get_default():  # pragma: no cover
    if _backend == "libxml2":
        return Libxml2API
    elif _backend == "etree":
        return ETreeAPI

    try:
        import libxml2

        _ignore = libxml2
        return Libxml2API
    except ImportError as e:
        log.debug("libxml2 import error: %s", e)
        return ETreeAPI


XMLAPI = _get_default()
log.debug("Using XMLAPI=%s", XMLAPI)
