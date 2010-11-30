#!/bin/sh

set -e

if [ -z "$AUTOBUILD_INSTALL_ROOT" ] ; then
    echo "This script is only meant to be used with an autobuild server."
    echo "Please see INSTALL for build instructions."
    exit 1
fi

# Make things clean.

make -k distclean ||:
rm -rf MANIFEST blib

# Make makefiles.

./autogen.sh --prefix=$AUTOBUILD_INSTALL_ROOT
cd build
make
make install

rm -f *.tar.gz
make dist

if [ -f /usr/bin/rpmbuild ]; then
  if [ -n "$AUTOBUILD_COUNTER" ]; then
    EXTRA_RELEASE=".auto$AUTOBUILD_COUNTER"
  else
    NOW=`date +"%s"`
    EXTRA_RELEASE=".$USER$NOW"
  fi
  rpmbuild --nodeps --define "extra_release $EXTRA_RELEASE" -ta --clean *.tar.gz
fi

