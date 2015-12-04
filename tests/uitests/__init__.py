import os
import sys
import warnings

# Dogtail is noisy with GTK and GI deprecation warnings
warnings.simplefilter("ignore")

# Ignores pylint error since dogtail doesn't specify this
import gi
gi.require_version('Atspi', '2.0')

import dogtail.config

from tests.uitests import utils

# Perform 5 search attempts if a widget lookup fails (default 20)
dogtail.config.config.searchCutoffCount = 5

# Use .4 second delay between each action (default 1)
dogtail.config.config.actionDelay = .1

# Turn off needlessly noisy debugging
DOGTAIL_DEBUG = False
dogtail.config.config.logDebugToStdOut = DOGTAIL_DEBUG
dogtail.config.config.logDebugToFile = False

# Dogtail screws with the default excepthook, disabling output if we turned
# off logging, so fix it
sys.excepthook = sys.__excepthook__

# Needed so labels are matched in english
os.environ['LANG'] = 'en_US.UTF-8'
