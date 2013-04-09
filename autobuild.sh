#!/bin/sh

set -v
set -e

if [ -z "$AUTOBUILD_INSTALL_ROOT" ] ; then
    echo "This script is only meant to be used with an autobuild server."
    echo "Please see INSTALL for build instructions."
    exit 1
fi

rm -rf MANIFEST dist/*

# support version-id changes
export AUTOBUILD_OVERRIDE_VERSION=y

python setup.py sdist

python setup.py build
python setup.py test
python setup.py install --root=$AUTOBUILD_INSTALL_ROOT

which /usr/bin/rpmbuild > /dev/null 2>&1 || exit 0

if [ -n "$AUTOBUILD_COUNTER" ]; then
    EXTRA_RELEASE=".auto$AUTOBUILD_COUNTER"
else
    NOW=`date +"%s"`
    EXTRA_RELEASE=".$USER$NOW"
fi
rpmbuild --nodeps --define "extra_release $EXTRA_RELEASE" -ta --clean dist/*.tar.gz

