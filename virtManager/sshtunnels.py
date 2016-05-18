#
# Copyright (C) 2014, 2015 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
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
#

import logging
import os
import Queue
import socket
import signal
import threading
import ipaddr

from .baseclass import vmmGObject


class ConnectionInfo(object):
    """
    Holds all the bits needed to make a connection to a graphical console
    """
    def __init__(self, conn, gdev):
        self.gtype = gdev.type
        self.gport = gdev.port and str(gdev.port) or None
        self.gsocket = gdev.socket
        self.gaddr = gdev.listen or "127.0.0.1"
        self.gtlsport = gdev.tlsPort or None

        self.transport = conn.get_uri_transport()
        self.connuser = conn.get_uri_username()

        self._connhost = conn.get_uri_hostname() or "localhost"
        self._connport = conn.get_uri_port()
        if self._connhost == "localhost":
            self._connhost = "127.0.0.1"

    def _is_listen_localhost(self, host=None):
        try:
            return ipaddr.IPNetwork(host or self.gaddr).is_loopback
        except:
            return False

    def _is_listen_any(self):
        try:
            return ipaddr.IPNetwork(self.gaddr).is_unspecified
        except:
            return False

    def _is_listen_none(self):
        return not (self.gsocket or self.gport or self.gtlsport)

    def need_tunnel(self):
        if not self._is_listen_localhost():
            return False
        return self.transport == "ssh"

    def bad_config(self):
        if self.transport and self._is_listen_none():
            return _("Guest is on a remote host, but is only configured "
                "to allow local file descriptor connections.")

        if self.need_tunnel() and (self.gtlsport and not self.gport):
            return _("Guest is configured for TLS only which does not "
                "work over SSH.")

        if (not self.need_tunnel() and
            self.transport and
            self._is_listen_localhost(self.get_conn_host()[0])):
            return _("Guest is on a remote host with transport '%s' "
                "but is only configured to listen locally. "
                "To connect remotely you will need to change the guest's "
                "listen address." % self.transport)

    def get_conn_host(self):
        """
        Return host/port/tlsport needed for direct spice/vnc connection
        """
        host = self.gaddr
        port = self.gport
        tlsport = self.gtlsport
        if self._is_listen_any():
            host = self._connhost

        return host, port, tlsport

    def get_tunnel_host(self):
        """
        Physical host name/port needed for ssh tunnel connection
        """
        return self._connhost, self._connport

    def logstring(self):
        return ("proto=%s trans=%s connhost=%s connuser=%s "
                "connport=%s gaddr=%s gport=%s gtlsport=%s gsocket=%s" %
                (self.gtype, self.transport, self._connhost, self.connuser,
                 self._connport, self.gaddr, self.gport, self.gtlsport,
                 self.gsocket))


class _TunnelScheduler(object):
    """
    If the user is using Spice + SSH URI + no SSH keys, we need to
    serialize connection opening otherwise ssh-askpass gets all angry.
    This handles the locking and scheduling.

    It's only instantiated once for the whole app, because we serialize
    independent of connection, vm, etc.
    """
    def __init__(self):
        self._thread = None
        self._queue = Queue.Queue()
        self._lock = threading.Lock()

    def _handle_queue(self):
        while True:
            lock_cb, cb, args, = self._queue.get()
            lock_cb()
            vmmGObject.idle_add(cb, *args)

    def schedule(self, lock_cb, cb, *args):
        if not self._thread:
            self._thread = threading.Thread(name="Tunnel thread",
                                            target=self._handle_queue,
                                            args=())
            self._thread.daemon = True
        if not self._thread.is_alive():
            self._thread.start()
        self._queue.put((lock_cb, cb, args))

    def lock(self):
        self._lock.acquire()
    def unlock(self):
        self._lock.release()


_tunnel_scheduler = _TunnelScheduler()


class _Tunnel(object):
    def __init__(self):
        self._pid = None
        self._closed = False
        self._errfd = None

    def close(self):
        if self._closed:
            return
        self._closed = True

        logging.debug("Close tunnel PID=%s ERRFD=%s",
                      self._pid, self._errfd and self._errfd.fileno() or None)

        # Since this is a socket object, the file descriptor is closed
        # when it's garbage collected.
        self._errfd = None

        if self._pid:
            os.kill(self._pid, signal.SIGKILL)
            os.waitpid(self._pid, 0)
        self._pid = None

    def get_err_output(self):
        errout = ""
        while True:
            try:
                new = self._errfd.recv(1024)
            except:
                break

            if not new:
                break

            errout += new

        return errout

    def open(self, argv, sshfd):
        if self._closed:
            return

        errfds = socket.socketpair()
        pid = os.fork()
        if pid == 0:
            errfds[0].close()

            os.dup2(sshfd.fileno(), 0)
            os.dup2(sshfd.fileno(), 1)
            os.dup2(errfds[1].fileno(), 2)
            os.execlp(*argv)
            os._exit(1)  # pylint: disable=protected-access

        sshfd.close()
        errfds[1].close()

        self._errfd = errfds[0]
        self._errfd.setblocking(0)
        logging.debug("Opened tunnel PID=%d ERRFD=%d",
                      pid, self._errfd.fileno())

        self._pid = pid


def _make_ssh_command(ginfo):
    if not ginfo.need_tunnel():
        return None

    host, port = ginfo.get_tunnel_host()

    # Build SSH cmd
    argv = ["ssh", "ssh"]
    if port:
        argv += ["-p", str(port)]

    if ginfo.connuser:
        argv += ['-l', ginfo.connuser]

    argv += [host]

    # Build 'nc' command run on the remote host
    #
    # This ugly thing is a shell script to detect availability of
    # the -q option for 'nc': debian and suse based distros need this
    # flag to ensure the remote nc will exit on EOF, so it will go away
    # when we close the VNC tunnel. If it doesn't go away, subsequent
    # VNC connection attempts will hang.
    #
    # Fedora's 'nc' doesn't have this option, and apparently defaults
    # to the desired behavior.
    #
    if ginfo.gsocket:
        nc_params = "-U %s" % ginfo.gsocket
    else:
        nc_params = "%s %s" % (ginfo.gaddr, ginfo.gport)

    nc_cmd = (
        """nc -q 2>&1 | grep "requires an argument" >/dev/null;"""
        """if [ $? -eq 0 ] ; then"""
        """   CMD="nc -q 0 %(nc_params)s";"""
        """else"""
        """   CMD="nc %(nc_params)s";"""
        """fi;"""
        """eval "$CMD";""" %
        {'nc_params': nc_params})

    argv.append("sh -c")
    argv.append("'%s'" % nc_cmd)

    argv_str = reduce(lambda x, y: x + " " + y, argv[1:])
    logging.debug("Pre-generated ssh command for ginfo: %s", argv_str)
    return argv


class SSHTunnels(object):
    def __init__(self, ginfo):
        self._tunnels = []
        self._sshcommand = _make_ssh_command(ginfo)
        self._locked = False

    def open_new(self):
        t = _Tunnel()
        self._tunnels.append(t)

        # socket FDs are closed when the object is garbage collected. This
        # can close an FD behind spice/vnc's back which causes crashes.
        #
        # Dup a bare FD for the viewer side of things, but keep the high
        # level socket object for the SSH side, since it simplifies things
        # in that area.
        viewerfd, sshfd = socket.socketpair()
        _tunnel_scheduler.schedule(self._lock, t.open, self._sshcommand, sshfd)

        retfd = os.dup(viewerfd.fileno())
        logging.debug("Generated tunnel fd=%s for viewer", retfd)
        return retfd

    def close_all(self):
        for l in self._tunnels:
            l.close()
        self._tunnels = []
        self.unlock()

    def get_err_output(self):
        errstrings = []
        for l in self._tunnels:
            e = l.get_err_output().strip()
            if e and e not in errstrings:
                errstrings.append(e)
        return "\n".join(errstrings)

    def _lock(self):
        _tunnel_scheduler.lock()
        self._locked = True

    def unlock(self, *args, **kwargs):
        if self._locked:
            _tunnel_scheduler.unlock(*args, **kwargs)
            self._locked = False
