#
# Copyright (C) 2015 Red Hat, Inc.
# Copyright (C) 2015 Cole Robinson <crobinso@redhat.com>
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

from gi.repository import Gio

from virtManager.engine import vmmEngine


class _DBusServer(object):
    """
    Initializing this object starts the dbus service. It's job is just
    to proxy run_cli_command calls from a virt-manager command line
    invocation to the already running virt-manager instance
    """
    SERVICE_NAME = "org.virt-manager.cli"
    OBJECT_PATH = "/org/virtmanager/cli"
    INTERFACE_NAME = "org.virtmanager.cli"

    API_XML = """
<node>
  <interface name='%s'>
    <method name='run_cli_command'>
      <arg type='s' name='uri' direction='in'/>
      <arg type='s' name='show_window' direction='in'/>
      <arg type='s' name='domain' direction='in'/>
    </method>
  </interface>
</node>
""" % INTERFACE_NAME

    def __init__(self, engine):
        self.engine = engine
        logging.debug("Starting dbus cli server")

        Gio.bus_own_name(
            Gio.BusType.SESSION,
            self.SERVICE_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            self._on_name_acquired,
            self._on_name_lost)


    def _handle_method_call(self,
            connection, sender, object_path, interface_name,
            method_name, parameters, invocation):
        ignore = connection
        ignore = sender
        ignore = object_path
        ignore = interface_name

        try:
            if method_name == "run_cli_command":
                logging.debug("dbus run_cli_command invoked with args=%s",
                    parameters)
                self.engine.run_cli_command(*parameters)
                invocation.return_value(None)
            else:
                raise RuntimeError("Unhandled method=%s" % method_name)
        except Exception, e:
            logging.debug("Error processing dbus method=%s",
                    method_name, exc_info=True)
            Gio.DBusMethodInvocation.return_error_literal(
                invocation, Gio.DBusError.quark(), Gio.DBusError.FAILED, str(e))


    def _on_bus_acquired(self, connection, name):
        ignore = name
        introspection_data = Gio.DBusNodeInfo.new_for_xml(self.API_XML)
        connection.register_object(
            self.OBJECT_PATH,
            introspection_data.interfaces[0],
            self._handle_method_call, None, None)

    def _on_name_acquired(self, *args, **kwargs):
        pass

    def _on_name_lost(self, *args, **kwargs):
        logging.debug("Failed to acquire dbus service args=%s kwargs=%s",
            args, kwargs)


class StartupAPI(object):
    def __init__(self):
        self._engine = vmmEngine()
        self._proxy = self._init_dbus()


    #################
    # Dbus handling #
    #################

    def _init_dbus(self):
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        proxy = Gio.DBusProxy.new_sync(
            bus, 0, None,
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus")

        if not proxy.NameHasOwner("(s)", _DBusServer.SERVICE_NAME):
            _DBusServer(self._engine)
            return

        logging.debug("Detected app is already running, connecting "
            "to existing instance.")
        return Gio.DBusProxy.new_sync(
            bus, 0, None,
            _DBusServer.SERVICE_NAME,
            _DBusServer.OBJECT_PATH,
            _DBusServer.INTERFACE_NAME)


    ##############
    # Public API #
    ##############

    def start(self, skip_autostart):
        # Unconditionally use the engine here, since GtkApplication already
        # provides us with app uniqueness checking.
        self._engine.start(skip_autostart)

    def run_cli_command(self, uri, show_window, domain):
        if self._proxy:
            self._proxy.run_cli_command("(sss)",
                uri or "", show_window or "", domain or "")
        else:
            self._engine.run_cli_command(uri, show_window, domain)
