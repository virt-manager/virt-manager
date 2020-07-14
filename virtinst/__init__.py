# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

# pylint: disable=wrong-import-position

import gi
gi.require_version('Libosinfo', '1.0')

from virtinst.buildconfig import BuildConfig


def _setup_i18n():
    import gettext
    import locale

    try:
        locale.setlocale(locale.LC_ALL, '')
    except Exception:  # pragma: no cover
        # Can happen if user passed a bogus LANG
        pass

    gettext.install("virt-manager", BuildConfig.gettext_dir,
                    names=["ngettext"])
    gettext.bindtextdomain("virt-manager", BuildConfig.gettext_dir)


def _set_libvirt_error_handler():
    """
    Ignore libvirt error reporting, we just use exceptions
    """
    import libvirt

    def libvirt_callback(userdata, err):
        ignore = userdata
        ignore = err
    ctx = None
    libvirt.registerErrorHandler(libvirt_callback, ctx)


_setup_i18n()
_set_libvirt_error_handler()


from virtinst import xmlutil
from virtinst.uri import URI
from virtinst.osdict import OSDB

from virtinst.domain import *  # pylint: disable=wildcard-import

from virtinst.capabilities import Capabilities
from virtinst.domcapabilities import DomainCapabilities
from virtinst.network import Network
from virtinst.nodedev import NodeDevice
from virtinst.storage import StoragePool, StorageVolume

from virtinst.devices import *  # pylint: disable=wildcard-import

from virtinst.install.installer import Installer

from virtinst.guest import Guest
from virtinst.cloner import Cloner
from virtinst.snapshot import DomainSnapshot

from virtinst.connection import VirtinstConnection

from virtinst.logger import log, reset_logging
