#!/usr/bin/env python3
#
# Copyright (C) 2006, 2014 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import argparse
import os
import signal
import sys
import traceback

import gi
gi.require_version('LibvirtGLib', '1.0')
from gi.repository import LibvirtGLib

from virtinst import BuildConfig
from virtinst import cli
from virtinst import log

from .lib.testmock import CLITestOptionsClass

try:
    gi.check_version("3.22.0")
except (ValueError, AttributeError):  # pragma: no cover
    print("pygobject3 3.22.0 or later is required.")
    sys.exit(1)


def _show_startup_error(msg, details):
    log.debug("Error starting virt-manager: %s\n%s", msg, details,
                  exc_info=True)
    from .error import vmmErrorDialog
    err = vmmErrorDialog.get_instance()
    title = _("Error starting Virtual Machine Manager")
    errmsg = (_("Error starting Virtual Machine Manager: %(error)s") %
              {"error": msg})
    err.show_err(errmsg,
                 details=details,
                 title=title,
                 modal=True,
                 debug=False)


def _import_gtk(leftovers):
    # The never ending fork+gsettings problems now require us to
    # import Gtk _after_ the fork. This creates a funny race, since we
    # need to parse the command line arguments to know if we need to
    # fork, but need to import Gtk before cli processing so it can
    # handle --g-fatal-args. We strip out our flags first and pass the
    # left overs to gtk
    origargv = sys.argv
    try:
        sys.argv = origargv[:1] + leftovers[:]
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        leftovers = sys.argv[1:]

        if Gtk.check_version(3, 22, 0):  # pragma: no cover
            print("gtk3 3.22.0 or later is required.")
            sys.exit(1)

        # This will error if Gtk wasn't correctly initialized
        Gtk.init()
        globals()["Gtk"] = Gtk

        # This ensures we can init gsettings correctly
        from . import config
        ignore = config
    finally:
        sys.argv = origargv

    return leftovers


def _setup_gsettings_path(schemadir):
    """
    If running from the virt-manager.git srcdir, compile our gsettings
    schema and use it directly
    """
    import subprocess
    import shutil

    exe = shutil.which("glib-compile-schemas")
    if not exe:  # pragma: no cover
        raise RuntimeError("You must install glib-compile-schemas to run "
            "virt-manager from git.")
    subprocess.check_call([exe, "--strict", schemadir])


def drop_tty():
    # We fork and setsid so that we drop the controlling
    # tty. This prevents libvirt's SSH tunnels from prompting
    # for user input if SSH keys/agent aren't configured.
    if os.fork() != 0:
        # pylint: disable=protected-access
        os._exit(0)  # pragma: no cover

    os.setsid()


def drop_stdio():
    # This is part of the fork process described in drop_tty()
    for fd in range(0, 2):
        try:
            os.close(fd)
        except OSError:  # pragma: no cover
            pass

    os.open(os.devnull, os.O_RDWR)
    os.dup2(0, 1)
    os.dup2(0, 2)


def parse_commandline():
    epilog = ("Also accepts standard GTK arguments like --g-fatal-warnings")
    parser = argparse.ArgumentParser(usage="virt-manager [options]",
                                     epilog=epilog)
    parser.add_argument('--version', action='version',
                        version=BuildConfig.version)
    parser.set_defaults(domain=None)

    # Trace every libvirt API call to debug output
    parser.add_argument("--trace-libvirt", choices=["all", "mainloop"],
        help=argparse.SUPPRESS)

    # comma separated string of options to tweak app behavior,
    # for manual and automated testing config
    parser.add_argument("--test-options", action='append',
            default=[], help=argparse.SUPPRESS)

    parser.add_argument("-c", "--connect", dest="uri",
        help="Connect to hypervisor at URI", metavar="URI")
    parser.add_argument("--debug", action="store_true",
        help="Print debug output to stdout (implies --no-fork)",
        default=False)
    parser.add_argument("--no-fork", action="store_true",
        help="Don't fork into background on startup")

    parser.add_argument("--show-domain-creator", action="store_true",
        help="Show 'New VM' wizard")
    parser.add_argument("--show-domain-editor", metavar="NAME|ID|UUID",
        help="Show domain details window")
    parser.add_argument("--show-domain-performance", metavar="NAME|ID|UUID",
        help="Show domain performance window")
    parser.add_argument("--show-domain-console", metavar="NAME|ID|UUID",
        help="Show domain graphical console window")
    parser.add_argument("--show-domain-delete", metavar="NAME|ID|UUID",
        help="Show domain delete window")
    parser.add_argument("--show-host-summary", action="store_true",
        help="Show connection details window")

    return parser.parse_known_args()


def main():
    (options, leftovers) = parse_commandline()

    cli.setupLogging("virt-manager", options.debug, False, False)

    log.debug("virt-manager version: %s", BuildConfig.version)
    log.debug("virtManager import: %s", os.path.dirname(__file__))

    if BuildConfig.running_from_srcdir:
        _setup_gsettings_path(BuildConfig.gsettings_dir)

    if options.trace_libvirt:
        log.debug("Libvirt tracing requested")
        from .lib import module_trace
        import libvirt
        module_trace.wrap_module(libvirt,
                mainloop=(options.trace_libvirt == "mainloop"),
                regex=None)

    CLITestOptions = CLITestOptionsClass(options.test_options)

    # With F27 gnome+wayland we need to set these before GTK import
    os.environ["GSETTINGS_SCHEMA_DIR"] = BuildConfig.gsettings_dir

    # Now we've got basic environment up & running we can fork
    do_drop_stdio = False
    if not options.no_fork and not options.debug:
        drop_tty()
        do_drop_stdio = True

        # Ignore SIGHUP, otherwise a serial console closing drops the whole app
        signal.signal(signal.SIGHUP, signal.SIG_IGN)

    leftovers = _import_gtk(leftovers)
    Gtk = globals()["Gtk"]

    # Do this after the Gtk import so the user has a chance of seeing any error
    if do_drop_stdio:
        drop_stdio()

    if leftovers:
        raise RuntimeError("Unhandled command line options '%s'" % leftovers)

    log.debug("PyGObject version: %d.%d.%d",
                  gi.version_info[0],
                  gi.version_info[1],
                  gi.version_info[2])
    log.debug("GTK version: %d.%d.%d",
                  Gtk.get_major_version(),
                  Gtk.get_minor_version(),
                  Gtk.get_micro_version())

    # Prime the vmmConfig cache
    from . import config
    config.vmmConfig.get_instance(BuildConfig, CLITestOptions)

    # Add our icon dir to icon theme
    icon_theme = Gtk.IconTheme.get_default()
    icon_theme.prepend_search_path(BuildConfig.icon_dir)

    from .engine import vmmEngine
    Gtk.Window.set_default_icon_name("virt-manager")

    show_window = None
    domain = None
    if options.show_domain_creator:
        show_window = vmmEngine.CLI_SHOW_DOMAIN_CREATOR
    elif options.show_host_summary:
        show_window = vmmEngine.CLI_SHOW_HOST_SUMMARY
    elif options.show_domain_editor:
        show_window = vmmEngine.CLI_SHOW_DOMAIN_EDITOR
        domain = options.show_domain_editor
    elif options.show_domain_performance:
        show_window = vmmEngine.CLI_SHOW_DOMAIN_PERFORMANCE
        domain = options.show_domain_performance
    elif options.show_domain_console:
        show_window = vmmEngine.CLI_SHOW_DOMAIN_CONSOLE
        domain = options.show_domain_console
    elif options.show_domain_delete:
        show_window = vmmEngine.CLI_SHOW_DOMAIN_DELETE
        domain = options.show_domain_delete

    if show_window and options.uri is None:  # pragma: no cover
        raise RuntimeError("can't use --show-* options without --connect")

    skip_autostart = False
    if show_window:
        skip_autostart = True

    # Hook libvirt events into glib main loop
    LibvirtGLib.init(None)
    LibvirtGLib.event_register()

    engine = vmmEngine.get_instance()

    # Actually exit when we receive ctrl-c
    from gi.repository import GLib
    def _sigint_handler(user_data):
        ignore = user_data
        log.debug("Received KeyboardInterrupt. Exiting application.")
        engine.exit_app()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT,
                         _sigint_handler, None)

    engine.start(options.uri, show_window, domain, skip_autostart)


def runcli():
    try:
        main()
    except KeyboardInterrupt:  # pragma: no cover
        log.debug("Received KeyboardInterrupt. Exiting application.")
    except Exception as run_e:
        if "Gtk" not in globals():
            raise  # pragma: no cover
        _show_startup_error(str(run_e), "".join(traceback.format_exc()))
