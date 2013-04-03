#!/bin/sh

set -v
set -e

if [ -z "$AUTOBUILD_INSTALL_ROOT" ] ; then
    echo "This script is only meant to be used with an autobuild server."
    echo "Please see INSTALL for build instructions."
    exit 1
fi

python setup.py build
python setup.py test
python setup.py install --prefix=$AUTOBUILD_INSTALL_ROOT
python setup.py sdist

which /usr/bin/rpmbuild > /dev/null 2>&1 || exit 0

if [ -n "$AUTOBUILD_COUNTER" ]; then
    EXTRA_RELEASE=".auto$AUTOBUILD_COUNTER"
else
    NOW=`date +"%s"`
    EXTRA_RELEASE=".$USER$NOW"
fi
rpmbuild --nodeps --define "extra_release $EXTRA_RELEASE" -ta --clean *.tar.gz

