#!/bin/sh

set -e

# Make things clean.

make -k distclean ||:
rm -rf MANIFEST blib

# Make makefiles.

autoreconf -i

rm -rf build
mkdir build
cd build
../configure --prefix=$AUTOBUILD_INSTALL_ROOT

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

