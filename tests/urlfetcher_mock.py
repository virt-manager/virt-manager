# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
#

import ftplib
import os
import urllib
from urllib.request import Request

import requests

from virtinst import log


def _in_testsuite():
    return "VIRTINST_TEST_SUITE" in os.environ


def _make_mock_url(url, filesyntax):
    if url.endswith("treeinfo"):
        # If the url is requesting treeinfo, give a fake treeinfo from
        # our testsuite data
        fn = ("%s/data/cli/fakerhel6tree/.treeinfo" %
                os.path.abspath(os.path.dirname(__file__)))
        abspath = os.path.abspath(fn)
    else:
        # Otherwise just copy this file
        abspath = os.path.abspath(__file__)

    if filesyntax:
        return "file://" + abspath
    return abspath


class _MockRequestsResponse:
    def __init__(self, url):
        log.debug("mocking requests session for url=%s", url)
        fn = _make_mock_url(url, filesyntax=False)
        self._content = open(fn).read()
        self.headers = {'content-length': len(self._content)}

    def raise_for_status(self):
        pass
    def iter_content(self, *args, **kwargs):
        dummy = args
        dummy = kwargs
        return [self._content.encode("utf-8")]


class _MockRequestsSession:
    def close(self):
        pass
    def head(self, url, *args, **kwargs):
        dummy = args
        dummy = kwargs
        return _MockRequestsResponse(url)
    def get(self, url, *args, **kwargs):
        dummy = args
        dummy = kwargs
        if "testsuitefail" in url:
            raise RuntimeError("testsuitefail seen, raising mock error")
        return _MockRequestsResponse(url)


class _MockFTPSession:
    def connect(self, *args, **kwargs):
        pass
    def login(self, *args, **kwargs):
        pass
    def voidcmd(self, *args, **kwargs):
        pass
    def quit(self, *args, **kwargs):
        pass
    def size(self, url):
        path = _make_mock_url(url, filesyntax=False)
        return os.path.getsize(path)


def _MockUrllibRequest(url):
    url = _make_mock_url(url, filesyntax=True)
    return Request(url)


def setup_mock():
    requests.Session = _MockRequestsSession
    ftplib.FTP = _MockFTPSession
    urllib.request.Request = _MockUrllibRequest
