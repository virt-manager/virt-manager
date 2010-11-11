#!/bin/sh

# pylint doesn't work well with a file named xxx.py.xxx
cp src/virt-manager.py.in src/_virt-manager

cd src || exit 1

IGNOREFILES="IPy.py"
FILES="virtManager/ _virt-manager"

# Deliberately ignored warnings:
# Don't print pylint config warning
NO_PYL_CONFIG=".*No config file found.*"

# The gettext function is installed in the builtin namespace
GETTEXT_VAR="Undefined variable '_'"

# These all work fine and are legit, just false positives
GOBJECT_VAR="has no '__gobject_init__' member"
GOBJECT_INIT="__init__ method from base class 'GObject' is not called"
EMIT_VAR="has no 'emit' member"
ERROR_VBOX="Class 'vbox' has no 'pack_start' member"
EXCEPTHOOK="no '__excepthook__' member"
CONNECT_VAR="no 'connect' member"
DISCONNECT_VAR="no 'disconnect' member"
UNABLE_IMPORT="Unable to import '(gtk.gdk.*|sparkline|appindicator)"

# os._exit is needed for forked processes.
OS_EXIT="protected member _exit of a client class"

# Avahi API may have requirements on callback argument names, so ignore these
# warnings
BTYPE_LIST="(vmmConnect.add_service|vmmConnect.remove_service|vmmConnect.add_conn_to_list)"
BUILTIN_TYPE="${BTYPE_LIST}.*Redefining built-in 'type'"

# Bogus 'unable to import' warnings


DMSG=""
addmsg() {
    DMSG="${DMSG},$1"
}

addchecker() {
    DCHECKERS="${DCHECKERS},$1"
}

addmsg_support() {
    out=`pylint --list-msgs`
    if `echo $out | grep -q $1` ; then
        addmsg "$1"
    fi
}

# Disabled unwanted messages
addmsg "C0103"      # C0103: Name doesn't match some style regex
addmsg "C0111"      # C0111: No docstring
addmsg "C0301"      # C0301: Line too long
addmsg "C0302"      # C0302: Too many lines in module
addmsg "C0324"      # C0324: *Comma not followed by a space*
addmsg "R0201"      # R0201: Method could be a function
addmsg "W0105"      # W0105: String statement has no effect
addmsg "W0141"      # W0141: Complaining about 'map' and 'filter'
addmsg "W0142"      # W0142: *Used * or ** magic*
addmsg "W0403"      # W0403: Relative imports
addmsg "W0603"      # W0603: Using the global statement
addmsg "W0702"      # W0703: No exception type specified
addmsg "W0703"      # W0703: Catch 'Exception'
addmsg "W0704"      # W0704: Exception doesn't do anything

# Potentially useful messages, disabled for now
addmsg "C0322"      # C0322: *Operator not preceded by a space*
addmsg "C0323"      # C0323: *Operator not followed by a space*
addmsg "W0511"      # W0511: FIXME and XXX: messages
addmsg "W0613"      # W0613: Unused arguments
addmsg_support "W6501"      # W6501: Using string formatters in logging message
                            #        (see help message for info)

# Disabled Checkers:
addchecker "Design"         # Things like "Too many func arguments",
                            #             "Too man public methods"
addchecker "Similarities"   # Finds duplicate code (enable this later?)

# May want to enable this in the future
SHOW_REPORT="n"

AWK=awk
[ `uname -s` = 'SunOS' ] && AWK=nawk

pylint --ignore=IPy.py $FILES \
  --reports=$SHOW_REPORT \
  --output-format=colorized \
  --dummy-variables-rgx="dummy|ignore*" \
  --disable=${DMSG}\
  --disable=${DCHECKERS} 2>&1 | \
  egrep -ve "$NO_PYL_CONFIG" \
        -ve "$GOBJECT_VAR" \
        -ve "$GOBJECT_INIT" \
        -ve "$EMIT_VAR" \
        -ve "$CONNECT_VAR" \
        -ve "$DISCONNECT_VAR" \
        -ve "$GETTEXT_VAR" \
        -ve "$OS_EXIT" \
        -ve "$BUILTIN_TYPE" \
        -ve "$ERROR_VBOX" \
        -ve "$UNABLE_IMPORT" \
        -ve "$EXCEPTHOOK" | \
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

cd - > /dev/null
rm src/_virt-manager
