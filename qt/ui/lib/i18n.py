import gettext
import os

DOMAIN = "virt-manager"

localedir = "/usr/share/locale"
if hasattr(os, 'readlink'):
    localedir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "share", "locale")

try:
    t = gettext.translation(DOMAIN, localedir, fallback=False)
except (FileNotFoundError, Exception):
    t = gettext.NullTranslations()

_ = t.gettext
ngettext = t.ngettext
