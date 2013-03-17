#!/usr/bin/python

#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
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
import optparse
import os
import signal
import sys
import traceback

from gi.repository import GObject
from gi.repository import LibvirtGLib

from virtcli import cliutils, cliconfig


GObject.threads_init()


try:
    # Make sure we have a default '_' implementation, in case something
    # fails before gettext is set up
    __builtins__._ = lambda msg: msg
except:
    pass


logging_setup = False


def _show_startup_error(msg, details):
    from virtManager.error import vmmErrorDialog
    err = vmmErrorDialog()
    title = _("Error starting Virtual Machine Manager")
    err.show_err(title + ": " + msg,
                 details=details,
                 title=title,
                 async=False,
                 debug=False)


def drop_tty():
    # We fork and setsid so that we drop the controlling
    # tty. This prevents libvirt's SSH tunnels from prompting
    # for user input if SSH keys/agent aren't configured.
    if os.fork() != 0:
        os._exit(0)

    os.setsid()

def drop_stdio():
    # We close STDIN/OUT/ERR since they're generally spewing
    # junk to console when domains are in process of shutting
    # down. Real errors will (hopefully) all be logged to the
    # main log file. This is also again to stop SSH prompting
    # for input
    for fd in range(0, 2):
        try:
            os.close(fd)
        except OSError:
            pass

    os.open(os.devnull, os.O_RDWR)
    os.dup2(0, 1)
    os.dup2(0, 2)

def parse_commandline():
    optParser = optparse.OptionParser(version=cliconfig.__version__,
                                      usage="virt-manager [options]")
    optParser.set_defaults(uuid=None)
    optParser.epilog = ("Also accepts standard GTK arguments like "
                        "--g-fatal-warnings")

    # Generate runtime performance profile stats with hotshot
    optParser.add_option("--profile", dest="profile",
        help=optparse.SUPPRESS_HELP, metavar="FILE")

    # Trace every libvirt API call to debug output
    optParser.add_option("--trace-libvirt", dest="tracelibvirt",
        help=optparse.SUPPRESS_HELP, action="store_true")

    # Don't load any connections on startup to test first run
    # PackageKit integration
    optParser.add_option("--test-first-run", dest="testfirstrun",
        help=optparse.SUPPRESS_HELP, action="store_true")

    optParser.add_option("-c", "--connect", dest="uri",
        help="Connect to hypervisor at URI", metavar="URI")
    optParser.add_option("--debug", action="store_true", dest="debug",
        help="Print debug output to stdout (implies --no-fork)",
        default=False)
    optParser.add_option("--no-dbus", action="store_true", dest="nodbus",
        help="Disable DBus service for controlling UI")
    optParser.add_option("--no-fork", action="store_true", dest="nofork",
        help="Don't fork into background on startup")
    optParser.add_option("--no-conn-autostart", action="store_true",
                         dest="no_conn_auto",
                         help="Do not autostart connections")

    optParser.add_option("--show-domain-creator", action="callback",
        callback=opt_show_cb, dest="show",
        help="Show 'New VM' wizard")
    optParser.add_option("--show-domain-editor", type="string",
        metavar="UUID", action="callback", callback=opt_show_cb,
        help="Show domain details window")
    optParser.add_option("--show-domain-performance", type="string",
        metavar="UUID", action="callback", callback=opt_show_cb,
        help="Show domain performance window")
    optParser.add_option("--show-domain-console", type="string",
        metavar="UUID", action="callback", callback=opt_show_cb,
        help="Show domain graphical console window")
    optParser.add_option("--show-host-summary", action="callback",
       callback=opt_show_cb, help="Show connection details window")

    return optParser.parse_args()


def launch_specific_window(engine, show, uri, uuid):
    if not show:
        return

    logging.debug("Launching requested window '%s'", show)
    if show == 'creator':
        engine.show_domain_creator(uri)
    elif show == 'editor':
        engine.show_domain_editor(uri, uuid)
    elif show == 'performance':
        engine.show_domain_performance(uri, uuid)
    elif show == 'console':
        engine.show_domain_console(uri, uuid)
    elif show == 'summary':
        engine.show_host_summary(uri)

def _conn_state_changed(conn, engine, show, uri, uuid):
    if conn.state == conn.STATE_DISCONNECTED:
        return True
    if conn.state != conn.STATE_ACTIVE:
        return

    launch_specific_window(engine, show, uri, uuid)
    return True

# maps --show-* to engine (ie local instance) methods
def show_engine(engine, show, uri, uuid, no_conn_auto):
    conn = None

    # Do this regardless
    engine.show_manager()

    if uri:
        conn = engine.add_conn_to_ui(uri)

        if conn and show:
            conn.connect_opt_out("state-changed",
                                 _conn_state_changed,
                                 engine, show, uri, uuid)

        engine.connect_to_uri(uri)

    if not no_conn_auto:
        engine.autostart_conns()

# maps --show-* to remote manager (ie dbus call) methods
def show_remote(managerObj, show, uri, uuid):
    # Do this regardless
    managerObj.show_manager()

    if show or uri or uuid:
        launch_specific_window(managerObj, show, uri, uuid)

def dbus_config(engine):
    """
    Setup dbus interface
    """
    import dbus
    from virtManager.remote import vmmRemote
    bus = None

    if os.getenv("DBUS_STARTER_ADDRESS") is None:
        bus = dbus.SessionBus()
    else:
        bus = dbus.StarterBus()

    dbusProxy = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
    dbusObj = dbus.Interface(dbusProxy, "org.freedesktop.DBus")

    if dbusObj.NameHasOwner("com.redhat.virt.manager"):
        # We're already running, so just talk to existing process
        managerProxy = bus.get_object("com.redhat.virt.manager",
                                      "/com/redhat/virt/manager")
        managerObj = dbus.Interface(managerProxy, "com.redhat.virt.manager")
        return managerObj

    else:
        # Grab the service to allow others to talk to us later
        import dbus.service
        name = dbus.service.BusName("com.redhat.virt.manager", bus=bus)
        vmmRemote(engine, name)

# Generic OptionParser callback for all --show-* options
# This routine stores UUID to options.uuid for all --show-* options
# where is metavar="UUID" and also sets options.show
def opt_show_cb(option, opt_str, value, parser):
    if option.metavar == "UUID":
        setattr(parser.values, "uuid", value)
    s = str(option)
    show = s[s.rindex('-') + 1:]
    setattr(parser.values, "show", show)


# Run me!
def main():
    cliutils.setup_i18n()

    # Need to do this before GTK strips args like --sync
    origargs = " ".join(sys.argv[:])

    try:
        from gi.repository import Gtk
    except:
        # Don't just let the exception raise here. abrt reports bugs
        # when users mess up su/sudo and DISPLAY isn't set. Printing
        # it avoids the issue
        print "".join(traceback.format_exc())
        return 1

    # Need to parse CLI after import gtk, since gtk strips --sync
    (options, ignore) = parse_commandline()

    cliutils.setup_logging("virt-manager", options.debug)
    global logging_setup
    logging_setup = True

    import virtManager
    logging.debug("Launched as: %s", origargs)
    logging.debug("GTK version: %d.%d.%d",
                  Gtk.get_major_version(),
                  Gtk.get_minor_version(),
                  Gtk.get_micro_version())
    logging.debug("virt-manager version: %s", cliconfig.__version__)
    logging.debug("virtManager import: %s", str(virtManager))

    cliutils.check_virtinst_version()

    if options.tracelibvirt:
        logging.debug("Libvirt tracing requested")
        import virtManager.module_trace
        import libvirt
        virtManager.module_trace.wrap_module(libvirt)

    import dbus
    import dbus.mainloop.glib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    dbus.mainloop.glib.threads_init()

    # Specifically init config/gconf before the fork, so that pam
    # doesn't think we closed the app, therefor robbing us of
    # display access
    import virtManager.config
    import virtManager.util
    config = virtManager.config.vmmConfig("virt-manager",
                                    cliconfig.__version__,
                                    os.path.join(cliconfig.asset_dir, "ui"),
                                    options.testfirstrun)
    virtManager.util.running_config = config
    config.default_qemu_user = cliconfig.default_qemu_user
    config.rhel6_defaults = cliconfig.rhel_enable_unsupported_opts
    config.preferred_distros = cliconfig.preferred_distros

    config.hv_packages = cliconfig.hv_packages
    config.libvirt_packages = cliconfig.libvirt_packages
    config.askpass_package = cliconfig.askpass_package
    config.default_graphics_from_config = cliconfig.default_graphics

    import virtManager.guidiff
    virtManager.guidiff.is_gui(True)

    # Now we've got basic environment up & running we can fork
    if not options.nofork and not options.debug:
        drop_tty()
        drop_stdio()

        # Ignore SIGHUP, otherwise a serial console closing drops the whole app
        signal.signal(signal.SIGHUP, signal.SIG_IGN)

    # Add our icon dir to icon theme
    icon_theme = Gtk.IconTheme.get_default()
    icon_theme.prepend_search_path(cliconfig.icon_dir)

    from virtManager.engine import vmmEngine

    Gtk.Window.set_default_icon_name("virt-manager")

    if options.show and options.uri is None:
        raise optparse.OptionValueError("can't use --show-* options "
                                        "without --connect")

    engine = vmmEngine()

    if not options.nodbus:
        try:
            managerObj = dbus_config(engine)
            if managerObj:
                # yes, we exit completely now - remote service is in charge
                logging.debug("Connected to already running instance.")
                show_remote(managerObj, options.show,
                            options.uri, options.uuid)
                return
        except:
            # Something went wrong doing dbus setup, just ignore & carry on
            logging.exception("Could not get connection to session bus, "
                              "disabling DBus service")

    # Hook libvirt events into glib main loop
    LibvirtGLib.init(None)
    LibvirtGLib.event_register()

    # At this point we're either starting a brand new controlling instance,
    # or the dbus comms to existing instance has failed

    # Finally start the app for real
    show_engine(engine, options.show, options.uri, options.uuid,
                options.no_conn_auto)
    if options.profile is not None:
        import hotshot
        prof = hotshot.Profile(options.profile)
        prof.runcall(Gtk.main)
        prof.close()
    else:
        Gtk.main()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.debug("Received KeyboardInterrupt. Exiting application.")
    except SystemExit:
        raise
    except Exception, run_e:
        if logging_setup:
            logging.exception(run_e)
        if "Gtk" not in globals():
            raise
        _show_startup_error(str(run_e), "".join(traceback.format_exc()))
