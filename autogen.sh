#!/bin/sh

set -e
set -x

rm -f config.status

# Make makefiles.
autoreconf --force --install --verbose
intltoolize --force --copy --automake

./configure $@
