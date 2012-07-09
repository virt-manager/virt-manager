#!/bin/sh

set -e
set -x

rm -f config.status

# Make makefiles.
autoreconf --install --force
intltoolize --automake --copy --force
autoreconf

./configure $@
