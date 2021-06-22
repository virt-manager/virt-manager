# Copyright(c) FUJITSU Limited 2007.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import argparse
import sys

from . import cli
from .cli import fail, print_stdout, print_stderr
from .cloner import Cloner


def _process_src(options):
    src_name = options.src_name
    src_xml = None
    if options.original_xml:
        src_xml = open(options.original_xml).read()
    elif not src_name:
        fail(_("An original machine name is required,"
            " use '--original src_name' and try again."))
    return src_name, src_xml


def _process_macs(options, cloner):
    new_macs = options.new_mac
    if not new_macs or new_macs[0] == "RANDOM":
        return

    for mac in new_macs:
        cli.validate_mac(cloner.conn, mac)

    for iface in cloner.new_guest.devices.interface[:]:
        iface.macaddr = new_macs.pop(0)


def _process_disks(options, cloner):
    newpaths = (options.new_diskfile or [])[:]

    diskinfos = cloner.get_nonshare_diskinfos()
    for diskinfo in diskinfos:
        origpath = diskinfo.disk.get_source_path()
        newpath = None
        if newpaths:
            newpath = newpaths.pop(0)
        elif options.auto_clone:
            break

        if origpath is None:
            newpath = None
        diskinfo.set_new_path(newpath, options.sparse)
        diskinfo.raise_error()


def _validate_disks(cloner):
    # Extra CLI validation for specified disks
    for diskinfo in cloner.get_diskinfos():
        diskinfo.raise_error()
        if not diskinfo.new_disk:
            continue
        warn_overwrite = not diskinfo.is_preserve_requested()
        cli.validate_disk(diskinfo.new_disk,
                warn_overwrite=warn_overwrite)


def parse_args():
    desc = _("Duplicate a virtual machine, changing all the unique "
        "host side configuration like MAC address, name, etc. \n\n"
        "The VM contents are NOT altered: virt-clone does not change "
        "anything _inside_ the guest OS, it only duplicates disks and "
        "does host side changes. So things like changing passwords, "
        "changing static IP address, etc are outside the scope of "
        "this tool. For these types of changes, please see virt-sysprep(1).")
    parser = cli.setupParser("%(prog)s --original [NAME] ...", desc)
    cli.add_connect_option(parser)

    geng = parser.add_argument_group(_("General Options"))
    geng.add_argument("-o", "--original", dest="src_name",
                    help=_("Name of the original guest to clone."))
    geng.add_argument("--original-xml",
                    help=_("XML file to use as the original guest."))
    geng.add_argument("--auto-clone", action="store_true",
                    help=_("Auto generate clone name and storage paths from"
                           " the original guest configuration."))
    geng.add_argument("-n", "--name", dest="new_name",
                    help=_("Name for the new guest"))
    geng.add_argument("-u", "--uuid", dest="new_uuid", help=argparse.SUPPRESS)
    geng.add_argument("--reflink", action="store_true",
            help=_("use btrfs COW lightweight copy"))

    stog = parser.add_argument_group(_("Storage Configuration"))
    stog.add_argument("-f", "--file", dest="new_diskfile", action="append",
                    help=_("New file to use as the disk image for the "
                           "new guest"))
    stog.add_argument("--force-copy", dest="target", action="append",
                    help=_("Force to copy devices (eg, if 'hdc' is a "
                           "readonly cdrom device, --force-copy=hdc)"))
    stog.add_argument("--skip-copy", action="append",
                    help=_("Skip copy of the device target. (eg, if 'vda' is a "
                           "disk you don't want to copy and use the same path "
                           "in the new VM, use --skip-copy=vda)"))
    stog.add_argument("--nonsparse", action="store_false", dest="sparse",
                    default=True,
                    help=_("Do not use a sparse file for the clone's "
                           "disk image"))
    stog.add_argument("--preserve-data", dest="preserve",
            action="store_true", default=False,
            help=_("Do not clone storage contents to specified file paths, "
                   "their contents will be left untouched. "
                   "This requires specifying existing paths for "
                   "every cloneable disk image."))
    stog.add_argument("--nvram", dest="new_nvram",
                      help=_("New file to use as storage for nvram VARS"))

    netg = parser.add_argument_group(_("Networking Configuration"))
    netg.add_argument("-m", "--mac", dest="new_mac", action="append",
                    help=_("New fixed MAC address for the clone guest. "
                           "Default is a randomly generated MAC"))

    misc = parser.add_argument_group(_("Miscellaneous Options"))

    # Just used for clone tests
    misc.add_argument("--__test-nodry", action="store_true", dest="test_nodry",
                      default=False, help=argparse.SUPPRESS)

    cli.add_misc_options(misc, prompt=True, replace=True, printxml=True)

    cli.autocomplete(parser)

    return parser.parse_args()


def main(conn=None):
    cli.earlyLogging()
    options = parse_args()

    options.quiet = options.quiet or options.xmlonly
    cli.setupLogging("virt-clone", options.debug, options.quiet)

    cli.convert_old_force(options)
    cli.parse_check(options.check)
    cli.set_prompt(options.prompt)
    conn = cli.getConnection(options.connect, conn=conn)

    if (options.new_diskfile is None and
        options.auto_clone is False):
        fail(_("Either --auto-clone or --file is required,"
               " use '--auto-clone or --file' and try again."))

    src_name, src_xml = _process_src(options)
    cloner = Cloner(conn, src_name, src_xml)

    cloner.set_replace(bool(options.replace))
    cloner.set_reflink(bool(options.reflink))
    cloner.set_sparse(bool(options.sparse))

    if options.new_uuid is not None:
        cloner.set_clone_uuid(options.new_uuid)
    if options.new_nvram:
        cloner.set_nvram_path(options.new_nvram)

    force_targets = options.target or []
    skip_targets = options.skip_copy or []
    for diskinfo in cloner.get_diskinfos():
        if diskinfo.disk.target in force_targets:
            diskinfo.set_clone_requested()
        if diskinfo.disk.target in skip_targets:
            diskinfo.set_share_requested()

    if options.preserve:
        for diskinfo in cloner.get_nonshare_diskinfos():
            diskinfo.set_preserve_requested()
        if cloner.nvram_diskinfo:
            cloner.nvram_diskinfo.set_preserve_requested()

    if options.new_name:
        cloner.set_clone_name(options.new_name)
    elif not options.auto_clone:
        fail(_("A name is required for the new virtual machine,"
            " use '--name NEW_VM_NAME' to specify one."))

    _process_macs(options, cloner)
    _process_disks(options, cloner)

    cloner.prepare()

    _validate_disks(cloner)

    run = True
    if options.xmlonly:
        run = options.test_nodry
        print_stdout(cloner.new_guest.get_xml(), do_force=True)
    if run:
        cloner.start_duplicate(cli.get_meter())
        print_stdout("")
        print_stdout(_("Clone '%s' created successfully.") % cloner.new_guest.name)

    return 0


def runcli():  # pragma: no cover
    try:
        sys.exit(main())
    except SystemExit as sys_e:
        sys.exit(sys_e.code)
    except KeyboardInterrupt:
        print_stderr(_("Installation aborted at user request"))
    except Exception as main_e:
        fail(main_e)
