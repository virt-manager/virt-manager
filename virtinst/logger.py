# Copyright 2019 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging

# This is exported by virtinst/__init__.py
log = logging.getLogger("virtinst")


def reset_logging():
    rootLogger = logging.getLogger()

    # Undo early logging
    for handler in rootLogger.handlers:
        rootLogger.removeHandler(handler)

    # Undo any logging on our log handler. Needed for test suite
    for handler in log.handlers:
        log.removeHandler(handler)
