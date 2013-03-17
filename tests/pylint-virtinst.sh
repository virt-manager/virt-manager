#!/bin/sh

FILES="setup.py tests/ virt-install virt-image virt-clone virt-convert virtinst/ virtconv virtconv/parsers/*.py"

# Don't print pylint config warning
NO_PYL_CONFIG=".*No config file found.*"

# Exceptions: deliberately ignore these regex

# False positive: using the private excepthook is needed for custom exception
# handler
EXCEPTHOOK='__excepthook__'

# Following functions are in the public api which have argument names that
# override builtin 'type'.
BUILTIN_TYPE="(StoragePool.__init__|randomMAC|Capabilities.guestForOSType|acquireKernel|acquireBootDisk|DistroInstaller.__init__|PXEInstaller.__init__|Guest.list_os_variants|Guest.get_os_type_label|Guest.get_os_variant_label|FullVirtGuest.__init__|VirtualNetworkInterface.__init__|VirtualGraphics.__init__|Installer.__init__|Guest.__init__|LiveCDInstaller.__init__|ParaVirtGuest.__init__|VirtOptionParser.print_help|get_max_vcpus|setupLogging.exception_log|VirtualDisk.__init__|disk.__init__|netdev.__init__)|guest_lookup"
BTYPE_TYPE="${BUILTIN_TYPE}.*Redefining built-in 'type'"

# Built-in type 'format'
BUILTIN_FORMAT="(*Pool.__init__|*Volume.__init__|find_input)"
BTYPE_FORMAT="${BUILTIN_FORMAT}.*Redefining built-in 'format'"

# Following functions are in the public api which have argument names that
# override builtin 'str'.
BUILTIN_STR="(xml_escape)"
BTYPE_STR="${BUILTIN_STR}.*Redefining built-in 'str'"

# Following functions are in the public api which have argument names that
# override builtin 'str'.
BUILTIN_FILE="(VirtOptionParser.print_help)"
BTYPE_FILE="${BUILTIN_FILE}.*Redefining built-in 'file'"

# Using os._exit is required in forked processes
USE_OF__EXIT="member _exit"

# False positive: we install the _ function in the builtin namespace, but
# pylint doesn't pick it up
UNDEF_GETTEXT="Undefined variable '_'"

# Don't complain about 'ucred' or 'selinux' not being available
UCRED="import 'ucred'"
SELINUX="import 'selinux'"
COVERAGE="import 'coverage'"
OLDSELINUX="'selinux' has no "
HASHLIB_CONFUSION="Module 'hashlib' has no 'sha.*"

# Public api error
VD_MISMATCHED_ARGS="get_xml_config.*Arguments number differs"

# Pylint getting confused with XMLBuilder complication
XMLBUILDER_CONFUSION="xml_property.*protected member _xml.*"

# urltest needs access to protected members for testing purposes
URLTEST_ACCESS="TestURLFetch.*Access to a protected member"

# We use some hacks in the test driver to simulate remote libvirt URIs
TEST_HACKS="TestClone.*protected member _util|testQEMUDriverName.*protected member _get_uri|Access to a protected member _util"

# Scattered examples of legitimately unused arguments
UNUSED_ARGS="(SuseDistro|SolarisDistro|NetWareDistro).isValidStore.*Unused argument 'progresscb'|.*Installer.prepare.*Unused argument|post_install_check.*Unused argument 'guest'|Guest.__init__.*Unused argument 'type'|_get_bootdev"

# Outside __init__ checks throw false positives with distutils custom commands
# tests.storage also invokes false positives using hasattr
OUTSIDE_INIT="(.*Test.*|.*createPool.*)outside __init__"

# pylint complains about some of the subclass funkiness in chardev classes
CHAR_SUBCLASS=".*VirtualCharDevice' has no '(source_mode|source_path)' member.*|.*Method '_char_xml' is abstract in class 'VirtualCharDevice'.*"

# FIXME: Everything skipped below are all bugs

# Libvirt connect() method is broken for getting an objects connection, this
# workaround is required for now
ACCESS__CONN="Access to a protected member _conn"

# There isn't a clean API way to access this functions from the API, but
# they provide info that is needed. These need need to be fixed.
PROT_MEM_BUGS="protected member (_lookup_osdict_key|_OS_TYPES|_prepare_install|_create_devices|_cleanup_install|_install_bootconfig|_channels|_get_caps|_open_test_uri|_set_rhel6)|'virtinst.FullVirtGuest' has no '_OS_TYPES'"


# This doesn't belong here, but makes sure I don't break the test suite :)
if grep -qIR crobinso tests --exclude pylint\* ; then
    echo "Test suite borked:"
    grep -IR crobinso tests --exclude pylint\*
    exit 1
fi

DMSG=""
skipmsg() {
    DMSG="${DMSG},$1"
    }

DCHECKERS=""
skipchecker() {
    DCHECKERS="${DCHECKERS},$1"
}

skipmsg_checksupport() {
    out=`pylint --list-msgs 2>&1`
    if `echo $out | grep -q $1` ; then
        echo "adding!"
        skipmsg "$1"
    fi
}

# Disabled Messages:
skipmsg "C0103"  # C0103: Name doesn't match some style regex
skipmsg "C0111"  # C0111: No docstring
skipmsg "C0301"  # C0301: Line too long
skipmsg "C0302"  # C0302: Too many lines in module
skipmsg "W0105"  # W0105: String statement has no effect (annoying for docs)
skipmsg "W0141"  # W0141: Complaining about 'map' and 'filter'
skipmsg "W0142"  # W0142: Use of * or **
skipmsg "W0603"  # W0603: Using the global statement
skipmsg "W0703"  # W0703: Catch 'Exception'
skipmsg "W0704"  # W0704: Exception doesn't do anything
skipmsg "W0702"  # W0702: No exception type specified
skipmsg "R0201"  # R0201: Method could be a function
skipchecker "Design" # Things like "Too many func arguments",
                    #             "Too man public methods"

# Possibly useful at some point
skipmsg "W0403"  # W0403: Relative imports
skipmsg "W0511"  # W0511: FIXME and XXX: messages
skipmsg "R0401"  # R0401: Cyclic imports
skipchecker "Similarities"   # Finds duplicate code

# Not supported in many pylint versions
# Put new messages here with skipmsg_checksupport


AWK=awk
[ `uname -s` = 'SunOS' ] && AWK=nawk

pylint --ignore=coverage.py, $FILES \
  --reports=n \
  --output-format=colorized \
  --dummy-variables-rgx="dummy|ignore*|.*ignore" \
  --disable=${DMSG} \
  --disable=${DCHECKERS} 2>&1 | \
  egrep -ve "$EXCEPTHOOK" \
        -ve "$NO_PYL_CONFIG" \
        -ve "$BTYPE_TYPE" \
        -ve "$BTYPE_FILE" \
        -ve "$BTYPE_STR" \
        -ve "$BTYPE_FORMAT" \
        -ve "$UCRED" \
        -ve "$SELINUX" \
        -ve "$COVERAGE" \
        -ve "$OLDSELINUX" \
        -ve "$HASHLIB_CONFUSION" \
        -ve "$USE_OF__EXIT" \
        -ve "$UNDEF_GETTEXT" \
        -ve "$VD_MISMATCHED_ARGS" \
        -ve "$ACCESS__CONN" \
        -ve "$URLTEST_ACCESS" \
        -ve "$UNUSED_ARGS" \
        -ve "$TEST_HACKS" \
        -ve "$PROT_MEM_BUGS" \
        -ve "$CHAR_SUBCLASS" \
        -ve "$XMLBUILDER_CONFUSION" \
        -ve "$OUTSIDE_INIT" | \
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

skip_pep8 "E201"            # Spaces after [, before ]
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
pep8 -r --ignore $SKIP_PEP8 $FILES
