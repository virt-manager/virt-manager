#
# Copyright 2006-2007, 2013 Red Hat, Inc.
# Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import ftplib
import io
import logging
import os
import subprocess
import tempfile
import urllib

import requests


#########################################################################
# Backends for the various URL types we support (http, ftp, nfs, local) #
#########################################################################

class _URLFetcher(object):
    """
    This is a generic base class for fetching/extracting files from
    a media source, such as CD ISO, NFS server, or HTTP/FTP server
    """
    _block_size = 16384

    def __init__(self, location, scratchdir, meter):
        self.location = location
        self.scratchdir = scratchdir
        self.meter = meter

        self._srcdir = None

        logging.debug("Using scratchdir=%s", scratchdir)


    ####################
    # Internal helpers #
    ####################

    def _make_full_url(self, filename):
        """
        Generate a full fetchable URL from the passed filename, which
        is relative to the self.location
        """
        ret = self._srcdir or self.location
        if not filename:
            return ret

        if not ret.endswith("/"):
            ret += "/"
        return ret + filename

    def _grabURL(self, filename, fileobj):
        """
        Download the filename from self.location, and write contents to
        fileobj
        """
        url = self._make_full_url(filename)

        try:
            urlobj, size = self._grabber(url)
        except Exception as e:
            raise ValueError(_("Couldn't acquire file %s: %s") %
                               (url, str(e)))

        logging.debug("Fetching URI: %s", url)
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

    def prepareLocation(self):
        """
        Perform any necessary setup
        """
        pass

    def cleanupLocation(self):
        """
        Perform any necessary cleanup
        """
        pass

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
        logging.debug("hasFile(%s) returning %s", url, ret)
        return ret

    def acquireFile(self, filename):
        """
        Grab the passed filename from self.location and save it to
        a temporary file, returning the temp filename
        """
        prefix = "virtinst-" + os.path.basename(filename) + "."

        # pylint: disable=redefined-variable-type
        if "VIRTINST_TEST_SUITE" in os.environ:
            fn = os.path.join("/tmp", prefix)
            fileobj = open(fn, "wb")
        else:
            fileobj = tempfile.NamedTemporaryFile(
                dir=self.scratchdir, prefix=prefix, delete=False)
            fn = fileobj.name

        self._grabURL(filename, fileobj)
        logging.debug("Saved file to %s", fn)
        return fn

    def acquireFileContent(self, filename):
        """
        Grab the passed filename from self.location and return it as a string
        """
        fileobj = io.BytesIO()
        self._grabURL(filename, fileobj)
        return fileobj.getvalue().decode("utf-8")


class _HTTPURLFetcher(_URLFetcher):
    _session = None

    def prepareLocation(self):
        self._session = requests.Session()

    def cleanupLocation(self):
        if self._session:
            try:
                self._session.close()
            except Exception:
                logging.debug("Error closing requests.session", exc_info=True)
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
        except Exception as e:
            logging.debug("HTTP hasFile request failed: %s", str(e))
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
        except Exception:
            size = None
        return response, size

    def _write(self, urlobj, fileobj):
        """
        The requests object doesn't have a file-like read() option, so
        we need to implemente it ourselves
        """
        total = 0
        for data in urlobj.iter_content(chunk_size=self._block_size):
            fileobj.write(data)
            total += len(data)
            self.meter.update(total)
        return total


class _FTPURLFetcher(_URLFetcher):
    _ftp = None

    def prepareLocation(self):
        if self._ftp:
            return

        try:
            parsed = urllib.parse.urlparse(self.location)
            self._ftp = ftplib.FTP()
            username = urllib.parse.unquote(parsed.username or '')
            password = urllib.parse.unquote(parsed.password or '')
            self._ftp.connect(parsed.hostname, parsed.port or 0)
            self._ftp.login(username, password)
            # Force binary mode
            self._ftp.voidcmd("TYPE I")
        except Exception as e:
            raise ValueError(_("Opening URL %s failed: %s.") %
                              (self.location, str(e)))

    def _grabber(self, url):
        """
        Use urllib and ftplib to grab the file
        """
        request = urllib.request.Request(url)
        urlobj = urllib.request.urlopen(request)
        size = self._ftp.size(urllib.parse.urlparse(url)[2])
        return urlobj, size


    def cleanupLocation(self):
        if not self._ftp:
            return

        try:
            self._ftp.quit()
        except Exception:
            logging.debug("Error quitting ftp connection", exc_info=True)

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
        except ftplib.all_errors as e:
            logging.debug("FTP hasFile: couldn't access %s: %s",
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


class _MountedURLFetcher(_LocalURLFetcher):
    """
    Fetcher capable of extracting files from a NFS server
    or loopback mounted file, or local CDROM device
    """
    _in_test_suite = bool("VIRTINST_TEST_SUITE" in os.environ)
    _mounted = False

    def prepareLocation(self):
        if self._mounted:
            return

        if self._in_test_suite:
            self._srcdir = os.environ["VIRTINST_TEST_URL_DIR"]
        else:
            self._srcdir = tempfile.mkdtemp(prefix="virtinstmnt.",
                                           dir=self.scratchdir)
        mountcmd = "/bin/mount"

        logging.debug("Preparing mount at %s", self._srcdir)
        cmd = [mountcmd, "-o", "ro", self.location[4:], self._srcdir]

        logging.debug("mount cmd: %s", cmd)
        if not self._in_test_suite:
            ret = subprocess.call(cmd)
            if ret != 0:
                self.cleanupLocation()
                raise ValueError(_("Mounting location '%s' failed") %
                                 (self.location))

        self._mounted = True

    def cleanupLocation(self):
        if not self._mounted:
            return

        logging.debug("Cleaning up mount at %s", self._srcdir)
        try:
            if not self._in_test_suite:
                cmd = ["/bin/umount", self._srcdir]
                subprocess.call(cmd)
                try:
                    os.rmdir(self._srcdir)
                except Exception:
                    pass
        finally:
            self._mounted = False


class _ISOURLFetcher(_URLFetcher):
    _cache_file_list = None

    def _make_full_url(self, filename):
        return "/" + filename

    def _grabber(self, url):
        """
        Use isoinfo to grab the file
        """
        if not self._hasFile(url):
            raise RuntimeError("isoinfo didn't find file=%s" % url)

        cmd = ["isoinfo", "-J", "-i", self.location, "-x", url]

        logging.debug("Running isoinfo: %s", cmd)
        output = subprocess.check_output(cmd)

        return io.BytesIO(output), len(output)

    def _hasFile(self, url):
        """
        Use isoinfo to list and search for the file
        """
        if not self._cache_file_list:
            cmd = ["isoinfo", "-J", "-i", self.location, "-f"]

            logging.debug("Running isoinfo: %s", cmd)
            output = subprocess.check_output(cmd)

            self._cache_file_list = output.splitlines(False)

        return url.encode("ascii") in self._cache_file_list


def fetcherForURI(uri, *args, **kwargs):
    if uri.startswith("http://") or uri.startswith("https://"):
        fclass = _HTTPURLFetcher
    elif uri.startswith("ftp://"):
        fclass = _FTPURLFetcher
    elif uri.startswith("nfs:"):
        fclass = _MountedURLFetcher
    elif os.path.isdir(uri):
        # Pointing to a local tree
        fclass = _LocalURLFetcher
    else:
        # Pointing to a path (e.g. iso), or a block device (e.g. /dev/cdrom)
        fclass = _ISOURLFetcher
    return fclass(uri, *args, **kwargs)
