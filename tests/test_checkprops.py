# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import traceback

import pytest

import tests.utils

import virtinst


def _skipIfTestsFailed():
    if tests.utils.TESTCONFIG.skip_checkprops:
        pytest.skip("Other tests failed or were skipped, don't do prop checks")


def testCheckXMLBuilderProps():
    """
    If a certain environment variable is set, XMLBuilder tracks
    every property registered and every one of those that is
    actually altered. The test suite sets that env variable.
    If no tests failed or were skipped, we check to ensure the
    test suite is tickling every XML property
    """
    _skipIfTestsFailed()

    # pylint: disable=protected-access
    fail = [p for p in virtinst.xmlbuilder._allprops
            if p not in virtinst.xmlbuilder._seenprops]
    msg = None
    try:
        if fail:
            raise RuntimeError(str(fail))
    except Exception:
        msg = "".join(traceback.format_exc()) + "\n\n"
        msg += ("This means that there are XML properties that are\n"
                "untested in the test suite. This could be caused\n"
                "by a previous test suite failure, or if you added\n"
                "a new property and didn't extend the test suite.\n"
                "Look into extending test_cli.py and/or test_xmlparse.py.")

    if msg:
        pytest.fail(msg)


def testCheckCLISuboptions():
    """
    Track which command line suboptions and aliases we actually hit with
    the test suite.
    """
    _skipIfTestsFailed()

    # pylint: disable=protected-access
    from virtinst import cli
    unchecked = cli._SuboptChecker.get_unseen()
    if unchecked:
        msg = "\n\n"
        msg += "\n".join(sorted(a for a in unchecked)) + "\n\n"
        msg += ("These command line arguments or aliases are not checked\n"
               "in the test suite. Please test them.\n"
               "Total unchecked arguments: %s" % len(unchecked))
        pytest.fail(msg)
