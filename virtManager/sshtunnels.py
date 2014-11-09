# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 Red Hat, Inc.
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

from .baseclass import vmmGObject


class ConnectionInfo(object):
    """
    Holds all the bits needed to make a connection to a graphical console
    """
    def __init__(self, conn, gdev):
        self.gtype      = gdev.type
        self.gport      = gdev.port and str(gdev.port) or None
        self.gsocket    = gdev.socket
        self.gaddr      = gdev.listen or "127.0.0.1"
        self.gtlsport   = gdev.tlsPort or None

        self.transport, self.connuser = conn.get_transport()

        (self._connhost,
         self._connport) = conn.get_backend().get_uri_host_port()
        if self._connhost == "localhost":
            self._connhost = "127.0.0.1"

    def _is_listen_localhost(self, host=None):
        return (host or self.gaddr) in ["127.0.0.1", "::1"]

    def _is_listen_any(self):
        return self.gaddr in ["0.0.0.0", "::"]

    def need_tunnel(self):
        if not self._is_listen_localhost():
            return False
        return self.transport in ["ssh", "ext"]

    def is_bad_localhost(self):
        """
        Return True if the guest is listening on localhost, but the libvirt
        URI doesn't give us any way to tunnel the connection
        """
        host = self.get_conn_host()[0]
        if self.need_tunnel():
            return False
        return self.transport and self._is_listen_localhost(host)

    def get_conn_host(self):
        host = self._connhost
        port = self._connport
        tlsport = None

        if not self.need_tunnel():
            port = self.gport
            tlsport = self.gtlsport
            if not self._is_listen_any():
                host = self.gaddr

        return host, port, tlsport

    def logstring(self):
        return ("proto=%s trans=%s connhost=%s connuser=%s "
                "connport=%s gaddr=%s gport=%s gtlsport=%s gsocket=%s" %
                (self.gtype, self.transport, self._connhost, self.connuser,
                 self._connport, self.gaddr, self.gport, self.gtlsport,
                 self.gsocket))
    def console_active(self):
        if self.gsocket:
            return True
        if (self.gport in [None, -1] and self.gtlsport in [None, -1]):
            return False
        return True


class _TunnelScheduler(object):
    """
    If the user is using Spice + SSH URI + no SSH keys, we need to
    serialize connection opening otherwise ssh-askpass gets all angry.
    This handles the locking and scheduling.

    It's only instantiated once for the whole app, because we serialize
    independent of connection, vm, etc.
    """
    def __init__(self):
        self._thread = threading.Thread(name="Tunnel thread",
                                        target=self._handle_queue,
                                        args=())
        self._thread.daemon = True
        self._queue = Queue.Queue()
        self._lock = threading.Lock()

    def _handle_queue(self):
        while True:
            cb, args, = self._queue.get()
            self.lock()
            vmmGObject.idle_add(cb, *args)

    def schedule(self, cb, *args):
        if not self._thread.is_alive():
            self._thread.start()
        self._queue.put((cb, args))

    def lock(self):
        self._lock.acquire()
    def unlock(self):
        self._lock.release()


class _Tunnel(object):
    def __init__(self):
        self.outfd = None
        self.errfd = None
        self.pid = None
        self._outfds = None
        self._errfds = None
        self.closed = False

    def open(self, ginfo):
        self._outfds = socket.socketpair()
        self._errfds = socket.socketpair()

        return self._outfds[0].fileno(), self._launch_tunnel, ginfo

    def close(self):
        if self.closed:
            return
        self.closed = True

        logging.debug("Close tunnel PID=%s OUTFD=%s ERRFD=%s",
                      self.pid,
                      self.outfd and self.outfd.fileno() or self._outfds,
                      self.errfd and self.errfd.fileno() or self._errfds)

        if self._outfds:
            self._outfds[1].close()
        self.outfd = None
        self._outfds = None

        if self.errfd:
            self.errfd.close()
        elif self._errfds:
            self._errfds[0].close()
            self._errfds[1].close()
        self.errfd = None
        self._errfds = None

        if self.pid:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        self.pid = None

    def get_err_output(self):
        errout = ""
        while True:
            try:
                new = self.errfd.recv(1024)
            except:
                break

            if not new:
                break

            errout += new

        return errout

    def _launch_tunnel(self, ginfo):
        if self.closed:
            return -1

        host, port, ignore = ginfo.get_conn_host()

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
        logging.debug("Creating SSH tunnel: %s", argv_str)

        pid = os.fork()
        if pid == 0:
            self._outfds[0].close()
            self._errfds[0].close()

            os.close(0)
            os.close(1)
            os.close(2)
            os.dup(self._outfds[1].fileno())
            os.dup(self._outfds[1].fileno())
            os.dup(self._errfds[1].fileno())
            os.execlp(*argv)
            os._exit(1)  # pylint: disable=protected-access
        else:
            self._outfds[1].close()
            self._errfds[1].close()

        logging.debug("Opened tunnel PID=%d OUTFD=%d ERRFD=%d",
                      pid, self._outfds[0].fileno(), self._errfds[0].fileno())
        self._errfds[0].setblocking(0)

        self.outfd = self._outfds[0]
        self.errfd = self._errfds[0]
        self._outfds = None
        self._errfds = None
        self.pid = pid


class SSHTunnels(object):
    _tunnel_sched = _TunnelScheduler()

    def __init__(self, ginfo):
        self.ginfo = ginfo
        self._tunnels = []

    def open_new(self):
        t = _Tunnel()
        fd, cb, args = t.open(self.ginfo)
        self._tunnels.append(t)
        self._tunnel_sched.schedule(cb, args)

        return fd

    def close_all(self):
        for l in self._tunnels:
            l.close()

    def get_err_output(self):
        errout = ""
        for l in self._tunnels:
            errout += l.get_err_output()
        return errout

    def lock(self, *args, **kwargs):
        return self._tunnel_sched.lock(*args, **kwargs)
    def unlock(self, *args, **kwargs):
        return self._tunnel_sched.unlock(*args, **kwargs)
