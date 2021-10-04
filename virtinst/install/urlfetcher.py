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


#########################
# isoreader abstraction #
#########################

class _XorrisoReader():
    def __init__(self, location):
        self._location = location
        self._cache_file_list = self._make_file_list()

    def _make_file_list(self):
        delim = "VIRTINST_BEGINLIST"
        cmd = ["xorriso", "-indev", self._location, "-print", delim, "-find"]

        log.debug("Generating iso filelist: %s", cmd)
        output = subprocess.check_output(cmd,
                stderr=subprocess.DEVNULL, universal_newlines=True)
        return output.split(delim, 1)[1].strip().splitlines()

    def grabFile(self, url, scratchdir):
        tmp = tempfile.NamedTemporaryFile(
                prefix="virtinst-iso", suffix="-" + os.path.basename(url),
                dir=scratchdir)

        cmd = ["xorriso", "-osirrox", "on", "-indev", self._location,
               "-extract", url, tmp.name]
        log.debug("Extracting iso file: %s", cmd)
        subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return open(tmp.name, "rb").read()

    def hasFile(self, url):
        return ("'.%s'" % url) in self._cache_file_list


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
            msg = (_("Couldn't acquire file %(url)s: %(error)s") % {
                    "url": url, "error": str(e)})
            raise ValueError(msg) from None

        log.debug("Fetching URI: %s", url)
        msg = _("Retrieving '%(filename)s'") % {
                "filename": os.path.basename(filename)}
        self.meter.start(msg, size)

        self._write(urlobj, fileobj)
        self.meter.end()

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
        fileobj.flush()
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
        fn = None
        try:
            fileobj = tempfile.NamedTemporaryFile(
                prefix="virtinst-", suffix="-" + os.path.basename(filename),
                dir=self.scratchdir, delete=False)
            fn = fileobj.name

            self._grabURL(filename, fileobj, fullurl=fullurl)
            log.debug("Saved file to %s", fn)
            return fn
        except BaseException:  # pragma: no cover
            if fn and os.path.exists(fn):
                os.unlink(fn)
            raise

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
        fileobj.flush()
        return total


class _FTPURLFetcher(_URLFetcher):
    _ftp = None

    def _prepare(self):
        if self._ftp:
            return  # pragma: no cover

        try:
            parsed = urllib.parse.urlparse(self.location)
            self._ftp = ftplib.FTP()
            username = urllib.parse.unquote(parsed.username or '')
            password = urllib.parse.unquote(parsed.password or '')
            self._ftp.connect(parsed.hostname, parsed.port or 0)
            self._ftp.login(username, password)
            # Force binary mode
            self._ftp.voidcmd("TYPE I")
        except Exception as e:  # pragma: no cover
            msg = (_("Opening URL %(url)s failed: %(error)s") % {
                    "url": self.location, "error": str(e)})
            raise ValueError(msg) from None

    def _grabber(self, url):
        """
        Use urllib and ftplib to grab the file
        """
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
            except ftplib.all_errors:  # pragma: no cover
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
        parsed = urllib.parse.urlparse(url)
        return os.path.exists(parsed.path)

    def _grabber(self, url):
        parsed = urllib.parse.urlparse(url)
        urlobj = open(parsed.path, "rb")
        size = os.path.getsize(parsed.path)
        return urlobj, size


class _ISOURLFetcher(_URLFetcher):
    _isoreader = None
    _is_iso = True

    def _make_full_url(self, filename):
        return os.path.join("/", filename)

    def _get_isoreader(self):
        if not self._isoreader:
            self._isoreader = _XorrisoReader(self.location)
        return self._isoreader

    def _grabber(self, url):
        if not self._hasFile(url):
            raise RuntimeError("iso doesn't have file=%s" % url)

        output = self._get_isoreader().grabFile(url, self.scratchdir)
        return io.BytesIO(output), len(output)

    def _hasFile(self, url):
        return self._get_isoreader().hasFile(url)


class DirectFetcher(_URLFetcher):
    def _make_full_url(self, filename):
        return filename

    def acquireFile(self, filename, fullurl=None):
        if not fullurl:
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
