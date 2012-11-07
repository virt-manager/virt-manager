#!/bin/sh

set -e
set -x

# Remove config.status, so rerunning autogen.sh regenerates everything
rm -f config.status

# Touch this to work around gettext issues following intltool I18N-HOWTO:
# http://lists.gnu.org/archive/html/bug-gettext/2011-10/msg00012.html
mkdir -p build-aux/m4
touch build-aux/config.rpath

autoreconf --force --install --verbose
intltoolize --force --copy --automake

./configure "$@"
