# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os

import pytest

import tests
from tests.utils import TESTCONFIG


def pytest_addoption(parser):
    parser.addoption("--uitests", action="store_true", default=False,
            help="Run dogtail UI tests")

    parser.addoption("--regenerate-output",
            action="store_true", default=False,
            help="Regenerate test output")

    # test_urls options
    parser.addoption('--urls-skip-libosinfo',
            action="store_true", default=False,
            help=("For test_urls.py, "
                  "Don't use libosinfo for media/tree detection, "
                  "Use our internal detection logic."))
    parser.addoption("--urls-force-libosinfo",
            action="store_true", default=False,
            help=("For test_urls.py, Only use libosinfo for "
                  "media/tree detection. This will skip "
                  "some cases that are known not to work, "
                  "like debian/ubuntu tree detection."))
    parser.addoption("--urls-iso-only",
            action="store_true", default=False,
            help=("For test_urls.py, Only run iso tests."))
    parser.addoption("--urls-url-only",
            action="store_true", default=False,
            help=("For test_urls.py, Only run url tests"))


def pytest_ignore_collect(path, config):
    uitests_requested = config.getoption("--uitests")

    # Default --uitests to --verbosity=2
    if uitests_requested:
        config.option.verbose = max(2, config.option.verbose)

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
        from tests import urlfetcher_mock
        urlfetcher_mock.setup_mock()

    if find_items("test_inject.py"):
        if not config.getoption("--capture") == "no":
            pytest.fail("test_inject.py requires `pytest --capture=no`")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    Hooks into test reporting so we can track if any tests didn't
    pass, so we can skip checkprops checks which require everything to pass.
    """
    ignore = item
    ignore = call
    outcome = yield
    testreport = outcome.get_result()
    if not testreport.passed:
        TESTCONFIG.skip_checkprops = True


def pytest_configure(config):
    TESTCONFIG.url_iso_only = config.getoption("--urls-iso-only")
    TESTCONFIG.url_only = config.getoption("--urls-url-only")
    TESTCONFIG.url_skip_libosinfo = config.getoption("--urls-skip-libosinfo")
    TESTCONFIG.url_force_libosinfo = config.getoption("--urls-force-libosinfo")
    TESTCONFIG.regenerate_output = config.getoption("--regenerate-output")

    TESTCONFIG.debug = config.getoption("--log-level") == "debug"
    tests.setup_logging()
