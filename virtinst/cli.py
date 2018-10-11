#
# Utility functions for the command line drivers
#
# Copyright 2006-2007, 2013, 2014 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import argparse
import collections
import logging
import logging.handlers
import os
import re
import shlex
import subprocess
import sys
import traceback

import libvirt

from virtcli import CLIConfig

from . import util
from .devices import (Device, DeviceController, DeviceDisk, DeviceGraphics,
        DeviceInterface, DevicePanic)
from .domain import DomainClock, DomainOs
from .nodedev import NodeDevice
from .storage import StoragePool, StorageVolume


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
            return return_default()

        try:
            text = args[0]
            if "\n" in text:
                return text.splitlines()
            return return_default()
        except Exception:
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
                        version=CLIConfig.version)

    return parser


def earlyLogging():
    logging.basicConfig(level=logging.DEBUG, format='%(message)s')


def setupLogging(appname, debug_stdout, do_quiet, cli_app=True):
    _reset_global_state()
    get_global_state().quiet = do_quiet

    vi_dir = None
    logfile = None
    if not _in_testsuite():
        vi_dir = util.get_cache_dir()
        logfile = os.path.join(vi_dir, appname + ".log")

    try:
        if vi_dir and not os.access(vi_dir, os.W_OK):
            if os.path.exists(vi_dir):
                raise RuntimeError("No write access to directory %s" % vi_dir)

            try:
                os.makedirs(vi_dir, 0o751)
            except IOError as e:
                raise RuntimeError("Could not create directory %s: %s" %
                                   (vi_dir, e))

        if (logfile and
            os.path.exists(logfile) and
            not os.access(logfile, os.W_OK)):
            raise RuntimeError("No write access to logfile %s" % logfile)
    except Exception as e:
        logging.warning("Error setting up logfile: %s", e)
        logfile = None


    dateFormat = "%a, %d %b %Y %H:%M:%S"
    fileFormat = ("[%(asctime)s " + appname + " %(process)d] "
                  "%(levelname)s (%(module)s:%(lineno)d) %(message)s")
    streamErrorFormat = "%(levelname)-8s %(message)s"

    rootLogger = logging.getLogger()

    # Undo early logging
    for handler in rootLogger.handlers:
        rootLogger.removeHandler(handler)

    rootLogger.setLevel(logging.DEBUG)
    if logfile:
        fileHandler = logging.handlers.RotatingFileHandler(
            logfile, "ae", 1024 * 1024, 5)
        fileHandler.setFormatter(
            logging.Formatter(fileFormat, dateFormat))
        rootLogger.addHandler(fileHandler)

    streamHandler = logging.StreamHandler(sys.stderr)
    if debug_stdout:
        streamHandler.setLevel(logging.DEBUG)
        streamHandler.setFormatter(logging.Formatter(fileFormat,
                                                     dateFormat))
    elif cli_app or not logfile:
        if get_global_state().quiet:
            level = logging.ERROR
        else:
            level = logging.WARN
        streamHandler.setLevel(level)
        streamHandler.setFormatter(logging.Formatter(streamErrorFormat))
    else:
        streamHandler = None

    if streamHandler:
        rootLogger.addHandler(streamHandler)

    util.register_libvirt_error_handler()

    # Log uncaught exceptions
    def exception_log(typ, val, tb):
        logging.debug("Uncaught exception:\n%s",
                      "".join(traceback.format_exception(typ, val, tb)))
        if not debug_stdout:
            # If we are already logging to stdout, don't double print
            # the backtrace
            sys.__excepthook__(typ, val, tb)
    sys.excepthook = exception_log

    logging.getLogger("requests").setLevel(logging.ERROR)

    # Log the app command string
    logging.debug("Launched with command line: %s", " ".join(sys.argv))


def _in_testsuite():
    return "VIRTINST_TEST_SUITE" in os.environ


##############################
# Libvirt connection helpers #
##############################

def getConnection(uri):
    from .connection import VirtinstConnection

    logging.debug("Requesting libvirt URI %s", (uri or "default"))
    conn = VirtinstConnection(uri)
    conn.open(_openauth_cb, None)
    logging.debug("Received libvirt URI %s", conn.uri)

    return conn


def _openauth_cb(creds, _cbdata):
    for cred in creds:
        # Libvirt virConnectCredential
        credtype, prompt, _challenge, _defresult, _result = cred
        noecho = credtype in [
                libvirt.VIR_CRED_PASSPHRASE, libvirt.VIR_CRED_NOECHOPROMPT]
        if not prompt:
            logging.error("No prompt for auth credtype=%s", credtype)
            return -1
        logging.debug("openauth_cb prompt=%s", prompt)

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
    logging.debug("".join(traceback.format_stack()))
    logging.error(msg)
    if sys.exc_info()[0] is not None:
        logging.debug("", exc_info=True)
    if do_exit:
        _fail_exit()


def print_stdout(msg, do_force=False):
    if do_force or not get_global_state().quiet:
        print(msg)


def print_stderr(msg):
    logging.debug(msg)
    print(msg, file=sys.stderr)


def _fail_exit():
    sys.exit(1)


def nice_exit():
    print_stdout(_("Exiting at user request."))
    sys.exit(0)


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
        logging.warning("--prompt mode is no longer supported.")


def validate_disk(dev, warn_overwrite=False):
    def _optional_fail(msg, checkname, warn_on_skip=True):
        do_check = get_global_state().get_validation_check(checkname)
        if do_check:
            fail(msg + (_(" (Use --check %s=off or "
                "--check all=off to override)") % checkname))

        logging.debug("Skipping --check %s error condition '%s'",
            checkname, msg)
        if warn_on_skip:
            logging.warning(msg)

    def check_path_exists(dev):
        """
        Prompt if disk file already exists and preserve mode is not used
        """
        if not warn_overwrite:
            return
        if not DeviceDisk.path_definitely_exists(dev.conn, dev.path):
            return
        _optional_fail(
            _("This will overwrite the existing path '%s'") % dev.path,
            "path_exists")

    def check_inuse_conflict(dev):
        """
        Check if disk is inuse by another guest
        """
        names = dev.is_conflict_disk()
        if not names:
            return

        _optional_fail(_("Disk %s is already in use by other guests %s." %
            (dev.path, names)),
            "path_in_use")

    def check_size_conflict(dev):
        """
        Check if specified size exceeds available storage
        """
        isfatal, errmsg = dev.is_size_conflict()
        # The isfatal case should have already caused us to fail
        if not isfatal and errmsg:
            _optional_fail(errmsg, "disk_size", warn_on_skip=False)

    def check_path_search(dev):
        user, broken_paths = dev.check_path_search(dev.conn, dev.path)
        if not broken_paths:
            return
        logging.warning(_("%s may not be accessible by the hypervisor. "
            "You will need to grant the '%s' user search permissions for "
            "the following directories: %s"), dev.path, user, broken_paths)

    check_path_exists(dev)
    check_inuse_conflict(dev)
    check_size_conflict(dev)
    check_path_search(dev)


def _run_console(domain, args):
    logging.debug("Running: %s", " ".join(args))
    if _in_testsuite():
        # Add this destroy() in here to trigger more virt-install code
        # for the test suite
        domain.destroy()
        return None

    child = os.fork()
    if child:
        return child

    os.execvp(args[0], args)
    os._exit(1)  # pylint: disable=protected-access


def _gfx_console(guest, domain):
    args = ["virt-viewer",
            "--connect", guest.conn.uri,
            "--wait", guest.name]

    # Currently virt-viewer needs attaching to the local display while
    # spice gl is enabled or listen type none is used.
    if guest.has_gl() or guest.has_listen_none():
        args.append("--attach")

    logging.debug("Launching virt-viewer for graphics type '%s'",
        guest.devices.graphics[0].type)
    return _run_console(domain, args)


def _txt_console(guest, domain):
    args = ["virsh",
            "--connect", guest.conn.uri,
            "console", guest.name]

    logging.debug("Connecting to text console")
    return _run_console(domain, args)


def connect_console(guest, domain, consolecb, wait):
    """
    Launched the passed console callback for the already defined
    domain. If domain isn't running, return an error.
    """
    child = None
    if consolecb:
        child = consolecb(guest, domain)

    if not child or not wait:
        return

    # If we connected the console, wait for it to finish
    try:
        os.waitpid(child, 0)
    except OSError as e:
        logging.debug("waitpid error: %s", e)


def get_console_cb(guest):
    gdevs = guest.devices.graphics
    if not gdevs:
        return _txt_console

    gtype = gdevs[0].type
    if gtype not in ["default",
            DeviceGraphics.TYPE_VNC,
            DeviceGraphics.TYPE_SPICE]:
        logging.debug("No viewer to launch for graphics type '%s'", gtype)
        return

    if not _in_testsuite():
        try:
            subprocess.check_output(["virt-viewer", "--version"])
        except OSError:
            logging.warning(_("Unable to connect to graphical console: "
                           "virt-viewer not installed. Please install "
                           "the 'virt-viewer' package."))
            return None

        if not os.environ.get("DISPLAY", ""):
            logging.warning(_("Graphics requested but DISPLAY is not set. "
                           "Not running virt-viewer."))
            return None

    return _gfx_console


def get_meter():
    quiet = (get_global_state().quiet or _in_testsuite())
    return util.make_meter(quiet=quiet)


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
        grp.add_argument("--noautoconsole", action="store_false",
            dest="autoconsole", default=True,
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
    grp.add_argument("--metadata", action="append",
        help=_("Configure guest metadata. Ex:\n"
        "--metadata name=foo,title=\"My pretty title\",uuid=...\n"
        "--metadata description=\"My nice long description\""))


def add_memory_option(grp, backcompat=False):
    grp.add_argument("--memory", action="append",
        help=_("Configure guest memory allocation. Ex:\n"
               "--memory 1024 (in MiB)\n"
               "--memory 512,maxmemory=1024\n"
               "--memory 512,maxmemory=1024,hotplugmemorymax=2048,"
               "hotplugmemoryslots=2"))
    if backcompat:
        grp.add_argument("-r", "--ram", type=int, dest="oldmemory",
            help=argparse.SUPPRESS)


def vcpu_cli_options(grp, backcompat=True, editexample=False):
    grp.add_argument("--vcpus", action="append",
        help=_("Number of vcpus to configure for your guest. Ex:\n"
               "--vcpus 5\n"
               "--vcpus 5,maxcpus=10,cpuset=1-4,6,8\n"
               "--vcpus sockets=2,cores=4,threads=2,"))

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
    devg.add_argument("--graphics", action="append",
      help=_("Configure guest display settings. Ex:\n"
             "--graphics vnc\n"
             "--graphics spice,port=5901,tlsport=5902\n"
             "--graphics none\n"
             "--graphics vnc,password=foobar,port=5910,keymap=ja"))


def add_net_option(devg):
    devg.add_argument("-w", "--network", action="append",
      help=_("Configure a guest network interface. Ex:\n"
             "--network bridge=mybr0\n"
             "--network network=my_libvirt_virtual_net\n"
             "--network network=mynet,model=virtio,mac=00:11...\n"
             "--network none\n"
             "--network help"))


def add_device_options(devg, sound_back_compat=False):
    devg.add_argument("--controller", action="append",
        help=_("Configure a guest controller device. Ex:\n"
               "--controller type=usb,model=qemu-xhci\n"
               "--controller virtio-scsi\n"))
    devg.add_argument("--input", action="append",
        help=_("Configure a guest input device. Ex:\n"
               "--input tablet\n"
               "--input keyboard,bus=usb"))
    devg.add_argument("--serial", action="append",
                    help=_("Configure a guest serial device"))
    devg.add_argument("--parallel", action="append",
                    help=_("Configure a guest parallel device"))
    devg.add_argument("--channel", action="append",
                    help=_("Configure a guest communication channel"))
    devg.add_argument("--console", action="append",
                    help=_("Configure a text console connection between "
                           "the guest and host"))
    devg.add_argument("--hostdev", action="append",
                    help=_("Configure physical USB/PCI/etc host devices "
                           "to be shared with the guest"))
    devg.add_argument("--filesystem", action="append",
        help=_("Pass host directory to the guest. Ex: \n"
               "--filesystem /my/source/dir,/dir/in/guest\n"
               "--filesystem template_name,/,type=template"))

    # Back compat name
    devg.add_argument("--host-device", action="append", dest="hostdev",
                    help=argparse.SUPPRESS)

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

    devg.add_argument("--watchdog", action="append",
                    help=_("Configure a guest watchdog device"))
    devg.add_argument("--video", action="append",
                    help=_("Configure guest video hardware."))
    devg.add_argument("--smartcard", action="append",
                    help=_("Configure a guest smartcard device. Ex:\n"
                           "--smartcard mode=passthrough"))
    devg.add_argument("--redirdev", action="append",
                    help=_("Configure a guest redirection device. Ex:\n"
                           "--redirdev usb,type=tcp,server=192.168.1.1:4000"))
    devg.add_argument("--memballoon", action="append",
                    help=_("Configure a guest memballoon device. Ex:\n"
                           "--memballoon model=virtio"))
    devg.add_argument("--tpm", action="append",
                    help=_("Configure a guest TPM device. Ex:\n"
                           "--tpm /dev/tpm"))
    devg.add_argument("--rng", action="append",
                    help=_("Configure a guest RNG device. Ex:\n"
                           "--rng /dev/urandom"))
    devg.add_argument("--panic", action="append",
                    help=_("Configure a guest panic device. Ex:\n"
                           "--panic default"))
    devg.add_argument("--memdev", action="append",
                    help=_("Configure a guest memory device. Ex:\n"
                           "--memdev dimm,target_size=1024"))


def add_guest_xml_options(geng):
    geng.add_argument("--security", action="append",
        help=_("Set domain security driver configuration."))
    geng.add_argument("--cputune", action="append",
        help=_("Tune CPU parameters for the domain process."))
    geng.add_argument("--numatune", action="append",
        help=_("Tune NUMA policy for the domain process."))
    geng.add_argument("--memtune", action="append",
        help=_("Tune memory policy for the domain process."))
    geng.add_argument("--blkiotune", action="append",
        help=_("Tune blkio policy for the domain process."))
    geng.add_argument("--memorybacking", action="append",
        help=_("Set memory backing policy for the domain process. Ex:\n"
               "--memorybacking hugepages=on"))
    geng.add_argument("--features", action="append",
        help=_("Set domain <features> XML. Ex:\n"
               "--features acpi=off\n"
               "--features apic=on,eoi=on"))
    geng.add_argument("--clock", action="append",
        help=_("Set domain <clock> XML. Ex:\n"
               "--clock offset=localtime,rtc_tickpolicy=catchup"))
    geng.add_argument("--pm", action="append",
        help=_("Configure VM power management features"))
    geng.add_argument("--events", action="append",
        help=_("Configure VM lifecycle management policy"))
    geng.add_argument("--resource", action="append",
        help=_("Configure VM resource partitioning (cgroups)"))
    geng.add_argument("--sysinfo", action="append",
        help=_("Configure SMBIOS System Information. Ex:\n"
               "--sysinfo host\n"
               "--sysinfo bios_vendor=MyVendor,bios_version=1.2.3,...\n"))
    geng.add_argument("--qemu-commandline", action="append",
        help=_("Pass arguments directly to the qemu emulator. Ex:\n"
               "--qemu-commandline='-display gtk,gl=on'\n"
               "--qemu-commandline env=DISPLAY=:0.1"))


def add_boot_options(insg):
    insg.add_argument("--boot", action="append",
        help=_("Configure guest boot settings. Ex:\n"
               "--boot hd,cdrom,menu=on\n"
               "--boot init=/sbin/init (for containers)"))
    insg.add_argument("--idmap", action="append",
        help=_("Enable user namespace for LXC container. Ex:\n"
               "--idmap uid_start=0,uid_target=1000,uid_count=10"))


def add_disk_option(stog, editexample=False):
    editmsg = ""
    if editexample:
        editmsg += "\n--disk cache=  (unset cache)"
    stog.add_argument("--disk", action="append",
        help=_("Specify storage with various options. Ex.\n"
               "--disk size=10 (new 10GiB image in default location)\n"
               "--disk /my/existing/disk,cache=none\n"
               "--disk device=cdrom,bus=scsi\n"
               "--disk=?") + editmsg)


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


def _set_attribute(obj, attr, val):  # pylint: disable=unused-argument
    exec("obj." + attr + " = val ")  # pylint: disable=exec-used


class _VirtCLIArgumentStatic(object):
    """
    Helper class to hold all of the static data we need for knowing
    how to parse a cli subargument, like --disk path=, or --network mac=.

    @attrname: The virtinst API attribute name the cliargument maps to.
        If this is a virtinst object method, it will be called.
    @cliname: The command line option name, 'path' for path=FOO

    @cb: Rather than set an attribute directly on the virtinst
        object, (self, inst, val, virtarg) to this callback to handle it.
    @ignore_default: If the value passed on the cli is 'default', don't
        do anything.
    @can_comma: If True, this option is expected to have embedded commas.
        After the parser sees this option, it will iterate over the
        option string until it finds another known argument name:
        everything prior to that argument name is considered part of
        the value of this option, '=' included. Should be used sparingly.
    @aliases: List of cli aliases. Useful if we want to change a property
        name on the cli but maintain back compat.
    @is_list: This value should be stored as a list, so multiple instances
        are appended.
    @is_onoff: The value expected on the cli is on/off or yes/no, convert
        it to true/false.
    @lookup_cb: If specified, use this function for performing match
        lookups.
    @is_novalue: If specified, the parameter is not expected in the
        form FOO=BAR, but just FOO.
    @find_inst_cb: If specified, this can be used to return a different
        'inst' to check and set attributes against. For example,
        DeviceDisk has multiple seclabel children, this provides a hook
        to lookup the specified child object.
    """
    def __init__(self, attrname, cliname,
                 cb=None, can_comma=None,
                 ignore_default=False, aliases=None,
                 is_list=False, is_onoff=False,
                 lookup_cb=None, is_novalue=False,
                 find_inst_cb=None):
        self.attrname = attrname
        self.cliname = cliname
        self.cb = cb
        self.can_comma = can_comma
        self.ignore_default = ignore_default
        self.aliases = aliases
        self.is_list = is_list
        self.is_onoff = is_onoff
        self.lookup_cb = lookup_cb
        self.is_novalue = is_novalue
        self.find_inst_cb = find_inst_cb

    def match_name(self, cliname):
        """
        Return True if the passed argument name matches this
        VirtCLIArgument. So for an option like --foo bar=X, this
        checks if we are the parser for 'bar'
        """
        for argname in [self.cliname] + util.listify(self.aliases):
            if re.match("^%s$" % argname, cliname):
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
        # Sanitize the value
        if val is None:
            if not virtarg.is_novalue:
                raise RuntimeError("Option '%s' had no value set." % key)
            val = ""
        if val == "":
            val = None
        if virtarg.is_onoff:
            val = _on_off_convert(key, val)

        self.val = val
        self.key = key
        self._virtarg = virtarg

        # For convenience
        self.attrname = virtarg.attrname
        self.cliname = virtarg.cliname

    def parse_param(self, parser, inst, support_cb):
        """
        Process the cli param against the pass inst.

        So if we are VirtCLIArgument for --disk device=, and the user
        specified --disk device=foo, we were instantiated with
        key=device val=foo, so set inst.device = foo
        """
        if support_cb:
            support_cb(inst, self)
        if self.val == "default" and self._virtarg.ignore_default:
            return

        if self._virtarg.find_inst_cb:
            inst = self._virtarg.find_inst_cb(parser,
                                              inst, self.val, self, True)

        try:
            if self.attrname:
                eval("inst." + self.attrname)  # pylint: disable=eval-used
        except AttributeError:
            raise RuntimeError("programming error: obj=%s does not have "
                               "member=%s" % (inst, self.attrname))

        if self._virtarg.cb:
            self._virtarg.cb(parser, inst, self.val, self)
        else:
            _set_attribute(inst, self.attrname, self.val)

    def lookup_param(self, parser, inst):
        """
        See if the passed value matches our Argument, like via virt-xml

        So if this Argument is for --disk device=, and the user
        specified virt-xml --edit device=floppy --disk ..., we were
        instantiated with key=device val=floppy, so return
        'inst.device == floppy'
        """
        if not self.attrname and not self._virtarg.lookup_cb:
            raise RuntimeError(
                _("Don't know how to match device type '%(device_type)s' "
                  "property '%(property_name)s'") %
                {"device_type": getattr(inst, "DEVICE_TYPE", ""),
                 "property_name": self.key})

        if self._virtarg.find_inst_cb:
            inst = self._virtarg.find_inst_cb(parser,
                                              inst, self.val, self, False)
            if not inst:
                return False

        if self._virtarg.lookup_cb:
            return self._virtarg.lookup_cb(parser,
                                           inst, self.val, self)
        else:
            return eval(  # pylint: disable=eval-used
                "inst." + self.attrname) == self.val


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
        if not opt:
            continue

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

    def _add_opt(virtarg, cliname, val):
        if (cliname not in optdict and
            virtarg.is_list):
            optdict[cliname] = []

        if isinstance(optdict.get(cliname), list):
            optdict[cliname].append(val)
        else:
            optdict[cliname] = val

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
            _add_opt(virtarg, commaopt[0], commaopt[1])
        else:
            _add_opt(virtarg, cliname, val)

    return optdict


class VirtCLIParser(object):
    """
    Parse a compound arg string like --option foo=bar,baz=12. This is
    the desired interface to VirtCLIArgument and VirtCLIOptionString.

    A command line argument like --disk just extends this interface
    and calls add_arg a bunch to register subarguments like path=,
    size=, etc. See existing impls examples of how to do all sorts of
    crazy stuff.

    Class parameters:
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
    @support_cb: An extra support check function for further validation.
        Called before the virtinst object is altered. Take arguments
        (inst, attrname, cliname)
    @cli_arg_name: The command line argument this maps to, so
        "hostdev" for --hostdev
    """
    propname = None
    remove_first = None
    stub_none = True
    support_cb = None
    cli_arg_name = None
    _virtargs = []

    @classmethod
    def add_arg(cls, *args, **kwargs):
        """
        Add a VirtCLIArgument for this class.
        """
        if not cls._virtargs:
            cls._virtargs = [_VirtCLIArgumentStatic(
                None, "clearxml", cb=cls._clearxml_cb, is_onoff=True)]
        cls._virtargs.append(_VirtCLIArgumentStatic(*args, **kwargs))

    @classmethod
    def print_introspection(cls):
        """
        Print out all _param names, triggered via ex. --disk help
        """
        print("--%s options:" % cls.cli_arg_name)
        for arg in sorted(cls._virtargs, key=lambda p: p.cliname):
            print("  %s" % arg.cliname)
        print("")

    @classmethod
    def lookup_prop(cls, obj):
        """
        For the passed obj, return the equivalent of
        getattr(obj, cls.propname), but handle '.' in the propname
        """
        if not cls.propname:
            return None
        parent = obj
        pieces = cls.propname.split(".")
        for piece in pieces[:-1]:
            parent = getattr(parent, piece)

        return getattr(parent, pieces[-1])

    @classmethod
    def prop_is_list(cls, obj):
        inst = cls.lookup_prop(obj)
        return isinstance(inst, list)


    def __init__(self, guest, optstr):
        self.guest = guest
        self.optstr = optstr
        self.optdict = _parse_optstr_to_dict(self.optstr,
                self._virtargs, util.listify(self.remove_first)[:])

    def _clearxml_cb(self, inst, val, virtarg):
        """
        Callback that handles virt-xml clearxml=yes|no magic
        """
        if not self.propname:
            raise RuntimeError("Don't know how to clearxml --%s" %
                               self.cli_arg_name)
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

    def _make_find_inst_cb(self, cliarg, objpropname):
        """
        Create a callback used for find_inst_cb command line lookup.

        :param cliarg: The cliarg string that is followed by an index.
            Example, for --disk seclabel[0-9]* mapping, this is 'seclabel'
        :param objpropname: The property name on the virtinst object that
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
                while len(getattr(inst, objpropname)) < (num + 1):
                    getattr(inst, objpropname).add_new()
            try:
                return getattr(inst, objpropname)[num]
            except IndexError:
                if not can_edit:
                    return None
                raise
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
            fail(_("Unknown options %s") % list(optdict.keys()))

    def _parse(self, inst):
        """
        Subclasses can hook into this to do any pre/post processing
        of the inst, or self.optdict
        """
        optdict = self.optdict.copy()
        for param in self._optdict_to_param_list(optdict):
            param.parse_param(self, inst, self.support_cb)

        self._check_leftover_opts(optdict)
        return inst

    def parse(self, inst, validate=True):
        """
        Main entry point. Iterate over self._virtargs, and serialize
        self.optdict into 'inst'.

        For virt-xml, 'inst' is the virtinst object we are editing,
        ex. a DeviceDisk from a parsed Guest object.
        For virt-install, 'inst' is None, and we will create a new
        inst for self.propname, or edit a singleton object in place
        like Guest.features/DomainFeatures
        """
        if not self.optstr:
            return None
        if self.stub_none and self.optstr == "none":
            return None

        new_object = False
        if self.propname and not inst:
            inst = self.lookup_prop(self.guest)
            new_object = self.prop_is_list(self.guest)
            if new_object:
                inst = inst.new()

        ret = []
        try:
            objs = self._parse(inst or self.guest)
            if new_object:
                for obj in util.listify(objs):
                    if validate:
                        obj.validate()

                    if isinstance(obj, Device):
                        self.guest.add_device(obj)
                    else:
                        self.guest.add_child(obj)

            ret += util.listify(objs)
        except Exception as e:
            logging.debug("Exception parsing inst=%s optstr=%s",
                          inst, self.optstr, exc_info=True)
            fail(_("Error: --%(cli_arg_name)s %(options)s: %(err)s") %
                    {"cli_arg_name": self.cli_arg_name,
                     "options": self.optstr, "err": str(e)})

        return ret

    def lookup_child_from_option_string(self):
        """
        Given a passed option string, search the guests' child list
        for all objects which match the passed options.

        Used only by virt-xml --edit lookups
        """
        ret = []
        objlist = util.listify(self.lookup_prop(self.guest))

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
            logging.debug("Exception parsing inst=%s optstr=%s",
                          inst, self.optstr, exc_info=True)
            fail(_("Error: --%(cli_arg_name)s %(options)s: %(err)s") %
                    {"cli_arg_name": self.cli_arg_name,
                     "options": self.optstr, "err": str(e)})

        return ret


VIRT_PARSERS = []


def _register_virt_parser(parserclass):
    VIRT_PARSERS.append(parserclass)


###################
# --check parsing #
###################

def convert_old_force(options):
    if options.force:
        if not options.check:
            options.check = "all=off"
        del(options.force)


class ParseCLICheck(VirtCLIParser):
    cli_arg_name = "check"

    def set_cb(self, inst, val, virtarg):
        # This sets properties on the _GlobalState objects
        inst.set_validation_check(virtarg.cliname, val)


ParseCLICheck.add_arg(None, "path_in_use", is_onoff=True,
                      cb=ParseCLICheck.set_cb)
ParseCLICheck.add_arg(None, "disk_size", is_onoff=True,
                      cb=ParseCLICheck.set_cb)
ParseCLICheck.add_arg(None, "path_exists", is_onoff=True,
                      cb=ParseCLICheck.set_cb)
ParseCLICheck.add_arg("all_checks", "all", is_onoff=True)


def parse_check(checks):
    # Overwrite this for each parse
    for checkstr in util.listify(checks):
        parser = ParseCLICheck(None, checkstr)
        parser.parse(get_global_state())


######################
# --metadata parsing #
######################

class ParserMetadata(VirtCLIParser):
    cli_arg_name = "metadata"

    def set_os_name_cb(self, inst, val, virtarg):
        inst.set_os_name(val)

    def set_os_full_id_cb(self, inst, val, virtarg):
        inst.set_os_full_id(val)

_register_virt_parser(ParserMetadata)
ParserMetadata.add_arg("name", "name", can_comma=True)
ParserMetadata.add_arg("title", "title", can_comma=True)
ParserMetadata.add_arg("uuid", "uuid")
ParserMetadata.add_arg("description", "description", can_comma=True)
ParserMetadata.add_arg(None, "os_name", cb=ParserMetadata.set_os_name_cb)
ParserMetadata.add_arg(None, "os_full_id", cb=ParserMetadata.set_os_full_id_cb)


####################
# --events parsing #
####################

class ParserEvents(VirtCLIParser):
    cli_arg_name = "events"

_register_virt_parser(ParserEvents)
ParserEvents.add_arg("on_poweroff", "on_poweroff")
ParserEvents.add_arg("on_reboot", "on_reboot")
ParserEvents.add_arg("on_crash", "on_crash")
ParserEvents.add_arg("on_lockfailure", "on_lockfailure")


######################
# --resource parsing #
######################

class ParserResource(VirtCLIParser):
    cli_arg_name = "resource"
    propname = "resource"
    remove_first = "partition"

_register_virt_parser(ParserResource)
ParserResource.add_arg("partition", "partition")


######################
# --numatune parsing #
######################

class ParserNumatune(VirtCLIParser):
    cli_arg_name = "numatune"
    propname = "numatune"
    remove_first = "nodeset"

_register_virt_parser(ParserNumatune)
ParserNumatune.add_arg("memory_nodeset", "nodeset", can_comma=True)
ParserNumatune.add_arg("memory_mode", "mode")


####################
# --memory parsing #
####################

class ParserMemory(VirtCLIParser):
    cli_arg_name = "memory"
    remove_first = "memory"

    def set_memory_cb(self, inst, val, virtarg):
        setattr(inst, virtarg.cliname, int(val) * 1024)


_register_virt_parser(ParserMemory)
ParserMemory.add_arg("memory", "memory", cb=ParserMemory.set_memory_cb)
ParserMemory.add_arg("maxmemory", "maxmemory", cb=ParserMemory.set_memory_cb)
ParserMemory.add_arg("memoryBacking.hugepages", "hugepages", is_onoff=True)
ParserMemory.add_arg("hotplugmemorymax", "hotplugmemorymax",
                     cb=ParserMemory.set_memory_cb)
ParserMemory.add_arg("hotplugmemoryslots", "hotplugmemoryslots")


#####################
# --memtune parsing #
#####################

class ParserMemtune(VirtCLIParser):
    cli_arg_name = "memtune"
    propname = "memtune"
    remove_first = "soft_limit"

_register_virt_parser(ParserMemtune)
ParserMemtune.add_arg("hard_limit", "hard_limit")
ParserMemtune.add_arg("soft_limit", "soft_limit")
ParserMemtune.add_arg("swap_hard_limit", "swap_hard_limit")
ParserMemtune.add_arg("min_guarantee", "min_guarantee")


#######################
# --blkiotune parsing #
#######################

class ParserBlkiotune(VirtCLIParser):
    cli_arg_name = "blkiotune"
    propname = "blkiotune"
    remove_first = "weight"

_register_virt_parser(ParserBlkiotune)
ParserBlkiotune.add_arg("weight", "weight")
ParserBlkiotune.add_arg("device_path", "device_path")
ParserBlkiotune.add_arg("device_weight", "device_weight")


###########################
# --memorybacking parsing #
###########################

class ParserMemoryBacking(VirtCLIParser):
    cli_arg_name = "memorybacking"
    propname = "memoryBacking"

_register_virt_parser(ParserMemoryBacking)
ParserMemoryBacking.add_arg("hugepages", "hugepages", is_onoff=True)
ParserMemoryBacking.add_arg("page_size", "size")
ParserMemoryBacking.add_arg("page_unit", "unit")
ParserMemoryBacking.add_arg("page_nodeset", "nodeset", can_comma=True)
ParserMemoryBacking.add_arg("nosharepages", "nosharepages", is_onoff=True)
ParserMemoryBacking.add_arg("locked", "locked", is_onoff=True)
ParserMemoryBacking.add_arg("access_mode", "access_mode")
ParserMemoryBacking.add_arg("source_type", "source_type")


#################
# --cpu parsing #
#################

class ParserCPU(VirtCLIParser):
    cli_arg_name = "cpu"
    propname = "cpu"
    remove_first = "model"
    stub_none = False


    def cell_find_inst_cb(self, *args, **kwargs):
        cliarg = "cell"  # cell[0-9]*
        objpropname = "cells"  # cpu.cells
        cb = self._make_find_inst_cb(cliarg, objpropname)
        return cb(*args, **kwargs)

    def sibling_find_inst_cb(self, inst, *args, **kwargs):
        cell = self.cell_find_inst_cb(inst, *args, **kwargs)
        inst = cell

        cliarg = "sibling"  # cell[0-9]*.distances.sibling[0-9]*
        objpropname = "siblings"  # cell.siblings
        cb = self._make_find_inst_cb(cliarg, objpropname)
        return cb(inst, *args, **kwargs)

    def set_model_cb(self, inst, val, virtarg):
        if val == "host":
            val = inst.SPECIAL_MODE_HOST_MODEL
        if val == "none":
            val = inst.SPECIAL_MODE_CLEAR

        if val in inst.SPECIAL_MODES:
            inst.set_special_mode(self.guest, val)
        else:
            inst.model = val

    def set_feature_cb(self, inst, val, virtarg):
        policy = virtarg.cliname
        for feature_name in util.listify(val):
            featureobj = None

            for f in inst.features:
                if f.name == feature_name:
                    featureobj = f
                    break

            if featureobj:
                featureobj.policy = policy
            else:
                inst.add_feature(feature_name, policy)

    def set_l3_cache_cb(self, inst, val, virtarg, can_edit):
        cpu = inst

        if can_edit and not cpu.cache:
            cpu.cache.add_new()
        try:
            return cpu.cache[0]
        except IndexError:
            if not can_edit:
                return None
            raise

    def _parse(self, inst):
        # Convert +feature, -feature into expected format
        for key, value in list(self.optdict.items()):
            policy = None
            if value or len(key) == 1:
                continue

            if key.startswith("+"):
                policy = "force"
            elif key.startswith("-"):
                policy = "disable"

            if policy:
                del(self.optdict[key])
                if self.optdict.get(policy) is None:
                    self.optdict[policy] = []
                self.optdict[policy].append(key[1:])

        return VirtCLIParser._parse(self, inst)


_register_virt_parser(ParserCPU)
ParserCPU.add_arg(None, "model", cb=ParserCPU.set_model_cb)
ParserCPU.add_arg("mode", "mode")
ParserCPU.add_arg("match", "match")
ParserCPU.add_arg("vendor", "vendor")

ParserCPU.add_arg(None, "force", is_list=True, cb=ParserCPU.set_feature_cb)
ParserCPU.add_arg(None, "require", is_list=True, cb=ParserCPU.set_feature_cb)
ParserCPU.add_arg(None, "optional", is_list=True, cb=ParserCPU.set_feature_cb)
ParserCPU.add_arg(None, "disable", is_list=True, cb=ParserCPU.set_feature_cb)
ParserCPU.add_arg(None, "forbid", is_list=True, cb=ParserCPU.set_feature_cb)

# Options for CPU.cells config
ParserCPU.add_arg("id", "cell[0-9]*.id",
                  find_inst_cb=ParserCPU.cell_find_inst_cb)
ParserCPU.add_arg("cpus", "cell[0-9]*.cpus", can_comma=True,
                  find_inst_cb=ParserCPU.cell_find_inst_cb)
ParserCPU.add_arg("memory", "cell[0-9]*.memory",
                  find_inst_cb=ParserCPU.cell_find_inst_cb)
ParserCPU.add_arg("id", "cell[0-9]*.distances.sibling[0-9]*.id",
                  find_inst_cb=ParserCPU.sibling_find_inst_cb)
ParserCPU.add_arg("value", "cell[0-9]*.distances.sibling[0-9]*.value",
                  find_inst_cb=ParserCPU.sibling_find_inst_cb)

# Options for CPU.cache
ParserCPU.add_arg("mode", "cache.mode", find_inst_cb=ParserCPU.set_l3_cache_cb)
ParserCPU.add_arg("level", "cache.level", find_inst_cb=ParserCPU.set_l3_cache_cb)


#####################
# --cputune parsing #
#####################

class ParserCputune(VirtCLIParser):
    cli_arg_name = "cputune"
    propname = "cputune"
    remove_first = "model"
    stub_none = False

    def vcpu_find_inst_cb(self, *args, **kwargs):
        cliarg = "vcpupin"  # vcpupin[0-9]*
        objpropname = "vcpus"
        cb = self._make_find_inst_cb(cliarg, objpropname)
        return cb(*args, **kwargs)

_register_virt_parser(ParserCputune)
# Options for CPU.vcpus config
ParserCputune.add_arg("vcpu", "vcpupin[0-9]*.vcpu",
                  find_inst_cb=ParserCputune.vcpu_find_inst_cb)
ParserCputune.add_arg("cpuset", "vcpupin[0-9]*.cpuset", can_comma=True,
                  find_inst_cb=ParserCputune.vcpu_find_inst_cb)


###################
# --vcpus parsing #
###################

class ParserVCPU(VirtCLIParser):
    cli_arg_name = "vcpus"
    remove_first = "vcpus"

    def set_vcpus_cb(self, inst, val, virtarg):
        attrname = (("maxvcpus" in self.optdict) and
                    "curvcpus" or "vcpus")
        setattr(inst, attrname, val)

    def set_cpuset_cb(self, inst, val, virtarg):
        if not val:
            return
        if val != "auto":
            inst.cpuset = val
            return

        # Previously we did our own one-time cpuset placement
        # based on current NUMA memory availability, but that's
        # pretty dumb unless the conditions on the host never change.
        # So instead use newer vcpu placement=
        inst.vcpu_placement = "auto"

    def _parse(self, inst):
        set_from_top = ("maxvcpus" not in self.optdict and
                        "vcpus" not in self.optdict)

        ret = VirtCLIParser._parse(self, inst)

        if set_from_top:
            inst.vcpus = inst.cpu.vcpus_from_topology()
        return ret


_register_virt_parser(ParserVCPU)
ParserVCPU.add_arg("cpu.sockets", "sockets")
ParserVCPU.add_arg("cpu.cores", "cores")
ParserVCPU.add_arg("cpu.threads", "threads")

ParserVCPU.add_arg(None, "vcpus", cb=ParserVCPU.set_vcpus_cb)
ParserVCPU.add_arg("vcpus", "maxvcpus")

ParserVCPU.add_arg(None, "cpuset", can_comma=True, cb=ParserVCPU.set_cpuset_cb)
ParserVCPU.add_arg("vcpu_placement", "placement")


##################
# --boot parsing #
##################

class ParserBoot(VirtCLIParser):
    cli_arg_name = "boot"
    propname = "os"

    def set_uefi_cb(self, inst, val, virtarg):
        self.guest.set_uefi_path(self.guest.get_uefi_path())

    def set_initargs_cb(self, inst, val, virtarg):
        inst.set_initargs_string(val)

    def set_smbios_mode_cb(self, inst, val, virtarg):
        inst.smbios_mode = val
        self.optdict["smbios_mode"] = val

    def set_bootloader_cb(self, inst, val, virtarg):
        self.guest.bootloader = val

    def set_domain_type_cb(self, inst, val, virtarg):
        self.guest.type = val

    def set_emulator_cb(self, inst, val, virtarg):
        self.guest.emulator = val

    def noset_cb(self, inst, val, virtarg):
        pass

    def _parse(self, inst):
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

        VirtCLIParser._parse(self, inst)


_register_virt_parser(ParserBoot)
# UEFI depends on these bits, so set them first
ParserBoot.add_arg("arch", "arch")
ParserBoot.add_arg(None, "bootloader", cb=ParserBoot.set_bootloader_cb)
ParserBoot.add_arg(None, "domain_type", cb=ParserBoot.set_domain_type_cb)
ParserBoot.add_arg("os_type", "os_type")
ParserBoot.add_arg(None, "emulator", cb=ParserBoot.set_emulator_cb)
ParserBoot.add_arg("machine", "machine")
ParserBoot.add_arg(None, "uefi", cb=ParserBoot.set_uefi_cb, is_novalue=True)

ParserBoot.add_arg("useserial", "useserial", is_onoff=True)
ParserBoot.add_arg("enable_bootmenu", "menu", is_onoff=True)
ParserBoot.add_arg("os.rebootTimeout", "rebootTimeout")
ParserBoot.add_arg("kernel", "kernel")
ParserBoot.add_arg("initrd", "initrd")
ParserBoot.add_arg("dtb", "dtb")
ParserBoot.add_arg("loader", "loader")
ParserBoot.add_arg("loader_ro", "loader_ro", is_onoff=True)
ParserBoot.add_arg("loader_type", "loader_type")
ParserBoot.add_arg("loader_secure", "loader_secure", is_onoff=True)
ParserBoot.add_arg("nvram", "nvram")
ParserBoot.add_arg("nvram_template", "nvram_template")
ParserBoot.add_arg("kernel_args", "kernel_args",
                   aliases=["extra_args"], can_comma=True)
ParserBoot.add_arg("init", "init")
ParserBoot.add_arg("initargs", "initargs", cb=ParserBoot.set_initargs_cb)
ParserBoot.add_arg("smbios_mode", "smbios_mode")

# This is simply so the boot options are advertised with --boot help,
# actual processing is handled by _parse
for _bootdev in DomainOs.BOOT_DEVICES:
    ParserBoot.add_arg(None, _bootdev, is_novalue=True, cb=ParserBoot.noset_cb)


###################
# --idmap parsing #
###################

class ParserIdmap(VirtCLIParser):
    cli_arg_name = "idmap"
    propname = "idmap"

_register_virt_parser(ParserIdmap)
ParserIdmap.add_arg("uid_start", "uid_start")
ParserIdmap.add_arg("uid_target", "uid_target")
ParserIdmap.add_arg("uid_count", "uid_count")
ParserIdmap.add_arg("gid_start", "gid_start")
ParserIdmap.add_arg("gid_target", "gid_target")
ParserIdmap.add_arg("gid_count", "gid_count")


######################
# --security parsing #
######################

class ParserSecurity(VirtCLIParser):
    cli_arg_name = "security"
    propname = "seclabels"

_register_virt_parser(ParserSecurity)
ParserSecurity.add_arg("type", "type")
ParserSecurity.add_arg("model", "model")
ParserSecurity.add_arg("relabel", "relabel", is_onoff=True)
ParserSecurity.add_arg("label", "label", can_comma=True)
ParserSecurity.add_arg("baselabel", "label", can_comma=True)


######################
# --features parsing #
######################

class ParserFeatures(VirtCLIParser):
    cli_arg_name = "features"
    propname = "features"

_register_virt_parser(ParserFeatures)
ParserFeatures.add_arg("acpi", "acpi", is_onoff=True)
ParserFeatures.add_arg("apic", "apic", is_onoff=True)
ParserFeatures.add_arg("pae", "pae", is_onoff=True)
ParserFeatures.add_arg("privnet", "privnet", is_onoff=True)
ParserFeatures.add_arg("hap", "hap", is_onoff=True)
ParserFeatures.add_arg("viridian", "viridian", is_onoff=True)
ParserFeatures.add_arg("eoi", "eoi", is_onoff=True)
ParserFeatures.add_arg("pmu", "pmu", is_onoff=True)

ParserFeatures.add_arg("hyperv_reset", "hyperv_reset", is_onoff=True)
ParserFeatures.add_arg("hyperv_vapic", "hyperv_vapic", is_onoff=True)
ParserFeatures.add_arg("hyperv_relaxed", "hyperv_relaxed", is_onoff=True)
ParserFeatures.add_arg("hyperv_spinlocks", "hyperv_spinlocks", is_onoff=True)
ParserFeatures.add_arg("hyperv_spinlocks_retries",
                       "hyperv_spinlocks_retries")
ParserFeatures.add_arg("hyperv_synic", "hyperv_synic", is_onoff=True)

ParserFeatures.add_arg("vmport", "vmport", is_onoff=True)
ParserFeatures.add_arg("kvm_hidden", "kvm_hidden", is_onoff=True)
ParserFeatures.add_arg("pvspinlock", "pvspinlock", is_onoff=True)

ParserFeatures.add_arg("gic_version", "gic_version")

ParserFeatures.add_arg("smm", "smm", is_onoff=True)
ParserFeatures.add_arg("vmcoreinfo", "vmcoreinfo", is_onoff=True)


###################
# --clock parsing #
###################

class ParserClock(VirtCLIParser):
    cli_arg_name = "clock"
    propname = "clock"

    def set_timer(self, inst, val, virtarg):
        tname, attrname = virtarg.cliname.split("_")

        timerobj = None
        for t in inst.timers:
            if t.name == tname:
                timerobj = t
                break

        if not timerobj:
            timerobj = inst.timers.add_new()
            timerobj.name = tname

        setattr(timerobj, attrname, val)


_register_virt_parser(ParserClock)
ParserClock.add_arg("offset", "offset")

for _tname in DomainClock.TIMER_NAMES:
    ParserClock.add_arg(None, _tname + "_present",
                        is_onoff=True,
                        cb=ParserClock.set_timer)
    ParserClock.add_arg(None, _tname + "_tickpolicy", cb=ParserClock.set_timer)


################
# --pm parsing #
################

class ParserPM(VirtCLIParser):
    cli_arg_name = "pm"
    propname = "pm"

_register_virt_parser(ParserPM)
ParserPM.add_arg("suspend_to_mem", "suspend_to_mem", is_onoff=True)
ParserPM.add_arg("suspend_to_disk", "suspend_to_disk", is_onoff=True)


#####################
# --sysinfo parsing #
#####################

class ParserSysinfo(VirtCLIParser):
    cli_arg_name = "sysinfo"
    propname = "sysinfo"
    remove_first = "type"

    def set_type_cb(self, inst, val, virtarg):
        if val == "host" or val == "emulate":
            self.guest.os.smbios_mode = val
        elif val == "smbios":
            self.guest.os.smbios_mode = "sysinfo"
            inst.type = val
        else:
            fail(_("Unknown sysinfo flag '%s'") % val)

    def set_uuid_cb(self, inst, val, virtarg):
        # If a uuid is supplied it must match the guest UUID. This would be
        # impossible to guess if the guest uuid is autogenerated so just
        # overwrite the guest uuid with what is passed in assuming it passes
        # the sanity checking below.
        inst.system_uuid = val
        self.guest.uuid = val

    def _parse(self, inst):
        if self.optstr == "host" or self.optstr == "emulate":
            self.optdict['type'] = self.optstr
        elif self.optstr:
            # If any string specified, default to type=smbios otherwise
            # libvirt errors. User args can still override this though
            self.optdict['type'] = 'smbios'

        return VirtCLIParser._parse(self, inst)

_register_virt_parser(ParserSysinfo)
# <sysinfo type='smbios'>
ParserSysinfo.add_arg("type", "type",
                      cb=ParserSysinfo.set_type_cb, can_comma=True)

# <bios> type 0 BIOS Information
ParserSysinfo.add_arg("bios_vendor", "bios_vendor")
ParserSysinfo.add_arg("bios_version", "bios_version")
ParserSysinfo.add_arg("bios_date", "bios_date")
ParserSysinfo.add_arg("bios_release", "bios_release")

# <system> type 1 System Information
ParserSysinfo.add_arg("system_manufacturer", "system_manufacturer")
ParserSysinfo.add_arg("system_product", "system_product")
ParserSysinfo.add_arg("system_version", "system_version")
ParserSysinfo.add_arg("system_serial", "system_serial")
ParserSysinfo.add_arg("system_uuid", "system_uuid",
                      cb=ParserSysinfo.set_uuid_cb)
ParserSysinfo.add_arg("system_sku", "system_sku")
ParserSysinfo.add_arg("system_family", "system_family")

# <baseBoard> type 2 Baseboard (or Module) Information
ParserSysinfo.add_arg("baseBoard_manufacturer", "baseBoard_manufacturer")
ParserSysinfo.add_arg("baseBoard_product", "baseBoard_product")
ParserSysinfo.add_arg("baseBoard_version", "baseBoard_version")
ParserSysinfo.add_arg("baseBoard_serial", "baseBoard_serial")
ParserSysinfo.add_arg("baseBoard_asset", "baseBoard_asset")
ParserSysinfo.add_arg("baseBoard_location", "baseBoard_location")


##############################
# --qemu-commandline parsing #
##############################

class ParserQemuCLI(VirtCLIParser):
    cli_arg_name = "qemu_commandline"
    propname = "xmlns_qemu"

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
        return VirtCLIParser._parse(self, inst)


_register_virt_parser(ParserQemuCLI)
ParserQemuCLI.add_arg(None, "args", cb=ParserQemuCLI.args_cb, can_comma=True)
ParserQemuCLI.add_arg(None, "env", cb=ParserQemuCLI.env_cb, can_comma=True)


##########################
# Guest <device> parsing #
##########################

def _add_device_address_args(cls):
    """
    Add DeviceAddress parameters if we are parsing for a device
    """
    cls.add_arg("address.type", "address.type")
    cls.add_arg("address.domain", "address.domain")
    cls.add_arg("address.bus", "address.bus")
    cls.add_arg("address.slot", "address.slot")
    cls.add_arg("address.multifunction", "address.multifunction",
                is_onoff=True)
    cls.add_arg("address.function", "address.function")
    cls.add_arg("address.controller", "address.controller")
    cls.add_arg("address.unit", "address.unit")
    cls.add_arg("address.port", "address.port")
    cls.add_arg("address.target", "address.target")
    cls.add_arg("address.reg", "address.reg")
    cls.add_arg("address.cssid", "address.cssid")
    cls.add_arg("address.ssid", "address.ssid")
    cls.add_arg("address.devno", "address.devno")
    cls.add_arg("address.iobase", "address.iobase")
    cls.add_arg("address.irq", "address.irq")
    cls.add_arg("address.base", "address.base")


##################
# --disk parsing #
##################

def _default_image_file_format(conn):
    if conn.check_support(conn.SUPPORT_CONN_DEFAULT_QCOW2):
        return "qcow2"
    return "raw"


def _get_default_image_format(conn, poolobj):
    tmpvol = StorageVolume(conn)
    tmpvol.pool = poolobj

    if tmpvol.file_type != StorageVolume.TYPE_FILE:
        return None
    return _default_image_file_format(conn)


def _generate_new_volume_name(guest, poolobj, fmt):
    collidelist = []
    for disk in guest.devices.disk:
        if (disk.get_vol_install() and
            disk.get_vol_install().pool.name() == poolobj.name()):
            collidelist.append(os.path.basename(disk.path))

    ext = StorageVolume.get_file_extension_for_format(fmt)
    return StorageVolume.find_free_name(
        poolobj, guest.name, suffix=ext, collidelist=collidelist)


class ParserDisk(VirtCLIParser):
    cli_arg_name = "disk"
    propname = "devices.disk"
    remove_first = "path"
    stub_none = False

    def noset_cb(self, inst, val, virtarg):
        ignore = self, inst, val, virtarg

    def seclabel_find_inst_cb(self, *args, **kwargs):
        cliarg = "seclabel"  # seclabel[0-9]*
        objpropname = "seclabels"  # disk.seclabels
        cb = self._make_find_inst_cb(cliarg, objpropname)
        return cb(*args, **kwargs)

    def _parse(self, inst):
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
                fail(_("Unknown '%s' value '%s'") % ("perms", val))

        has_path = "path" in self.optdict
        backing_store = self.optdict.pop("backing_store", None)
        backing_format = self.optdict.pop("backing_format", None)
        poolname = self.optdict.pop("pool", None)
        volname = self.optdict.pop("vol", None)
        size = parse_size(self.optdict.pop("size", None))
        fmt = self.optdict.pop("format", None)
        sparse = _on_off_convert("sparse", self.optdict.pop("sparse", "yes"))
        convert_perms(self.optdict.pop("perms", None))
        has_type_volume = ("source_pool" in self.optdict or
                           "source_volume" in self.optdict)
        has_type_network = ("source_protocol" in self.optdict)

        optcount = sum([bool(p) for p in [has_path, poolname, volname,
                                          has_type_volume, has_type_network]])
        if optcount > 1:
            fail(_("Cannot specify more than 1 storage path"))
        if optcount == 0 and size:
            # Saw something like --disk size=X, have it imply pool=default
            poolname = "default"

        if volname:
            if volname.count("/") != 1:
                raise ValueError(_("Storage volume must be specified as "
                                   "vol=poolname/volname"))
            poolname, volname = volname.split("/")
            logging.debug("Parsed --disk volume as: pool=%s vol=%s",
                          poolname, volname)

        VirtCLIParser._parse(self, inst)

        # Generate and fill in the disk source info
        newvolname = None
        poolobj = None
        if poolname:
            if poolname == "default":
                StoragePool.build_default_pool(self.guest.conn)
            poolobj = self.guest.conn.storagePoolLookupByName(poolname)

        if volname:
            vol_object = poolobj.storageVolLookupByName(volname)
            inst.set_vol_object(vol_object, poolobj)
            poolobj = None

        if ((poolobj or inst.wants_storage_creation()) and
            (fmt or size or sparse or backing_store)):
            if not poolobj:
                poolobj = inst.get_parent_pool()
                newvolname = os.path.basename(inst.path)
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


_register_virt_parser(ParserDisk)
_add_device_address_args(ParserDisk)

# These are all handled specially in _parse
ParserDisk.add_arg(None, "backing_store", cb=ParserDisk.noset_cb)
ParserDisk.add_arg(None, "backing_format", cb=ParserDisk.noset_cb)
ParserDisk.add_arg(None, "pool", cb=ParserDisk.noset_cb)
ParserDisk.add_arg(None, "vol", cb=ParserDisk.noset_cb)
ParserDisk.add_arg(None, "size", cb=ParserDisk.noset_cb)
ParserDisk.add_arg(None, "format", cb=ParserDisk.noset_cb)
ParserDisk.add_arg(None, "sparse", cb=ParserDisk.noset_cb)

ParserDisk.add_arg("source_pool", "source_pool")
ParserDisk.add_arg("source_volume", "source_volume")
ParserDisk.add_arg("source_name", "source_name")
ParserDisk.add_arg("source_protocol", "source_protocol")
ParserDisk.add_arg("source_host_name", "source_host_name")
ParserDisk.add_arg("source_host_port", "source_host_port")
ParserDisk.add_arg("source_host_socket", "source_host_socket")
ParserDisk.add_arg("source_host_transport", "source_host_transport")

ParserDisk.add_arg("path", "path")
ParserDisk.add_arg("device", "device")
ParserDisk.add_arg("snapshot_policy", "snapshot_policy")
ParserDisk.add_arg("bus", "bus")
ParserDisk.add_arg("removable", "removable", is_onoff=True)
ParserDisk.add_arg("driver_cache", "cache")
ParserDisk.add_arg("driver_discard", "discard")
ParserDisk.add_arg("driver_detect_zeroes", "detect_zeroes")
ParserDisk.add_arg("driver_name", "driver_name")
ParserDisk.add_arg("driver_type", "driver_type")
ParserDisk.add_arg("driver_copy_on_read", "driver.copy_on_read", is_onoff=True)
ParserDisk.add_arg("driver_io", "io")
ParserDisk.add_arg("error_policy", "error_policy")
ParserDisk.add_arg("serial", "serial")
ParserDisk.add_arg("target", "target")
ParserDisk.add_arg("startup_policy", "startup_policy")
ParserDisk.add_arg("read_only", "readonly", is_onoff=True)
ParserDisk.add_arg("shareable", "shareable", is_onoff=True)
ParserDisk.add_arg("boot.order", "boot_order")

ParserDisk.add_arg("iotune_rbs", "read_bytes_sec")
ParserDisk.add_arg("iotune_wbs", "write_bytes_sec")
ParserDisk.add_arg("iotune_tbs", "total_bytes_sec")
ParserDisk.add_arg("iotune_ris", "read_iops_sec")
ParserDisk.add_arg("iotune_wis", "write_iops_sec")
ParserDisk.add_arg("iotune_tis", "total_iops_sec")
ParserDisk.add_arg("sgio", "sgio")
ParserDisk.add_arg("logical_block_size", "logical_block_size")
ParserDisk.add_arg("physical_block_size", "physical_block_size")

# DeviceDisk.seclabels properties
ParserDisk.add_arg("model", "seclabel[0-9]*.model",
                   find_inst_cb=ParserDisk.seclabel_find_inst_cb)
ParserDisk.add_arg("relabel", "seclabel[0-9]*.relabel", is_onoff=True,
                   find_inst_cb=ParserDisk.seclabel_find_inst_cb)
ParserDisk.add_arg("label", "seclabel[0-9]*.label", can_comma=True,
                   find_inst_cb=ParserDisk.seclabel_find_inst_cb)

ParserDisk.add_arg("geometry_cyls", "geometry.cyls")
ParserDisk.add_arg("geometry_heads", "geometry.heads")
ParserDisk.add_arg("geometry_secs", "geometry.secs")
ParserDisk.add_arg("geometry_trans", "geometry.trans")


#####################
# --network parsing #
#####################

class ParserNetwork(VirtCLIParser):
    cli_arg_name = "network"
    propname = "devices.interface"
    remove_first = "type"
    stub_none = False

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

    def _parse(self, inst):
        if self.optstr == "none":
            return

        if "type" not in self.optdict:
            if "network" in self.optdict:
                self.optdict["type"] = DeviceInterface.TYPE_VIRTUAL
                self.optdict["source"] = self.optdict.pop("network")
            elif "bridge" in self.optdict:
                self.optdict["type"] = DeviceInterface.TYPE_BRIDGE
                self.optdict["source"] = self.optdict.pop("bridge")

        return VirtCLIParser._parse(self, inst)


_register_virt_parser(ParserNetwork)
_add_device_address_args(ParserNetwork)
ParserNetwork.add_arg("type", "type", cb=ParserNetwork.set_type_cb)
ParserNetwork.add_arg("trustGuestRxFilters", "trustGuestRxFilters",
                      is_onoff=True)
ParserNetwork.add_arg("source", "source")
ParserNetwork.add_arg("source_mode", "source_mode")
ParserNetwork.add_arg("source_type", "source_type")
ParserNetwork.add_arg("source_path", "source_path")
ParserNetwork.add_arg("portgroup", "portgroup")
ParserNetwork.add_arg("target_dev", "target")
ParserNetwork.add_arg("model", "model")
ParserNetwork.add_arg("macaddr", "mac", cb=ParserNetwork.set_mac_cb)
ParserNetwork.add_arg("filterref", "filterref")
ParserNetwork.add_arg("boot.order", "boot_order")
ParserNetwork.add_arg("link_state", "link_state",
                      cb=ParserNetwork.set_link_state)

ParserNetwork.add_arg("driver_name", "driver_name")
ParserNetwork.add_arg("driver_queues", "driver_queues")

ParserNetwork.add_arg("rom_file", "rom_file")
ParserNetwork.add_arg("rom_bar", "rom_bar", is_onoff=True)

ParserNetwork.add_arg("mtu_size", "mtu.size")

# For 802.1Qbg
ParserNetwork.add_arg("virtualport.type", "virtualport_type")
ParserNetwork.add_arg("virtualport.managerid", "virtualport_managerid")
ParserNetwork.add_arg("virtualport.typeid", "virtualport_typeid")
ParserNetwork.add_arg("virtualport.typeidversion",
            "virtualport_typeidversion")
ParserNetwork.add_arg("virtualport.instanceid", "virtualport_instanceid")
# For openvswitch & 802.1Qbh
ParserNetwork.add_arg("virtualport.profileid", "virtualport_profileid")
# For openvswitch & midonet
ParserNetwork.add_arg("virtualport.interfaceid", "virtualport_interfaceid")


######################
# --graphics parsing #
######################

class ParserGraphics(VirtCLIParser):
    cli_arg_name = "graphics"
    propname = "devices.graphics"
    remove_first = "type"
    stub_none = False

    def set_keymap_cb(self, inst, val, virtarg):
        from . import hostkeymap

        if not val:
            val = None
        elif val.lower() == "local":
            val = DeviceGraphics.KEYMAP_LOCAL
        elif val.lower() == "none":
            val = None
        else:
            use_keymap = hostkeymap.sanitize_keymap(val)
            if not use_keymap:
                raise ValueError(
                    _("Didn't match keymap '%s' in keytable!") % val)
            val = use_keymap
        inst.keymap = val

    def set_type_cb(self, inst, val, virtarg):
        if val == "default":
            return
        inst.type = val

    def set_listen_cb(self, inst, val, virtarg):
        if val == "none":
            inst.set_listen_none()
        elif val == "socket":
            inst.remove_all_listens()
            obj = inst.listens.add_new()
            obj.type = "socket"
        else:
            inst.listen = val

    def listens_find_inst_cb(self, *args, **kwargs):
        cliarg = "listens"  # listens[0-9]*
        objpropname = "listens"  # graphics.listens
        cb = self._make_find_inst_cb(cliarg, objpropname)
        return cb(*args, **kwargs)

    def _parse(self, inst):
        if self.optstr == "none":
            self.guest.skip_default_graphics = True
            return

        ret = VirtCLIParser._parse(self, inst)

        if inst.conn.is_qemu() and inst.gl:
            if inst.type != "spice":
                logging.warning("graphics type=%s does not support GL", inst.type)
            elif not inst.conn.check_support(
                    inst.conn.SUPPORT_CONN_SPICE_GL):
                logging.warning("qemu/libvirt version may not support spice GL")
        if inst.conn.is_qemu() and inst.rendernode:
            if inst.type != "spice":
                logging.warning("graphics type=%s does not support rendernode", inst.type)
            elif not inst.conn.check_support(
                    inst.conn.SUPPORT_CONN_SPICE_RENDERNODE):
                logging.warning("qemu/libvirt version may not support rendernode")

        return ret

_register_virt_parser(ParserGraphics)
_add_device_address_args(ParserGraphics)
ParserGraphics.add_arg(None, "type", cb=ParserGraphics.set_type_cb)
ParserGraphics.add_arg("port", "port")
ParserGraphics.add_arg("tlsPort", "tlsport")
ParserGraphics.add_arg("listen", "listen", cb=ParserGraphics.set_listen_cb)
ParserGraphics.add_arg("type", "listens[0-9]*.type",
                       find_inst_cb=ParserGraphics.listens_find_inst_cb)
ParserGraphics.add_arg("address", "listens[0-9]*.address",
                       find_inst_cb=ParserGraphics.listens_find_inst_cb)
ParserGraphics.add_arg("network", "listens[0-9]*.network",
                       find_inst_cb=ParserGraphics.listens_find_inst_cb)
ParserGraphics.add_arg("socket", "listens[0-9]*.socket",
                       find_inst_cb=ParserGraphics.listens_find_inst_cb)
ParserGraphics.add_arg(None, "keymap", cb=ParserGraphics.set_keymap_cb)
ParserGraphics.add_arg("passwd", "password")
ParserGraphics.add_arg("passwdValidTo", "passwordvalidto")
ParserGraphics.add_arg("connected", "connected")
ParserGraphics.add_arg("defaultMode", "defaultMode")

ParserGraphics.add_arg("image_compression", "image_compression")
ParserGraphics.add_arg("streaming_mode", "streaming_mode")
ParserGraphics.add_arg("clipboard_copypaste", "clipboard_copypaste",
            is_onoff=True)
ParserGraphics.add_arg("mouse_mode", "mouse_mode")
ParserGraphics.add_arg("filetransfer_enable", "filetransfer_enable",
            is_onoff=True)
ParserGraphics.add_arg("gl", "gl", is_onoff=True)
ParserGraphics.add_arg("rendernode", "rendernode")


########################
# --controller parsing #
########################

class ParserController(VirtCLIParser):
    cli_arg_name = "controller"
    propname = "devices.controller"
    remove_first = "type"

    def set_server_cb(self, inst, val, virtarg):
        inst.address.set_addrstr(val)

    def _parse(self, inst):
        if self.optstr == "usb2":
            return DeviceController.get_usb2_controllers(inst.conn)
        elif self.optstr == "usb3":
            return DeviceController.get_usb3_controller(inst.conn, self.guest)
        return VirtCLIParser._parse(self, inst)


_register_virt_parser(ParserController)
_add_device_address_args(ParserController)
ParserController.add_arg("type", "type")
ParserController.add_arg("model", "model")
ParserController.add_arg("index", "index")
ParserController.add_arg("master_startport", "master")

ParserController.add_arg(None, "address", cb=ParserController.set_server_cb)


###################
# --input parsing #
###################

class ParserInput(VirtCLIParser):
    cli_arg_name = "input"
    propname = "devices.input"
    remove_first = "type"

_register_virt_parser(ParserInput)
_add_device_address_args(ParserInput)
ParserInput.add_arg("type", "type", ignore_default=True)
ParserInput.add_arg("bus", "bus", ignore_default=True)


#######################
# --smartcard parsing #
#######################

class ParserSmartcard(VirtCLIParser):
    cli_arg_name = "smartcard"
    propname = "devices.smartcard"
    remove_first = "mode"

_register_virt_parser(ParserSmartcard)
_add_device_address_args(ParserSmartcard)
ParserSmartcard.add_arg("mode", "mode", ignore_default=True)
ParserSmartcard.add_arg("type", "type", ignore_default=True)


######################
# --redirdev parsing #
######################

class ParserRedir(VirtCLIParser):
    cli_arg_name = "redirdev"
    propname = "devices.redirdev"
    remove_first = "bus"
    stub_none = False

    def set_server_cb(self, inst, val, virtarg):
        inst.parse_friendly_server(val)

    def _parse(self, inst):
        if self.optstr == "none":
            self.guest.skip_default_usbredir = True
            return
        return VirtCLIParser._parse(self, inst)

_register_virt_parser(ParserRedir)
_add_device_address_args(ParserRedir)
ParserRedir.add_arg("bus", "bus", ignore_default=True)
ParserRedir.add_arg("type", "type", ignore_default=True)
ParserRedir.add_arg("boot.order", "boot_order")
ParserRedir.add_arg(None, "server", cb=ParserRedir.set_server_cb)


#################
# --tpm parsing #
#################

class ParserTPM(VirtCLIParser):
    cli_arg_name = "tpm"
    propname = "devices.tpm"
    remove_first = "type"

    def _parse(self, inst):
        if (self.optdict.get("type", "").startswith("/")):
            self.optdict["path"] = self.optdict.pop("type")
        return VirtCLIParser._parse(self, inst)

_register_virt_parser(ParserTPM)
_add_device_address_args(ParserTPM)
ParserTPM.add_arg("type", "type")
ParserTPM.add_arg("model", "model")
ParserTPM.add_arg("version", "version")
ParserTPM.add_arg("device_path", "path")


#################
# --rng parsing #
#################

class ParserRNG(VirtCLIParser):
    cli_arg_name = "rng"
    propname = "devices.rng"
    remove_first = "type"
    stub_none = False

    def set_hosts_cb(self, inst, val, virtarg):
        namemap = {}
        inst.backend_type = inst.cli_backend_type

        if inst.cli_backend_mode == "connect":
            namemap["backend_host"] = "connect_host"
            namemap["backend_service"] = "connect_service"

        if inst.cli_backend_mode == "bind":
            namemap["backend_host"] = "bind_host"
            namemap["backend_service"] = "bind_service"

            if inst.cli_backend_type == "udp":
                namemap["backend_connect_host"] = "connect_host"
                namemap["backend_connect_service"] = "connect_service"

        if virtarg.cliname in namemap:
            setattr(inst, namemap[virtarg.cliname], val)

    def set_backend_cb(self, inst, val, virtarg):
        if virtarg.cliname == "backend_mode":
            inst.cli_backend_mode = val
        elif virtarg.cliname == "backend_type":
            inst.cli_backend_type = val

    def _parse(self, inst):
        if self.optstr == "none":
            self.guest.skip_default_rng = True
            return

        inst.cli_backend_mode = "connect"
        inst.cli_backend_type = "udp"

        if self.optdict.get("type", "").startswith("/"):
            # Allow --rng /dev/random
            self.optdict["device"] = self.optdict.pop("type")
            self.optdict["type"] = "random"

        return VirtCLIParser._parse(self, inst)


_register_virt_parser(ParserRNG)
_add_device_address_args(ParserRNG)
ParserRNG.add_arg("type", "type")

ParserRNG.add_arg(None, "backend_mode", cb=ParserRNG.set_backend_cb)
ParserRNG.add_arg(None, "backend_type", cb=ParserRNG.set_backend_cb)

ParserRNG.add_arg(None, "backend_host", cb=ParserRNG.set_hosts_cb)
ParserRNG.add_arg(None, "backend_service", cb=ParserRNG.set_hosts_cb)
ParserRNG.add_arg(None, "backend_connect_host", cb=ParserRNG.set_hosts_cb)
ParserRNG.add_arg(None, "backend_connect_service", cb=ParserRNG.set_hosts_cb)

ParserRNG.add_arg("device", "device")
ParserRNG.add_arg("model", "model")
ParserRNG.add_arg("rate_bytes", "rate_bytes")
ParserRNG.add_arg("rate_period", "rate_period")


######################
# --watchdog parsing #
######################

class ParserWatchdog(VirtCLIParser):
    cli_arg_name = "watchdog"
    propname = "devices.watchdog"
    remove_first = "model"

_register_virt_parser(ParserWatchdog)
_add_device_address_args(ParserWatchdog)
ParserWatchdog.add_arg("model", "model", ignore_default=True)
ParserWatchdog.add_arg("action", "action", ignore_default=True)


####################
# --memdev parsing #
####################

class ParseMemdev(VirtCLIParser):
    cli_arg_name = "memdev"
    propname = "devices.memory"
    remove_first = "model"

    def set_target_size(self, inst, val, virtarg):
        _set_attribute(inst, virtarg.attrname, int(val) * 1024)

_register_virt_parser(ParseMemdev)
ParseMemdev.add_arg("model", "model")
ParseMemdev.add_arg("access", "access")
ParseMemdev.add_arg("target.size", "target_size", cb=ParseMemdev.set_target_size)
ParseMemdev.add_arg("target.node", "target_node")
ParseMemdev.add_arg("target.label_size", "target_label_size",
                    cb=ParseMemdev.set_target_size)
ParseMemdev.add_arg("source.pagesize", "source_pagesize")
ParseMemdev.add_arg("source.path", "source_path")
ParseMemdev.add_arg("source.nodemask", "source_nodemask", can_comma=True)


########################
# --memballoon parsing #
########################

class ParserMemballoon(VirtCLIParser):
    cli_arg_name = "memballoon"
    propname = "devices.memballoon"
    remove_first = "model"
    stub_none = False

_register_virt_parser(ParserMemballoon)
_add_device_address_args(ParserMemballoon)
ParserMemballoon.add_arg("model", "model")


###################
# --panic parsing #
###################

class ParserPanic(VirtCLIParser):
    cli_arg_name = "panic"
    propname = "devices.panic"
    remove_first = "model"
    compat_mode = False

    def set_model_cb(self, inst, val, virtarg):
        if self.compat_mode and val.startswith("0x"):
            inst.model = DevicePanic.MODEL_ISA
            inst.iobase = val
        else:
            inst.model = val

    def _parse(self, inst):
        if (len(self.optstr.split(",")) == 1 and
                not self.optstr.startswith("model=")):
            self.compat_mode = True
        return VirtCLIParser._parse(self, inst)

_register_virt_parser(ParserPanic)
ParserPanic.add_arg(None, "model", cb=ParserPanic.set_model_cb,
                    ignore_default=True)
ParserPanic.add_arg("iobase", "iobase")


######################################################
# --serial, --parallel, --channel, --console parsing #
######################################################

class _ParserChar(VirtCLIParser):
    remove_first = "char_type"
    stub_none = False

    def support_check(self, inst, virtarg):
        if not isinstance(virtarg.attrname, str):
            return
        if not inst.supports_property(virtarg.attrname):
            raise ValueError(_("%(devtype)s type '%(chartype)s' does not "
                "support '%(optname)s' option.") %
                {"devtype": inst.DEVICE_TYPE,
                 "chartype": inst.type,
                 "optname": virtarg.cliname})
    support_cb = support_check

    def set_host_cb(self, inst, val, virtarg):
        if ("bind_host" not in self.optdict and
            self.optdict.get("mode", None) == "bind"):
            inst.set_friendly_bind(val)
        else:
            inst.set_friendly_source(val)

    def set_bind_cb(self, inst, val, virtarg):
        inst.set_friendly_bind(val)

    def set_target_cb(self, inst, val, virtarg):
        inst.set_friendly_target(val)

    def _parse(self, inst):
        if self.optstr == "none" and inst.DEVICE_TYPE == "console":
            self.guest.skip_default_console = True
            return
        if self.optstr == "none" and inst.DEVICE_TYPE == "channel":
            self.guest.skip_default_channel = True
            return

        return VirtCLIParser._parse(self, inst)


_add_device_address_args(_ParserChar)
_ParserChar.add_arg("type", "char_type")
_ParserChar.add_arg("source_path", "path")
_ParserChar.add_arg("protocol",   "protocol")
_ParserChar.add_arg("target_type", "target_type")
_ParserChar.add_arg("target_name", "name")
_ParserChar.add_arg(None, "host", cb=_ParserChar.set_host_cb)
_ParserChar.add_arg(None, "bind_host", cb=_ParserChar.set_bind_cb)
_ParserChar.add_arg(None, "target_address", cb=_ParserChar.set_target_cb)
_ParserChar.add_arg("source_mode", "mode")
_ParserChar.add_arg("source_master", "source.master")
_ParserChar.add_arg("source_slave", "source.slave")
_ParserChar.add_arg("log_file", "log.file")
_ParserChar.add_arg("log_append", "log.append", is_onoff=True)



class ParserSerial(_ParserChar):
    cli_arg_name = "serial"
    propname = "devices.serial"
_register_virt_parser(ParserSerial)


class ParserParallel(_ParserChar):
    cli_arg_name = "parallel"
    propname = "devices.parallel"
_register_virt_parser(ParserParallel)


class ParserChannel(_ParserChar):
    cli_arg_name = "channel"
    propname = "devices.channel"
_register_virt_parser(ParserChannel)


class ParserConsole(_ParserChar):
    cli_arg_name = "console"
    propname = "devices.console"
_register_virt_parser(ParserConsole)


########################
# --filesystem parsing #
########################

class ParserFilesystem(VirtCLIParser):
    cli_arg_name = "filesystem"
    propname = "devices.filesystem"
    remove_first = ["source", "target"]

_register_virt_parser(ParserFilesystem)
_add_device_address_args(ParserFilesystem)
ParserFilesystem.add_arg("type", "type")
ParserFilesystem.add_arg("accessmode", "accessmode", aliases=["mode"])
ParserFilesystem.add_arg("source", "source")
ParserFilesystem.add_arg("target", "target")


###################
# --video parsing #
###################

class ParserVideo(VirtCLIParser):
    cli_arg_name = "video"
    propname = "devices.video"
    remove_first = "model"

    def _parse(self, inst):
        ret = VirtCLIParser._parse(self, inst)

        if inst.conn.is_qemu() and inst.accel3d:
            if inst.model != "virtio":
                logging.warning("video model=%s does not support accel3d",
                    inst.model)
            elif not inst.conn.check_support(
                    inst.conn.SUPPORT_CONN_VIDEO_VIRTIO_ACCEL3D):
                logging.warning("qemu/libvirt version may not support "
                             "virtio accel3d")

        return ret

_register_virt_parser(ParserVideo)
_add_device_address_args(ParserVideo)
ParserVideo.add_arg("model", "model", ignore_default=True)
ParserVideo.add_arg("accel3d", "accel3d", is_onoff=True)
ParserVideo.add_arg("heads", "heads")
ParserVideo.add_arg("ram", "ram")
ParserVideo.add_arg("vram", "vram")
ParserVideo.add_arg("vram64", "vram64")
ParserVideo.add_arg("vgamem", "vgamem")


###################
# --sound parsing #
###################

class ParserSound(VirtCLIParser):
    cli_arg_name = "sound"
    propname = "devices.sound"
    remove_first = "model"
    stub_none = False

    def _parse(self, inst):
        if self.optstr == "none":
            self.guest.skip_default_sound = True
            return
        return VirtCLIParser._parse(self, inst)

    def codec_find_inst_cb(self, *args, **kwargs):
        cliarg = "codec"  # codec[0-9]*
        objpropname = "codecs"
        cb = self._make_find_inst_cb(cliarg, objpropname)
        return cb(*args, **kwargs)

_register_virt_parser(ParserSound)
_add_device_address_args(ParserSound)
ParserSound.add_arg("model", "model", ignore_default=True)
# Options for sound.codecs config
ParserSound.add_arg("type", "codec[0-9]*.type",
                  find_inst_cb=ParserSound.codec_find_inst_cb)


#####################
# --hostdev parsing #
#####################

class ParserHostdev(VirtCLIParser):
    cli_arg_name = "hostdev"
    propname = "devices.hostdev"
    remove_first = "name"

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

_register_virt_parser(ParserHostdev)
_add_device_address_args(ParserHostdev)
ParserHostdev.add_arg("type", "type")
ParserHostdev.add_arg(None, "name",
                      cb=ParserHostdev.set_name_cb,
                      lookup_cb=ParserHostdev.name_lookup_cb)
ParserHostdev.add_arg("driver_name", "driver_name")
ParserHostdev.add_arg("boot.order", "boot_order")
ParserHostdev.add_arg("rom_bar", "rom_bar", is_onoff=True)


###########################
# Public virt parser APIs #
###########################

def parse_option_strings(options, guest, instlist, update=False):
    """
    Iterate over VIRT_PARSERS, and launch the associated parser
    function for every value that was filled in on 'options', which
    came from argparse/the command line.

    @update: If we are updating an existing guest, like from virt-xml
    """
    instlist = util.listify(instlist)
    if not instlist:
        instlist = [None]

    ret = []
    for parserclass in VIRT_PARSERS:
        optlist = util.listify(getattr(options, parserclass.cli_arg_name))
        if not optlist:
            continue

        for inst in instlist:
            if inst and optlist:
                # If an object is passed in, we are updating it in place, and
                # only use the last command line occurrence, eg. from virt-xml
                optlist = [optlist[-1]]

            for optstr in optlist:
                parserobj = parserclass(guest, optstr)
                parseret = parserobj.parse(inst, validate=not update)
                ret += util.listify(parseret)

    return ret


def check_option_introspection(options):
    """
    Check if the user requested option introspection with ex: '--disk=?'
    """
    ret = False
    for parserclass in VIRT_PARSERS:
        optlist = util.listify(getattr(options, parserclass.cli_arg_name))
        if not optlist:
            continue

        for optstr in optlist:
            if optstr == "?" or optstr == "help":
                parserclass.print_introspection()
                ret = True

    return ret
