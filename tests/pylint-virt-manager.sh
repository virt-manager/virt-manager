#!/bin/sh

# pylint doesn't work well with a file named xxx.py.xxx
cp src/virt-manager.py.in src/_virt-manager
cp src/virt-manager-tui.py.in src/_virt-manager-tui

cd src || exit 1

IGNOREFILES="IPy.py"

##################
# pylint Section #
##################

PYLINT_FILES="virtManager/ _virt-manager virtManagerTui/ _virt-manager-tui"

# Deliberately ignored warnings:
# Don't print pylint config warning
NO_PYL_CONFIG=".*No config file found.*"

# Optional modules that may not be available
UNABLE_IMPORT="Unable to import '(appindicator)"

# os._exit is needed for forked processes.
OS_EXIT="protected member _exit of a client class"

# False positives
MAIN_NONETYPE="main:.*Raising NoneType while.*"
STYLE_ATTACH="Class 'style' has no 'attach' member"
VBOX_PACK="Class 'vbox' has no 'pack_start' member"

# Avahi API may have requirements on callback argument names, so ignore these
# warnings
BTYPE_LIST="(vmmConnect.add_service|vmmConnect.remove_service|vmmConnect.add_conn_to_list)"
BUILTIN_TYPE="${BTYPE_LIST}.*Redefining built-in 'type'"

# Types can't be inferred errors
INFER_LIST="(MenuItem|StatusIcon|.*storagePoolLookupByName)"
INFER_ERRORS="Instance of '${INFER_LIST}.*not be inferred"

# Hacks for testing
TEST_HACKS="protected member (_is_virtinst_test_uri|_open_test_uri)"

# cli/gui diff causes confusion
STUBCLASS="Instance of 'stubclass'"
DBUSINTERFACE="Instance of 'Interface'"

DMSG=""
skipmsg() {
    DMSG="${DMSG},$1"
}

skipchecker() {
    DCHECKERS="${DCHECKERS},$1"
}

skipmsg_checksupport() {
    out=`pylint --list-msgs 2>&1`
    if `echo $out | grep -q $1` ; then
        skipmsg "$1"
    fi
}

# Disabled unwanted messages
skipmsg "C0103"      # C0103: Name doesn't match some style regex
skipmsg "C0111"      # C0111: No docstring
skipmsg "C0301"      # C0301: Line too long
skipmsg "C0302"      # C0302: Too many lines in module
skipmsg "R0201"      # R0201: Method could be a function
skipmsg "W0141"      # W0141: Complaining about 'map' and 'filter'
skipmsg "W0142"      # W0142: *Used * or ** magic*
skipmsg "W0403"      # W0403: Relative imports
skipmsg "W0603"      # W0603: Using the global statement
skipmsg "W0702"      # W0703: No exception type specified
skipmsg "W0703"      # W0703: Catch 'Exception'
skipmsg "W0704"      # W0704: Exception doesn't do anything
skipchecker "Design" # Things like "Too many func arguments",
                     #             "Too man public methods"

# Potentially useful messages, disabled for now
skipmsg "W0511"      # W0511: FIXME and XXX: messages
skipchecker "Similarities"   # Finds duplicate code

# May want to enable this in the future
SHOW_REPORT="n"

AWK=awk
[ `uname -s` = 'SunOS' ] && AWK=nawk


echo "Running pylint"
pylint --ignore=$IGNOREFILES $PYLINT_FILES \
  --additional-builtins=_ \
  --reports=$SHOW_REPORT \
  --output-format=colorized \
  --dummy-variables-rgx="dummy|ignore.*|.*_ignore" \
  --disable=${DMSG}\
  --disable=${DCHECKERS} 2>&1 | \
egrep -ve "$NO_PYL_CONFIG" \
      -ve "$OS_EXIT" \
      -ve "$BUILTIN_TYPE" \
      -ve "$STUBCLASS" \
      -ve "$DBUSINTERFACE" \
      -ve "$MAIN_NONETYPE" \
      -ve "$TEST_HACKS" \
      -ve "$UNABLE_IMPORT" \
      -ve "$STYLE_ATTACH" \
      -ve "$VBOX_PACK" \
      -ve "$INFER_ERRORS" | \
$AWK '\
# Strip out any "*** Module name" lines if we dont list any errors for them
BEGIN { found=0; cur_line="" }
{
    if (found == 1) {
        if ( /\*\*\*/ ) {
            prev_line = $0
        } else {
            print prev_line
            print $0
            found = 0
        }
    } else if ( /\*\*\*/ ) {
        found = 1
        prev_line = $0
    } else {
        print $0
    }
}'

################
# pep8 section #
################

SKIP_PEP8=""
skip_pep8() {
    if [ ! -z ${SKIP_PEP8} ] ; then
        SKIP_PEP8="${SKIP_PEP8},"
    fi
    SKIP_PEP8="${SKIP_PEP8}$1"
}

skip_pep8 "E203"            # Space before : in dictionary defs
skip_pep8 "E221"            # Multiple spaces before operator (warns
                            # about column aligning assigments
skip_pep8 "E241"            # Space after , column alignment nono
skip_pep8 "E261"            # 2 spaces before inline comment?
skip_pep8 "E301"            # 1 blank line between methods
skip_pep8 "E302"            # 2 blank lines between function defs
skip_pep8 "E303"            # Too many blank lines
skip_pep8 "E501"            # Line too long

echo "Running pep8"
pep8 -r --exclude=$IGNOREFILES --ignore $SKIP_PEP8 \
    $PYLINT_FILES

cd - > /dev/null
rm src/_virt-manager
rm src/_virt-manager-tui
