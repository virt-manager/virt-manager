#
# Copyright 2006-2007, 2013 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.
#
# Backends for the various URL types we support (http, https, ftp, local)

import ftplib
import io
import os
import subprocess
import tempfile
import urllib

import requests

from ..logger import log


##############################
# Mocking for the test suite #
##############################

def _in_testsuite():
    return "VIRTINST_TEST_SUITE" in os.environ


def _make_mock_url(url, filesyntax):
    if url.endswith("treeinfo"):
        # If the url is requesting treeinfo, give a fake treeinfo from
        # our testsuite data
        fn = ("%s/../../tests/cli-test-xml/fakerhel6tree/.treeinfo" %
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


###########################
# Fetcher implementations #
###########################

class _URLFetcher(object):
    """
    This is a generic base class for fetching/extracting files from
    a media source, such as CD ISO, or HTTP/HTTPS/FTP server
    """
    _block_size = 16384
    _is_iso = False

    def __init__(self, location, scratchdir, meter):
        self.location = location
        self.scratchdir = scratchdir
        self.meter = meter

        log.debug("Using scratchdir=%s", scratchdir)
        self._prepare()


    ####################
    # Internal helpers #
    ####################

    def _make_full_url(self, filename):
        """
        Generate a full fetchable URL from the passed filename, which
        is relative to the self.location
        """
        if self._is_iso:
            return os.path.join("/", filename)
        if not filename:
            return self.location
        return os.path.join(self.location, filename)

    def _grabURL(self, filename, fileobj, fullurl=None):
        """
        Download the filename from self.location, and write contents to
        fileobj
        """
        if fullurl:
            url = fullurl
        else:
            url = self._make_full_url(filename)

        try:
            urlobj, size = self._grabber(url)
        except Exception as e:
            raise ValueError(_("Couldn't acquire file %s: %s") %
                               (url, str(e)))

        log.debug("Fetching URI: %s", url)
        self.meter.start(
            text=_("Retrieving file %s...") % os.path.basename(filename),
            size=size)

        total = self._write(urlobj, fileobj)
        self.meter.end(total)

    def _write(self, urlobj, fileobj):
        """
        Write the contents of urlobj to python file like object fileobj
        """
        total = 0
        while 1:
            buff = urlobj.read(self._block_size)
            if not buff:
                break
            fileobj.write(buff)
            total += len(buff)
            self.meter.update(total)
        return total

    def _grabber(self, url):
        """
        Returns the urlobj, size for the passed URL. urlobj is whatever
        data needs to be passed to self._write
        """
        raise NotImplementedError("must be implemented in subclass")


    ##############
    # Public API #
    ##############

    def is_iso(self):
        """
        If this is a fetcher for local CDROM/ISO
        """
        return self._is_iso

    def _prepare(self):
        """
        Perform any necessary setup
        """

    def _cleanup(self):
        """
        Perform any necessary cleanup
        """

    def __del__(self):
        self._cleanup()

    def can_access(self):
        """
        Return True if the location URL seems to be valid
        """
        return True

    def _hasFile(self, url):
        raise NotImplementedError("Must be implemented in subclass")

    def hasFile(self, filename):
        """
        Return True if self.location has the passed filename
        """
        url = self._make_full_url(filename)
        ret = self._hasFile(url)
        log.debug("hasFile(%s) returning %s", url, ret)
        return ret

    def acquireFile(self, filename, fullurl=None):
        """
        Grab the passed filename from self.location and save it to
        a temporary file, returning the temp filename
        """
        # pylint: disable=redefined-variable-type
        fn = None
        try:
            fileobj = tempfile.NamedTemporaryFile(
                prefix="virtinst-", suffix="-" + os.path.basename(filename),
                dir=self.scratchdir, delete=False)
            fn = fileobj.name

            self._grabURL(filename, fileobj, fullurl=fullurl)
            log.debug("Saved file to %s", fn)
            return fn
        except:  # noqa
            if fn and os.path.exists(fn):  # pragma: no cover
                os.unlink(fn)  # pragma: no cover
            raise  # pragma: no cover

    def acquireFileContent(self, filename):
        """
        Grab the passed filename from self.location and return it as a string
        """
        fileobj = io.BytesIO()
        self._grabURL(filename, fileobj)
        return fileobj.getvalue().decode("utf-8")


class _HTTPURLFetcher(_URLFetcher):
    _session = None

    def _prepare(self):
        if _in_testsuite():
            self._session = _MockRequestsSession()
        else:
            self._session = requests.Session()

    def _cleanup(self):
        if self._session:
            try:
                self._session.close()
            except Exception:  # pragma: no cover
                log.debug("Error closing requests.session", exc_info=True)
        self._session = None

    def can_access(self):
        return self.hasFile("")

    def _hasFile(self, url):
        """
        We just do a HEAD request to see if the file exists
        """
        try:
            response = self._session.head(url, allow_redirects=True)
            response.raise_for_status()
        except Exception as e:  # pragma: no cover
            log.debug("HTTP hasFile request failed: %s", str(e))
            return False
        return True

    def _grabber(self, url):
        """
        Use requests for this
        """
        response = self._session.get(url, stream=True)
        response.raise_for_status()
        try:
            size = int(response.headers.get('content-length'))
        except Exception:  # pragma: no cover
            size = None
        return response, size

    def _write(self, urlobj, fileobj):
        """
        The requests object doesn't have a file-like read() option, so
        we need to implement it ourselves
        """
        total = 0
        for data in urlobj.iter_content(chunk_size=self._block_size):
            fileobj.write(data)
            total += len(data)
            self.meter.update(total)
        return total


class _FTPURLFetcher(_URLFetcher):
    _ftp = None

    def _prepare(self):
        if self._ftp:
            return  # pragma: no cover

        try:
            parsed = urllib.parse.urlparse(self.location)
            if _in_testsuite():
                self._ftp = _MockFTPSession()
            else:
                self._ftp = ftplib.FTP()
            username = urllib.parse.unquote(parsed.username or '')
            password = urllib.parse.unquote(parsed.password or '')
            self._ftp.connect(parsed.hostname, parsed.port or 0)
            self._ftp.login(username, password)
            # Force binary mode
            self._ftp.voidcmd("TYPE I")
        except Exception as e:  # pragma: no cover
            raise ValueError(_("Opening URL %s failed: %s.") %
                              (self.location, str(e)))

    def _grabber(self, url):
        """
        Use urllib and ftplib to grab the file
        """
        if _in_testsuite():
            url = _make_mock_url(url, filesyntax=True)
        request = urllib.request.Request(url)
        urlobj = urllib.request.urlopen(request)
        size = self._ftp.size(urllib.parse.urlparse(url)[2])
        return urlobj, size


    def _cleanup(self):
        if not self._ftp:
            return  # pragma: no cover

        try:
            self._ftp.quit()
        except Exception:  # pragma: no cover
            log.debug("Error quitting ftp connection", exc_info=True)

        self._ftp = None

    def _hasFile(self, url):
        path = urllib.parse.urlparse(url)[2]

        try:
            try:
                # If it's a file
                self._ftp.size(path)
            except ftplib.all_errors:
                # If it's a dir
                self._ftp.cwd(path)
        except ftplib.all_errors as e:  # pragma: no cover
            log.debug("FTP hasFile: couldn't access %s: %s",
                          url, str(e))
            return False

        return True


class _LocalURLFetcher(_URLFetcher):
    """
    For grabbing files from a local directory
    """
    def _hasFile(self, url):
        return os.path.exists(url)

    def _grabber(self, url):
        urlobj = open(url, "rb")
        size = os.path.getsize(url)
        return urlobj, size


class _ISOURLFetcher(_URLFetcher):
    _cache_file_list = None
    _is_iso = True

    def _grabber(self, url):
        """
        Use isoinfo to grab the file
        """
        if not self._hasFile(url):
            raise RuntimeError("isoinfo didn't find file=%s" % url)

        cmd = ["isoinfo", "-J", "-i", self.location, "-x", url]

        log.debug("Running isoinfo: %s", cmd)
        output = subprocess.check_output(cmd)

        return io.BytesIO(output), len(output)

    def _hasFile(self, url):
        """
        Use isoinfo to list and search for the file
        """
        if not self._cache_file_list:
            cmd = ["isoinfo", "-J", "-i", self.location, "-f"]

            log.debug("Running isoinfo: %s", cmd)
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)

            self._cache_file_list = output.splitlines(False)

        return url.encode("ascii") in self._cache_file_list


class DirectFetcher(_URLFetcher):
    def _make_full_url(self, filename):
        return filename

    def acquireFile(self, filename, fullurl=None):
        fullurl = filename
        filename = os.path.basename(filename)
        fetcher = fetcherForURI(fullurl, self.scratchdir, self.meter, direct=True)
        return fetcher.acquireFile(filename, fullurl)  # pylint: disable=protected-access

    def _hasFile(self, url):
        return True

    def _grabber(self, url):
        raise RuntimeError(  # pragma: no cover
                "DirectFetcher shouldn't be used for file access.")


def fetcherForURI(uri, scratchdir, meter, direct=False):
    if uri.startswith("http://") or uri.startswith("https://"):
        fclass = _HTTPURLFetcher
    elif uri.startswith("ftp://"):
        fclass = _FTPURLFetcher
    elif direct or os.path.isdir(uri):
        # Pointing to a local tree
        fclass = _LocalURLFetcher
    else:
        # Pointing to a path (e.g. iso), or a block device (e.g. /dev/cdrom)
        fclass = _ISOURLFetcher
    return fclass(uri, scratchdir, meter)
