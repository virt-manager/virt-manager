#
# Utility functions for the command line drivers
#
# Copyright 2006-2007, 2013, 2014 Red Hat, Inc.
# Jeremy Katz <katzj@redhat.com>
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

import argparse
import logging
import logging.handlers
import os
import shlex
import subprocess
import sys
import traceback

import libvirt

from virtcli import CLIConfig

from . import util
from .clock import Clock
from .cpu import CPU
from .deviceaudio import VirtualAudio
from .devicechar import (VirtualChannelDevice, VirtualConsoleDevice,
                         VirtualSerialDevice, VirtualParallelDevice)
from .devicecontroller import VirtualController
from .devicedisk import VirtualDisk
from .devicefilesystem import VirtualFilesystem
from .devicegraphics import VirtualGraphics
from .devicehostdev import VirtualHostDevice
from .deviceinput import VirtualInputDevice
from .deviceinterface import VirtualNetworkInterface
from .devicememballoon import VirtualMemballoon
from .devicepanic import VirtualPanicDevice
from .deviceredirdev import VirtualRedirDevice
from .devicerng import VirtualRNGDevice
from .devicesmartcard import VirtualSmartCardDevice
from .devicetpm import VirtualTPMDevice
from .devicevideo import VirtualVideoDevice
from .devicewatchdog import VirtualWatchdog
from .domainblkiotune import DomainBlkiotune
from .domainfeatures import DomainFeatures
from .domainmemorybacking import DomainMemorybacking
from .domainmemorytune import DomainMemorytune
from .domainnumatune import DomainNumatune
from .domainresource import DomainResource
from .idmap import IdMap
from .nodedev import NodeDevice
from .osxml import OSXML
from .pm import PM
from .seclabel import Seclabel
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

class VirtStreamHandler(logging.StreamHandler):
    def emit(self, record):
        """
        Based on the StreamHandler code from python 2.6: ripping out all
        the unicode handling and just unconditionally logging seems to fix
        logging backtraces with unicode locales (for me at least).

        No doubt this is atrocious, but it WORKSFORME!
        """
        try:
            msg = self.format(record)
            stream = self.stream
            fs = "%s\n"

            stream.write(fs % msg)

            self.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


class VirtHelpFormatter(argparse.RawDescriptionHelpFormatter):
    '''
    Subclass the default help formatter to allow printing newline characters
    in --help output. The way we do this is a huge hack :(

    Inspiration: http://groups.google.com/group/comp.lang.python/browse_thread/thread/6df6e6b541a15bc2/09f28e26af0699b1
    '''
    oldwrap = None

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
        except:
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
    if "VIRTINST_TEST_SUITE" not in os.environ:
        vi_dir = util.get_cache_dir()
        logfile = os.path.join(vi_dir, appname + ".log")

    try:
        if vi_dir and not os.access(vi_dir, os.W_OK):
            if os.path.exists(vi_dir):
                raise RuntimeError("No write access to directory %s" % vi_dir)

            try:
                os.makedirs(vi_dir, 0751)
            except IOError, e:
                raise RuntimeError("Could not create directory %s: %s" %
                                   (vi_dir, e))

        if (logfile and
            os.path.exists(logfile) and
            not os.access(logfile, os.W_OK)):
            raise RuntimeError("No write access to logfile %s" % logfile)
    except Exception, e:
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

    streamHandler = VirtStreamHandler(sys.stderr)
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
        sys.__excepthook__(typ, val, tb)
    sys.excepthook = exception_log

    logging.getLogger("requests").setLevel(logging.ERROR)

    # Log the app command string
    logging.debug("Launched with command line: %s", " ".join(sys.argv))


##############################
# Libvirt connection helpers #
##############################

def getConnection(uri):
    from .connection import VirtualConnection

    logging.debug("Requesting libvirt URI %s", (uri or "default"))
    conn = VirtualConnection(uri)
    conn.open(_do_creds_authname)
    conn.cache_object_fetch = True
    logging.debug("Received libvirt URI %s", conn.uri)

    return conn


# SASL username/pass auth
def _do_creds_authname(creds):
    retindex = 4

    for cred in creds:
        credtype, prompt, ignore, ignore, ignore = cred
        prompt += ": "

        res = cred[retindex]
        if credtype == libvirt.VIR_CRED_AUTHNAME:
            res = raw_input(prompt)
        elif credtype == libvirt.VIR_CRED_PASSPHRASE:
            import getpass
            res = getpass.getpass(prompt)
        else:
            raise RuntimeError("Unknown auth type in creds callback: %d" %
                               credtype)

        cred[retindex] = res
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
    if traceback.format_exc().strip() != "None":
        logging.debug("", exc_info=True)
    if do_exit:
        _fail_exit()


def print_stdout(msg, do_force=False):
    if do_force or not get_global_state().quiet:
        print msg


def print_stderr(msg):
    logging.debug(msg)
    print >> sys.stderr, msg


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
    def _optional_fail(msg, checkname):
        do_check = get_global_state().get_validation_check(checkname)
        if do_check:
            fail(msg + (_(" (Use --check %s=off or "
                "--check all=off to override)") % checkname))

        logging.debug("Skipping --check %s error condition '%s'",
            checkname, msg)
        logging.warn(msg)

    def check_path_exists(dev):
        """
        Prompt if disk file already exists and preserve mode is not used
        """
        if not warn_overwrite:
            return
        if not VirtualDisk.path_definitely_exists(dev.conn, dev.path):
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
            _optional_fail(errmsg, "disk_size")

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


def _run_console(args):
    logging.debug("Running: %s", " ".join(args))
    child = os.fork()
    if child:
        return child

    os.execvp(args[0], args)
    os._exit(1)  # pylint: disable=protected-access


def _gfx_console(guest):
    args = ["virt-viewer",
            "--connect", guest.conn.uri,
            "--wait", guest.name]

    # Currently virt-viewer needs attaching to the local display while
    # spice gl is enabled.
    if guest.has_gl():
        args.append("--attach")

    logging.debug("Launching virt-viewer for graphics type '%s'",
        guest.get_devices("graphics")[0].type)
    return _run_console(args)


def _txt_console(guest):
    args = ["virsh",
            "--connect", guest.conn.uri,
            "console", guest.name]

    logging.debug("Connecting to text console")
    return _run_console(args)


def connect_console(guest, consolecb, wait):
    """
    Launched the passed console callback for the already defined
    domain. If domain isn't running, return an error.
    """
    child = None
    if consolecb:
        child = consolecb(guest)

    if not child or not wait:
        return

    # If we connected the console, wait for it to finish
    try:
        os.waitpid(child, 0)
    except OSError, e:
        logging.debug("waitpid: %s: %s", e.errno, e.message)


def get_console_cb(guest):
    gdevs = guest.get_devices("graphics")
    if not gdevs:
        return _txt_console

    gtype = gdevs[0].type
    if gtype not in ["default",
        VirtualGraphics.TYPE_VNC,
        VirtualGraphics.TYPE_SPICE]:
        logging.debug("No viewer to launch for graphics type '%s'", gtype)
        return

    try:
        subprocess.check_output(["virt-viewer", "--version"])
    except OSError:
        logging.warn(_("Unable to connect to graphical console: "
                       "virt-viewer not installed. Please install "
                       "the 'virt-viewer' package."))
        return None

    if not os.environ.get("DISPLAY", ""):
        logging.warn(_("Graphics requested but DISPLAY is not set. "
                       "Not running virt-viewer."))
        return None

    return _gfx_console


def get_meter():
    quiet = (get_global_state().quiet or "VIRTINST_TEST_SUITE" in os.environ)
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
        grp.add_argument("--check",
            help=_("Enable or disable validation checks. Example:\n"
                   "--check path_in_use=off\n"
                   "--check all=off"))
    grp.add_argument("-q", "--quiet", action="store_true",
                   help=_("Suppress non-error output"))
    grp.add_argument("-d", "--debug", action="store_true",
                   help=_("Print debugging information"))


def add_metadata_option(grp):
    grp.add_argument("--metadata",
        help=_("Configure guest metadata. Ex:\n"
        "--metadata name=foo,title=\"My pretty title\",uuid=...\n"
        "--metadata description=\"My nice long description\""))


def add_memory_option(grp, backcompat=False):
    grp.add_argument("--memory",
        help=_("Configure guest memory allocation. Ex:\n"
               "--memory 1024 (in MiB)\n"
               "--memory 512,maxmemory=1024"))
    if backcompat:
        grp.add_argument("-r", "--ram", type=int, dest="oldmemory",
            help=argparse.SUPPRESS)


def vcpu_cli_options(grp, backcompat=True, editexample=False):
    grp.add_argument("--vcpus",
        help=_("Number of vcpus to configure for your guest. Ex:\n"
               "--vcpus 5\n"
               "--vcpus 5,maxcpus=10,cpuset=1-4,6,8\n"
               "--vcpus sockets=2,cores=4,threads=2,"))

    extramsg = "--cpu host"
    if editexample:
        extramsg = "--cpu host-model,clearxml=yes"
    grp.add_argument("--cpu",
        help=_("CPU model and features. Ex:\n"
               "--cpu coreduo,+x2apic\n") + extramsg)

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
                           "--controller type=usb,model=ich9-ehci1"))
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
                           "--rng /dev/random"))
    devg.add_argument("--panic", action="append",
                    help=_("Configure a guest panic device. Ex:\n"
                           "--panic default"))


def add_guest_xml_options(geng):
    geng.add_argument("--security", action="append",
        help=_("Set domain security driver configuration."))
    geng.add_argument("--numatune",
        help=_("Tune NUMA policy for the domain process."))
    geng.add_argument("--memtune", action="append",
        help=_("Tune memory policy for the domain process."))
    geng.add_argument("--blkiotune", action="append",
        help=_("Tune blkio policy for the domain process."))
    geng.add_argument("--memorybacking", action="append",
        help=_("Set memory backing policy for the domain process. Ex:\n"
               "--memorybacking hugepages=on"))
    geng.add_argument("--features",
        help=_("Set domain <features> XML. Ex:\n"
               "--features acpi=off\n"
               "--features apic=on,eoi=on"))
    geng.add_argument("--clock",
        help=_("Set domain <clock> XML. Ex:\n"
               "--clock offset=localtime,rtc_tickpolicy=catchup"))
    geng.add_argument("--pm",
        help=_("Configure VM power management features"))
    geng.add_argument("--events",
        help=_("Configure VM lifecycle management policy"))
    geng.add_argument("--resource", action="append",
        help=_("Configure VM resource partitioning (cgroups)"))


def add_boot_options(insg):
    insg.add_argument("--boot",
        help=_("Configure guest boot settings. Ex:\n"
               "--boot hd,cdrom,menu=on\n"
               "--boot init=/sbin/init (for containers)"))
    insg.add_argument("--idmap",
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


class _SetterCBData(object):
    """
    Structure holding all the data we want to pass to the cli
    setter_cb callbacks. Makes it simpler to add new fields in the future.
    """
    def __init__(self, opts, cliname):
        self.opts = opts
        self.cliname = cliname


class _VirtCLIArgument(object):
    def __init__(self, attrname, cliname,
                 setter_cb=None, ignore_default=False,
                 can_comma=False, aliases=None,
                 is_list=False, is_onoff=False,
                 lookup_cb=None, is_novalue=False):
        """
        A single subargument passed to compound command lines like --disk,
        --network, etc.

        @attrname: The virtinst API attribute name the cliargument maps to.
            If this is a virtinst object method, it will be called.
        @cliname: The command line option name, 'path' for path=FOO

        @setter_cb: Rather than set an attribute directly on the virtinst
            object, (inst, val, cbdata) to this callback to handle it.
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
        """
        self.attrname = attrname
        self.cliname = cliname

        self.setter_cb = setter_cb
        self.can_comma = can_comma
        self.ignore_default = ignore_default
        self.aliases = util.listify(aliases)
        self.is_list = is_list
        self.is_onoff = is_onoff
        self.lookup_cb = lookup_cb
        self.is_novalue = is_novalue


    def parse(self, opts, inst, support_cb=None, lookup=False):
        val = None
        for cliname in self.aliases + [self.cliname]:
            # We iterate over all values unconditionally, so they are
            # removed from opts
            foundval = opts.get_opt_param(cliname, self.is_novalue)
            if foundval is not None:
                val = foundval
        if val is None:
            return
        if val == "":
            val = None

        if support_cb:
            support_cb(inst, self.attrname, self.cliname)
        if self.is_onoff:
            val = _on_off_convert(self.cliname, val)
        if val == "default" and self.ignore_default and not lookup:
            return

        if lookup and not self.attrname and not self.lookup_cb:
            raise RuntimeError(
                _("Don't know how to match device type '%(device_type)s' "
                  "property '%(property_name)s'") %
                {"device_type": getattr(inst, "virtual_device_type", ""),
                 "property_name": self.cliname})

        try:
            if self.attrname:
                eval("inst." + self.attrname)  # pylint: disable=eval-used
        except AttributeError:
            raise RuntimeError("programming error: obj=%s does not have "
                               "member=%s" % (inst, self.attrname))

        cbdata = _SetterCBData(opts, self.cliname)
        if lookup:
            if self.lookup_cb:
                return self.lookup_cb(inst, val, cbdata)
            else:
                return eval(  # pylint: disable=eval-used
                    "inst." + self.attrname) == val
        elif self.setter_cb:
            self.setter_cb(inst, val, cbdata)
        else:
            exec(  # pylint: disable=exec-used
                "inst." + self.attrname + " = val")


class VirtOptionString(object):
    def __init__(self, optstr, virtargs, remove_first):
        """
        Helper class for parsing opt strings of the form
        opt1=val1,opt2=val2,...

        @optstr: The full option string
        @virtargs: A list of VirtCLIArguments
        @remove_first: List or parameters to peel off the front of
            option string, and store in the returned dict.
            remove_first=["char_type"] for --serial pty,foo=bar
            maps to {"char_type", "pty", "foo" : "bar"}
        """
        self.fullopts = optstr

        virtargmap = {}
        for arg in virtargs:
            virtargmap[arg.cliname] = arg
            for alias in arg.aliases:
                virtargmap[alias] = arg

        # @opts: A dictionary of the mapping {cliname: val}
        # @orderedopts: A list of tuples (cliname: val), in the order
        #   they appeared on the CLI.
        self.opts, self.orderedopts = self._parse_optstr(
            virtargmap, remove_first)

    def get_opt_param(self, key, is_novalue=False):
        if key not in self.opts:
            return None

        ret = self.opts.pop(key)
        if ret is None:
            if not is_novalue:
                raise RuntimeError("Option '%s' had no value set." % key)
            ret = ""

        return ret

    def check_leftover_opts(self):
        if not self.opts:
            return
        raise fail(_("Unknown options %s") % self.opts.keys())


    ###########################
    # Actual parsing routines #
    ###########################

    def _parse_optstr_tuples(self, virtargmap, remove_first):
        """
        Parse the command string into an ordered list of tuples (see
        docs for orderedopts
        """
        optstr = str(self.fullopts or "")
        optlist = []

        argsplitter = shlex.shlex(optstr, posix=True)
        argsplitter.commenters = ""
        argsplitter.whitespace = ","
        argsplitter.whitespace_split = True

        remove_first = util.listify(remove_first)[:]
        commaopt = []
        for opt in list(argsplitter):
            if not opt:
                continue

            cliname = opt
            val = None
            if opt.count("="):
                cliname, val = opt.split("=", 1)
                remove_first = []
            elif remove_first:
                val = cliname
                cliname = remove_first.pop(0)

            if commaopt:
                if cliname in virtargmap:
                    optlist.append(tuple(commaopt))
                    commaopt = []
                else:
                    commaopt[1] += "," + cliname
                    if val:
                        commaopt[1] += "=" + val
                    continue

            if (cliname in virtargmap and virtargmap[cliname].can_comma):
                commaopt = [cliname, val]
                continue

            optlist.append((cliname, val))

        if commaopt:
            optlist.append(tuple(commaopt))

        return optlist

    def _parse_optstr(self, virtargmap, remove_first):
        orderedopts = self._parse_optstr_tuples(virtargmap, remove_first)
        optdict = {}

        for cliname, val in orderedopts:
            if (cliname not in optdict and
                cliname in virtargmap and
                virtargmap[cliname].is_list):
                optdict[cliname] = []

            if type(optdict.get(cliname)) is list:
                optdict[cliname].append(val)
            else:
                optdict[cliname] = val

        return optdict, orderedopts


class VirtCLIParser(object):
    """
    Parse a compound arg string like --option foo=bar,baz=12. This is
    the desired interface to VirtCLIArgument and VirtCLIOptionString.

    A command line argument just extends this interface, implements
    _init_params, and calls set_param in the order it wants the options
    parsed on the command line. See existing impls examples of how to
    do all sorts of crazy stuff.

    set_param must be set unconditionally (ex from _init_params and not
    from overriding _parse), so that we can show all options when the
    user requests command line introspection like --disk=?
    """
    objclass = None

    def __init__(self, cli_arg_name):
        """
        These values should be set by subclasses in _init_params

        @cli_arg_name: The command line argument this maps to, so
            "hostdev" for --hostdev
        @guest: Will be set parse(), the toplevel Guest object
        @remove_first: Passed to VirtOptionString
        @check_none: If the parsed option string is just 'none', return None
        @support_cb: An extra support check function for further validation.
            Called before the virtinst object is altered. Take arguments
            (inst, attrname, cliname)
        @clear_attr: If the user requests to clear the XML (--disk clearxml),
            this is the property name we grab from inst to actually clear
            (so 'security' to get guest.security). If it's True, then
            clear inst (in the case of devices)
        """
        self.cli_arg_name = cli_arg_name
        # This is the name of the variable that argparse will set in
        # the result of parse_args()
        self.option_variable_name = cli_arg_name.replace("-", "_")

        self.guest = None
        self.remove_first = None
        self.check_none = False
        self.support_cb = None
        self.clear_attr = None

        self._params = []
        self._inparse = False

        self.__init_global_params()
        self._init_params()


    def __init_global_params(self):
        def set_clearxml_cb(inst, val, cbdata):
            ignore = cbdata
            if not self.objclass and not self.clear_attr:
                raise RuntimeError("Don't know how to clearxml --%s" %
                                   self.cli_arg_name)
            if val is not True:
                return

            clear_inst = inst
            if self.clear_attr:
                clear_inst = getattr(inst, self.clear_attr)

            # If there's any opts remaining, leave the root stub element
            # in place, so virt-xml updates are done in place.
            #
            # So --edit --cpu clearxml=yes  should remove the entire <cpu>
            # block. But --edit --cpu clearxml=yes,model=foo should leave
            # a <cpu> stub in place, so that it gets model=foo in place,
            # otherwise the newly created cpu block gets appened to the
            # end of the domain XML, which gives an ugly diff
            clear_inst.clear(leave_stub=bool(cbdata.opts.opts))

        self.set_param(None, "clearxml",
                       setter_cb=set_clearxml_cb, is_onoff=True)

    def _add_device_address_params(self):
        """
        Add VirtualDeviceAddress parameters if we are parsing for a device
        """
        self.set_param("address.type", "address.type")
        self.set_param("address.domain", "address.domain")
        self.set_param("address.bus", "address.bus")
        self.set_param("address.slot", "address.slot")
        self.set_param("address.multifunction", "address.multifunction",
                       is_onoff=True)
        self.set_param("address.function", "address.function")
        self.set_param("address.controller", "address.controller")
        self.set_param("address.unit", "address.unit")
        self.set_param("address.port", "address.port")
        self.set_param("address.target", "address.target")
        self.set_param("address.reg", "address.reg")
        self.set_param("address.cssid", "address.cssid")
        self.set_param("address.ssid", "address.ssid")
        self.set_param("address.devno", "address.devno")
        self.set_param("address.iobase", "address.iobase")
        self.set_param("address.irq", "address.irq")
        self.set_param("address.base", "address.base")


    def check_introspection(self, option):
        for optstr in util.listify(option):
            if optstr == "?" or optstr == "help":
                print "--%s options:" % self.cli_arg_name
                for arg in sorted(self._params, key=lambda p: p.cliname):
                    print "  %s" % arg.cliname
                print
                return True
        return False

    def set_param(self, *args, **kwargs):
        if self._inparse:
            # Otherwise we might break command line introspection
            raise RuntimeError("programming error: Can not call set_param "
                               "from parse handler.")
        self._params.append(_VirtCLIArgument(*args, **kwargs))

    def parse(self, guest, optlist, inst, validate=True):
        optlist = util.listify(optlist)
        editting = bool(inst)

        if editting and optlist:
            # If an object is passed in, we are updating it in place, and
            # only use the last command line occurrence, eg. from virt-xml
            optlist = [optlist[-1]]

        ret = []
        for optstr in optlist:
            new_object = False
            optinst = inst
            if self.objclass and not inst:
                if guest.child_class_is_singleton(self.objclass):
                    optinst = guest.list_children_for_class(
                        self.objclass)[0]
                else:
                    new_object = True
                    optinst = self.objclass(guest.conn)  # pylint: disable=not-callable

            try:
                objs = self._parse_single_optstr(guest, optstr, optinst)
                for obj in util.listify(objs):
                    if not new_object:
                        break
                    if validate:
                        obj.validate()
                    guest.add_child(obj)

                ret += util.listify(objs)
            except Exception, e:
                logging.debug("Exception parsing inst=%s optstr=%s",
                              inst, optstr, exc_info=True)
                fail(_("Error: --%(cli_arg_name)s %(options)s: %(err)s") %
                        {"cli_arg_name": self.cli_arg_name,
                         "options": optstr, "err": str(e)})

        if not ret:
            return None
        if len(ret) == 1:
            return ret[0]
        return ret

    def lookup_child_from_option_string(self, guest, optstr):
        """
        Given a passed option string, search the guests' child list
        for all objects which match the passed options.

        Used only by virt-xml --edit lookups
        """
        ret = []
        objlist = guest.list_children_for_class(self.objclass)

        for inst in objlist:
            try:
                opts = VirtOptionString(optstr, self._params,
                                        self.remove_first)
                valid = True
                for param in self._params:
                    if param.parse(opts, inst,
                                   support_cb=None, lookup=True) is False:
                        valid = False
                        break
                if valid:
                    ret.append(inst)
            except Exception, e:
                logging.debug("Exception parsing inst=%s optstr=%s",
                              inst, optstr, exc_info=True)
                fail(_("Error: --%(cli_arg_name)s %(options)s: %(err)s") %
                        {"cli_arg_name": self.cli_arg_name,
                         "options": optstr, "err": str(e)})

        return ret

    def _parse_single_optstr(self, guest, optstr, inst):
        if not optstr:
            return None
        if self.check_none and optstr == "none":
            return None

        if not inst:
            inst = guest

        try:
            self.guest = guest
            self._inparse = True
            opts = VirtOptionString(optstr, self._params, self.remove_first)
            return self._parse(opts, inst)
        finally:
            self.guest = None
            self._inparse = False

    def _parse(self, opts, inst):
        for param in self._params:
            param.parse(opts, inst, self.support_cb)
        opts.check_leftover_opts()
        return inst

    def _init_params(self):
        raise NotImplementedError()


###################
# --check parsing #
###################

def convert_old_force(options):
    if options.force:
        if not options.check:
            options.check = "all=off"
        del(options.force)


class ParseCLICheck(VirtCLIParser):
    # This sets properties on the _GlobalState objects

    def _init_params(self):
        def _set_check(inst, val, cbdata):
            inst.set_validation_check(cbdata.cliname, val)

        self.set_param(None, "path_in_use",
            is_onoff=True, setter_cb=_set_check)
        self.set_param(None, "disk_size",
            is_onoff=True, setter_cb=_set_check)
        self.set_param(None, "path_exists",
            is_onoff=True, setter_cb=_set_check)

        self.set_param("all_checks", "all", is_onoff=True)


def parse_check(checkstr):
    # Overwrite this for each parse,
    parser = ParseCLICheck("check")
    parser.parse(None, checkstr, get_global_state())


######################
# --metadata parsing #
######################

class ParserMetadata(VirtCLIParser):
    def _init_params(self):
        self.set_param("name", "name", can_comma=True)
        self.set_param("title", "title", can_comma=True)
        self.set_param("uuid", "uuid")
        self.set_param("description", "description", can_comma=True)


####################
# --events parsing #
####################

class ParserEvents(VirtCLIParser):
    def _init_params(self):
        self.set_param("on_poweroff", "on_poweroff")
        self.set_param("on_reboot", "on_reboot")
        self.set_param("on_crash", "on_crash")
        self.set_param("on_lockfailure", "on_lockfailure")


######################
# --resource parsing #
######################

class ParserResource(VirtCLIParser):
    def _init_params(self):
        self.objclass = DomainResource
        self.remove_first = "partition"

        self.set_param("partition", "partition")


######################
# --numatune parsing #
######################

class ParserNumatune(VirtCLIParser):
    def _init_params(self):
        self.objclass = DomainNumatune
        self.remove_first = "nodeset"

        self.set_param("memory_nodeset", "nodeset", can_comma=True)
        self.set_param("memory_mode", "mode")


####################
# --memory parsing #
####################

class ParserMemory(VirtCLIParser):
    def _init_params(self):
        self.remove_first = "memory"

        def set_memory_cb(inst, val, cbdata):
            setattr(inst, cbdata.cliname, int(val) * 1024)
        self.set_param("memory", "memory", setter_cb=set_memory_cb)
        self.set_param("maxmemory", "maxmemory", setter_cb=set_memory_cb)
        self.set_param("memoryBacking.hugepages", "hugepages", is_onoff=True)


#####################
# --memtune parsing #
#####################

class ParserMemorytune(VirtCLIParser):
    def _init_params(self):
        self.objclass = DomainMemorytune
        self.remove_first = "soft_limit"

        self.set_param("hard_limit", "hard_limit")
        self.set_param("soft_limit", "soft_limit")
        self.set_param("swap_hard_limit", "swap_hard_limit")
        self.set_param("min_guarantee", "min_guarantee")


#######################
# --blkiotune parsing #
#######################

class ParserBlkiotune(VirtCLIParser):
    def _init_params(self):
        self.objclass = DomainBlkiotune
        self.remove_first = "weight"

        self.set_param("weight", "weight")
        self.set_param("device_path", "device_path")
        self.set_param("device_weight", "device_weight")


###########################
# --memorybacking parsing #
###########################

class ParserMemorybacking(VirtCLIParser):
    def _init_params(self):
        self.objclass = DomainMemorybacking

        self.set_param("hugepages", "hugepages", is_onoff=True)
        self.set_param("page_size", "size")
        self.set_param("page_unit", "unit")
        self.set_param("page_nodeset", "nodeset", can_comma=True)
        self.set_param("nosharepages", "nosharepages", is_onoff=True)
        self.set_param("locked", "locked", is_onoff=True)


###################
# --vcpus parsing #
###################

class ParserVCPU(VirtCLIParser):
    def _init_params(self):
        self.remove_first = "vcpus"

        def set_vcpus_cb(inst, val, cbdata):
            attrname = (("maxvcpus" in cbdata.opts.opts) and
                        "curvcpus" or "vcpus")
            setattr(inst, attrname, val)

        def set_cpuset_cb(inst, val, cbdata):
            if not val:
                return
            if val != "auto":
                inst.cpuset = val
                return

            # Previously we did our own one-time cpuset placement
            # based on current NUMA memory availability, but that's
            # pretty dumb unless the conditions on the host never change.
            # So instead use newer vcpu placement=, but only if it's
            # supported.
            if not inst.conn.check_support(
                    inst.conn.SUPPORT_CONN_VCPU_PLACEMENT):
                logging.warning("vcpu placement=auto not supported, skipping.")
                return

            inst.vcpu_placement = "auto"

        self.set_param("cpu.sockets", "sockets")
        self.set_param("cpu.cores", "cores")
        self.set_param("cpu.threads", "threads")

        self.set_param(None, "vcpus", setter_cb=set_vcpus_cb)
        self.set_param("vcpus", "maxvcpus")

        self.set_param(None, "cpuset", can_comma=True,
                       setter_cb=set_cpuset_cb)
        self.set_param("vcpu_placement", "placement")


    def _parse(self, opts, inst):
        set_from_top = ("maxvcpus" not in opts.opts and
                        "vcpus" not in opts.opts)

        ret = VirtCLIParser._parse(self, opts, inst)

        if set_from_top:
            inst.vcpus = inst.cpu.vcpus_from_topology()
        return ret


#################
# --cpu parsing #
#################

class ParserCPU(VirtCLIParser):
    def _init_params(self):
        self.objclass = CPU
        self.remove_first = "model"

        def set_model_cb(inst, val, cbdata):
            ignore = cbdata
            if val == "host":
                val = inst.SPECIAL_MODE_HOST_MODEL
            if val == "none":
                val = inst.SPECIAL_MODE_CLEAR

            if val in inst.SPECIAL_MODES:
                inst.set_special_mode(val)
            else:
                inst.model = val

        def set_feature_cb(inst, val, cbdata):
            policy = cbdata.cliname
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

        self.set_param(None, "model", setter_cb=set_model_cb)
        self.set_param("mode", "mode")
        self.set_param("match", "match")
        self.set_param("vendor", "vendor")

        self.set_param(None, "force", is_list=True, setter_cb=set_feature_cb)
        self.set_param(None, "require", is_list=True, setter_cb=set_feature_cb)
        self.set_param(None, "optional", is_list=True, setter_cb=set_feature_cb)
        self.set_param(None, "disable", is_list=True, setter_cb=set_feature_cb)
        self.set_param(None, "forbid", is_list=True, setter_cb=set_feature_cb)

    def _parse(self, optsobj, inst):
        opts = optsobj.opts

        # Convert +feature, -feature into expected format
        for key, value in opts.items():
            policy = None
            if value or len(key) == 1:
                continue

            if key.startswith("+"):
                policy = "force"
            elif key.startswith("-"):
                policy = "disable"

            if policy:
                del(opts[key])
                if opts.get(policy) is None:
                    opts[policy] = []
                opts[policy].append(key[1:])

        return VirtCLIParser._parse(self, optsobj, inst)


##################
# --boot parsing #
##################

class ParserBoot(VirtCLIParser):
    def _init_params(self):
        self.clear_attr = "os"

        # UEFI depends on these bits, so set them first
        self.set_param("os.arch", "arch")
        self.set_param("type", "domain_type")
        self.set_param("os.os_type", "os_type")
        self.set_param("emulator", "emulator")

        def set_uefi(inst, val, cbdata):
            ignore = val
            ignore = cbdata
            inst.set_uefi_default()
        self.set_param(None, "uefi", setter_cb=set_uefi, is_novalue=True)

        self.set_param("os.useserial", "useserial", is_onoff=True)
        self.set_param("os.enable_bootmenu", "menu", is_onoff=True)
        self.set_param("os.kernel", "kernel")
        self.set_param("os.initrd", "initrd")
        self.set_param("os.dtb", "dtb")
        self.set_param("os.loader", "loader")
        self.set_param("os.loader_ro", "loader_ro", is_onoff=True)
        self.set_param("os.loader_type", "loader_type")
        self.set_param("os.nvram", "nvram")
        self.set_param("os.nvram_template", "nvram_template")
        self.set_param("os.kernel_args", "kernel_args",
            aliases=["extra_args"], can_comma=True)
        self.set_param("os.init", "init")
        self.set_param("os.machine", "machine")

        def set_initargs_cb(inst, val, cbdata):
            ignore = cbdata
            inst.os.set_initargs_string(val)
        self.set_param("os.initargs", "initargs", setter_cb=set_initargs_cb)

        # Order matters for boot devices, we handle it specially in parse
        def noset_cb(val):
            ignore = val
        for b in OSXML.BOOT_DEVICES:
            self.set_param(noset_cb, b)

    def _parse(self, opts, inst):
        # Build boot order
        boot_order = []
        for cliname, ignore in opts.orderedopts:
            if cliname not in inst.os.BOOT_DEVICES:
                continue

            del(opts.opts[cliname])
            if cliname not in boot_order:
                boot_order.append(cliname)

        if boot_order:
            inst.os.bootorder = boot_order

        VirtCLIParser._parse(self, opts, inst)


###################
# --idmap parsing #
###################

class ParserIdmap(VirtCLIParser):
    def _init_params(self):
        self.objclass = IdMap

        self.set_param("uid_start", "uid_start")
        self.set_param("uid_target", "uid_target")
        self.set_param("uid_count", "uid_count")

        self.set_param("gid_start", "gid_start")
        self.set_param("gid_target", "gid_target")
        self.set_param("gid_count", "gid_count")


######################
# --security parsing #
######################

class ParserSecurity(VirtCLIParser):
    def _init_params(self):
        self.objclass = Seclabel

        self.set_param("type", "type")
        self.set_param("model", "model")
        self.set_param("relabel", "relabel", is_onoff=True)
        self.set_param("label", "label", can_comma=True)
        self.set_param("baselabel", "label", can_comma=True)


######################
# --features parsing #
######################

class ParserFeatures(VirtCLIParser):
    def _init_params(self):
        self.objclass = DomainFeatures

        self.set_param("acpi", "acpi", is_onoff=True)
        self.set_param("apic", "apic", is_onoff=True)
        self.set_param("pae", "pae", is_onoff=True)
        self.set_param("privnet", "privnet",
            is_onoff=True)
        self.set_param("hap", "hap",
            is_onoff=True)
        self.set_param("viridian", "viridian",
            is_onoff=True)
        self.set_param("eoi", "eoi", is_onoff=True)
        self.set_param("pmu", "pmu", is_onoff=True)

        self.set_param("hyperv_vapic", "hyperv_vapic",
            is_onoff=True)
        self.set_param("hyperv_relaxed", "hyperv_relaxed",
            is_onoff=True)
        self.set_param("hyperv_spinlocks", "hyperv_spinlocks",
            is_onoff=True)
        self.set_param("hyperv_spinlocks_retries",
            "hyperv_spinlocks_retries")

        self.set_param("vmport", "vmport", is_onoff=True)
        self.set_param("kvm_hidden", "kvm_hidden", is_onoff=True)
        self.set_param("pvspinlock", "pvspinlock", is_onoff=True)

        self.set_param("gic_version", "gic_version")


###################
# --clock parsing #
###################

class ParserClock(VirtCLIParser):
    def _init_params(self):
        self.objclass = Clock

        self.set_param("offset", "offset")

        def set_timer(inst, val, cbdata):
            tname, attrname = cbdata.cliname.split("_")

            timerobj = None
            for t in inst.timers:
                if t.name == tname:
                    timerobj = t
                    break

            if not timerobj:
                timerobj = inst.add_timer()
                timerobj.name = tname

            setattr(timerobj, attrname, val)

        for tname in Clock.TIMER_NAMES:
            self.set_param(None, tname + "_present",
                is_onoff=True,
                setter_cb=set_timer)
            self.set_param(None, tname + "_tickpolicy", setter_cb=set_timer)


################
# --pm parsing #
################

class ParserPM(VirtCLIParser):
    def _init_params(self):
        self.objclass = PM

        self.set_param("suspend_to_mem", "suspend_to_mem", is_onoff=True)
        self.set_param("suspend_to_disk", "suspend_to_disk", is_onoff=True)


##########################
# Guest <device> parsing #
##########################

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
    for disk in guest.get_devices("disk"):
        if (disk.get_vol_install() and
            disk.get_vol_install().pool.name() == poolobj.name()):
            collidelist.append(os.path.basename(disk.path))

    ext = StorageVolume.get_file_extension_for_format(fmt)
    return StorageVolume.find_free_name(
        poolobj, guest.name, suffix=ext, collidelist=collidelist)


class ParserDisk(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualDisk
        self.remove_first = "path"
        self._add_device_address_params()

        def noset_cb(inst, val, cbdata):
            ignore = inst, val, cbdata

        # These are all handled specially in _parse
        self.set_param(None, "backing_store", setter_cb=noset_cb)
        self.set_param(None, "pool", setter_cb=noset_cb)
        self.set_param(None, "vol", setter_cb=noset_cb)
        self.set_param(None, "size", setter_cb=noset_cb)
        self.set_param(None, "format", setter_cb=noset_cb)
        self.set_param(None, "sparse", setter_cb=noset_cb)

        self.set_param("source_pool", "source_pool")
        self.set_param("source_volume", "source_volume")
        self.set_param("source_name", "source_name")
        self.set_param("source_protocol", "source_protocol")
        self.set_param("source_host_name", "source_host_name")
        self.set_param("source_host_port", "source_host_port")
        self.set_param("source_host_socket", "source_host_socket")
        self.set_param("source_host_transport", "source_host_transport")

        self.set_param("path", "path")
        self.set_param("device", "device")
        self.set_param("bus", "bus")
        self.set_param("removable", "removable", is_onoff=True)
        self.set_param("driver_cache", "cache")
        self.set_param("driver_discard", "discard")
        self.set_param("driver_name", "driver_name")
        self.set_param("driver_type", "driver_type")
        self.set_param("driver_io", "io")
        self.set_param("error_policy", "error_policy")
        self.set_param("serial", "serial")
        self.set_param("target", "target")
        self.set_param("startup_policy", "startup_policy")
        self.set_param("read_only", "readonly", is_onoff=True)
        self.set_param("shareable", "shareable", is_onoff=True)
        self.set_param("boot.order", "boot_order")

        self.set_param("iotune_rbs", "read_bytes_sec")
        self.set_param("iotune_wbs", "write_bytes_sec")
        self.set_param("iotune_tbs", "total_bytes_sec")
        self.set_param("iotune_ris", "read_iops_sec")
        self.set_param("iotune_wis", "write_iops_sec")
        self.set_param("iotune_tis", "total_iops_sec")
        self.set_param("sgio", "sgio")

    def _parse(self, opts, inst):
        if opts.fullopts == "none":
            return

        def parse_size(val):
            if val is None:
                return None
            try:
                return float(val)
            except Exception, e:
                fail(_("Improper value for 'size': %s") % str(e))

        def convert_perms(val):
            if val is None:
                return
            if val == "ro":
                opts.opts["readonly"] = "on"
            elif val == "sh":
                opts.opts["shareable"] = "on"
            elif val == "rw":
                # It's default. Nothing to do.
                pass
            else:
                fail(_("Unknown '%s' value '%s'") % ("perms", val))

        has_path = "path" in opts.opts
        backing_store = opts.get_opt_param("backing_store")
        poolname = opts.get_opt_param("pool")
        volname = opts.get_opt_param("vol")
        size = parse_size(opts.get_opt_param("size"))
        fmt = opts.get_opt_param("format")
        sparse = _on_off_convert("sparse", opts.get_opt_param("sparse"))
        convert_perms(opts.get_opt_param("perms"))
        has_type_volume = ("source_pool" in opts.opts or
                           "source_volume" in opts.opts)
        has_type_network = ("source_protocol" in opts.opts)

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

        VirtCLIParser._parse(self, opts, inst)

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
            vol_install = VirtualDisk.build_vol_install(
                    self.guest.conn, newvolname, poolobj, size, sparse,
                    fmt=fmt, backing_store=backing_store)
            inst.set_vol_install(vol_install)

        if not inst.target:
            skip_targets = [d.target for d in self.guest.get_devices("disk")]
            inst.generate_target(skip_targets)
            inst.cli_generated_target = True

        return inst


#####################
# --network parsing #
#####################

class ParserNetwork(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualNetworkInterface
        self.remove_first = "type"
        self._add_device_address_params()

        def set_mac_cb(inst, val, cbdata):
            ignore = cbdata
            if val == "RANDOM":
                return None
            inst.macaddr = val
            return val

        def set_type_cb(inst, val, cbdata):
            ignore = cbdata
            if val == "default":
                inst.set_default_source()
            else:
                inst.type = val

        def set_link_state(inst, val, cbdata):
            ignore = cbdata
            if val in ["up", "down"]:
                inst.link_state = val
                return

            ret = _raw_on_off_convert(val)
            if ret is True:
                val = "up"
            elif ret is False:
                val = "down"
            inst.link_state = val

        self.set_param("type", "type", setter_cb=set_type_cb)
        self.set_param("source", "source")
        self.set_param("source_mode", "source_mode")
        self.set_param("portgroup", "portgroup")
        self.set_param("target_dev", "target")
        self.set_param("model", "model")
        self.set_param("macaddr", "mac", setter_cb=set_mac_cb)
        self.set_param("filterref", "filterref")
        self.set_param("boot.order", "boot_order")
        self.set_param("link_state", "link_state", setter_cb=set_link_state)

        self.set_param("driver_name", "driver_name")
        self.set_param("driver_queues", "driver_queues")

        self.set_param("rom_file", "rom_file")
        self.set_param("rom_bar", "rom_bar", is_onoff=True)

        self.set_param("virtualport.type", "virtualport_type")

        # For 802.1Qbg
        self.set_param("virtualport.managerid", "virtualport_managerid")
        self.set_param("virtualport.typeid", "virtualport_typeid")
        self.set_param("virtualport.typeidversion",
            "virtualport_typeidversion")
        self.set_param("virtualport.instanceid", "virtualport_instanceid")

        # For openvswitch & 802.1Qbh
        self.set_param("virtualport.profileid", "virtualport_profileid")

        # For openvswitch & midonet
        self.set_param("virtualport.interfaceid", "virtualport_interfaceid")

    def _parse(self, optsobj, inst):
        if optsobj.fullopts == "none":
            return

        opts = optsobj.opts
        if "type" not in opts:
            if "network" in opts:
                opts["type"] = VirtualNetworkInterface.TYPE_VIRTUAL
                opts["source"] = opts.pop("network")
            elif "bridge" in opts:
                opts["type"] = VirtualNetworkInterface.TYPE_BRIDGE
                opts["source"] = opts.pop("bridge")

        return VirtCLIParser._parse(self, optsobj, inst)


######################
# --graphics parsing #
######################

class ParserGraphics(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualGraphics
        self.remove_first = "type"
        self._add_device_address_params()

        def set_keymap_cb(inst, val, cbdata):
            ignore = cbdata
            from . import hostkeymap

            if not val:
                val = None
            elif val.lower() == "local":
                val = VirtualGraphics.KEYMAP_LOCAL
            elif val.lower() == "none":
                val = None
            else:
                use_keymap = hostkeymap.sanitize_keymap(val)
                if not use_keymap:
                    raise ValueError(
                        _("Didn't match keymap '%s' in keytable!") % val)
                val = use_keymap
            inst.keymap = val

        def set_type_cb(inst, val, cbdata):
            ignore = cbdata
            if val == "default":
                return
            inst.type = val

        def set_listen_cb(inst, val, cbdata):
            if val == "none":
                inst.set_listen_none()
            elif val == "socket":
                inst.remove_all_listens()
                obj = inst.add_listen()
                obj.type = "socket"
            else:
                inst.listen = val

        self.set_param(None, "type", setter_cb=set_type_cb)
        self.set_param("port", "port")
        self.set_param("tlsPort", "tlsport")
        self.set_param("listen", "listen", setter_cb=set_listen_cb)
        self.set_param(None, "keymap", setter_cb=set_keymap_cb)
        self.set_param("passwd", "password")
        self.set_param("passwdValidTo", "passwordvalidto")
        self.set_param("connected", "connected")
        self.set_param("defaultMode", "defaultMode")

        self.set_param("image_compression", "image_compression")
        self.set_param("streaming_mode", "streaming_mode")
        self.set_param("clipboard_copypaste", "clipboard_copypaste",
            is_onoff=True)
        self.set_param("mouse_mode", "mouse_mode")
        self.set_param("filetransfer_enable", "filetransfer_enable",
            is_onoff=True)
        self.set_param("gl", "gl", is_onoff=True)

    def _parse(self, opts, inst):
        if opts.fullopts == "none":
            self.guest.skip_default_graphics = True
            return

        ret = VirtCLIParser._parse(self, opts, inst)

        if inst.conn.is_qemu() and inst.gl:
            if inst.type != "spice":
                logging.warn("graphics type=%s does not support GL", inst.type)
            elif not inst.conn.check_support(
                    inst.conn.SUPPORT_CONN_SPICE_GL):
                logging.warn("qemu/libvirt version may not support spice GL")

        return ret


########################
# --controller parsing #
########################

class ParserController(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualController
        self.remove_first = "type"
        self._add_device_address_params()

        self.set_param("type", "type")
        self.set_param("model", "model")
        self.set_param("index", "index")
        self.set_param("master_startport", "master")

        def set_server_cb(inst, val, cbdata):
            ignore = cbdata
            inst.address.set_addrstr(val)
        self.set_param(None, "address", setter_cb=set_server_cb)

    def _parse(self, opts, inst):
        if opts.fullopts == "usb2":
            return VirtualController.get_usb2_controllers(inst.conn)
        elif opts.fullopts == "usb3":
            inst.type = "usb"
            inst.model = "nec-xhci"
            return inst
        return VirtCLIParser._parse(self, opts, inst)


###################
# --input parsing #
###################

class ParserInput(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualInputDevice
        self.remove_first = "type"
        self._add_device_address_params()

        self.set_param("type", "type")
        self.set_param("bus", "bus")


#######################
# --smartcard parsing #
#######################

class ParserSmartcard(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualSmartCardDevice
        self.remove_first = "mode"
        self.check_none = True
        self._add_device_address_params()

        self.set_param("mode", "mode")
        self.set_param("type", "type")


######################
# --redirdev parsing #
######################

class ParserRedir(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualRedirDevice
        self.remove_first = "bus"
        self._add_device_address_params()

        self.set_param("bus", "bus")
        self.set_param("type", "type")
        self.set_param("boot.order", "boot_order")

        def set_server_cb(inst, val, cbdata):
            ignore = cbdata
            inst.parse_friendly_server(val)

        self.set_param(None, "server", setter_cb=set_server_cb)

    def _parse(self, opts, inst):
        if opts.fullopts == "none":
            self.guest.skip_default_usbredir = True
            return
        return VirtCLIParser._parse(self, opts, inst)


#################
# --tpm parsing #
#################

class ParserTPM(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualTPMDevice
        self.remove_first = "type"
        self.check_none = True
        self._add_device_address_params()

        self.set_param("type", "type")
        self.set_param("model", "model")
        self.set_param("device_path", "path")

    def _parse(self, opts, inst):
        if (opts.opts.get("type", "").startswith("/")):
            opts.opts["path"] = opts.opts.pop("type")
        return VirtCLIParser._parse(self, opts, inst)


#################
# --rng parsing #
#################

class ParserRNG(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualRNGDevice
        self.remove_first = "type"
        self.check_none = True
        self._add_device_address_params()

        def set_hosts_cb(inst, val, cbdata):
            namemap = {}
            inst.backend_type = self._cli_backend_type

            if self._cli_backend_mode == "connect":
                namemap["backend_host"] = "connect_host"
                namemap["backend_service"] = "connect_service"

            if self._cli_backend_mode == "bind":
                namemap["backend_host"] = "bind_host"
                namemap["backend_service"] = "bind_service"

                if self._cli_backend_type == "udp":
                    namemap["backend_connect_host"] = "connect_host"
                    namemap["backend_connect_service"] = "connect_service"

            if cbdata.cliname in namemap:
                setattr(inst, namemap[cbdata.cliname], val)

        def set_backend_cb(inst, val, cbdata):
            ignore = cbdata
            ignore = inst
            # pylint: disable=attribute-defined-outside-init
            if cbdata.cliname == "backend_mode":
                self._cli_backend_mode = val
            elif cbdata.cliname == "backend_type":
                self._cli_backend_type = val

        self.set_param("type", "type")

        self.set_param(None, "backend_mode", setter_cb=set_backend_cb)
        self.set_param(None, "backend_type", setter_cb=set_backend_cb)

        self.set_param(None, "backend_host", setter_cb=set_hosts_cb)
        self.set_param(None, "backend_service", setter_cb=set_hosts_cb)
        self.set_param(None, "backend_connect_host", setter_cb=set_hosts_cb)
        self.set_param(None, "backend_connect_service", setter_cb=set_hosts_cb)

        self.set_param("device", "device")
        self.set_param("model", "model")
        self.set_param("rate_bytes", "rate_bytes")
        self.set_param("rate_period", "rate_period")

    def _parse(self, optsobj, inst):
        opts = optsobj.opts

        # pylint: disable=attribute-defined-outside-init
        # Defined outside init, but its easier this way
        self._cli_backend_mode = "connect"
        self._cli_backend_type = "udp"
        # pylint: enable=attribute-defined-outside-init

        if opts.get("type", "").startswith("/"):
            # Allow --rng /dev/random
            opts["device"] = opts.pop("type")
            opts["type"] = "random"

        return VirtCLIParser._parse(self, optsobj, inst)


######################
# --watchdog parsing #
######################

class ParserWatchdog(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualWatchdog
        self.remove_first = "model"
        self._add_device_address_params()

        self.set_param("model", "model")
        self.set_param("action", "action")


########################
# --memballoon parsing #
########################

class ParserMemballoon(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualMemballoon
        self.remove_first = "model"
        self._add_device_address_params()

        self.set_param("model", "model")


###################
# --panic parsing #
###################

class ParserPanic(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualPanicDevice
        self.remove_first = "iobase"
        self._add_device_address_params()

        def set_iobase_cb(inst, val, cbdata):
            ignore = cbdata
            if val == "default":
                return
            inst.iobase = val
        self.set_param(None, "iobase", setter_cb=set_iobase_cb)


######################################################
# --serial, --parallel, --channel, --console parsing #
######################################################

class _ParserChar(VirtCLIParser):
    def _init_params(self):
        self.remove_first = "char_type"
        self._add_device_address_params()

        def support_check(inst, attrname, cliname):
            if type(attrname) is not str:
                return
            if not inst.supports_property(attrname):
                raise ValueError(_("%(devtype)s type '%(chartype)s' does not "
                    "support '%(optname)s' option.") %
                    {"devtype" : inst.virtual_device_type,
                     "chartype": inst.type,
                     "optname" : cliname})
        self.support_cb = support_check

        self.set_param("type", "char_type")
        self.set_param("source_path", "path")
        self.set_param("protocol",   "protocol")
        self.set_param("target_type", "target_type")
        self.set_param("target_name", "name")

        def set_host_cb(inst, val, cbdata):
            if ("bind_host" not in cbdata.opts.opts and
                cbdata.opts.opts.get("mode", None) == "bind"):
                inst.set_friendly_bind(val)
            else:
                inst.set_friendly_source(val)
        self.set_param(None, "host", setter_cb=set_host_cb)

        def set_bind_cb(inst, val, cbdata):
            ignore = cbdata
            inst.set_friendly_bind(val)
        self.set_param(None, "bind_host", setter_cb=set_bind_cb)

        def set_target_cb(inst, val, cbdata):
            ignore = cbdata
            inst.set_friendly_target(val)
        self.set_param(None, "target_address", setter_cb=set_target_cb)

        self.set_param("source_mode", "mode")

    def _parse(self, opts, inst):
        if opts.fullopts == "none" and inst.virtual_device_type == "console":
            self.guest.skip_default_console = True
            return
        if opts.fullopts == "none" and inst.virtual_device_type == "channel":
            self.guest.skip_default_channel = True
            return

        return VirtCLIParser._parse(self, opts, inst)


class ParserSerial(_ParserChar):
    objclass = VirtualSerialDevice


class ParserParallel(_ParserChar):
    objclass = VirtualParallelDevice


class ParserChannel(_ParserChar):
    objclass = VirtualChannelDevice


class ParserConsole(_ParserChar):
    objclass = VirtualConsoleDevice


########################
# --filesystem parsing #
########################

class ParserFilesystem(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualFilesystem
        self.remove_first = ["source", "target"]
        self._add_device_address_params()

        self.set_param("type", "type")
        self.set_param("accessmode", "accessmode", aliases=["mode"])
        self.set_param("source", "source")
        self.set_param("target", "target")


###################
# --video parsing #
###################

class ParserVideo(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualVideoDevice
        self.remove_first = "model"
        self._add_device_address_params()

        self.set_param("model", "model", ignore_default=True)
        self.set_param("accel3d", "accel3d", is_onoff=True)
        self.set_param("heads", "heads")
        self.set_param("ram", "ram")
        self.set_param("vram", "vram")
        self.set_param("vgamem", "vgamem")

    def _parse(self, opts, inst):
        ret = VirtCLIParser._parse(self, opts, inst)

        if inst.conn.is_qemu() and inst.accel3d:
            if inst.model != "virtio":
                logging.warn("video model=%s does not support accel3d",
                    inst.model)
            elif not inst.conn.check_support(
                    inst.conn.SUPPORT_CONN_VIDEO_VIRTIO_ACCEL3D):
                logging.warn("qemu/libvirt version may not support "
                             "virtio accel3d")

        return ret


###################
# --sound parsing #
###################

class ParserSound(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualAudio
        self.remove_first = "model"
        self._add_device_address_params()

        self.set_param("model", "model", ignore_default=True)

    def _parse(self, opts, inst):
        if opts.fullopts == "none":
            self.guest.skip_default_sound = True
            return
        return VirtCLIParser._parse(self, opts, inst)


#########################
# --hostdev parsing #
#########################

class ParserHostdev(VirtCLIParser):
    def _init_params(self):
        self.objclass = VirtualHostDevice
        self.remove_first = "name"
        self._add_device_address_params()

        # If using the name_lookup_cb, this saves us repeatedly trying to
        # lookup the nodedev
        _nodedev_lookup_cache = {}

        def set_name_cb(inst, val, cbdata):
            ignore = cbdata
            val = NodeDevice.lookupNodedevFromString(inst.conn, val)
            inst.set_from_nodedev(val)
        def name_lookup_cb(inst, val, cbdata):
            ignore = cbdata

            if val not in _nodedev_lookup_cache:
                _nodedev_lookup_cache[val] = \
                    NodeDevice.lookupNodedevFromString(inst.conn, val)
            nodedev = _nodedev_lookup_cache[val]
            return nodedev.compare_to_hostdev(inst)

        self.set_param(None, "name",
                       setter_cb=set_name_cb, lookup_cb=name_lookup_cb)
        self.set_param("driver_name", "driver_name")
        self.set_param("boot.order", "boot_order")
        self.set_param("rom_bar", "rom_bar", is_onoff=True)


###########################
# Register parser classes #
###########################

def build_parser_map(options, skip=None, only=None):
    """
    Build a dictionary with mapping of cli-name->parserinstance, so
    --vcpus -> ParserVCPU object.
    """
    parsermap = {}
    def register_parser(cli_arg_name, parserclass):
        if cli_arg_name in util.listify(skip):
            return
        if only and cli_arg_name not in util.listify(only):
            return

        parserobj = parserclass(cli_arg_name)
        if not hasattr(options, parserobj.option_variable_name):
            raise RuntimeError("programming error: unknown option=%s "
                               "cliname=%s class=%s" %
                               (parserobj.option_variable_name,
                                parserobj.cli_arg_name, parserclass))
        parsermap[parserobj.option_variable_name] = parserobj

    register_parser("metadata", ParserMetadata)
    register_parser("events", ParserEvents)
    register_parser("resource", ParserResource)
    register_parser("memory", ParserMemory)
    register_parser("memtune", ParserMemorytune)
    register_parser("vcpus", ParserVCPU)
    register_parser("cpu", ParserCPU)
    register_parser("numatune", ParserNumatune)
    register_parser("blkiotune", ParserBlkiotune)
    register_parser("memorybacking", ParserMemorybacking)
    register_parser("idmap", ParserIdmap)
    register_parser("boot", ParserBoot)
    register_parser("security", ParserSecurity)
    register_parser("features", ParserFeatures)
    register_parser("clock", ParserClock)
    register_parser("pm", ParserPM)
    register_parser("disk", ParserDisk)
    register_parser("network", ParserNetwork)
    register_parser("graphics", ParserGraphics)
    register_parser("controller", ParserController)
    register_parser("input", ParserInput)
    register_parser("smartcard", ParserSmartcard)
    register_parser("redirdev", ParserRedir)
    register_parser("tpm", ParserTPM)
    register_parser("rng", ParserRNG)
    register_parser("watchdog", ParserWatchdog)
    register_parser("memballoon", ParserMemballoon)
    register_parser("serial", ParserSerial)
    register_parser("parallel", ParserParallel)
    register_parser("channel", ParserChannel)
    register_parser("console", ParserConsole)
    register_parser("filesystem", ParserFilesystem)
    register_parser("video", ParserVideo)
    register_parser("sound", ParserSound)
    register_parser("hostdev", ParserHostdev)
    register_parser("panic", ParserPanic)

    return parsermap


def parse_option_strings(parsermap, options, guest, instlist, update=False):
    """
    Iterate over the parsermap, and launch the associated parser
    function for every value that was filled in on 'options', which
    came from argparse/the command line.

    @update: If we are updating an existing guest, like from virt-xml
    """
    instlist = util.listify(instlist)
    if not instlist:
        instlist = [None]

    ret = []
    for option_variable_name in dir(options):
        if option_variable_name not in parsermap:
            continue

        for inst in util.listify(instlist):
            parseret = parsermap[option_variable_name].parse(
                guest, getattr(options, option_variable_name), inst,
                validate=not update)
            ret += util.listify(parseret)

    return ret


def check_option_introspection(options, parsermap):
    """
    Check if the user requested option introspection with ex: '--disk=?'
    """
    ret = False
    for option_variable_name in dir(options):
        if option_variable_name not in parsermap:
            continue
        if parsermap[option_variable_name].check_introspection(
            getattr(options, option_variable_name)):
            ret = True

    return ret
