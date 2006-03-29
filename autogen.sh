#!/bin/sh

set -e

# Make makefiles.

autoreconf -i

test -d build && rm -rf build
mkdir build
cd build
../configure $@ 

