#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free  Software Foundation; either version 2 of the License, or
# (at your option)  any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

import unittest

from virtinst import support

import utils

conn = utils.open_testdriver()

class TestSupport(unittest.TestCase):

    def testSupportCollide(self):
        """
        Verify no support.SUPPORT* have the same value
        """
        valdict = {}
        supportnames = filter(lambda x: x.startswith("SUPPORT"),
                              dir(support))

        for supportname in supportnames:
            checkval = int(getattr(support, supportname))

            if checkval in valdict.values():
                collidename = "unknown?"
                for key, val in valdict.items():
                    if val == checkval:
                        collidename = key
                        break

                raise AssertionError("%s == %s" % (collidename, supportname))

            valdict[supportname] = checkval

if __name__ == "__main__":
    unittest.main()
