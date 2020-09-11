# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import pytest


@pytest.fixture
def app():
    """
    Custom pytest fixture to a VMMDogtailApp instance to the testcase
    """
    from .lib.app import VMMDogtailApp
    testapp = VMMDogtailApp()
    try:
        yield testapp
    finally:
        testapp.stop()
