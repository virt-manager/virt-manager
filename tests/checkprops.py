# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import traceback
import unittest

import virtinst
from virtinst import log


_do_skip = None


class CheckPropsTest(unittest.TestCase):
    maxDiff = None

    def _skipIfTestsFailed(self):
        # pylint: disable=protected-access
        # Access to protected member, needed to unittest stuff
        global _do_skip
        if _do_skip is None:
            _do_skip = False
            try:
                # Accessing an internal detail of unittest, but it's only
                # to prevent incorrect output in the case that other tests
                # failed or were skipped, which can give a false positive here
                result = self._outcome.result
                _do_skip = bool(
                        result.errors or result.failures or result.skipped)
            except Exception:
                log.debug("unittest skip hack failed", exc_info=True)

        if _do_skip:
            self.skipTest("skipping as other tests failed/skipped")

    def testCheckXMLBuilderProps(self):
        """
        If a certain environment variable is set, XMLBuilder tracks
        every property registered and every one of those that is
        actually altered. The test suite sets that env variable.
        If no tests failed or were skipped, we check to ensure the
        test suite is tickling every XML property
        """
        self._skipIfTestsFailed()

        # pylint: disable=protected-access
        fail = [p for p in virtinst.xmlbuilder._allprops
                if p not in virtinst.xmlbuilder._seenprops]
        msg = None
        try:
            self.assertEqual([], fail)
        except AssertionError:
            msg = "".join(traceback.format_exc()) + "\n\n"
            msg += ("This means that there are XML properties that are\n"
                    "untested in the test suite. This could be caused\n"
                    "by a previous test suite failure, or if you added\n"
                    "a new property and didn't extend the test suite.\n"
                    "Look into extending clitest.py and/or xmlparse.py.")

        if msg:
            self.fail(msg)

    def testCheckCLISuboptions(self):
        """
        Track which command line suboptions and aliases we actually hit with
        the test suite.
        """
        self._skipIfTestsFailed()

        # pylint: disable=protected-access
        from virtinst import cli
        unchecked = cli._SuboptChecker.get_unseen()
        if unchecked:
            msg = "\n\n"
            msg += "\n".join(sorted(a for a in unchecked)) + "\n\n"
            msg += ("These command line arguments or aliases are not checked\n"
                   "in the test suite. Please test them.\n"
                   "Total unchecked arguments: %s" % len(unchecked))
            self.fail(msg)
