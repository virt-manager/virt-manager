# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

import pytest


def pytest_addoption(parser):
    parser.addoption("--uitests", action="store_true", default=False,
            help="Run dogtail UI tests")


def pytest_ignore_collect(path, config):
    uitests_requested = config.getoption("--uitests")

    # Unless explicitly requested, ignore these tests
    if "test_dist.py" in str(path):
        return True
    if "test_urls.py" in str(path):
        return True
    if "test_inject.py" in str(path):
        return True

    uitest_file = "tests/uitests" in str(path)
    if uitest_file and not uitests_requested:
        return True
    if not uitest_file and uitests_requested:
        return True


def pytest_collection_modifyitems(config, items):
    def find_items(basename):
        return [i for i in items
                if os.path.basename(i.fspath) == basename]

    # Move test_cli cases to the end, because they are slow
    # Move test_checkprops to the very end, because it needs to run
    #   after everything else to give proper results
    cliitems = find_items("test_cli.py")
    chkitems = find_items("test_checkprops.py")

    for i in cliitems + chkitems:
        items.remove(i)
        items.append(i)

    if not find_items("test_urls.py"):
        # Don't setup urlfetcher mocking for test_urls.py
        # All other tests need it
        import tests.urlfetcher_mock
        tests.urlfetcher_mock.setup_mock()

    if find_items("test_inject.py"):
        if not config.getoption("--capture") == "no":
            pytest.fail("test_inject.py requires `pytest --capture=no`")
