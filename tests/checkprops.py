# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import logging
import traceback
import unittest

import virtinst


class CheckPropsTest(unittest.TestCase):
    maxDiff = None

    def testCheckProps(self):
        # pylint: disable=protected-access
        # Access to protected member, needed to unittest stuff

        skip = False
        try:
            # Accessing an internal detail of unittest, but it's only
            # to prevent incorrect output in the case that other tests
            # failed or were skipped, which can give a false postive here
            result = self._outcome.result
            skip = bool(result.errors or result.failures or result.skipped)
        except Exception:
            logging.debug("unittest skip hack failed", exc_info=True)
        if skip:
            self.skipTest("skipping as other tests failed/skipped")

        # If a certain environment variable is set, XMLBuilder tracks
        # every property registered and every one of those that is
        # actually altered. The test suite sets that env variable.
        #
        # testClearProps resets the 'set' list, and this test
        # ensures that every property we know about has been touched
        # by one of the above tests.
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
