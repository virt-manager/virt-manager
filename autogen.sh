#!/bin/sh

set -e

# Hack around autoconf wierdness. Need to figure out what's really wrong
touch config.rpath

# Make makefiles.
rm -f config.status
intltoolize --automake --copy --force
perl -i -p -e 's,^DATADIRNAME.*$,DATADIRNAME = share,' po/Makefile.in.in
perl -i -p -e 's,^GETTEXT_PACKAGE.*$,GETTEXT_PACKAGE = virt-manager,' po/Makefile.in.in
aclocal -I m4
libtoolize
automake -a
autoconf

test -d build && rm -rf build
mkdir build
cd build
../configure $@ 

