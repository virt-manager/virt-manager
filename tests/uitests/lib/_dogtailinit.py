# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import signal
import sys
import warnings

# Dogtail is noisy with GTK and GI deprecation warnings
warnings.simplefilter("ignore")

# Ignores pylint error since dogtail doesn't specify this
import gi
gi.require_version('Atspi', '2.0')

import dogtail.config
import dogtail.utils

# find() backoff handling
dogtail.config.config.searchBackoffDuration = .1
dogtail.config.config.searchCutoffCount = 20

# Use .1 second delay between each action (default 1)
dogtail.config.config.actionDelay = .1
dogtail.config.config.defaultDelay = .1

# Turn off needlessly noisy debugging
DOGTAIL_DEBUG = False
dogtail.config.config.logDebugToStdOut = DOGTAIL_DEBUG
dogtail.config.config.logDebugToFile = False

# Dogtail screws with the default excepthook, disabling output if we turned
# off logging, so fix it
sys.excepthook = sys.__excepthook__

# dogtail.utils.Blinker creates a GLib.MainLoop on module import, which
# screws up SIGINT handling somehow. This reregisters the
# unittest.installHandler magic
signal.signal(signal.SIGINT, signal.getsignal(signal.SIGINT))

# Needed so labels are matched in english
os.environ['LANG'] = 'en_US.UTF-8'

os.environ.pop("VIRTINST_TEST_SUITE", None)

if not dogtail.utils.isA11yEnabled():
    print("Enabling gsettings accessibility")
    dogtail.utils.enableA11y()

# This will trigger an error if accessibility isn't enabled
import dogtail.tree  # pylint: disable=wrong-import-order,ungrouped-imports
