#
# Utility functions for the command line drivers
#
# Copyright 2006-2007, 2013, 2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import argparse
import collections
import os
import re
import shlex
import shutil
import sys
import traceback
import types

import libvirt

from . import xmlutil
from .buildconfig import BuildConfig
from .connection import VirtinstConnection
from .devices import (Device, DeviceController, DeviceDisk, DeviceGraphics,
        DeviceInterface, DevicePanic)
from .guest import Guest
from .logger import log, reset_logging
from .nodedev import NodeDevice
from .osdict import OSDB
from .storage import StoragePool, StorageVolume
from .install.unattended import UnattendedData
from .install.cloudinit import CloudInitData


HAS_VIRTVIEWER = shutil.which("virt-viewer")


##########################
# Global option handling #
##########################

class _GlobalState(object):
    def __init__(self):
        self.quiet = False

        self.all_checks = None
        self._validation_checks = {}

    def set_validation_check(self, checkname, val):
        self._validation_checks[checkname] = val

    def get_validation_check(self, checkname):
        if self.all_checks is not None:
            return self.all_checks

        # Default to True for all checks
        return self._validation_checks.get(checkname, True)


_globalstate = None


def get_global_state():
    return _globalstate


def _reset_global_state():
    global _globalstate
    _globalstate = _GlobalState()


VIRT_PARSERS = []


####################
# CLI init helpers #
####################

class VirtHelpFormatter(argparse.RawDescriptionHelpFormatter):
    '''
    Subclass the default help formatter to allow printing newline characters
    in --help output. The way we do this is a huge hack :(

    Inspiration: http://groups.google.com/group/comp.lang.python/browse_thread/thread/6df6e6b541a15bc2/09f28e26af0699b1
    '''
    oldwrap = None

    # pylint: disable=arguments-differ
    def _split_lines(self, *args, **kwargs):
        def return_default():
            return argparse.RawDescriptionHelpFormatter._split_lines(
                self, *args, **kwargs)

        if len(kwargs) != 0 and len(args) != 2:
            return return_default()  # pragma: no cover

        try:
            text = args[0]
            if "\n" in text:
                return text.splitlines()
            return return_default()
        except Exception:  # pragma: no cover
            return return_default()


def setupParser(usage, description, introspection_epilog=False):
    epilog = _("See man page for examples and full option syntax.")
    if introspection_epilog:
        epilog = _("Use '--option=?' or '--option help' to see "
            "available suboptions") + "\n" + epilog

    parser = argparse.ArgumentParser(
        usage=usage, description=description,
        formatter_class=VirtHelpFormatter,
        epilog=epilog)
    parser.add_argument('--version', action='version',
                        version=BuildConfig.version)

    return parser


def earlyLogging():
    reset_logging()
    import logging
    logging.basicConfig(level=logging.DEBUG, format='%(message)s')


def setupLogging(appname, debug_stdout, do_quiet, cli_app=True):
    _reset_global_state()
    get_global_state().quiet = do_quiet

    vi_dir = VirtinstConnection.get_app_cache_dir()
    logfile = os.path.join(vi_dir, appname + ".log")
    if xmlutil.in_testsuite():
        vi_dir = None
        logfile = None

    try:  # pragma: no cover
        if vi_dir and not os.access(vi_dir, os.W_OK):
            if os.path.exists(vi_dir):
                raise RuntimeError("No write access to directory %s" % vi_dir)

            try:
                os.makedirs(vi_dir, 0o751)
            except IOError as e:
                raise RuntimeError("Could not create directory %s: %s" %
                                   (vi_dir, e)) from None

        if (logfile and
            os.path.exists(logfile) and
            not os.access(logfile, os.W_OK)):
            raise RuntimeError("No write access to logfile %s" % logfile)
    except Exception as e:  # pragma: no cover
        log.warning("Error setting up logfile: %s", e)
        logfile = None

    dateFormat = "%a, %d %b %Y %H:%M:%S"
    fileFormat = ("[%(asctime)s " + appname + " %(process)d] "
                  "%(levelname)s (%(module)s:%(lineno)d) %(message)s")
    streamErrorFormat = "%(levelname)-8s %(message)s"

    import logging
    import logging.handlers
    reset_logging()

    log.setLevel(logging.DEBUG)
    if logfile:
        fileHandler = logging.handlers.RotatingFileHandler(
            logfile, "ae", 1024 * 1024, 5)
        fileHandler.setFormatter(
            logging.Formatter(fileFormat, dateFormat))
        log.addHandler(fileHandler)

    streamHandler = logging.StreamHandler(sys.stderr)
    if debug_stdout:
        streamHandler.setLevel(logging.DEBUG)
        streamHandler.setFormatter(logging.Formatter(fileFormat,
                                                     dateFormat))
    elif cli_app or not logfile:
        # Have cli tools show WARN/ERROR by default
        if get_global_state().quiet:
            level = logging.ERROR
        else:
            level = logging.WARN
        streamHandler.setLevel(level)
        streamHandler.setFormatter(logging.Formatter(streamErrorFormat))
    else:  # pragma: no cover
        streamHandler = None

    if streamHandler:
        log.addHandler(streamHandler)

    # Log uncaught exceptions
    def exception_log(typ, val, tb):  # pragma: no cover
        log.debug("Uncaught exception:\n%s",
                      "".join(traceback.format_exception(typ, val, tb)))
        if not debug_stdout:
            # If we are already logging to stdout, don't double print
            # the backtrace
            sys.__excepthook__(typ, val, tb)
    sys.excepthook = exception_log

    # Log the app command string
    log.debug("Launched with command line: %s", " ".join(sys.argv))


##############################
# Libvirt connection helpers #
##############################

def getConnection(uri, conn=None):
    if conn:
        # preopened connection passed in via test suite
        return conn

    log.debug("Requesting libvirt URI %s", (uri or "default"))
    conn = VirtinstConnection(uri)
    conn.open(_openauth_cb, None)
    log.debug("Received libvirt URI %s", conn.uri)

    return conn


def _openauth_cb(creds, _cbdata):  # pragma: no cover
    for cred in creds:
        # Libvirt virConnectCredential
        credtype, prompt, _challenge, _defresult, _result = cred
        noecho = credtype in [
                libvirt.VIR_CRED_PASSPHRASE, libvirt.VIR_CRED_NOECHOPROMPT]
        if not prompt:
            log.error("No prompt for auth credtype=%s", credtype)
            return -1
        log.debug("openauth_cb prompt=%s", prompt)

        prompt += ": "
        if noecho:
            import getpass
            res = getpass.getpass(prompt)
        else:
            res = input(prompt)

        # Overwriting 'result' is how we return values to libvirt
        cred[-1] = res
    return 0


##############################
# Misc CLI utility functions #
##############################

def fail(msg, do_exit=True):
    """
    Convenience function when failing in cli app
    """
    log.debug("".join(traceback.format_stack()))
    log.error(msg)
    if sys.exc_info()[0] is not None:
        log.debug("", exc_info=True)
    if do_exit:
        _fail_exit()


def print_stdout(msg, do_force=False, do_log=True):
    if do_log:
        log.debug(msg)
    if do_force or not get_global_state().quiet or not do_log:
        print(msg)


def print_stderr(msg):
    log.debug(msg)
    print(msg, file=sys.stderr)


def _fail_exit():
    sys.exit(1)


def virsh_start_cmd(guest):
    return ("virsh --connect %s start %s" % (guest.conn.uri, guest.name))


def install_fail(guest):
    virshcmd = virsh_start_cmd(guest)

    print_stderr(
        _("Domain installation does not appear to have been successful.\n"
          "If it was, you can restart your domain by running:\n"
          "  %s\n"
          "otherwise, please restart your installation.") % virshcmd)
    sys.exit(1)


def set_prompt(prompt):
    # Set whether we allow prompts, or fail if a prompt pops up
    if prompt:
        log.warning("--prompt mode is no longer supported.")


def check_path_search(conn, path):
    searchdata = DeviceDisk.check_path_search(conn, path)
    if not searchdata.fixlist:
        return
    msg = (  # pragma: no cover
        _("%(path)s may not be accessible by the hypervisor. "
        "You will need to grant the '%(user)s' user search permissions for "
        "the following directories: %(dirs)s") %
        {"path": path, "user": searchdata.user, "dirs": searchdata.fixlist})
    log.warning(msg)  # pragma: no cover


def _optional_fail(msg, checkname, warn_on_skip=True):
    """
    Handle printing a message with an associated --check option
    """
    do_check = get_global_state().get_validation_check(checkname)
    if do_check:
        fail(msg + (_(" (Use --check %s=off or "
            "--check all=off to override)") % checkname))

    log.debug("Skipping --check %s error condition '%s'",
        checkname, msg)
    if warn_on_skip:
        log.warning(msg)


def validate_mac(conn, macaddr):
    """
    There's legitimate use cases for creating/cloning VMs with duplicate
    MACs, so we do the collision check here but allow it to be skipped
    with --check
    """
    try:
        DeviceInterface.check_mac_in_use(conn, macaddr)
        return
    except Exception as e:
        _optional_fail(str(e), "mac_in_use")


def validate_disk(dev, warn_overwrite=False):
    path = dev.get_source_path()

    def check_path_exists():
        """
        Prompt if disk file already exists and preserve mode is not used
        """
        if not warn_overwrite:
            return
        if not DeviceDisk.path_definitely_exists(dev.conn, path):
            return
        _optional_fail(
            _("This will overwrite the existing path '%s'") % path,
            "path_exists")

    def check_inuse_conflict():
        """
        Check if disk is inuse by another guest
        """
        names = dev.is_conflict_disk()
        if not names:
            return

        msg = (_("Disk %(path)s is already in use by other guests %(names)s.") %
            {"path": path, "names": names})
        _optional_fail(msg, "path_in_use")

    def check_size_conflict():
        """
        Check if specified size exceeds available storage
        """
        isfatal, errmsg = dev.is_size_conflict()
        # The isfatal case should have already caused us to fail
        if not isfatal and errmsg:
            _optional_fail(errmsg, "disk_size", warn_on_skip=False)

    check_path_exists()
    check_inuse_conflict()
    check_size_conflict()
    check_path_search(dev.conn, path)


def _run_console(message, args):
    log.debug("Running: %s", " ".join(args))
    argstr = " ".join([shlex.quote(a) for a in args])
    print_stdout(message % {"command": argstr})

    if xmlutil.in_testsuite():
        args = ["/bin/test"]

    child = os.fork()
    if child:
        return child

    # pylint: disable=protected-access
    try:  # pragma: no cover
        os.execvp(args[0], args)
    except Exception as e:  # pragma: no cover
        print("Error launching %s: %s" % (args, e))
    finally:
        os._exit(1)  # pragma: no cover


def _gfx_console(guest):
    args = ["virt-viewer",
            "--connect", guest.conn.uri,
            "--wait", guest.name]
    message = _("Running graphical console command: %(command)s")

    # Currently virt-viewer needs attaching to the local display while
    # spice gl is enabled or listen type none is used.
    if guest.has_gl() or guest.has_listen_none():
        args.append("--attach")

    return _run_console(message, args)


def _txt_console(guest):
    args = ["virsh",
            "--connect", guest.conn.uri,
            "console", guest.name]
    message = _("Running text console command: %(command)s")

    return _run_console(message, args)


def get_meter():
    import virtinst.progress
    quiet = (get_global_state().quiet or xmlutil.in_testsuite())
    return virtinst.progress.make_meter(quiet=quiet)


def get_xmldesc(domain, inactive=False):
    flags = libvirt.VIR_DOMAIN_XML_SECURE
    if inactive:
        flags |= libvirt.VIR_DOMAIN_XML_INACTIVE
    return domain.XMLDesc(flags)


def get_domain_and_guest(conn, domstr):
    try:
        int(domstr)
        isint = True
    except ValueError:
        isint = False

    uuidre = "[a-fA-F0-9]{8}[-]([a-fA-F0-9]{4}[-]){3}[a-fA-F0-9]{12}$"
    isuuid = bool(re.match(uuidre, domstr))

    try:
        domain = None
        try:
            domain = conn.lookupByName(domstr)
        except Exception:
            # In case the VM has a UUID or ID for a name
            log.debug("Error looking up domain by name", exc_info=True)
            if isint:
                domain = conn.lookupByID(int(domstr))
            elif isuuid:
                domain = conn.lookupByUUIDString(domstr)
            else:
                raise
    except libvirt.libvirtError as e:
        fail(_("Could not find domain '%(domain)s': %(error)s") % {
                 "domain": domstr,
                 "error": str(e),
             })

    state = domain.info()[0]
    active_xmlobj = None
    inactive_xmlobj = Guest(conn, parsexml=get_xmldesc(domain))
    if state != libvirt.VIR_DOMAIN_SHUTOFF:
        active_xmlobj = inactive_xmlobj
        inactive_xmlobj = Guest(conn,
                parsexml=get_xmldesc(domain, inactive=True))

    return (domain, inactive_xmlobj, active_xmlobj)


def fail_conflicting(option1, option2):
    # translators: option1 and option2 are command line options,
    # e.g. -a or --disk
    msg = _("Cannot use %(option1)s and %(option2)s at the same time") % {
        "option1": option1,
        "option2": option2,
    }
    fail(msg)


###########################
# bash completion helpers #
###########################

def _get_completer_parsers():
    return VIRT_PARSERS + [ParserCheck, ParserLocation,
            ParserUnattended, ParserInstall, ParserCloudInit, ParserXML,
            ParserOSVariant]


def _virtparser_completer(prefix, **kwargs):
    sub_options = []
    for parserclass in _get_completer_parsers():
        if kwargs['action'].dest == parserclass.cli_arg_name:
            # pylint: disable=protected-access
            for virtarg in sorted(parserclass._virtargs,
                                  key=lambda p: p.nonregex_cliname()):
                sub_options.append(virtarg.nonregex_cliname() + "=")

    entered_options = prefix.split(",")
    for option in entered_options:
        pos = option.find("=")
        if pos > 0 and option[: pos + 1] in sub_options:
            sub_options.remove(option[: pos + 1])
    return sub_options


def _completer_validator(suboption, current_input):
    """
    :param suboption: The virtarg.cliname we are checking for a match
    :param current_input: The user typed string we are checking against.
        So if the user types '--disk path=foo,dev<TAB>',
        current_input=='path=foo,dev'

    For debugging here, 'export _ARC_DEBUG=1'. Now exceptions/printing
    will be shown on stderr
    """
    # e.g. for: --disk <TAB><TAB>  (return all suboptions)
    if current_input == "":
        return True

    # e.g. for: --disk path=foo,<TAB><TAB>  (return all suboptions)
    #       or: --disk path=foo,de<TAB>TAB> (return all 'de*' options)
    current_option = current_input.rsplit(",", 1)[-1]
    return suboption.startswith(current_option)


def autocomplete(parser):
    if "_ARGCOMPLETE" not in os.environ:
        return

    import argcomplete
    import unittest.mock

    parsernames = [pclass.cli_flag_name() for pclass in
                   _get_completer_parsers()]
    # pylint: disable=protected-access
    for action in parser._actions:
        for opt in action.option_strings:
            if opt in parsernames:
                action.completer = _virtparser_completer
                break

    kwargs = {"validator": _completer_validator}
    if xmlutil.in_testsuite():
        import io
        kwargs["output_stream"] = io.BytesIO()
        kwargs["exit_method"] = sys.exit

    # This fdopen hackery is to avoid argcomplete debug_stream behavior
    # from taking over an fd that pytest wants to use
    fake_fdopen = os.fdopen
    if xmlutil.in_testsuite():
        def fake_fdopen_cb(*args, **kwargs):
            return sys.stderr
        fake_fdopen = fake_fdopen_cb

    with unittest.mock.patch.object(os, "fdopen", fake_fdopen):
        try:
            argcomplete.autocomplete(parser, **kwargs)
        except SystemExit:
            if xmlutil.in_testsuite():
                output = kwargs["output_stream"].getvalue().decode("utf-8")
                print(output)
            raise


###########################
# Common CLI option/group #
###########################

def add_connect_option(parser, invoker=None):
    if invoker == "virt-xml":
        parser.add_argument("-c", "--connect", metavar="URI",
                help=_("Connect to hypervisor with libvirt URI"))
    else:
        parser.add_argument("--connect", metavar="URI",
                help=_("Connect to hypervisor with libvirt URI"))


def add_misc_options(grp, prompt=False, replace=False,
                     printxml=False, printstep=False,
                     noreboot=False, dryrun=False,
                     noautoconsole=False):
    if prompt:
        grp.add_argument("--prompt", action="store_true",
                        default=False, help=argparse.SUPPRESS)
        grp.add_argument("--force", action="store_true",
                        default=False, help=argparse.SUPPRESS)

    if noautoconsole:
        grp.add_argument("--autoconsole", default="default",
            help=_("Configure guest console auto connect. Example:\n"
                   "--autoconsole text\n"
                   "--autoconsole graphical\n"
                   "--autoconsole none"))
        grp.add_argument("--noautoconsole", dest="autoconsole",
            action="store_const", const="none",
            help=_("Don't automatically try to connect to the guest console"))

    if noreboot:
        grp.add_argument("--noreboot", action="store_true",
                       help=_("Don't boot guest after completing install."))

    if replace:
        grp.add_argument("--replace", action="store_true",
            help=_("Don't check name collision, overwrite any guest "
                   "with the same name."))

    if printxml:
        print_kwargs = {
            "dest": "xmlonly",
            "default": False,
            "help": _("Print the generated domain XML rather than create "
                "the guest."),
        }

        if printstep:
            print_kwargs["nargs"] = "?"
            print_kwargs["const"] = "all"
        else:
            print_kwargs["action"] = "store_true"

        grp.add_argument("--print-xml", **print_kwargs)
        if printstep:
            # Back compat, argparse allows us to use --print-xml
            # for everything.
            grp.add_argument("--print-step", dest="xmlstep",
                help=argparse.SUPPRESS)

    if dryrun:
        grp.add_argument("--dry-run", action="store_true", dest="dry",
                       help=_("Run through install process, but do not "
                              "create devices or define the guest."))

    if prompt:
        grp.add_argument("--check", action="append",
            help=_("Enable or disable validation checks. Example:\n"
                   "--check path_in_use=off\n"
                   "--check all=off"))
    grp.add_argument("-q", "--quiet", action="store_true",
                   help=_("Suppress non-error output"))
    grp.add_argument("-d", "--debug", action="store_true",
                   help=_("Print debugging information"))


def add_metadata_option(grp):
    ParserMetadata.register()
    grp.add_argument("--metadata", action="append",
        help=_("Configure guest metadata. Ex:\n"
        "--metadata name=foo,title=\"My pretty title\",uuid=...\n"
        "--metadata description=\"My nice long description\""))


def add_memory_option(grp, backcompat=False):
    ParserMemory.register()
    grp.add_argument("--memory", action="append",
        help=_("Configure guest memory allocation. Ex:\n"
               "--memory 1024 (in MiB)\n"
               "--memory memory=1024,currentMemory=512\n"))
    if backcompat:
        grp.add_argument("-r", "--ram", type=int, dest="oldmemory",
            help=argparse.SUPPRESS)


def vcpu_cli_options(grp, backcompat=True, editexample=False):
    # The order of the parser registration is important here!
    ParserCPU.register()
    ParserVCPU.register()
    grp.add_argument("--vcpus", action="append",
        help=_("Number of vCPUs to configure for your guest. Ex:\n"
               "--vcpus 5\n"
               "--vcpus 5,maxvcpus=10,cpuset=1-4,6,8\n"
               "--vcpus sockets=2,cores=4,threads=2"))

    extramsg = "--cpu host"
    if editexample:
        extramsg = "--cpu host-model,clearxml=yes"
    grp.add_argument("--cpu", action="append",
        help=_("CPU model and features. Ex:\n"
               "--cpu coreduo,+x2apic\n"
               "--cpu host-passthrough\n") + extramsg)

    if backcompat:
        grp.add_argument("--check-cpu", action="store_true",
                         help=argparse.SUPPRESS)
        grp.add_argument("--cpuset", help=argparse.SUPPRESS)


def add_gfx_option(devg):
    ParserGraphics.register()
    devg.add_argument("--graphics", action="append",
      help=_("Configure guest display settings. Ex:\n"
             "--graphics spice\n"
             "--graphics vnc,port=5901,listen=0.0.0.0\n"
             "--graphics none\n"))


def add_net_option(devg):
    ParserNetwork.register()
    devg.add_argument("-w", "--network", action="append",
      help=_("Configure a guest network interface. Ex:\n"
             "--network bridge=mybr0\n"
             "--network network=my_libvirt_virtual_net\n"
             "--network network=mynet,model=virtio,mac=00:11...\n"
             "--network none\n"
             "--network help"))


def add_device_options(devg, sound_back_compat=False):
    ParserController.register()
    devg.add_argument("--controller", action="append",
        help=_("Configure a guest controller device. Ex:\n"
               "--controller type=usb,model=qemu-xhci\n"
               "--controller virtio-scsi\n"))
    ParserInput.register()
    devg.add_argument("--input", action="append",
        help=_("Configure a guest input device. Ex:\n"
               "--input tablet\n"
               "--input keyboard,bus=usb"))
    ParserSerial.register()
    devg.add_argument("--serial", action="append",
                    help=_("Configure a guest serial device"))
    ParserParallel.register()
    devg.add_argument("--parallel", action="append",
                    help=_("Configure a guest parallel device"))
    ParserChannel.register()
    devg.add_argument("--channel", action="append",
                    help=_("Configure a guest communication channel"))
    ParserConsole.register()
    devg.add_argument("--console", action="append",
                    help=_("Configure a text console connection between "
                           "the guest and host"))
    ParserHostdev.register()
    devg.add_argument("--hostdev", action="append",
                    help=_("Configure physical USB/PCI/etc host devices "
                           "to be shared with the guest"))
    # Back compat name
    devg.add_argument("--host-device", action="append", dest="hostdev",
                    help=argparse.SUPPRESS)

    ParserFilesystem.register()
    devg.add_argument("--filesystem", action="append",
        help=_("Pass host directory to the guest. Ex: \n"
               "--filesystem /my/source/dir,/dir/in/guest\n"
               "--filesystem template_name,/,type=template"))

    ParserSound.register()
    # --sound used to be a boolean option, hence the nargs handling
    sound_kwargs = {
        "action": "append",
        "help": _("Configure guest sound device emulation"),
    }
    if sound_back_compat:
        sound_kwargs["nargs"] = '?'
    devg.add_argument("--sound", **sound_kwargs)
    if sound_back_compat:
        devg.add_argument("--soundhw", action="append", dest="sound",
            help=argparse.SUPPRESS)

    ParserWatchdog.register()
    devg.add_argument("--watchdog", action="append",
                    help=_("Configure a guest watchdog device"))
    ParserVideo.register()
    devg.add_argument("--video", action="append",
                    help=_("Configure guest video hardware."))
    ParserSmartcard.register()
    devg.add_argument("--smartcard", action="append",
                    help=_("Configure a guest smartcard device. Ex:\n"
                           "--smartcard mode=passthrough"))
    ParserRedir.register()
    devg.add_argument("--redirdev", action="append",
                    help=_("Configure a guest redirection device. Ex:\n"
                           "--redirdev usb,type=tcp,server=192.168.1.1:4000"))
    ParserMemballoon.register()
    devg.add_argument("--memballoon", action="append",
                    help=_("Configure a guest memballoon device. Ex:\n"
                           "--memballoon model=virtio"))
    ParserTPM.register()
    devg.add_argument("--tpm", action="append",
                    help=_("Configure a guest TPM device. Ex:\n"
                           "--tpm /dev/tpm"))
    ParserRNG.register()
    devg.add_argument("--rng", action="append",
                    help=_("Configure a guest RNG device. Ex:\n"
                           "--rng /dev/urandom"))
    ParserPanic.register()
    devg.add_argument("--panic", action="append",
                    help=_("Configure a guest panic device. Ex:\n"
                           "--panic default"))
    ParserMemdev.register()
    devg.add_argument("--memdev", action="append",
                    help=_("Configure a guest memory device. Ex:\n"
                           "--memdev dimm,target.size=1024"))
    ParserVsock.register()
    devg.add_argument("--vsock", action="append",
                    help=_("Configure guest vsock sockets. Ex:\n"
                           "--vsock cid.auto=yes\n"
                           "--vsock cid.address=7"))
    ParserIommu.register()
    devg.add_argument("--iommu", action="append",
                    help=_("Configure an IOMMU device. Ex:\n"
                           "--iommu model=intel,driver.aw_bits=48"))


def add_guest_xml_options(geng):
    ParserIOThreads.register()
    geng.add_argument("--iothreads", action="append",
        help=_("Set domain <iothreads> and <iothreadids> configuration."))

    ParserSeclabel.register()
    geng.add_argument("--seclabel", "--security", action="append",
        help=_("Set domain seclabel configuration."))

    ParserKeyWrap.register()
    geng.add_argument("--keywrap", action="append",
        help=_("Set guest to perform the S390 cryptographic "
               "key management operations."))

    ParserCputune.register()
    geng.add_argument("--cputune", action="append",
        help=_("Tune CPU parameters for the domain process."))

    ParserNumatune.register()
    geng.add_argument("--numatune", action="append",
        help=_("Tune NUMA policy for the domain process."))

    ParserMemtune.register()
    geng.add_argument("--memtune", action="append",
        help=_("Tune memory policy for the domain process."))

    ParserBlkiotune.register()
    geng.add_argument("--blkiotune", action="append",
        help=_("Tune blkio policy for the domain process."))

    ParserMemoryBacking.register()
    geng.add_argument("--memorybacking", action="append",
        help=_("Set memory backing policy for the domain process. Ex:\n"
               "--memorybacking hugepages=on"))

    ParserFeatures.register()
    geng.add_argument("--features", action="append",
        help=_("Set domain <features> XML. Ex:\n"
               "--features acpi=off\n"
               "--features apic=on,apic.eoi=on"))

    ParserClock.register()
    geng.add_argument("--clock", action="append",
        help=_("Set domain <clock> XML. Ex:\n"
               "--clock offset=localtime,rtc_tickpolicy=catchup"))

    ParserPM.register()
    geng.add_argument("--pm", action="append",
        help=_("Configure VM power management features"))

    ParserEvents.register()
    geng.add_argument("--events", action="append",
        help=_("Configure VM lifecycle management policy"))

    ParserResource.register()
    geng.add_argument("--resource", action="append",
        help=_("Configure VM resource partitioning (cgroups)"))

    ParserSysinfo.register()
    geng.add_argument("--sysinfo", action="append",
        help=_("Configure SMBIOS System Information. Ex:\n"
               "--sysinfo host\n"
               "--sysinfo bios.vendor=MyVendor,bios.version=1.2.3,...\n"))

    ParserQemuCLI.register()
    geng.add_argument("--qemu-commandline", action="append",
        help=_("Pass arguments directly to the QEMU emulator. Ex:\n"
               "--qemu-commandline='-display gtk,gl=on'\n"
               "--qemu-commandline env=DISPLAY=:0.1"))

    ParserLaunchSecurity.register()
    geng.add_argument("--launchSecurity", "--launchsecurity", action="append",
        help=_("Configure VM launch security (e.g. SEV memory encryption). Ex:\n"
               "--launchSecurity type=sev,cbitpos=47,reducedPhysBits=1,policy=0x0001,dhCert=BASE64CERT\n"
               "--launchSecurity sev"))


def add_boot_options(insg):
    ParserBoot.register()
    insg.add_argument("--boot", action="append",
        help=_("Configure guest boot settings. Ex:\n"
               "--boot hd,cdrom,menu=on\n"
               "--boot init=/sbin/init (for containers)"))

    ParserIdmap.register()
    insg.add_argument("--idmap", action="append",
        help=_("Enable user namespace for LXC container. Ex:\n"
               "--idmap uid.start=0,uid.target=1000,uid.count=10"))


def add_disk_option(stog, editexample=False):
    ParserDisk.register()
    editmsg = ""
    if editexample:
        editmsg += "\n--disk cache=  (unset cache)"
    stog.add_argument("--disk", action="append",
        help=_("Specify storage with various options. Ex.\n"
               "--disk size=10 (new 10GiB image in default location)\n"
               "--disk /my/existing/disk,cache=none\n"
               "--disk device=cdrom,bus=scsi\n"
               "--disk=?") + editmsg)


def add_os_variant_option(parser, virtinstall):
    osg = parser.add_argument_group(_("OS options"))

    if virtinstall:
        msg = _("The OS being installed in the guest.")
    else:
        msg = _("The OS installed in the guest.")
    msg += "\n"
    msg += _("This is used for deciding optimal defaults like VirtIO.\n"
             "Example values: fedora29, rhel7.0, win10, ...\n"
             "See 'osinfo-query os' for a full list.")

    osg.add_argument("--os-variant", "--osinfo", help=msg)
    return osg


def add_xml_option(grp):
    grp.add_argument("--xml", action="append", default=[],
            help=_("Perform raw XML XPath options on the final XML. Example:\n"
                   "--xml ./cpu/@mode=host-passthrough\n"
                   "--xml ./devices/disk[2]/serial=new-serial\n"
                   "--xml xpath.delete=./clock"))


#############################################
# CLI complex parsing helpers               #
# (for options like --disk, --network, etc. #
#############################################

def _raw_on_off_convert(s):
    tvalues = ["y", "yes", "1", "true", "t", "on"]
    fvalues = ["n", "no", "0", "false", "f", "off"]

    s = (s or "").lower()
    if s in tvalues:
        return True
    elif s in fvalues:
        return False
    return None


def _on_off_convert(key, val):
    if val is None:
        return None

    val = _raw_on_off_convert(val)
    if val is not None:
        return val
    raise fail(_("%(key)s must be 'yes' or 'no'") % {"key": key})


class _SuboptCheckerClass:
    """
    Used by the test suite to ensure we actually test all cli suboptions
    """
    def __init__(self):
        self._all = set()
        self._seen = set()

    def add_all(self, name):
        self._all.add(name)

    def add_seen(self, name):
        self._seen.add(name)

    def get_unseen(self):
        return self._all - self._seen


_SuboptChecker = _SuboptCheckerClass()


class _VirtCLIArgumentStatic(object):
    """
    Helper class to hold all of the static data we need for knowing
    how to parse a cli subargument, like --disk path=, or --network mac=.

    @cliname: The command line option name, 'path' for path=FOO
    @propname: The virtinst API attribute name the cliargument maps to.
    @cb: Rather than set a virtinst object property directly, use
        this callback instead. It should have the signature:
        cb(parser, inst, val, virtarg)

    @ignore_default: If the value passed on the cli is 'default', don't
        do anything.
    @can_comma: If True, this option is expected to have embedded commas.
        After the parser sees this option, it will iterate over the
        option string until it finds another known argument name:
        everything prior to that argument name is considered part of
        the value of this option, '=' included. Should be used sparingly.
    @is_onoff: The value expected on the cli is on/off or yes/no, convert
        it to true/false.
    @lookup_cb: If specified, use this function for performing match
        lookups.
    @find_inst_cb: If specified, this can be used to return a different
        'inst' to check and set attributes against. For example,
        DeviceDisk has multiple seclabel children, this provides a hook
        to lookup the specified child object.
    """
    def __init__(self, cliname, propname, parent_cliname,
                 cb=None, can_comma=None,
                 ignore_default=False, is_onoff=False,
                 lookup_cb=-1, find_inst_cb=None):
        self.cliname = cliname
        self.propname = propname
        self.cb = cb
        self.can_comma = can_comma
        self.ignore_default = ignore_default
        self.is_onoff = is_onoff
        self.lookup_cb = lookup_cb
        self.find_inst_cb = find_inst_cb
        self._parent_cliname = parent_cliname
        self._aliases = []

        if not self.propname and not self.cb:
            raise xmlutil.DevError("propname or cb must be specified.")

        if not self.propname and self.lookup_cb == -1:
            raise xmlutil.DevError(
                "cliname=%s propname is None but lookup_cb is not specified. "
                "Even if a 'cb' is passed, 'propname' is still used for "
                "device lookup for virt-xml --edit.\n\nIf cb is just "
                "a converter function for a single propname, then set "
                "both propname and cb. If this cliname is truly "
                "not backed by a single propname, set lookup_cb=None or "
                "better yet implement a lookup_cb. This message is here "
                "to ensure propname isn't omitted without understanding "
                "the distinction." % self.cliname)

        if self.lookup_cb == -1:
            self.lookup_cb = None
        _SuboptChecker.add_all(self._testsuite_argcheck_name(self.cliname))

    def _testsuite_argcheck_name(self, cliname):
        if not self._parent_cliname:
            return "sharedoption %s" % cliname
        return "--%s %s" % (self._parent_cliname, cliname)

    def set_aliases(self, aliases):
        self._aliases = aliases
        for alias in self._aliases:
            _SuboptChecker.add_all(self._testsuite_argcheck_name(alias))

    def nonregex_cliname(self):
        return self.cliname.replace("[0-9]*", "")

    def match_name(self, userstr):
        """
        Return True if the passed user string matches this
        VirtCLIArgument. So for an option like --foo bar=X, this
        checks if we are the parser for 'bar'
        """
        for cliname in [self.cliname] + xmlutil.listify(self._aliases):
            if "[" in cliname:
                ret = re.match("^%s$" % cliname.replace(".", r"\."), userstr)
            else:
                ret = (cliname == userstr)
            if ret:
                _SuboptChecker.add_seen(self._testsuite_argcheck_name(cliname))
                return True
        return False


class _VirtCLIArgument(object):
    """
    A class that combines the static parsing data _VirtCLIArgumentStatic
    with actual values passed on the command line.
    """

    def __init__(self, virtarg, key, val):
        """
        Instantiate a VirtCLIArgument with the actual key=val pair
        from the command line.
        """
        if val is None:
            # When a command line tuple option has no value set, say
            #   --network bridge=br0,model=virtio
            # is instead called
            #   --network bridge=br0,model
            # We error that 'model' didn't have a value
            raise RuntimeError("Option '%s' had no value set." % key)
        if val == "":
            val = None
        if virtarg.is_onoff:
            val = _on_off_convert(key, val)

        self.val = val
        self.key = key
        self._virtarg = virtarg

        # For convenience
        self.propname = virtarg.propname
        self.cliname = virtarg.cliname

    def parse_param(self, parser, inst):
        """
        Process the cli param against the pass inst.

        So if we are VirtCLIArgument for --disk device=, and the user
        specified --disk device=foo, we were instantiated with
        key=device val=foo, so set inst.device = foo
        """
        if self.val == "default" and self._virtarg.ignore_default:
            return

        if self._virtarg.find_inst_cb:
            inst = self._virtarg.find_inst_cb(parser,
                                              inst, self.val, self,
                                              can_edit=True)

        try:
            if self.propname:
                xmlutil.get_prop_path(inst, self.propname)
        except AttributeError:  # pragma: no cover
            msg = "obj=%s does not have member=%s" % (inst, self.propname)
            raise xmlutil.DevError(msg) from None

        if self._virtarg.cb:
            self._virtarg.cb(parser, inst, self.val, self)
        else:
            xmlutil.set_prop_path(inst, self.propname, self.val)

    def lookup_param(self, parser, inst):
        """
        See if the passed value matches our Argument, like via virt-xml

        So if this Argument is for --disk device=, and the user
        specified virt-xml --edit device=floppy --disk ..., we were
        instantiated with key=device val=floppy, so return
        'inst.device == floppy'
        """
        if not self.propname and not self._virtarg.lookup_cb:
            raise RuntimeError(
                _("Don't know how to match device type '%(device_type)s' "
                  "property '%(property_name)s'") %
                {"device_type": getattr(inst, "DEVICE_TYPE", ""),
                 "property_name": self.key})

        if self._virtarg.find_inst_cb:
            inst = self._virtarg.find_inst_cb(parser,
                                              inst, self.val, self,
                                              can_edit=False)
            if not inst:
                return False

        if self._virtarg.lookup_cb:
            return self._virtarg.lookup_cb(parser,
                                           inst, self.val, self)
        else:
            return xmlutil.get_prop_path(inst, self.propname) == self.val


def parse_optstr_tuples(optstr):
    """
    Parse the command string into an ordered list of tuples. So
    a string like --disk path=foo,size=5,path=bar will end up like

    [("path", "foo"), ("size", "5"), ("path", "bar")]
    """
    argsplitter = shlex.shlex(optstr or "", posix=True)
    argsplitter.commenters = ""
    argsplitter.whitespace = ","
    argsplitter.whitespace_split = True
    ret = []

    for opt in list(argsplitter):
        if "=" in opt:
            cliname, val = opt.split("=", 1)
        else:
            cliname = opt
            val = None

        ret.append((cliname, val))
    return ret


def _parse_optstr_to_dict(optstr, virtargs, remove_first):
    """
    Parse the passed argument string into an OrderedDict WRT
    the passed list of VirtCLIArguments and their special handling.

    So for --disk path=foo,size=5, optstr is 'path=foo,size=5', and
    we return {"path": "foo", "size": "5"}
    """
    optdict = collections.OrderedDict()
    opttuples = parse_optstr_tuples(optstr)

    def _lookup_virtarg(cliname):
        for virtarg in virtargs:
            if virtarg.match_name(cliname):
                return virtarg

    def _consume_comma_arg(commaopt):
        while opttuples:
            cliname, val = opttuples[0]
            if _lookup_virtarg(cliname):
                # Next tuple is for an actual virtarg
                break

            # Next tuple is a continuation of the comma argument,
            # sum it up
            opttuples.pop(0)
            commaopt[1] += "," + cliname
            if val:
                commaopt[1] += "=" + val

        return commaopt

    # Splice in remove_first names upfront
    for idx, (cliname, val) in enumerate(opttuples):
        if val is not None or not remove_first:
            break
        opttuples[idx] = (remove_first.pop(0), cliname)

    while opttuples:
        cliname, val = opttuples.pop(0)
        virtarg = _lookup_virtarg(cliname)
        if not virtarg:
            optdict[cliname] = val
            continue

        if virtarg.can_comma:
            commaopt = _consume_comma_arg([cliname, val])
            cliname = commaopt[0]
            val = commaopt[1]

        optdict[cliname] = val

    return optdict


class _InitClass(type):
    """Metaclass for providing the _init_class function.

    This allows the customisation of class creation. Similar to
    '__init_subclass__' (see https://www.python.org/dev/peps/pep-0487/),
    but without giving us an explicit dep on python 3.6

    """
    def __new__(cls, *args, **kwargs):
        if len(args) != 3:
            return super().__new__(cls, *args)  # pragma: no cover
        name, bases, ns = args
        init = ns.get('_init_class')
        if isinstance(init, types.FunctionType):
            raise RuntimeError(  # pragma: no cover
                    "_init_class must be a @classmethod")
        self = super().__new__(cls, name, bases, ns)
        self._init_class(**kwargs)  # pylint: disable=protected-access

        # Check for leftover aliases
        if self.aliases:
            raise xmlutil.DevError(
                    "class=%s leftover aliases=%s" % (self, self.aliases))
        return self


class VirtCLIParser(metaclass=_InitClass):
    """
    Parse a compound arg string like --option foo=bar,baz=12. This is
    the desired interface to VirtCLIArgument and VirtCLIOptionString.

    A command line argument like --disk just extends this interface
    and calls add_arg a bunch to register subarguments like path=,
    size=, etc. See existing impls examples of how to do all sorts of
    crazy stuff.

    Class parameters:
    @guest_propname: The property name in the Guest class that tracks
        the object type that backs this parser. For example, the --sound
        option maps to DeviceSound, which on the guest class is at
        guest.devices.sound, so guest_propname = "devices.sound"
    @remove_first: List of parameters to peel off the front of the
        option string, and store in the optdict. So:
        remove_first=["char_type"] for --serial pty,foo=bar
        maps to {"char_type", "pty", "foo": "bar"}
    @stub_none: If the parsed option string is just 'none', make it a no-op.
        This helps us be backwards compatible: for example, --rng none is
        a no-op, but one day we decide to add an rng device by default to
        certain VMs, and --rng none is extended to handle that. --rng none
        can be added to users command lines and it will give the expected
        results regardless of the virt-install version.
    @cli_arg_name: The command line argument this maps to, so
        "hostdev" for --hostdev
    """
    guest_propname = None
    remove_first = None
    stub_none = True
    cli_arg_name = None
    _virtargs = []
    aliases = {}
    supports_clearxml = True

    @classmethod
    def add_arg(cls, cliname, propname, *args, **kwargs):
        """
        Add a VirtCLIArgument for this class.

        :param skip_testsuite_tracking: Special argument handled here. If True,
            if means the argument is shared among multiple cli commands.
            Don't insist that each instance has full testsuite coverage.
        """
        if not cls._virtargs:
            cls._virtargs = []
            if cls.supports_clearxml:
                clearxmlvirtarg = _VirtCLIArgumentStatic(
                    "clearxml", None, None,
                    cb=cls._clearxml_cb, lookup_cb=None,
                    is_onoff=True)
                cls._virtargs.append(clearxmlvirtarg)

        parent_cliname = cls.cli_arg_name
        if kwargs.pop("skip_testsuite_tracking", False):
            parent_cliname = None

        virtarg = _VirtCLIArgumentStatic(cliname, propname, parent_cliname,
                *args, **kwargs)
        if virtarg.cliname in cls.aliases:
            virtarg.set_aliases(xmlutil.listify(cls.aliases.pop(virtarg.cliname)))
        cls._virtargs.append(virtarg)

    @classmethod
    def cli_flag_name(cls):
        return "--" + cls.cli_arg_name.replace("_", "-")

    @classmethod
    def print_introspection(cls):
        """
        Print out all _param names, triggered via ex. --disk help
        """
        def _sortkey(virtarg):
            prefix = ""
            if virtarg.cliname == "clearxml":
                prefix = "0"
            if virtarg.cliname.startswith("address."):
                prefix = "1"
            return prefix + virtarg.cliname

        print("%s options:" % cls.cli_flag_name())
        for arg in sorted(cls._virtargs, key=_sortkey):
            print("  %s" % arg.cliname)
        print("")

    @classmethod
    def lookup_prop(cls, obj):
        """
        For the passed obj, return the equivalent of
        getattr(obj, cls.guest_propname), but handle '.' in the guest_propname
        """
        if not cls.guest_propname:
            return None  # pragma: no cover
        return xmlutil.get_prop_path(obj, cls.guest_propname)

    @classmethod
    def prop_is_list(cls, obj):
        inst = cls.lookup_prop(obj)
        return isinstance(inst, list)

    @classmethod
    def register(cls):
        # register the parser class only once
        if cls not in VIRT_PARSERS:
            VIRT_PARSERS.append(cls)

    @classmethod
    def _init_class(cls, **kwargs):
        """This method also terminates the super() chain"""

    def __init__(self, optstr, guest=None, editing=None):
        self.optstr = optstr
        self.guest = guest
        self.editing = editing
        self.optdict = _parse_optstr_to_dict(self.optstr,
                self._virtargs, xmlutil.listify(self.remove_first)[:])

    def _clearxml_cb(self, inst, val, virtarg):
        """
        Callback that handles virt-xml clearxml=yes|no magic
        """
        if not self.guest_propname:
            raise RuntimeError("Don't know how to clearxml for %s" %
                               self.cli_flag_name())
        if val is not True:
            return

        # If there's any opts remaining, leave the root stub element
        # in place with leave_stub=True, so virt-xml updates are done
        # in place.
        #
        # Example: --edit --cpu clearxml=yes should remove the <cpu>
        # block. But --edit --cpu clearxml=yes,model=foo should leave
        # a <cpu> stub in place, so that it gets model=foo in place,
        # otherwise the newly created cpu block gets appended to the
        # end of the domain XML, which gives an ugly diff
        inst.clear(leave_stub=("," in self.optstr))

    def _make_find_inst_cb(self, cliarg, list_propname):
        """
        Create a callback used for find_inst_cb command line lookup.

        :param cliarg: The cliarg string that is followed by an index.
            Example, for --disk seclabel[0-9]* mapping, this is 'seclabel'
        :param list_propname: The property name on the virtinst object that
            this parameter maps too. For the seclabel example, we want
            disk.seclabels, so this value is 'seclabels'
        """
        def cb(inst, val, virtarg, can_edit):
            ignore = val
            num = 0
            reg = re.search(r"%s(\d+)" % cliarg, virtarg.key)
            if reg:
                num = int(reg.groups()[0])

            if can_edit:
                while len(xmlutil.get_prop_path(inst, list_propname)) < (num + 1):
                    xmlutil.get_prop_path(inst, list_propname).add_new()
            try:
                return xmlutil.get_prop_path(inst, list_propname)[num]
            except IndexError:
                if not can_edit:
                    return None
                raise  # pragma: no cover
        return cb

    def _optdict_to_param_list(self, optdict):
        """
        Convert the passed optdict to a list of instantiated
        VirtCLIArguments to actually interact with
        """
        ret = []
        for virtargstatic in self._virtargs:
            for key in list(optdict.keys()):
                if virtargstatic.match_name(key):
                    arginst = _VirtCLIArgument(virtargstatic,
                                               key, optdict.pop(key))
                    ret.append(arginst)
        return ret

    def _check_leftover_opts(self, optdict):
        """
        Used to check if there were any unprocessed entries in the
        optdict after we should have emptied it. Like if the user
        passed an invalid argument such as --disk idontexist=foo
        """
        if optdict:
            fail(_("Unknown %(optionflag)s options: %(string)s") %
                    {"optionflag": self.cli_flag_name(),
                     "string": list(optdict.keys())})

    def _parse(self, inst):
        """
        Subclasses can hook into this to do any pre/post processing
        of the inst, or self.optdict
        """
        optdict = self.optdict.copy()
        for param in self._optdict_to_param_list(optdict):
            param.parse_param(self, inst)

        self._check_leftover_opts(optdict)
        return inst

    def parse(self, inst):
        """
        Main entry point. Iterate over self._virtargs, and serialize
        self.optdict into 'inst'.

        For virt-xml, 'inst' is the virtinst object we are editing,
        ex. a DeviceDisk from a parsed Guest object.
        For virt-install, 'inst' is None, and we will create a new
        inst for self.guest_propname, or edit a singleton object in place
        like Guest.features/DomainFeatures
        """
        if not self.optstr:
            return None
        if self.stub_none and self.optstr == "none":
            return None

        new_object = False
        if self.guest_propname and not inst:
            inst = self.lookup_prop(self.guest)
            new_object = self.prop_is_list(self.guest)
            if new_object:
                inst = inst.new()

        ret = []
        try:
            objs = self._parse(inst is None and self.guest or inst)
            for obj in xmlutil.listify(objs):
                if not self.editing and hasattr(obj, "validate"):
                    obj.validate()
                if not new_object:
                    continue
                if isinstance(obj, Device):
                    self.guest.add_device(obj)
                else:
                    self.guest.add_child(obj)

            ret += xmlutil.listify(objs)
        except Exception as e:
            log.debug("Exception parsing inst=%s optstr=%s",
                          inst, self.optstr, exc_info=True)
            fail(_("Error: %(cli_flag_name)s %(options)s: %(err)s") %
                    {"cli_flag_name": self.cli_flag_name(),
                     "options": self.optstr, "err": str(e)})

        return ret

    def lookup_child_from_option_string(self):
        """
        Given a passed option string, search the guests' child list
        for all objects which match the passed options.

        Used only by virt-xml --edit lookups
        """
        ret = []
        objlist = xmlutil.listify(self.lookup_prop(self.guest))

        try:
            for inst in objlist:
                optdict = self.optdict.copy()
                valid = True
                for param in self._optdict_to_param_list(optdict):
                    paramret = param.lookup_param(self, inst)
                    if paramret is False:
                        valid = False
                        break
                if valid:
                    ret.append(inst)
                self._check_leftover_opts(optdict)
        except Exception as e:
            log.debug("Exception parsing inst=%s optstr=%s",
                          inst, self.optstr, exc_info=True)
            fail(_("Error: %(cli_flag_name)s %(options)s: %(err)s") %
                    {"cli_flag_name": self.cli_flag_name(),
                     "options": self.optstr, "err": str(e)})

        return ret

    def noset_cb(self, inst, val, virtarg):
        """Do nothing callback"""


#################
# --xml parsing #
#################

class _XMLCLIInstance:
    """
    Helper class to parse --xml content into.
    Generates XMLManualAction which actually performs the work
    """
    def __init__(self):
        self.xpath_delete = None
        self.xpath_set = None
        self.xpath_create = None
        self.xpath_value = None

    def build_action(self):
        from .xmlbuilder import XMLManualAction
        if self.xpath_delete:
            return XMLManualAction(self.xpath_delete,
                    action=XMLManualAction.ACTION_DELETE)
        if self.xpath_create:
            return XMLManualAction(self.xpath_create,
                    action=XMLManualAction.ACTION_CREATE)

        xpath = self.xpath_set
        if self.xpath_value:
            val = self.xpath_value
        else:
            if "=" not in str(xpath):
                fail("%s: Setting xpath must be in the form of XPATH=VALUE" %
                        xpath)
            xpath, val = xpath.rsplit("=", 1)
        return XMLManualAction(xpath, val or None)


class ParserXML(VirtCLIParser):
    cli_arg_name = "xml"
    supports_clearxml = False

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("xpath.delete", "xpath_delete", can_comma=True)
        cls.add_arg("xpath.set", "xpath_set", can_comma=True)
        cls.add_arg("xpath.create", "xpath_create", can_comma=True)
        cls.add_arg("xpath.value", "xpath_value", can_comma=True)

    def _parse(self, inst):
        if not self.optstr.startswith("xpath."):
            self.optdict.clear()
            self.optdict["xpath.set"] = self.optstr

        super()._parse(inst)


def parse_xmlcli(guest, options):
    """
    Parse --xml option strings and add the resulting XMLManualActions
    to the Guest instance
    """
    for optstr in options.xml:
        inst = _XMLCLIInstance()
        ParserXML(optstr).parse(inst)
        manualaction = inst.build_action()
        guest.add_xml_manual_action(manualaction)


########################
# --unattended parsing #
########################

class ParserUnattended(VirtCLIParser):
    cli_arg_name = "unattended"
    supports_clearxml = False

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("profile", "profile")
        cls.add_arg("admin-password-file", "admin_password_file")
        cls.add_arg("user-login", "user_login")
        cls.add_arg("user-password-file", "user_password_file")
        cls.add_arg("product-key", "product_key")
        cls.add_arg("reg-login", "reg_login")


def parse_unattended(optstr):
    ret = UnattendedData()
    if optstr == 1:
        # This means bare --unattended, so there's nothing to parse
        return ret

    parser = ParserUnattended(optstr)
    if parser.parse(ret):
        return ret


###################
# --check parsing #
###################

def convert_old_force(options):
    if options.force:
        if not options.check:
            options.check = "all=off"
        del(options.force)


class ParserCheck(VirtCLIParser):
    cli_arg_name = "check"
    supports_clearxml = False

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("path_in_use", None, is_onoff=True,
                    cb=cls.set_cb, lookup_cb=None)
        cls.add_arg("disk_size", None, is_onoff=True,
                    cb=cls.set_cb, lookup_cb=None)
        cls.add_arg("path_exists", None, is_onoff=True,
                    cb=cls.set_cb, lookup_cb=None)
        cls.add_arg("mac_in_use", None, is_onoff=True,
                    cb=cls.set_cb, lookup_cb=None)
        cls.add_arg("all", "all_checks", is_onoff=True)

    def set_cb(self, inst, val, virtarg):
        # This sets properties on the _GlobalState objects
        inst.set_validation_check(virtarg.cliname, val)


def parse_check(checks):
    # Overwrite this for each parse
    for optstr in xmlutil.listify(checks):
        parser = ParserCheck(optstr)
        parser.parse(get_global_state())


#####################
# --install parsing #
#####################

class ParserInstall(VirtCLIParser):
    cli_arg_name = "install"
    remove_first = "os"
    supports_clearxml = False

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("bootdev", "bootdev", can_comma=True)
        cls.add_arg("kernel", "kernel", can_comma=True)
        cls.add_arg("initrd", "initrd", can_comma=True)
        cls.add_arg("kernel_args", "kernel_args", can_comma=True)
        cls.add_arg("kernel_args_overwrite", "kernel_args_overwrite",
                is_onoff=True)
        cls.add_arg("os", "os")
        cls.add_arg("no_install", "no_install", is_onoff=True)


class InstallData:
    def __init__(self):
        self.bootdev = None
        self.kernel = None
        self.initrd = None
        self.kernel_args = None
        self.kernel_args_overwrite = None
        self.os = None
        self.is_set = False
        self.no_install = None


def parse_install(optstr):
    installdata = InstallData()
    installdata.is_set = bool(optstr)
    parser = ParserInstall(optstr or None)
    parser.parse(installdata)
    return installdata


########################
# --cloud-init parsing #
########################

class ParserCloudInit(VirtCLIParser):
    cli_arg_name = "cloud_init"
    supports_clearxml = False

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("root-password-generate", "root_password_generate", is_onoff=True)
        cls.add_arg("root-password-file", "root_password_file")
        cls.add_arg("disable", "disable", is_onoff=True)
        cls.add_arg("ssh-key", "ssh_key")
        cls.add_arg("user-data", "user_data")
        cls.add_arg("meta-data", "meta_data")


def parse_cloud_init(optstr):
    ret = CloudInitData()
    if optstr == 1:
        # This means bare --cloud-init, so there's nothing to parse.
        log.warning("Defaulting to --cloud-init root-password-generate=yes,disable=yes")
        ret.root_password_generate = True
        ret.disable = True
        return ret

    parser = ParserCloudInit(optstr)
    if parser.parse(ret):
        return ret


######################
# --location parsing #
######################

class ParserLocation(VirtCLIParser):
    cli_arg_name = "location"
    remove_first = "location"
    supports_clearxml = False

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("location", "location", can_comma=True)
        cls.add_arg("kernel", "kernel", can_comma=True)
        cls.add_arg("initrd", "initrd", can_comma=True)


def parse_location(optstr):
    class LocationData:
        def __init__(self):
            self.location = None
            self.kernel = None
            self.initrd = None
    parsedata = LocationData()
    parser = ParserLocation(optstr or None)
    parser.parse(parsedata)

    return parsedata.location, parsedata.kernel, parsedata.initrd


########################
# --os-variant parsing #
########################

class OSVariantData(object):
    def __init__(self):
        self._name = None
        self._id = None
        self._detect = False
        self._require = False

    def set_compat_str(self, rawstr):
        if rawstr is None or rawstr == "auto":
            # The default behavior
            self._detect = True
            return

        if rawstr == "none":
            self._name = "generic"
        elif "://" in rawstr:
            self._id = rawstr
        else:
            self._name = rawstr

    def validate(self):
        osobj = None
        if self._id:
            osobj = OSDB.lookup_os_by_full_id(self._id, raise_error=True)
        elif self._name:
            osobj = OSDB.lookup_os(self._name, raise_error=True)
        if osobj:
            self._name = osobj.name

    def is_generic_requested(self):
        return self._detect is False or self._name == "generic"
    def is_detect(self):
        return self._detect
    def is_require(self):
        return self._require
    def get_name(self):
        return self._name


class ParserOSVariant(VirtCLIParser):
    cli_arg_name = "os_variant"
    supports_clearxml = False

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("name", "_name")
        cls.add_arg("short-id", "_name")
        cls.add_arg("id", "_id")
        cls.add_arg("detect", "_detect", is_onoff=True)
        cls.add_arg("require", "_require", is_onoff=True)

    def parse(self, inst):
        if "=" not in str(self.optstr):
            inst.set_compat_str(self.optstr)
            return
        return super().parse(inst)


def parse_os_variant(optstr):
    data = OSVariantData()
    parser = ParserOSVariant(optstr)
    parser.parse(data)
    data.validate()
    return data


###########################
# --noautoconsole parsing #
###########################

def _determine_default_autoconsole_type(guest, installer):
    """
    Determine the default console for the passed guest config

    :returns: 'text', 'graphical', or None
    """
    if installer.has_cloudinit():
        log.info("--cloud-init specified, defaulting to --autoconsole text")
        return "text"

    gdevs = guest.devices.graphics
    if not gdevs:
        return "text"

    gtype = gdevs[0].type
    if gtype not in ["default",
            DeviceGraphics.TYPE_VNC,
            DeviceGraphics.TYPE_SPICE]:
        log.debug("No viewer to launch for graphics type '%s'", gtype)
        return None

    if not HAS_VIRTVIEWER and not xmlutil.in_testsuite():  # pragma: no cover
        log.warning(_("Unable to connect to graphical console: "
                       "virt-viewer not installed. Please install "
                       "the 'virt-viewer' package."))
        return None

    if (not os.environ.get("DISPLAY", "") and
        not xmlutil.in_testsuite()):  # pragma: no cover
        log.warning(_("Graphics requested but DISPLAY is not set. "
                       "Not running virt-viewer."))
        return None

    return "graphical"


class _AutoconsoleData(object):
    def __init__(self, autoconsole, guest, installer):
        self._autoconsole = autoconsole
        if self._autoconsole not in ["none", "default", "text", "graphical"]:
            fail(_("Unknown autoconsole type '%s'") % self._autoconsole)

        self._is_default = self._autoconsole == "default"
        if self._is_default:
            default = _determine_default_autoconsole_type(guest, installer)
            self._autoconsole = default or "none"

    def is_text(self):
        return self._autoconsole == "text"
    def is_graphical(self):
        return self._autoconsole == "graphical"
    def is_default(self):
        return self._is_default

    def has_console_cb(self):
        return bool(self.get_console_cb())
    def get_console_cb(self):
        if self.is_graphical():
            return _gfx_console
        if self.is_text():
            return _txt_console
        return None


def parse_autoconsole(options, guest, installer):
    return _AutoconsoleData(options.autoconsole, guest, installer)


######################
# --metadata parsing #
######################

class ParserMetadata(VirtCLIParser):
    cli_arg_name = "metadata"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("name", "name", can_comma=True)
        cls.add_arg("title", "title", can_comma=True)
        cls.add_arg("uuid", "uuid")
        cls.add_arg("genid", "genid")
        cls.add_arg("genid_enable", "genid_enable", is_onoff=True)
        cls.add_arg("description", "description", can_comma=True)
        cls.add_arg("os_name", None, lookup_cb=None,
                cb=cls.set_os_name_cb)
        cls.add_arg("os_full_id", None, lookup_cb=None,
                cb=cls.set_os_full_id_cb)

    def set_os_name_cb(self, inst, val, virtarg):
        inst.set_os_name(val)

    def set_os_full_id_cb(self, inst, val, virtarg):
        osobj = OSDB.lookup_os_by_full_id(val, raise_error=True)
        inst.set_os_name(osobj.name)


####################
# --events parsing #
####################

class ParserEvents(VirtCLIParser):
    cli_arg_name = "events"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("on_poweroff", "on_poweroff")
        cls.add_arg("on_reboot", "on_reboot")
        cls.add_arg("on_crash", "on_crash")
        cls.add_arg("on_lockfailure", "on_lockfailure")


######################
# --resource parsing #
######################

class ParserResource(VirtCLIParser):
    cli_arg_name = "resource"
    guest_propname = "resource"
    remove_first = "partition"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("partition", "partition")


######################
# --numatune parsing #
######################

class ParserNumatune(VirtCLIParser):
    cli_arg_name = "numatune"
    guest_propname = "numatune"
    remove_first = "nodeset"
    aliases = {
        "memory.mode": "mode",
        "memory.nodeset": "nodeset",
    }

    def memnode_find_inst_cb(self, *args, **kwargs):
        cliarg = "memnode"  # memnode[0-9]*
        list_propname = "memnode"
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("memory.nodeset", "memory_nodeset", can_comma=True)
        cls.add_arg("memory.mode", "memory_mode")
        cls.add_arg("memory.placement", "memory_placement")

        cls.add_arg("memnode[0-9]*.cellid", "cellid", can_comma=True,
                find_inst_cb=cls.memnode_find_inst_cb)
        cls.add_arg("memnode[0-9]*.mode", "mode",
                find_inst_cb=cls.memnode_find_inst_cb)
        cls.add_arg("memnode[0-9]*.nodeset", "nodeset", can_comma=True,
                find_inst_cb=cls.memnode_find_inst_cb)


####################
# --memory parsing #
####################

class ParserMemory(VirtCLIParser):
    cli_arg_name = "memory"
    remove_first = "memory"
    aliases = {
        "maxMemory.slots": "hotplugmemoryslots",
        "maxMemory": "hotplugmemorymax",
    }

    def _convert_old_memory_options(self):
        """
        Historically the cli had:
            memory -> ./currentMemory
            maxmemory -> ./memory
        Then later libvirt gained ./maxMemory. So things are quite a mess.

        Try to convert the back compat cases. Basically if new style option
        currentMemory is specified, interpret currentMemory and memory as
        the XML values. Otherwise treat memory and maxmemory as the old
        swapped names.
        """
        havecur = "currentMemory" in self.optdict
        havemax = "maxmemory" in self.optdict
        havemem = "memory" in self.optdict
        if havecur:
            if havemax:
                self.optdict["memory"] = self.optdict.pop("maxmemory", None)
        elif havemax:
            if havemem:
                self.optdict["currentMemory"] = self.optdict.pop("memory")
            self.optdict["memory"] = self.optdict.pop("maxmemory")
        elif havemem:
            self.optdict["currentMemory"] = self.optdict.pop("memory")

    def _parse(self, inst):
        self._convert_old_memory_options()
        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    def set_memory_cb(self, inst, val, virtarg):
        xmlutil.set_prop_path(inst, virtarg.propname, int(val) * 1024)

    @classmethod
    def _init_class(cls, **kwargs):
        cls.add_arg("memory", "memory", cb=cls.set_memory_cb)
        cls.add_arg("currentMemory", "currentMemory", cb=cls.set_memory_cb)
        cls.add_arg("maxMemory", "maxMemory", cb=cls.set_memory_cb)
        cls.add_arg("maxMemory.slots", "maxMemorySlots")

        # This is converted into either memory or currentMemory
        cls.add_arg("maxmemory", None, lookup_cb=None, cb=cls.noset_cb)

        # New memoryBacking properties should be added to the --memorybacking
        cls.add_arg("hugepages", "memoryBacking.hugepages", is_onoff=True)


#####################
# --memtune parsing #
#####################

class ParserMemtune(VirtCLIParser):
    cli_arg_name = "memtune"
    guest_propname = "memtune"
    remove_first = "soft_limit"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("hard_limit", "hard_limit")
        cls.add_arg("soft_limit", "soft_limit")
        cls.add_arg("swap_hard_limit", "swap_hard_limit")
        cls.add_arg("min_guarantee", "min_guarantee")


#######################
# --blkiotune parsing #
#######################

class ParserBlkiotune(VirtCLIParser):
    cli_arg_name = "blkiotune"
    guest_propname = "blkiotune"
    remove_first = "weight"
    aliases = {
        "device[0-9]*.path": "device_path",
        "device[0-9]*.weight": "device_weight",
        "device[0-9]*.read_bytes_sec": "read_bytes_sec",
        "device[0-9]*.write_bytes_sec": "write_bytes_sec",
        "device[0-9]*.read_iops_sec": "read_iops_sec",
        "device[0-9]*.write_iops_sec": "write_iops_sec",
    }

    def device_find_inst_cb(self, *args, **kwargs):
        cliarg = "device"  # device[0-9]*
        list_propname = "devices"  # blkiotune.devices
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("weight", "weight")
        cls.add_arg("device[0-9]*.path", "path",
                    find_inst_cb=cls.device_find_inst_cb)
        cls.add_arg("device[0-9]*.weight", "weight",
                    find_inst_cb=cls.device_find_inst_cb)
        cls.add_arg("device[0-9]*.read_bytes_sec", "read_bytes_sec",
                    find_inst_cb=cls.device_find_inst_cb)
        cls.add_arg("device[0-9]*.write_bytes_sec", "write_bytes_sec",
                    find_inst_cb=cls.device_find_inst_cb)
        cls.add_arg("device[0-9]*.read_iops_sec", "read_iops_sec",
                    find_inst_cb=cls.device_find_inst_cb)
        cls.add_arg("device[0-9]*.write_iops_sec", "write_iops_sec",
                    find_inst_cb=cls.device_find_inst_cb)


###########################
# --memorybacking parsing #
###########################

class ParserMemoryBacking(VirtCLIParser):
    cli_arg_name = "memorybacking"
    guest_propname = "memoryBacking"
    aliases = {
        "hugepages.page[0-9]*.size": "size",
        "hugepages.page[0-9]*.unit": "unit",
        "hugepages.page[0-9]*.nodeset": "nodeset",
        "access.mode": "access_mode",
        "source.type": "source_type",
    }

    def page_find_inst_cb(self, *args, **kwargs):
        cliarg = "page"  # page[0-9]*
        list_propname = "pages"  # memoryBacking.pages
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("hugepages", "hugepages", is_onoff=True)
        cls.add_arg("hugepages.page[0-9]*.size", "size",
                    find_inst_cb=cls.page_find_inst_cb)
        cls.add_arg("hugepages.page[0-9]*.unit", "unit",
                    find_inst_cb=cls.page_find_inst_cb)
        cls.add_arg("hugepages.page[0-9]*.nodeset", "nodeset", can_comma=True,
                    find_inst_cb=cls.page_find_inst_cb)

        cls.add_arg("nosharepages", "nosharepages", is_onoff=True)
        cls.add_arg("locked", "locked", is_onoff=True)
        cls.add_arg("access.mode", "access_mode")
        cls.add_arg("source.type", "source_type")
        cls.add_arg("discard", "discard", is_onoff=True)
        cls.add_arg("allocation.mode", "allocation_mode")


#################
# --cpu parsing #
#################

class ParserCPU(VirtCLIParser):
    cli_arg_name = "cpu"
    guest_propname = "cpu"
    remove_first = "model"
    stub_none = False
    aliases = {
        "numa.cell[0-9]*.distances.sibling[0-9]*.id":
            "cell[0-9]*.distances.sibling[0-9]*.id",
        "numa.cell[0-9]*.distances.sibling[0-9]*.value":
            "cell[0-9]*.distances.sibling[0-9]*.value",
        "numa.cell[0-9]*.id": "cell[0-9]*.id",
        "numa.cell[0-9]*.cpus": "cell[0-9]*.cpus",
        "numa.cell[0-9]*.memory": "cell[0-9]*.memory",
    }

    def _convert_old_feature_options(self):
        # For old CLI compat, --cpu force=foo,force=bar should force
        # enable 'foo' and 'bar' features, but that doesn't fit with the
        # CLI parser infrastructure very well.
        converted = collections.defaultdict(list)
        for key, value in parse_optstr_tuples(self.optstr):
            if key in ["force", "require", "optional", "disable", "forbid"]:
                converted[key].append(value)

        # Convert +feature, -feature into expected format
        for key, value in list(self.optdict.items()):
            policy = None
            if value or len(key) == 1:
                # We definitely hit this case, but coverage doesn't notice
                # for some reason
                continue  # pragma: no cover

            if key.startswith("+"):
                policy = "force"
            elif key.startswith("-"):
                policy = "disable"

            if policy:
                del(self.optdict[key])
                converted[policy].append(key[1:])

        self.optdict.update(converted)

    def _parse(self, inst):
        self._convert_old_feature_options()
        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    def cell_find_inst_cb(self, *args, **kwargs):
        cliarg = "cell"  # cell[0-9]*
        list_propname = "cells"  # cpu.cells
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    def sibling_find_inst_cb(self, inst, *args, **kwargs):
        cell = self.cell_find_inst_cb(inst, *args, **kwargs)
        inst = cell

        cliarg = "sibling"  # cell[0-9]*.distances.sibling[0-9]*
        list_propname = "siblings"  # cell.siblings
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(inst, *args, **kwargs)

    def set_model_cb(self, inst, val, virtarg):
        if val == "host":
            val = inst.SPECIAL_MODE_HOST_MODEL
        if val == "none":
            val = inst.SPECIAL_MODE_CLEAR

        if val in inst.SPECIAL_MODES:
            inst.set_special_mode(self.guest, val)
        else:
            inst.set_model(self.guest, val)

    def set_feature_cb(self, inst, val, virtarg):
        policy = virtarg.cliname
        for feature_name in xmlutil.listify(val):
            featureobj = None

            for f in inst.features:
                if f.name == feature_name:
                    featureobj = f
                    break

            if featureobj:
                featureobj.policy = policy
            else:
                inst.add_feature(feature_name, policy)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        # 'secure' needs to be parsed before 'model'
        cls.add_arg("secure", "secure", is_onoff=True)
        cls.add_arg("model", "model", cb=cls.set_model_cb)
        cls.add_arg("mode", "mode")
        cls.add_arg("match", "match")
        cls.add_arg("vendor", "vendor")
        cls.add_arg("cache.mode", "cache.mode")
        cls.add_arg("cache.level", "cache.level")

        # These are handled specially in _parse
        cls.add_arg("force", None, lookup_cb=None, cb=cls.set_feature_cb)
        cls.add_arg("require", None, lookup_cb=None, cb=cls.set_feature_cb)
        cls.add_arg("optional", None, lookup_cb=None, cb=cls.set_feature_cb)
        cls.add_arg("disable", None, lookup_cb=None, cb=cls.set_feature_cb)
        cls.add_arg("forbid", None, lookup_cb=None, cb=cls.set_feature_cb)

        cls.add_arg("topology.sockets", "topology.sockets")
        cls.add_arg("topology.cores", "topology.cores")
        cls.add_arg("topology.threads", "topology.threads")

        # Options for CPU.cells config
        cls.add_arg("numa.cell[0-9]*.id", "id",
                    find_inst_cb=cls.cell_find_inst_cb)
        cls.add_arg("numa.cell[0-9]*.cpus", "cpus", can_comma=True,
                    find_inst_cb=cls.cell_find_inst_cb)
        cls.add_arg("numa.cell[0-9]*.memAccess", "memAccess",
                    find_inst_cb=cls.cell_find_inst_cb)
        cls.add_arg("numa.cell[0-9]*.discard", "discard",
                    find_inst_cb=cls.cell_find_inst_cb)
        cls.add_arg("numa.cell[0-9]*.memory", "memory",
                    find_inst_cb=cls.cell_find_inst_cb)
        cls.add_arg("numa.cell[0-9]*.distances.sibling[0-9]*.id", "id",
                    find_inst_cb=cls.sibling_find_inst_cb)
        cls.add_arg("numa.cell[0-9]*.distances.sibling[0-9]*.value", "value",
                    find_inst_cb=cls.sibling_find_inst_cb)


#####################
# --cputune parsing #
#####################

class ParserCputune(VirtCLIParser):
    cli_arg_name = "cputune"
    guest_propname = "cputune"
    remove_first = "model"
    stub_none = False

    def vcpu_find_inst_cb(self, *args, **kwargs):
        cliarg = "vcpupin"  # vcpupin[0-9]*
        list_propname = "vcpus"
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    def vcpusched_find_inst_cb(self, *args, **kwargs):
        cliarg = "vcpusched"  # vcpusched[0-9]*
        list_propname = "vcpusched"
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    def cachetune_find_inst_cb(self, *args, **kwargs):
        cliarg = "cachetune"  # cachetune[0-9]*
        list_propname = "cachetune"
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    def cache_find_inst_cb(self, inst, *args, **kwargs):
        cachetune = self.cachetune_find_inst_cb(inst, *args, **kwargs)
        inst = cachetune

        cliarg = "cache"  # cachetune[0-9]*.cache[0-9]*
        list_propname = "caches"  # cachetune.caches
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(inst, *args, **kwargs)

    def memorytune_find_inst_cb(self, *args, **kwargs):
        cliarg = "memorytune"  # memorytune[0-9]*
        list_propname = "memorytune"
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    def node_find_inst_cb(self, inst, *args, **kwargs):
        memorytune = self.memorytune_find_inst_cb(inst, *args, **kwargs)
        inst = memorytune

        cliarg = "node"  # memorytune[0-9]*.node[0-9]*
        list_propname = "nodes"  # memorytune.nodes
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(inst, *args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        # Options for CPU.vcpus config
        cls.add_arg("vcpupin[0-9]*.vcpu", "vcpu",
                    find_inst_cb=cls.vcpu_find_inst_cb)
        cls.add_arg("vcpupin[0-9]*.cpuset", "cpuset", can_comma=True,
                    find_inst_cb=cls.vcpu_find_inst_cb)
        cls.add_arg("vcpusched[0-9]*.vcpus", "vcpus", can_comma=True,
                    find_inst_cb=cls.vcpusched_find_inst_cb)
        cls.add_arg("vcpusched[0-9]*.scheduler", "scheduler",
                    find_inst_cb=cls.vcpusched_find_inst_cb)
        cls.add_arg("vcpusched[0-9]*.priority", "priority",
                    find_inst_cb=cls.vcpusched_find_inst_cb)
        cls.add_arg("cachetune[0-9]*.vcpus", "vcpus",
                    find_inst_cb=cls.cachetune_find_inst_cb)
        cls.add_arg("cachetune[0-9]*.cache[0-9]*.level", "level",
                    find_inst_cb=cls.cache_find_inst_cb)
        cls.add_arg("cachetune[0-9]*.cache[0-9]*.id", "id",
                    find_inst_cb=cls.cache_find_inst_cb)
        cls.add_arg("cachetune[0-9]*.cache[0-9]*.type", "type",
                    find_inst_cb=cls.cache_find_inst_cb)
        cls.add_arg("cachetune[0-9]*.cache[0-9]*.size", "size",
                    find_inst_cb=cls.cache_find_inst_cb)
        cls.add_arg("cachetune[0-9]*.cache[0-9]*.unit", "unit",
                    find_inst_cb=cls.cache_find_inst_cb)
        cls.add_arg("memorytune[0-9]*.vcpus", "vcpus",
                    find_inst_cb=cls.memorytune_find_inst_cb)
        cls.add_arg("memorytune[0-9]*.node[0-9]*.id", "id",
                    find_inst_cb=cls.node_find_inst_cb)
        cls.add_arg("memorytune[0-9]*.node[0-9]*.bandwidth", "bandwidth",
                    find_inst_cb=cls.node_find_inst_cb)


#######################
# --iothreads parsing #
#######################

class ParserIOThreads(VirtCLIParser):
    cli_arg_name = "iothreads"
    guest_propname = "iothreads"
    remove_first = "iothreads"

    def iothreads_find_inst_cb(self, *args, **kwargs):
        cliarg = "iothread"  # iothreads[0-9]*
        list_propname = "iothreadids"
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        # Options for IOThreads config
        cls.add_arg("iothreads", "iothreads")
        cls.add_arg("iothreadids.iothread[0-9]*.id", "id",
                find_inst_cb=cls.iothreads_find_inst_cb)


###################
# --vcpus parsing #
###################

class ParserVCPU(VirtCLIParser):
    cli_arg_name = "vcpus"
    remove_first = "vcpu"
    aliases = {
        "vcpu.placement": "placement",
    }

    def _convert_old_vcpu_opts(self):
        havemax = "maxvcpus" in self.optdict
        havecur = "vcpu.current" in self.optdict
        havevcp = "vcpu" in self.optdict

        if havecur:
            if havemax:
                self.optdict["vcpu"] = self.optdict.pop("maxvcpus")
        elif havemax:
            if havevcp:
                self.optdict["vcpu.current"] = self.optdict.pop("vcpu")
            self.optdict["vcpu"] = self.optdict.pop("maxvcpus")

    def _add_advertised_aliases(self):
        # These are essentially aliases for new style options, but we still
        # want to advertise them in --vcpus=help output because they are
        # historically commonly used. This should rarely, if ever, be extended
        if "cpuset" in self.optdict:
            self.optdict["vcpu.cpuset"] = self.optdict.pop("cpuset")
        if "vcpus" in self.optdict:
            self.optdict["vcpu"] = self.optdict.pop("vcpus")

    def _parse(self, inst):
        self._add_advertised_aliases()
        self._convert_old_vcpu_opts()
        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    def vcpu_find_inst_cb(self, *args, **kwargs):
        cliarg = "vcpu"  # vcpu[0-9]*
        list_propname = "vcpulist.vcpu"  # guest.vcpulist.vcpu
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    def set_cpuset_cb(self, inst, val, virtarg):
        if val != "auto":
            inst.vcpu_cpuset = val
            return

        # Previously we did our own one-time cpuset placement
        # based on current NUMA memory availability, but that's
        # pretty dumb unless the conditions on the host never change.
        # So instead use newer vcpu placement=
        inst.vcpu_placement = "auto"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        # This is converted into either vcpu.current or vcpu
        cls.add_arg("maxvcpus", "vcpus", cb=cls.noset_cb)
        # These are handled in _add_advertised_aliases
        cls.add_arg("cpuset", "vcpu_cpuset", can_comma=True, cb=cls.noset_cb)
        cls.add_arg("vcpus", "vcpus", cb=cls.noset_cb)

        # Further CPU options should be added to --cpu
        cls.add_arg("sockets", "cpu.topology.sockets")
        cls.add_arg("cores", "cpu.topology.cores")
        cls.add_arg("threads", "cpu.topology.threads")

        # <domain><vcpu> options
        cls.add_arg("vcpu", "vcpus")
        cls.add_arg("vcpu.current", "vcpu_current")
        cls.add_arg("vcpu.cpuset", "vcpu_cpuset",
                can_comma=True, cb=cls.set_cpuset_cb)
        cls.add_arg("vcpu.placement", "vcpu_placement")

        # <domain><vcpus> options
        cls.add_arg("vcpus.vcpu[0-9]*.id", "id",
                    find_inst_cb=cls.vcpu_find_inst_cb)
        cls.add_arg("vcpus.vcpu[0-9]*.enabled", "enabled",
                    find_inst_cb=cls.vcpu_find_inst_cb, is_onoff=True)
        cls.add_arg("vcpus.vcpu[0-9]*.hotpluggable", "hotpluggable",
                    find_inst_cb=cls.vcpu_find_inst_cb, is_onoff=True)
        cls.add_arg("vcpus.vcpu[0-9]*.order", "order",
                    find_inst_cb=cls.vcpu_find_inst_cb)


##################
# --boot parsing #
##################

class ParserBoot(VirtCLIParser):
    cli_arg_name = "boot"
    guest_propname = "os"
    aliases = {
        "bios.rebootTimeout": "rebootTimeout",
        "bios.useserial": "useserial",
        "bootmenu.enable": "menu",
        "cmdline": ["extra_args", "kernel_args"],
        "loader.readonly": "loader_ro",
        "loader.type": "loader_type",
        "loader.secure": "loader_secure",
        "nvram.template": "nvram_template",
        "smbios.mode": "smbios_mode",
    }

    def _convert_boot_order(self, inst):
        # Build boot order
        boot_order = []
        for cliname in list(self.optdict.keys()):
            if cliname not in inst.BOOT_DEVICES:
                continue

            del(self.optdict[cliname])
            if cliname not in boot_order:
                boot_order.append(cliname)

        if boot_order:
            inst.bootorder = boot_order

    def _parse(self, inst):
        self._convert_boot_order(inst)

        # Back compat to allow uefi to have no cli value specified
        if "uefi" in self.optdict:
            self.optdict["uefi"] = True

        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    def set_uefi_cb(self, inst, val, virtarg):
        if not self.editing:
            # From virt-install, we just set this flag, and set_defaults()
            # will fill in everything for us, otherwise we have a circular
            # dep on determining arch/machine info
            self.guest.uefi_requested = True
        else:
            self.guest.set_uefi_path(self.guest.get_uefi_path())
            self.guest.disable_hyperv_for_uefi()

    def set_initargs_cb(self, inst, val, virtarg):
        inst.set_initargs_string(val)

    def set_bootloader_cb(self, inst, val, virtarg):
        self.guest.bootloader = val

    def set_domain_type_cb(self, inst, val, virtarg):
        self.guest.type = val

    def set_emulator_cb(self, inst, val, virtarg):
        self.guest.emulator = val

    def boot_find_inst_cb(self, *args, **kwargs):
        cliarg = "boot"  # boot[0-9]*
        list_propname = "bootdevs"  # os.bootdevs
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    def initarg_find_inst_cb(self, *args, **kwargs):
        cliarg = "initarg"  # initarg[0-9]*
        list_propname = "initargs"  # os.initargs
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)

        # This is simply so the boot options are advertised with --boot help,
        # actual processing is handled by _parse
        cls.add_arg("hd", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("cdrom", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("fd", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("network", None, lookup_cb=None, cb=cls.noset_cb)

        # UEFI depends on these bits, so set them first
        cls.add_arg("arch", "arch")
        cls.add_arg("bootloader", None, lookup_cb=None,
                cb=cls.set_bootloader_cb)
        cls.add_arg("domain_type", None, lookup_cb=None,
                cb=cls.set_domain_type_cb)
        cls.add_arg("emulator", None, lookup_cb=None,
                cb=cls.set_emulator_cb)
        cls.add_arg("uefi", None, lookup_cb=None,
                cb=cls.set_uefi_cb)
        cls.add_arg("os_type", "os_type")
        cls.add_arg("machine", "machine")

        cls.add_arg("kernel", "kernel")
        cls.add_arg("initrd", "initrd")
        cls.add_arg("dtb", "dtb")
        cls.add_arg("cmdline", "kernel_args", can_comma=True)

        cls.add_arg("firmware", "firmware")
        cls.add_arg("boot[0-9]*.dev", "dev",
                    find_inst_cb=cls.boot_find_inst_cb)
        cls.add_arg("bootmenu.enable", "enable_bootmenu", is_onoff=True)
        cls.add_arg("bios.useserial", "useserial", is_onoff=True)
        cls.add_arg("bios.rebootTimeout", "rebootTimeout")
        cls.add_arg("init", "init")
        cls.add_arg("initargs", "initargs", cb=cls.set_initargs_cb)
        cls.add_arg("initarg[0-9]*", "val",
                    find_inst_cb=cls.initarg_find_inst_cb)
        cls.add_arg("initdir", "initdir")
        cls.add_arg("inituser", "inituser")
        cls.add_arg("initgroup", "initgroup")
        cls.add_arg("loader", "loader")
        cls.add_arg("loader.readonly", "loader_ro", is_onoff=True)
        cls.add_arg("loader.type", "loader_type")
        cls.add_arg("loader.secure", "loader_secure", is_onoff=True)
        cls.add_arg("nvram", "nvram")
        cls.add_arg("nvram.template", "nvram_template")
        cls.add_arg("smbios.mode", "smbios_mode")


###################
# --idmap parsing #
###################

class ParserIdmap(VirtCLIParser):
    cli_arg_name = "idmap"
    guest_propname = "idmap"
    aliases = {
        "uid.start": "uid_start",
        "uid.target": "uid_target",
        "uid.count": "uid_count",
        "gid.start": "gid_start",
        "gid.target": "gid_target",
        "gid.count": "gid_count",
    }

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("uid.start", "uid_start")
        cls.add_arg("uid.target", "uid_target")
        cls.add_arg("uid.count", "uid_count")
        cls.add_arg("gid.start", "gid_start")
        cls.add_arg("gid.target", "gid_target")
        cls.add_arg("gid.count", "gid_count")


######################
# --seclabel parsing #
######################

class ParserSeclabel(VirtCLIParser):
    cli_arg_name = "seclabel"
    guest_propname = "seclabels"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("type", "type")
        cls.add_arg("model", "model")
        cls.add_arg("relabel", "relabel", is_onoff=True)
        cls.add_arg("label", "label", can_comma=True)
        cls.add_arg("baselabel", "baselabel", can_comma=True)


######################
# --keywrap parsing  #
######################

class ParserKeyWrap(VirtCLIParser):
    cli_arg_name = "keywrap"
    guest_propname = "keywrap"

    def cipher_find_inst_cb(self, *args, **kwargs):
        cliarg = "cipher"  # keywrap[0-9]*
        list_propname = "cipher"
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("cipher[0-9]*.name", "name", can_comma=True,
                find_inst_cb=cls.cipher_find_inst_cb)
        cls.add_arg("cipher[0-9]*.state", "state", can_comma=True,
                find_inst_cb=cls.cipher_find_inst_cb)


######################
# --features parsing #
######################

class ParserFeatures(VirtCLIParser):
    cli_arg_name = "features"
    guest_propname = "features"
    aliases = {
        "apic.eoi": "eoi",
        "pmu.state": "pmu",
        "vmport.state": "vmport",
        "kvm.hidden.state": "kvm_hidden",
        "gic.version": "gic_version",
        "smm.state": "smm",
        "vmcoreinfo.state": "vmcoreinfo",
        "hyperv.reset.state": "hyperv_reset",
        "hyperv.vapic.state": "hyperv_vapic",
        "hyperv.relaxed.state": "hyperv_relaxed",
        "hyperv.spinlocks.state": "hyperv_spinlocks",
        "hyperv.spinlocks.retries": "hyperv_spinlocks_retries",
        "hyperv.synic.state": "hyperv_synic",
    }

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("acpi", "acpi", is_onoff=True)
        cls.add_arg("apic", "apic", is_onoff=True)
        cls.add_arg("pae", "pae", is_onoff=True)
        cls.add_arg("privnet", "privnet", is_onoff=True)
        cls.add_arg("hap", "hap", is_onoff=True)
        cls.add_arg("viridian", "viridian", is_onoff=True)

        cls.add_arg("apic.eoi", "eoi", is_onoff=True)
        cls.add_arg("pmu.state", "pmu", is_onoff=True)

        cls.add_arg("hyperv.reset.state", "hyperv_reset", is_onoff=True)
        cls.add_arg("hyperv.vapic.state", "hyperv_vapic", is_onoff=True)
        cls.add_arg("hyperv.relaxed.state", "hyperv_relaxed", is_onoff=True)
        cls.add_arg("hyperv.spinlocks.state", "hyperv_spinlocks", is_onoff=True)
        cls.add_arg("hyperv.spinlocks.retries", "hyperv_spinlocks_retries")
        cls.add_arg("hyperv.synic.state", "hyperv_synic", is_onoff=True)

        cls.add_arg("vmport.state", "vmport", is_onoff=True)
        cls.add_arg("kvm.hidden.state", "kvm_hidden", is_onoff=True)
        cls.add_arg("kvm.hint-dedicated.state", "kvm_hint_dedicated", is_onoff=True)
        cls.add_arg("pvspinlock.state", "pvspinlock", is_onoff=True)

        cls.add_arg("gic.version", "gic_version")

        cls.add_arg("smm.state", "smm", is_onoff=True)
        cls.add_arg("vmcoreinfo.state", "vmcoreinfo", is_onoff=True)


###################
# --clock parsing #
###################

class ParserClock(VirtCLIParser):
    cli_arg_name = "clock"
    guest_propname = "clock"

    def _remove_old_options(self):
        # These _tickpolicy options have never had any effect in libvirt,
        # even though they aren't explicitly rejected. Make them no-ops.
        # Keep them unrolled so we can easily check for code coverage
        if "platform_tickpolicy" in self.optdict:
            self.optdict.pop("platform_tickpolicy")
        if "hpet_tickpolicy" in self.optdict:
            self.optdict.pop("hpet_tickpolicy")
        if "tsc_tickpolicy" in self.optdict:
            self.optdict.pop("tsc_tickpolicy")
        if "kvmclock_tickpolicy" in self.optdict:
            self.optdict.pop("kvmclock_tickpolicy")
        if "hypervclock_tickpolicy" in self.optdict:
            self.optdict.pop("hypervclock_tickpolicy")

    def _parse(self, inst):
        self._remove_old_options()
        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    def set_timer(self, inst, val, virtarg):
        tname, propname = virtarg.cliname.split("_")

        timerobj = None
        for t in inst.timers:
            if t.name == tname:
                timerobj = t
                break

        if not timerobj:
            timerobj = inst.timers.add_new()
            timerobj.name = tname

        xmlutil.set_prop_path(timerobj, propname, val)

    def timer_find_inst_cb(self, *args, **kwargs):
        cliarg = "timer"  # timer[0-9]*
        list_propname = "timers"  # clock.timers
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)

        # Timer convenience helpers. It's unclear if we should continue
        # extending this pattern, or just push users to use finegrained
        # timer* config
        cls.add_arg("pit_tickpolicy", None, lookup_cb=None,
                    cb=cls.set_timer)
        cls.add_arg("rtc_tickpolicy", None, lookup_cb=None,
                    cb=cls.set_timer)
        cls.add_arg("platform_present", None, lookup_cb=None, is_onoff=True,
                    cb=cls.set_timer)
        cls.add_arg("pit_present", None, lookup_cb=None, is_onoff=True,
                    cb=cls.set_timer)
        cls.add_arg("rtc_present", None, lookup_cb=None, is_onoff=True,
                    cb=cls.set_timer)
        cls.add_arg("hpet_present", None, lookup_cb=None, is_onoff=True,
                    cb=cls.set_timer)
        cls.add_arg("tsc_present", None, lookup_cb=None, is_onoff=True,
                    cb=cls.set_timer)
        cls.add_arg("kvmclock_present", None, lookup_cb=None, is_onoff=True,
                    cb=cls.set_timer)
        cls.add_arg("hypervclock_present", None, lookup_cb=None, is_onoff=True,
                    cb=cls.set_timer)

        # Standard XML options
        cls.add_arg("offset", "offset")
        cls.add_arg("timer[0-9]*.name", "name",
                    find_inst_cb=cls.timer_find_inst_cb)
        cls.add_arg("timer[0-9]*.present", "present", is_onoff=True,
                    find_inst_cb=cls.timer_find_inst_cb)
        cls.add_arg("timer[0-9]*.tickpolicy", "tickpolicy",
                    find_inst_cb=cls.timer_find_inst_cb)
        cls.add_arg("timer[0-9]*.track", "track",
                    find_inst_cb=cls.timer_find_inst_cb)
        cls.add_arg("timer[0-9]*.mode", "mode",
                    find_inst_cb=cls.timer_find_inst_cb)
        cls.add_arg("timer[0-9]*.frequency", "frequency",
                    find_inst_cb=cls.timer_find_inst_cb)
        cls.add_arg("timer[0-9]*.catchup.threshold", "threshold",
                    find_inst_cb=cls.timer_find_inst_cb)
        cls.add_arg("timer[0-9]*.catchup.slew", "slew",
                    find_inst_cb=cls.timer_find_inst_cb)
        cls.add_arg("timer[0-9]*.catchup.limit", "limit",
                    find_inst_cb=cls.timer_find_inst_cb)


################
# --pm parsing #
################

class ParserPM(VirtCLIParser):
    cli_arg_name = "pm"
    guest_propname = "pm"
    aliases = {
        "suspend_to_mem.enabled": "suspend_to_mem",
        "suspend_to_disk.enabled": "suspend_to_disk",
    }

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("suspend_to_mem.enabled", "suspend_to_mem", is_onoff=True)
        cls.add_arg("suspend_to_disk.enabled", "suspend_to_disk", is_onoff=True)


#####################
# --sysinfo parsing #
#####################

class ParserSysinfo(VirtCLIParser):
    cli_arg_name = "sysinfo"
    guest_propname = "sysinfo"
    remove_first = "type"
    aliases = {
        "bios.vendor": "bios_vendor",
        "bios.version": "bios_version",
        "bios.date": "bios_date",
        "bios.release": "bios_release",

        "system.manufacturer": "system_manufacturer",
        "system.product": "system_product",
        "system.version": "system_version",
        "system.serial": "system_serial",
        "system.uuid": "system_uuid",
        "system.sku": "system_sku",
        "system.family": "system_family",

        "baseBoard.manufacturer": "baseBoard_manufacturer",
        "baseBoard.product": "baseBoard_product",
        "baseBoard.version": "baseBoard_version",
        "baseBoard.serial": "baseBoard_serial",
        "baseBoard.asset": "baseBoard_asset",
        "baseBoard.location": "baseBoard_location",
    }

    def parse(self, inst):
        if self.optstr and 'type' not in self.optdict:
            # If any string specified, default to type=smbios otherwise
            # libvirt errors. User args can still override this though
            self.optdict['type'] = 'smbios'

        # Previously libvirt treated sysinfo as a singleton object, but
        # that changed with fwcfg support. Our cli would merge all options
        # together but now needs to support multiple. Maintain sorta
        # backcompat behavior by mergin options if 'type' matches
        if not inst:
            typ = self.optdict["type"]
            for sysinfo in self.guest.sysinfo:
                if sysinfo.type == typ:
                    inst = sysinfo
                    break

        return super().parse(inst)


    ###################
    # Option handling #
    ###################

    def set_type_cb(self, inst, val, virtarg):
        if val == "host" or val == "emulate":
            self.guest.os.smbios_mode = val
            return

        if val == "smbios":
            self.guest.os.smbios_mode = "sysinfo"
        inst.type = val

    def set_uuid_cb(self, inst, val, virtarg):
        # If a uuid is supplied it must match the guest UUID. This would be
        # impossible to guess if the guest uuid is autogenerated so just
        # overwrite the guest uuid with what is passed in assuming it passes
        # the sanity checking below.
        inst.system_uuid = val
        self.guest.uuid = val

    def oem_find_inst_cb(self, *args, **kwargs):
        # pylint: disable=protected-access
        cliarg = "entry"  # oemStrings.entry[0-9]*
        list_propname = "oemStrings"  # sysinfo.oemStrings
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    def entry_find_inst_cb(self, *args, **kwargs):
        # pylint: disable=protected-access
        cliarg = "entry"  # entry[0-9]*
        list_propname = "entries"  # sysinfo.entries
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)


    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        # <sysinfo type='smbios'>
        cls.add_arg("type", "type", cb=cls.set_type_cb, can_comma=True)

        # <bios> type 0 BIOS Information
        cls.add_arg("bios.vendor", "bios_vendor")
        cls.add_arg("bios.version", "bios_version")
        cls.add_arg("bios.date", "bios_date")
        cls.add_arg("bios.release", "bios_release")

        # <system> type 1 System Information
        cls.add_arg("system.manufacturer", "system_manufacturer")
        cls.add_arg("system.product", "system_product")
        cls.add_arg("system.version", "system_version")
        cls.add_arg("system.serial", "system_serial")
        cls.add_arg("system.uuid", "system_uuid", cb=cls.set_uuid_cb)
        cls.add_arg("system.sku", "system_sku")
        cls.add_arg("system.family", "system_family")

        # <baseBoard> type 2 Baseboard (or Module) Information
        cls.add_arg("baseBoard.manufacturer", "baseBoard_manufacturer")
        cls.add_arg("baseBoard.product", "baseBoard_product")
        cls.add_arg("baseBoard.version", "baseBoard_version")
        cls.add_arg("baseBoard.serial", "baseBoard_serial")
        cls.add_arg("baseBoard.asset", "baseBoard_asset")
        cls.add_arg("baseBoard.location", "baseBoard_location")

        cls.add_arg("chassis.manufacturer", "chassis_manufacturer")
        cls.add_arg("chassis.version", "chassis_version")
        cls.add_arg("chassis.serial", "chassis_serial")
        cls.add_arg("chassis.asset", "chassis_asset")
        cls.add_arg("chassis.sku", "chassis_sku")

        cls.add_arg("oemStrings.entry[0-9]*", "value", can_comma=True,
                    find_inst_cb=cls.oem_find_inst_cb)

        cls.add_arg("entry[0-9]*", "value", can_comma=True,
                    find_inst_cb=cls.entry_find_inst_cb)
        cls.add_arg("entry[0-9]*.name", "name", can_comma=True,
                    find_inst_cb=cls.entry_find_inst_cb)
        cls.add_arg("entry[0-9]*.file", "file", can_comma=True,
                    find_inst_cb=cls.entry_find_inst_cb)


##############################
# --qemu-commandline parsing #
##############################

class ParserQemuCLI(VirtCLIParser):
    cli_arg_name = "qemu_commandline"
    guest_propname = "xmlns_qemu"

    def args_cb(self, inst, val, virtarg):
        for opt in shlex.split(val):
            obj = inst.args.add_new()
            obj.value = opt

    def env_cb(self, inst, val, virtarg):
        name, envval = val.split("=", 1)
        obj = inst.envs.add_new()
        obj.name = name
        obj.value = envval

    def _parse(self, inst):
        self.optdict.clear()
        if self.optstr.startswith("env="):
            self.optdict["env"] = self.optstr.split("=", 1)[1]
        elif self.optstr.startswith("args="):
            self.optdict["args"] = self.optstr.split("=", 1)[1]
        elif self.optstr.startswith("clearxml="):
            self.optdict["clearxml"] = self.optstr.split("=", 1)[1]
        else:
            self.optdict["args"] = self.optstr
        return super()._parse(inst)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("args", None, lookup_cb=None,
                cb=cls.args_cb, can_comma=True)
        cls.add_arg("env", None, lookup_cb=None,
                cb=cls.env_cb, can_comma=True)


##########################
# Guest <device> parsing #
##########################

def _add_common_device_args(cls,
        boot_order=False, boot_loadparm=False, virtio_options=False):
    """
    Add common Device parameters, like address.*
    """
    def _add_arg(*args, **kwargs):
        kwargs["skip_testsuite_tracking"] = True
        cls.add_arg(*args, **kwargs)

    _add_arg("address.type", "address.type")
    _add_arg("address.domain", "address.domain")
    _add_arg("address.bus", "address.bus")
    _add_arg("address.slot", "address.slot")
    _add_arg("address.multifunction", "address.multifunction",
                is_onoff=True)
    _add_arg("address.function", "address.function")
    _add_arg("address.controller", "address.controller")
    _add_arg("address.unit", "address.unit")
    _add_arg("address.port", "address.port")
    _add_arg("address.target", "address.target")
    _add_arg("address.reg", "address.reg")
    _add_arg("address.cssid", "address.cssid")
    _add_arg("address.ssid", "address.ssid")
    _add_arg("address.devno", "address.devno")
    _add_arg("address.iobase", "address.iobase")
    _add_arg("address.irq", "address.irq")
    _add_arg("address.base", "address.base")
    _add_arg("address.zpci.uid", "address.zpci_uid")
    _add_arg("address.zpci.fid", "address.zpci_fid")

    _add_arg("alias.name", "alias.name")

    def set_boot_order_cb(self, inst, val, virtarg):
        val = int(val)
        self.guest.reorder_boot_order(inst, val)

    if boot_order:
        cls.aliases["boot.order"] = "boot_order"
        _add_arg("boot.order", "boot.order", cb=set_boot_order_cb)

    if boot_loadparm:
        _add_arg("boot.loadparm", "boot.loadparm")

    if virtio_options:
        _add_arg("driver.ats", "virtio_driver.ats", is_onoff=True)
        _add_arg("driver.iommu", "virtio_driver.iommu", is_onoff=True)
        _add_arg("driver.packed", "virtio_driver.packed", is_onoff=True)


def _add_device_seclabel_args(cls, list_propname, prefix=""):
    def seclabel_find_inst_cb(c, *args, **kwargs):
        # pylint: disable=protected-access
        cliarg = "seclabel"  # seclabel[0-9]*
        cb = c._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    def _add_arg(*args, **kwargs):
        kwargs["skip_testsuite_tracking"] = True
        cls.add_arg(*args, **kwargs)

    # DeviceDisk.seclabels properties
    _add_arg(prefix + "source.seclabel[0-9]*.model", "model",
                find_inst_cb=seclabel_find_inst_cb)
    _add_arg(prefix + "source.seclabel[0-9]*.relabel", "relabel",
                is_onoff=True, find_inst_cb=seclabel_find_inst_cb)
    _add_arg(prefix + "source.seclabel[0-9]*.label", "label",
                can_comma=True, find_inst_cb=seclabel_find_inst_cb)


def _add_char_source_args(cls, prefix=""):
    """
    Add arguments that represent the CharSource object, which is shared
    among multiple device types
    """
    def set_sourcehost_cb(c, inst, val, virtarg):
        inst.source.set_friendly_host(val)

    def set_bind_cb(c, inst, val, virtarg):
        inst.source.set_friendly_bind(val)

    def set_connect_cb(c, inst, val, virtarg):
        inst.source.set_friendly_connect(val)

    def _add_arg(cliname, propname, *args, **kwargs):
        kwargs["skip_testsuite_tracking"] = True
        cls.add_arg(prefix + cliname, propname, *args, **kwargs)

    _add_arg("source.path", "source.path")
    _add_arg("source.host", "source.host", cb=set_sourcehost_cb)
    _add_arg("source.service", "source.service")
    _add_arg("source.bind_host", "source.bind_host", cb=set_bind_cb)
    _add_arg("source.bind_service", "source.bind_service")
    _add_arg("source.connect_host", "source.connect_host", cb=set_connect_cb)
    _add_arg("source.connect_service", "source.connect_service")
    _add_arg("source.mode", "source.mode")
    _add_arg("source.master", "source.master")
    _add_arg("source.slave", "source.slave")
    _add_device_seclabel_args(cls, "source.seclabels", prefix=prefix)
    _add_arg("protocol.type", "source.protocol")
    _add_arg("log.file", "source.log_file")
    _add_arg("log.append", "source.log_append", is_onoff=True)


##################
# --disk parsing #
##################

def _default_image_file_format(conn):
    if conn.support.conn_default_qcow2():
        return "qcow2"
    return "raw"  # pragma: no cover


def _get_default_image_format(conn, poolobj):
    tmpvol = StorageVolume(conn)
    tmpvol.pool = poolobj

    if tmpvol.file_type != StorageVolume.TYPE_FILE:
        return None
    return _default_image_file_format(conn)


def _generate_new_volume_name(guest, poolobj, fmt):
    ext = StorageVolume.get_file_extension_for_format(fmt)
    return StorageVolume.find_free_name(
        guest.conn, poolobj, guest.name or "disk",
        suffix=ext, collideguest=guest)


class ParserDisk(VirtCLIParser):
    cli_arg_name = "disk"
    guest_propname = "devices.disk"
    remove_first = "path"
    stub_none = False
    aliases = {
        "blockio.logical_block_size": "logical_block_size",
        "blockio.physical_block_size": "physical_block_size",

        "iotune.read_bytes_sec": "read_bytes_sec",
        "iotune.write_bytes_sec": "write_bytes_sec",
        "iotune.total_bytes_sec": "total_bytes_sec",
        "iotune.read_iops_sec": "read_iops_sec",
        "iotune.write_iops_sec": "write_iops_sec",
        "iotune.total_iops_sec": "total_iops_sec",

        "source.pool": "source_pool",
        "source.volume": "source_volume",
        "source.name": "source_name",
        "source.protocol": "source_protocol",
        "source.host[0-9]*.name": "source_host_name",
        "source.host[0-9]*.port": "source_host_port",
        "source.host[0-9]*.socket": "source_host_socket",
        "source.host[0-9]*.transport": "source_host_transport",
        "source.startupPolicy": "startup_policy",
        "source.seclabel[0-9]*.model": "seclabel[0-9]*.model",
        "source.seclabel[0-9]*.relabel": "seclabel[0-9]*.relabel",
        "source.seclabel[0-9]*.label": "seclabel[0-9]*.label",

        "source.reservations.managed": "reservations.managed",
        "source.reservations.source.type": "reservations.source.type",
        "source.reservations.source.path": "reservations.source.path",
        "source.reservations.source.mode": "reservations.source.mode",

        "snapshot": "snapshot_policy",
        "target.dev": "target",
        "target.removable": "removable",

        "driver.discard": "discard",
        "driver.detect_zeroes": "detect_zeroes",
        "driver.error_policy": "error_policy",
        "driver.io": "io",
        "driver.name": "driver_name",
        "driver.type": "driver_type",
    }

    def _add_advertised_aliases(self):
        # These are essentially aliases for new style options, but we still
        # want to advertise them in --disk=help output because they are
        # historically commonly used. This should rarely, if ever, be extended
        if "bus" in self.optdict:
            self.optdict["target.bus"] = self.optdict.pop("bus")
        if "cache" in self.optdict:
            self.optdict["driver.cache"] = self.optdict.pop("cache")

    def _parse(self, inst):
        self._add_advertised_aliases()

        if self.optstr == "none":
            return

        def parse_size(val):
            if val is None:
                return None
            try:
                return float(val)
            except Exception as e:
                fail(_("Improper value for 'size': %s") % str(e))

        def convert_perms(val):
            if val is None:
                return
            if val == "ro":
                self.optdict["readonly"] = "on"
            elif val == "sh":
                self.optdict["shareable"] = "on"
            elif val == "rw":
                # It's default. Nothing to do.
                pass
            else:
                fail(_("Unknown '%(optionname)s' value '%(string)s'") %
                    {"optionname": "perms", "string": val})

        backing_store = self.optdict.pop("backing_store", None)
        backing_format = self.optdict.pop("backing_format", None)
        poolname = self.optdict.pop("pool", None)
        volname = self.optdict.pop("vol", None)
        size = parse_size(self.optdict.pop("size", None))
        fmt = self.optdict.pop("format", None)
        sparse = _on_off_convert("sparse", self.optdict.pop("sparse", "yes"))
        convert_perms(self.optdict.pop("perms", None))
        disktype = self.optdict.pop("type", None)

        if volname:
            if volname.count("/") != 1:
                raise ValueError(_("Storage volume must be specified as "
                                   "vol=poolname/volname"))
            poolname, volname = volname.split("/")
            log.debug("Parsed --disk volume as: pool=%s vol=%s",
                          poolname, volname)

        # Set this up front, it has lots of follow on effects
        if disktype:
            inst.type = disktype
        super()._parse(inst)

        if (size and
            not volname and
            not poolname and
            inst.is_empty() and
            inst.type == inst.TYPE_FILE):
            # Saw something like --disk size=X, have it imply pool=default
            poolname = "default"

        # Generate and fill in the disk source info
        newvolname = None
        poolobj = None
        if poolname:
            if poolname == "default":
                poolxml = StoragePool.build_default_pool(self.guest.conn)
                if poolxml:
                    poolname = poolxml.name
            poolobj = self.guest.conn.storagePoolLookupByName(poolname)
            StoragePool.ensure_pool_is_running(poolobj)

        if volname:
            vol_object = poolobj.storageVolLookupByName(volname)
            inst.set_vol_object(vol_object, poolobj)
            poolobj = None

        if ((poolobj or inst.wants_storage_creation()) and
            (fmt or size or sparse or backing_store)):
            if not poolobj:
                poolobj = inst.get_parent_pool()
                newvolname = os.path.basename(inst.get_source_path())
            if poolobj and not fmt:
                fmt = _get_default_image_format(self.guest.conn, poolobj)
            if newvolname is None:
                newvolname = _generate_new_volume_name(self.guest, poolobj,
                                                       fmt)
            vol_install = DeviceDisk.build_vol_install(
                    self.guest.conn, newvolname, poolobj, size, sparse,
                    fmt=fmt, backing_store=backing_store,
                    backing_format=backing_format)
            inst.set_vol_install(vol_install)

        return inst


    ###################
    # Option handling #
    ###################

    def set_path_cb(self, inst, val, virtarg):
        inst.set_source_path(val)
    def path_lookup_cb(self, inst, val, virtarg):
        return inst.get_source_path() == val

    def host_find_inst_cb(self, *args, **kwargs):
        cliarg = "hosts"  # host[0-9]*
        list_propname = "source.hosts"  # disk.hosts
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls,
                boot_order=True, boot_loadparm=True, virtio_options=True)

        # These are all handled specially in _parse
        cls.add_arg("backing_store", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("backing_format", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("pool", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("vol", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("size", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("format", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("sparse", None, lookup_cb=None, cb=cls.noset_cb)
        cls.add_arg("type", None, lookup_cb=None, cb=cls.noset_cb)

        # These are handled in _add_advertised_aliases
        cls.add_arg("bus", "bus", cb=cls.noset_cb)
        cls.add_arg("cache", "driver_cache", cb=cls.noset_cb)

        # More standard XML props
        cls.add_arg("source.dir", "source.dir")
        cls.add_arg("source.file", "source.file")
        cls.add_arg("source.dev", "source.dev")
        cls.add_arg("source.pool", "source.pool")
        cls.add_arg("source.volume", "source.volume")
        cls.add_arg("source.name", "source.name")
        cls.add_arg("source.protocol", "source.protocol")
        cls.add_arg("source.startupPolicy", "startup_policy")
        # type=nvme source props
        cls.add_arg("source.type", "source.type")
        cls.add_arg("source.namespace", "source.namespace")
        cls.add_arg("source.managed", "source.managed", is_onoff=True)
        cls.add_arg("source.address.domain", "source.address.domain")
        cls.add_arg("source.address.bus", "source.address.bus")
        cls.add_arg("source.address.slot", "source.address.slot")
        cls.add_arg("source.address.function", "source.address.function")

        cls.add_arg("source.host[0-9]*.name", "name",
                    find_inst_cb=cls.host_find_inst_cb)
        cls.add_arg("source.host[0-9]*.port", "port",
                    find_inst_cb=cls.host_find_inst_cb)
        cls.add_arg("source.host[0-9]*.socket", "socket",
                    find_inst_cb=cls.host_find_inst_cb)
        cls.add_arg("source.host[0-9]*.transport", "transport",
                    find_inst_cb=cls.host_find_inst_cb)

        _add_device_seclabel_args(cls, "seclabels")

        cls.add_arg("path", None,
                cb=cls.set_path_cb,
                lookup_cb=cls.path_lookup_cb)
        cls.add_arg("device", "device")
        cls.add_arg("snapshot", "snapshot_policy")
        cls.add_arg("sgio", "sgio")
        cls.add_arg("rawio", "rawio")
        cls.add_arg("serial", "serial")
        cls.add_arg("wwn", "wwn")
        cls.add_arg("readonly", "read_only", is_onoff=True)
        cls.add_arg("shareable", "shareable", is_onoff=True)

        cls.add_arg("target.bus", "bus")
        cls.add_arg("target.removable", "removable", is_onoff=True)
        cls.add_arg("target.dev", "target")

        cls.add_arg("driver.cache", "driver_cache")
        cls.add_arg("driver.discard", "driver_discard")
        cls.add_arg("driver.detect_zeroes", "driver_detect_zeroes")
        cls.add_arg("driver.name", "driver_name")
        cls.add_arg("driver.type", "driver_type")
        cls.add_arg("driver.copy_on_read", "driver_copy_on_read", is_onoff=True)
        cls.add_arg("driver.io", "driver_io")
        cls.add_arg("driver.iothread", "driver_iothread")
        cls.add_arg("driver.error_policy", "error_policy")

        cls.add_arg("iotune.read_bytes_sec", "iotune_rbs")
        cls.add_arg("iotune.write_bytes_sec", "iotune_wbs")
        cls.add_arg("iotune.total_bytes_sec", "iotune_tbs")
        cls.add_arg("iotune.read_iops_sec", "iotune_ris")
        cls.add_arg("iotune.write_iops_sec", "iotune_wis")
        cls.add_arg("iotune.total_iops_sec", "iotune_tis")

        cls.add_arg("blockio.logical_block_size", "logical_block_size")
        cls.add_arg("blockio.physical_block_size", "physical_block_size")

        cls.add_arg("geometry.cyls", "geometry_cyls")
        cls.add_arg("geometry.heads", "geometry_heads")
        cls.add_arg("geometry.secs", "geometry_secs")
        cls.add_arg("geometry.trans", "geometry_trans")

        cls.add_arg("source.reservations.managed",
                    "reservations_managed")
        cls.add_arg("source.reservations.source.type",
                    "reservations_source_type")
        cls.add_arg("source.reservations.source.path",
                    "reservations_source_path")
        cls.add_arg("source.reservations.source.mode",
                    "reservations_source_mode")


#####################
# --network parsing #
#####################

class ParserNetwork(VirtCLIParser):
    cli_arg_name = "network"
    guest_propname = "devices.interface"
    remove_first = "type"
    stub_none = False
    aliases = {
        "driver.name": "driver_name",
        "driver.queues": "driver_queues",
        "filterref.filter": "filterref",
        "link.state": "link_state",
        "mac.address": "mac",
        "model.type": "model",
        "rom.file": "rom_file",
        "rom.bar": "rom_bar",
        "target.dev": "target",

        "source.portgroup": "portgroup",
        "source.type": "source_type",
        "source.path": "source_path",
        "source.mode": "source_mode",

        "virtualport.type": "virtualport_type",
        "virtualport.parameters.managerid": "virtualport_managerid",
        "virtualport.parameters.typeid": "virtualport_typeid",
        "virtualport.parameters.typeidversion": "virtualport_typeidversion",
        "virtualport.parameters.instanceid": "virtualport_instanceid",
        "virtualport.parameters.profileid": "virtualport_profileid",
        "virtualport.parameters.interfaceid": "virtualport_interfaceid",
    }

    def _add_advertised_aliases(self):
        # These are essentially aliases for new style options, but we still
        # want to advertise them in --network=help output because they are
        # historically commonly used. This should rarely, if ever, be extended
        if "model" in self.optdict:
            self.optdict["model.type"] = self.optdict.pop("model")
        if "mac" in self.optdict:
            self.optdict["mac.address"] = self.optdict.pop("mac")

        # Back compat with old style network= and bridge=
        if "type" not in self.optdict:
            if "network" in self.optdict:
                self.optdict["type"] = DeviceInterface.TYPE_VIRTUAL
                self.optdict["source"] = self.optdict.pop("network")
            elif "bridge" in self.optdict:
                self.optdict["type"] = DeviceInterface.TYPE_BRIDGE
                self.optdict["source"] = self.optdict.pop("bridge")
        else:
            self.optdict.pop("network", None)
            self.optdict.pop("bridge", None)


    def _parse(self, inst):
        self._add_advertised_aliases()

        if self.optstr == "none":
            return

        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    def set_mac_cb(self, inst, val, virtarg):
        if val == "RANDOM":
            return None
        inst.macaddr = val
        return val

    def set_type_cb(self, inst, val, virtarg):
        if val == "default":
            inst.set_default_source()
        else:
            inst.type = val

    def set_link_state(self, inst, val, virtarg):
        ignore = virtarg
        if val in ["up", "down"]:
            inst.link_state = val
            return

        ret = _raw_on_off_convert(val)
        if ret is True:
            val = "up"
        elif ret is False:
            val = "down"
        inst.link_state = val

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls,
                boot_order=True, boot_loadparm=True, virtio_options=True)

        # These are handled in _add_advertised_aliases
        cls.add_arg("model", "model", cb=cls.noset_cb)
        cls.add_arg("mac", "macaddr", cb=cls.noset_cb)
        cls.add_arg("network", "source", cb=cls.noset_cb)
        cls.add_arg("bridge", "source", cb=cls.noset_cb)

        # Standard XML options
        cls.add_arg("type", "type", cb=cls.set_type_cb)
        cls.add_arg("trustGuestRxFilters", "trustGuestRxFilters", is_onoff=True)
        cls.add_arg("source", "source")
        cls.add_arg("source.mode", "source_mode")
        cls.add_arg("source.type", "source_type")
        cls.add_arg("source.path", "source_path")
        cls.add_arg("source.portgroup", "portgroup")
        cls.add_arg("target.dev", "target_dev")
        cls.add_arg("model.type", "model")
        cls.add_arg("mac.address", "macaddr", cb=cls.set_mac_cb)
        cls.add_arg("filterref.filter", "filterref")
        cls.add_arg("link.state", "link_state", cb=cls.set_link_state)

        cls.add_arg("driver.name", "driver_name")
        cls.add_arg("driver.queues", "driver_queues")

        cls.add_arg("rom.file", "rom_file")
        cls.add_arg("rom.bar", "rom_bar", is_onoff=True)

        cls.add_arg("mtu.size", "mtu_size")

        cls.add_arg("virtualport.type",
                    "virtualport.type")
        cls.add_arg("virtualport.parameters.managerid",
                    "virtualport.managerid")
        cls.add_arg("virtualport.parameters.typeid",
                    "virtualport.typeid")
        cls.add_arg("virtualport.parameters.typeidversion",
                    "virtualport.typeidversion")
        cls.add_arg("virtualport.parameters.instanceid",
                    "virtualport.instanceid")
        cls.add_arg("virtualport.parameters.profileid",
                    "virtualport.profileid")
        cls.add_arg("virtualport.parameters.interfaceid",
                    "virtualport.interfaceid")


######################
# --graphics parsing #
######################

class ParserGraphics(VirtCLIParser):
    cli_arg_name = "graphics"
    guest_propname = "devices.graphics"
    remove_first = "type"
    stub_none = False
    aliases = {
        "tlsPort": "tlsport",
        "password": "passwd",
        "passwordValidTo": "passwdValidTo",
        "image.compression": "image_compression",
        "streaming.mode": "streaming_mode",
        "clipboard.copypaste": "clipboard_copypaste",
        "filetransfer.enable": "filetransfer_enable",
        "mouse.mode": "mouse_mode",
        "gl.enable": "gl",
        "gl.rendernode": "rendernode",
    }

    def _parse(self, inst):
        if self.optstr == "none":
            self.guest.skip_default_graphics = True
            return

        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    def set_keymap_cb(self, inst, val, virtarg):
        if not val:
            val = None
        elif val.lower() == "local":
            log.debug("keymap=local is no longer implemented. Using None.")
            val = None
        elif val.lower() == "none":
            val = None
        inst.keymap = val

    def set_type_cb(self, inst, val, virtarg):
        if val == "default":
            return
        inst.type = val

    def listens_find_inst_cb(self, *args, **kwargs):
        cliarg = "listens"  # listens[0-9]*
        list_propname = "listens"  # graphics.listens
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls)

        cls.add_arg("type", "type", cb=cls.set_type_cb)
        cls.add_arg("port", "port")
        cls.add_arg("tlsPort", "tlsPort")
        cls.add_arg("websocket", "websocket")
        cls.add_arg("listen", "listen")
        cls.add_arg("keymap", "keymap", cb=cls.set_keymap_cb)
        cls.add_arg("password", "passwd")
        cls.add_arg("passwordValidTo", "passwdValidTo")
        cls.add_arg("connected", "connected")
        cls.add_arg("defaultMode", "defaultMode")

        cls.add_arg("listens[0-9]*.type", "type",
                    find_inst_cb=cls.listens_find_inst_cb)
        cls.add_arg("listens[0-9]*.address", "address",
                    find_inst_cb=cls.listens_find_inst_cb)
        cls.add_arg("listens[0-9]*.network", "network",
                    find_inst_cb=cls.listens_find_inst_cb)
        cls.add_arg("listens[0-9]*.socket", "socket",
                    find_inst_cb=cls.listens_find_inst_cb)

        cls.add_arg("image.compression", "image_compression")
        cls.add_arg("streaming.mode", "streaming_mode")
        cls.add_arg("clipboard.copypaste", "clipboard_copypaste",
                    is_onoff=True)
        cls.add_arg("mouse.mode", "mouse_mode")
        cls.add_arg("filetransfer.enable", "filetransfer_enable",
                    is_onoff=True)
        cls.add_arg("zlib.compression", "zlib_compression")

        cls.add_arg("gl.enable", "gl", is_onoff=True)
        cls.add_arg("gl.rendernode", "rendernode")


########################
# --controller parsing #
########################

class ParserController(VirtCLIParser):
    cli_arg_name = "controller"
    guest_propname = "devices.controller"
    remove_first = "type"
    aliases = {
        "master.startport": "master",
        "driver.queues": "driver_queues",
    }

    def _parse(self, inst):
        if self.optstr == "usb2":
            return DeviceController.get_usb2_controllers(inst.conn)
        elif self.optstr == "usb3":
            return DeviceController.get_usb3_controller(inst.conn, self.guest)
        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    def set_address_cb(self, inst, val, virtarg):
        # Convenience option for address= PCI parsing. This pattern should
        # not be extended IMO, make users manually specify the address
        # fields they need
        addrstr = val
        if addrstr.count(":") in [1, 2] and "." in addrstr:
            inst.address.type = inst.address.ADDRESS_TYPE_PCI
            addrstr, inst.address.function = addrstr.split(".", 1)
            addrstr, inst.address.slot = addrstr.rsplit(":", 1)
            inst.address.domain = "0"
            if ":" in addrstr:
                inst.address.domain, inst.address.bus = addrstr.split(":", 1)
            return
        raise ValueError(
                _("Expected PCI format string for '%s'") % addrstr)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls, virtio_options=True)

        cls.add_arg("type", "type")
        cls.add_arg("model", "model")
        cls.add_arg("index", "index")
        cls.add_arg("maxGrantFrames", "maxGrantFrames")
        cls.add_arg("vectors", "vectors")
        cls.add_arg("master.startport", "master_startport")
        cls.add_arg("driver.iothread", "driver_iothread")
        cls.add_arg("driver.queues", "driver_queues")
        cls.add_arg("target.chassisNr", "target_chassisNr")
        cls.add_arg("target.chassis", "target_chassis")
        cls.add_arg("target.port", "target_port")
        cls.add_arg("target.hotplug", "target_hotplug")
        cls.add_arg("target.busNr", "target_busNr")
        cls.add_arg("target.index", "target_index")
        cls.add_arg("target.node", "target_node")

        cls.add_arg("address", None, lookup_cb=None, cb=cls.set_address_cb)


###################
# --input parsing #
###################

class ParserInput(VirtCLIParser):
    cli_arg_name = "input"
    guest_propname = "devices.input"
    remove_first = "type"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls, virtio_options=True)

        cls.add_arg("type", "type", ignore_default=True)
        cls.add_arg("bus", "bus", ignore_default=True)


###################
# --iommu parsing #
###################

class ParserIommu(VirtCLIParser):
    cli_arg_name = "iommu"
    guest_propname = "devices.iommu"
    remove_first = "model"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)

        cls.add_arg("model", "model")
        cls.add_arg("driver.aw_bits", "aw_bits")
        cls.add_arg("driver.intremap", "intremap", is_onoff=True)
        cls.add_arg("driver.caching_mode", "caching_mode", is_onoff=True)
        cls.add_arg("driver.eim", "eim", is_onoff=True)
        cls.add_arg("driver.iotlb", "iotlb", is_onoff=True)


#######################
# --smartcard parsing #
#######################

class ParserSmartcard(VirtCLIParser):
    cli_arg_name = "smartcard"
    guest_propname = "devices.smartcard"
    remove_first = "mode"

    def certificate_find_inst_cb(self, *args, **kwargs):
        cliarg = "certificate"  # certificate[0-9]*
        list_propname = "certificates"
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls)

        cls.add_arg("mode", "mode", ignore_default=True)
        cls.add_arg("type", "type", ignore_default=True)
        _add_char_source_args(cls)

        cls.add_arg("database", "database", can_comma=True)
        cls.add_arg("certificate[0-9]*", "value", can_comma=True,
                    find_inst_cb=cls.certificate_find_inst_cb)


######################
# --redirdev parsing #
######################

class ParserRedir(VirtCLIParser):
    cli_arg_name = "redirdev"
    guest_propname = "devices.redirdev"
    remove_first = "bus"
    stub_none = False

    def set_server_cb(self, inst, val, virtarg):
        inst.source.set_friendly_host(val)

    def _parse(self, inst):
        if self.optstr == "none":
            self.guest.skip_default_usbredir = True
            return
        return super()._parse(inst)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls, boot_order=True)

        cls.add_arg("bus", "bus", ignore_default=True)
        cls.add_arg("type", "type", ignore_default=True)

        cls.add_arg("server", None, lookup_cb=None, cb=cls.set_server_cb)
        _add_char_source_args(cls)


#################
# --tpm parsing #
#################

class ParserTPM(VirtCLIParser):
    cli_arg_name = "tpm"
    guest_propname = "devices.tpm"
    remove_first = "type"
    aliases = {
        "backend.type": "type",
        "backend.version": "version",
        "backend.device.path": "path",
    }

    def _parse(self, inst):
        if (self.optdict.get("type", "").startswith("/")):
            self.optdict["path"] = self.optdict.pop("type")
        return super()._parse(inst)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls)

        cls.add_arg("model", "model")
        cls.add_arg("backend.type", "type")
        cls.add_arg("backend.version", "version")
        cls.add_arg("backend.device.path", "device_path")
        cls.add_arg("backend.encryption.secret", "encryption_secret")
        cls.add_arg("backend.persistent_state",
                    "persistent_state", is_onoff=True)


#################
# --rng parsing #
#################

class ParserRNG(VirtCLIParser):
    cli_arg_name = "rng"
    guest_propname = "devices.rng"
    remove_first = "backend.model"
    stub_none = False
    aliases = {
        "backend.type": "backend_type",
        "backend.source.mode": "backend_mode",
        "backend.source.host": "backend_host",
        "backend.source.service": "backend_service",
        "backend.source.connect_host": "backend_connect_host",
        "backend.source.connect_service": "backend_connect_service",
        "rate.bytes": "rate_bytes",
        "rate.period": "rate_period",
    }

    def _add_advertised_aliases(self):
        # These are essentially aliases for new style options, but we still
        # want to advertise them in --rng=help output because they are
        # historically commonly used. This should rarely, if ever, be extended
        if "type" in self.optdict:
            self.optdict["backend.model"] = self.optdict.pop("type")
        if "device" in self.optdict:
            self.optdict["backend"] = self.optdict.pop("device")

    def _parse(self, inst):
        if self.optstr == "none":
            self.guest.skip_default_rng = True
            return

        self._add_advertised_aliases()
        if self.optdict.get("backend.model", "").startswith("/"):
            # Handle --rng /path/to/dev
            self.optdict["backend"] = self.optdict.pop("backend.model")
            self.optdict["backend.model"] = "random"

        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls, virtio_options=True)

        # These are handled in _add_advertised_aliases
        cls.add_arg("type", "backend_model", cb=cls.noset_cb)
        cls.add_arg("device", "device", cb=cls.noset_cb)

        cls.add_arg("model", "model")
        cls.add_arg("backend", "device")
        cls.add_arg("backend.model", "backend_model")
        cls.add_arg("backend.type", "backend_type")

        _add_char_source_args(cls, prefix="backend.")

        cls.add_arg("rate.bytes", "rate_bytes")
        cls.add_arg("rate.period", "rate_period")


######################
# --watchdog parsing #
######################

class ParserWatchdog(VirtCLIParser):
    cli_arg_name = "watchdog"
    guest_propname = "devices.watchdog"
    remove_first = "model"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls)

        cls.add_arg("model", "model", ignore_default=True)
        cls.add_arg("action", "action", ignore_default=True)


####################
# --memdev parsing #
####################

class ParserMemdev(VirtCLIParser):
    cli_arg_name = "memdev"
    guest_propname = "devices.memory"
    remove_first = "model"
    aliases = {
        "target.size": "target_size",
        "target.node": "target_node",
        "target.label_size": "target_label_size",
        "source.pagesize": "source_pagesize",
        "source.path": "source_path",
        "source.nodemask": "source_nodemask",
    }

    def set_target_size(self, inst, val, virtarg):
        xmlutil.set_prop_path(inst, virtarg.propname, int(val) * 1024)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls)

        cls.add_arg("model", "model")
        cls.add_arg("access", "access")
        cls.add_arg("target.size", "target.size", cb=cls.set_target_size)
        cls.add_arg("target.node", "target.node")
        cls.add_arg("target.label_size", "target.label_size",
                cb=cls.set_target_size)
        cls.add_arg("source.pagesize", "source.pagesize")
        cls.add_arg("source.path", "source.path")
        cls.add_arg("source.nodemask", "source.nodemask", can_comma=True)


########################
# --memballoon parsing #
########################

class ParserMemballoon(VirtCLIParser):
    cli_arg_name = "memballoon"
    guest_propname = "devices.memballoon"
    remove_first = "model"
    stub_none = False

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls, virtio_options=True)

        cls.add_arg("model", "model", ignore_default=True)
        cls.add_arg("autodeflate", "autodeflate", is_onoff=True)
        cls.add_arg("stats.period", "stats_period")
        cls.add_arg("freePageReporting", "freePageReporting", is_onoff=True)


###################
# --panic parsing #
###################

class ParserPanic(VirtCLIParser):
    cli_arg_name = "panic"
    guest_propname = "devices.panic"
    remove_first = "model"
    aliases = {
        "address.iobase": "iobase",
    }

    def _parse(self, inst):
        # Handle old style '--panic 0xFOO' to set the iobase value
        if (len(self.optdict) == 1 and
            self.optdict.get("model", "").startswith("0x")):
            self.optdict["address.iobase"] = self.optdict["model"]
            self.optdict["model"] = DevicePanic.MODEL_ISA

        return super()._parse(inst)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls)

        cls.add_arg("model", "model", ignore_default=True)


###################
# --vsock parsing #
###################

class ParserVsock(VirtCLIParser):
    cli_arg_name = "vsock"
    guest_propname = "devices.vsock"
    remove_first = "model"
    stub_none = False
    aliases = {
        "cid.auto": "auto_cid",
        "cid.address": "cid",
    }

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls)

        cls.add_arg("model", "model", ignore_default=True)
        cls.add_arg("cid.auto", "auto_cid", is_onoff=True)
        cls.add_arg("cid.address", "cid")


######################################################
# --serial, --parallel, --channel, --console parsing #
######################################################

class _ParserChar(VirtCLIParser):
    remove_first = "type"
    stub_none = False
    aliases = {
        "type": "char_type",
        "protocol.type": "protocol",

        "target.address": "target_address",
        "target.type": "target_type",
        "target.name": "name",
    }

    def _add_advertised_aliases(self):
        # These are essentially aliases for new style options, but we still
        # want to advertise them in --$OPT=help output because they are
        # historically commonly used. This should rarely, if ever, be extended
        if "path" in self.optdict:
            self.optdict["source.path"] = self.optdict.pop("path")
        if "mode" in self.optdict:
            self.optdict["source.mode"] = self.optdict.pop("mode")
        if "bind_host" in self.optdict:
            self.optdict["source.bind_host"] = self.optdict.pop("bind_host")

    def _parse(self, inst):
        if self.optstr == "none" and inst.DEVICE_TYPE == "console":
            self.guest.skip_default_console = True
            return
        if self.optstr == "none" and inst.DEVICE_TYPE == "channel":
            self.guest.skip_default_channel = True
            return

        self._add_advertised_aliases()
        return super()._parse(inst)


    ###################
    # Option handling #
    ###################

    def set_host_cb(self, inst, val, virtarg):
        if ("source.bind_host" not in self.optdict and
            self.optdict.get("source.mode", None) == "bind"):
            inst.source.set_friendly_bind(val)
        else:
            inst.source.set_friendly_connect(val)

    def set_target_cb(self, inst, val, virtarg):
        inst.set_friendly_target(val)

    @classmethod
    def _init_class(cls, **kwargs):
        # _virtargs already populated via subclass creation, so
        # don't double register options
        if cls._virtargs:
            return

        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls)

        cls.add_arg("type", "type")

        # These are handled in _add_advertised_aliases
        cls.add_arg("path", "source.path", cb=cls.noset_cb)
        cls.add_arg("mode", "source.mode", cb=cls.noset_cb)
        cls.add_arg("bind_host", "source.bind_host", cb=cls.noset_cb)
        # Old backcompat argument
        cls.add_arg("host", "source.host", cb=cls.set_host_cb)

        _add_char_source_args(cls)

        cls.add_arg("target.address", "target_address", cb=cls.set_target_cb)
        cls.add_arg("target.type", "target_type")
        cls.add_arg("target.name", "target_name")
        cls.add_arg("target.port", "target_port")
        cls.add_arg("target.model.name", "target_model_name")


class ParserSerial(_ParserChar):
    cli_arg_name = "serial"
    guest_propname = "devices.serial"


class ParserParallel(_ParserChar):
    cli_arg_name = "parallel"
    guest_propname = "devices.parallel"


class ParserChannel(_ParserChar):
    cli_arg_name = "channel"
    guest_propname = "devices.channel"


class ParserConsole(_ParserChar):
    cli_arg_name = "console"
    guest_propname = "devices.console"


########################
# --filesystem parsing #
########################

class ParserFilesystem(VirtCLIParser):
    cli_arg_name = "filesystem"
    guest_propname = "devices.filesystem"
    remove_first = ["source", "target"]
    aliases = {
        "accessmode": "mode",
    }

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls, virtio_options=True)

        cls.add_arg("type", "type")
        cls.add_arg("accessmode", "accessmode")
        cls.add_arg("model", "model")
        cls.add_arg("multidevs", "multidevs")
        cls.add_arg("readonly", "readonly", is_onoff=True)
        cls.add_arg("space_hard_limit", "space_hard_limit")
        cls.add_arg("space_soft_limit", "space_soft_limit")
        cls.add_arg("fmode", "fmode")
        cls.add_arg("dmode", "dmode")

        cls.add_arg("source", "source")
        cls.add_arg("target", "target")

        cls.add_arg("source.file", "source_file")
        cls.add_arg("source.dir", "source_dir")
        cls.add_arg("source.dev", "source_dev")
        cls.add_arg("source.name", "source_name")
        cls.add_arg("source.pool", "source_pool")
        cls.add_arg("source.volume", "source_volume")
        cls.add_arg("source.units", "source_units")
        cls.add_arg("source.usage", "source_usage")

        cls.add_arg("target.dir", "target_dir")

        cls.add_arg("binary.path", "binary_path")
        cls.add_arg("binary.xattr", "binary_xattr", is_onoff=True)
        cls.add_arg("binary.cache.mode", "binary_cache_mode")
        cls.add_arg("binary.lock.posix", "binary_lock_posix", is_onoff=True)
        cls.add_arg("binary.lock.flock", "binary_lock_flock", is_onoff=True)

        cls.add_arg("driver.format", "driver_format")
        cls.add_arg("driver.name", "driver_name")
        cls.add_arg("driver.queue", "driver_queue")
        cls.add_arg("driver.type", "driver_type")
        cls.add_arg("driver.wrpolicy", "driver_wrpolicy")


###################
# --video parsing #
###################

class ParserVideo(VirtCLIParser):
    cli_arg_name = "video"
    guest_propname = "devices.video"
    remove_first = "model.type"
    aliases = {
        "model.type": "model",
        "model.heads": "heads",
        "model.ram": "ram",
        "model.vram": "vram",
        "model.vram64": "vram64",
        "model.vgamem": "vgamem",
        "model.acceleration.accel3d": "accel3d",
    }

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls, virtio_options=True)

        cls.add_arg("model.type", "model", ignore_default=True)
        cls.add_arg("model.acceleration.accel3d", "accel3d", is_onoff=True)
        cls.add_arg("model.heads", "heads")
        cls.add_arg("model.ram", "ram")
        cls.add_arg("model.vram", "vram")
        cls.add_arg("model.vram64", "vram64")
        cls.add_arg("model.vgamem", "vgamem")


###################
# --sound parsing #
###################

class ParserSound(VirtCLIParser):
    cli_arg_name = "sound"
    guest_propname = "devices.sound"
    remove_first = "model"
    stub_none = False

    def _parse(self, inst):
        if self.optstr == "none":
            self.guest.skip_default_sound = True
            return
        return super()._parse(inst)

    def codec_find_inst_cb(self, *args, **kwargs):
        cliarg = "codec"  # codec[0-9]*
        list_propname = "codecs"
        cb = self._make_find_inst_cb(cliarg, list_propname)
        return cb(*args, **kwargs)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls)

        cls.add_arg("model", "model", ignore_default=True)
        cls.add_arg("audio.id", "audio_id")
        cls.add_arg("codec[0-9]*.type", "type",
                    find_inst_cb=cls.codec_find_inst_cb)


#####################
# --hostdev parsing #
#####################

class ParserHostdev(VirtCLIParser):
    cli_arg_name = "hostdev"
    guest_propname = "devices.hostdev"
    remove_first = "name"
    aliases = {
        "driver.name": "driver_name",
        "rom.bar": "rom_bar",
    }

    def set_name_cb(self, inst, val, virtarg):
        if inst.type == "net":
            inst.mode = "capabilities"
            inst.net_interface = val
        elif inst.type == "misc":
            inst.mode = "capabilities"
            inst.misc_char = val
        elif inst.type == "storage":
            inst.mode = "capabilities"
            inst.storage_block = val
        else:
            val = NodeDevice.lookupNodedevFromString(inst.conn, val)
            inst.set_from_nodedev(val)

    def name_lookup_cb(self, inst, val, virtarg):
        nodedev = NodeDevice.lookupNodedevFromString(inst.conn, val)
        return nodedev.compare_to_hostdev(inst)

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        _add_common_device_args(cls, boot_order=True)

        cls.add_arg("type", "type")
        cls.add_arg("name", None,
                    cb=cls.set_name_cb,
                    lookup_cb=cls.name_lookup_cb)
        cls.add_arg("driver.name", "driver_name")
        cls.add_arg("rom.bar", "rom_bar", is_onoff=True)


#############################
# --launchSecurity parsing #
#############################

class ParserLaunchSecurity(VirtCLIParser):
    cli_arg_name = "launchSecurity"
    guest_propname = "launchSecurity"
    remove_first = "type"

    @classmethod
    def _init_class(cls, **kwargs):
        VirtCLIParser._init_class(**kwargs)
        cls.add_arg("type", "type")
        cls.add_arg("cbitpos", "cbitpos")
        cls.add_arg("reducedPhysBits", "reducedPhysBits")
        cls.add_arg("policy", "policy")
        cls.add_arg("session", "session")
        cls.add_arg("dhCert", "dhCert")


###########################
# Public virt parser APIs #
###########################

def parse_option_strings(options, guest, instlist, editing=False):
    """
    Iterate over VIRT_PARSERS, and launch the associated parser
    function for every value that was filled in on 'options', which
    came from argparse/the command line.

    @editing: If we are updating an existing guest, like from virt-xml
    """
    instlist = xmlutil.listify(instlist)
    if not instlist:
        instlist = [None]

    ret = []
    for parserclass in VIRT_PARSERS:
        optlist = xmlutil.listify(getattr(options, parserclass.cli_arg_name))
        if not optlist:
            continue

        for inst in instlist:
            if inst and optlist:
                # If an object is passed in, we are updating it in place, and
                # only use the last command line occurrence, eg. from virt-xml
                optlist = [optlist[-1]]

            for optstr in optlist:
                parserobj = parserclass(optstr, guest=guest, editing=editing)
                parseret = parserobj.parse(inst)
                ret += xmlutil.listify(parseret)

    return ret


def check_option_introspection(options):
    """
    Check if the user requested option introspection with ex: '--disk=?'
    """
    ret = False
    for parserclass in _get_completer_parsers():
        if not hasattr(options, parserclass.cli_arg_name):
            continue
        optlist = xmlutil.listify(getattr(options, parserclass.cli_arg_name))
        if not optlist:
            continue

        for optstr in optlist:
            if optstr == "?" or optstr == "help":
                parserclass.print_introspection()
                ret = True

    return ret
