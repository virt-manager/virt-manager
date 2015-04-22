
import traceback
import unittest

import virtinst


class CheckPropsTest(unittest.TestCase):
    maxDiff = None

    def testCheckProps(self):
        # pylint: disable=protected-access
        # Access to protected member, needed to unittest stuff

        # If a certain environment variable is set, XMLBuilder tracks
        # every property registered and every one of those that is
        # actually altered. The test suite sets that env variable.
        #
        # test000ClearProps resets the 'set' list, and this test
        # ensures that every property we know about has been touched
        # by one of the above tests.
        fail = [p for p in virtinst.xmlbuilder._allprops
                if p not in virtinst.xmlbuilder._seenprops]
        try:
            self.assertEquals([], fail)
        except AssertionError:
            msg = "".join(traceback.format_exc()) + "\n\n"
            msg += ("This means that there are XML properties that are\n"
                    "untested in the test suite. This could be caused\n"
                    "by a previous test suite failure, or if you added\n"
                    "a new property and didn't extend the test suite.\n"
                    "Look into extending clitest.py and/or xmlparse.py.")
            self.fail(msg)
