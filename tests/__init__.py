# Copyright (C) 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import imp
import os

# Need to do this before any tests or virtinst import
os.environ["VIRTINST_TEST_SUITE"] = "1"
# Need to do this before we import argcomplete
os.environ.pop("_ARC_DEBUG", None)

# pylint: disable=wrong-import-position
from virtinst import buildconfig
from virtinst import log, reset_logging
# This sets all the cli bits back to their defaults
imp.reload(buildconfig)

from tests import utils

# pylint: disable=ungrouped-imports
from virtinst import virtinstall
from virtinst import virtclone
from virtinst import virtxml


def setup_logging():
    import logging
    reset_logging()

    fmt = "%(levelname)-8s %(message)s"
    streamHandler = logging.StreamHandler()
    streamHandler.setFormatter(logging.Formatter(fmt))
    if utils.TESTCONFIG.debug:
        streamHandler.setLevel(logging.DEBUG)
        log.setLevel(logging.DEBUG)
    else:
        streamHandler.setLevel(logging.ERROR)
        log.setLevel(logging.ERROR)
    log.addHandler(streamHandler)
