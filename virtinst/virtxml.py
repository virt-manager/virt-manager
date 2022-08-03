# Copyright 2013-2014 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import os
import sys

import libvirt

from . import cli
from .cli import fail, fail_conflicting, print_stdout, print_stderr
from .devices import DeviceConsole
from .guest import Guest
from .logger import log
from . import xmlutil


###################
# Utility helpers #
###################

def prompt_yes_or_no(msg):
    while 1:
        printmsg = msg + " (y/n): "
        sys.stdout.write(printmsg)
        sys.stdout.flush()
        inp = sys.stdin.readline().lower().strip()

        if inp in ["y", "yes"]:
            return True
        elif inp in ["n", "no"]:
            return False
        else:
            print_stdout(_("Please enter 'yes' or 'no'."))


def get_diff(origxml, newxml):
    diff = xmlutil.diff(origxml, newxml, "Original XML", "Altered XML")

    if diff:
        log.debug("XML diff:\n%s", diff)
    else:
        log.debug("No XML diff, didn't generate any change.")
    return diff


def set_os_variant(options, guest):
    if options.os_variant is None:
        return

    osdata = cli.parse_os_variant(options.os_variant)
    if osdata.get_name():
        guest.set_os_name(osdata.get_name())


def defined_xml_is_unchanged(conn, domain, original_xml):
    rawxml = cli.get_xmldesc(domain, inactive=True)
    new_xml = Guest(conn, parsexml=rawxml).get_xml()
    return new_xml == original_xml


################
# Change logic #
################

def _find_objects_to_edit(guest, action_name, editval, parserclass):
    objlist = xmlutil.listify(parserclass.lookup_prop(guest))
    idx = None

    if editval is None:
        idx = 1
    elif (editval.isdigit() or
          editval.startswith("-") and editval[1:].isdigit()):
        idx = int(editval)

    if idx is not None:
        # Edit device by index
        if idx == 0:
            fail(_("Invalid --edit option '%s'") % editval)

        if not objlist:
            fail(_("No --%s objects found in the XML") %
                parserclass.cli_arg_name)
        if len(objlist) < abs(idx):
            fail(ngettext("'--edit %(number)s' requested but there's only "
                          "%(max)s --%(type)s object in the XML",
                          "'--edit %(number)s' requested but there are only "
                          "%(max)s --%(type)s objects in the XML",
                          len(objlist)) %
                {"number": idx, "max": len(objlist),
                 "type": parserclass.cli_arg_name})

        if idx > 0:
            idx -= 1
        inst = objlist[idx]

    elif editval == "all":
        # Edit 'all' devices
        inst = objlist[:]

    else:
        # Lookup device by the passed prop string
        parserobj = parserclass(editval, guest=guest)
        inst = parserobj.lookup_child_from_option_string()
        if not inst:
            fail(_("No matching objects found for %s") %
                 ("--%s %s" % (action_name, editval)))

    return inst


def check_action_collision(options):
    actions = ["edit", "add-device", "remove-device", "build-xml"]

    collisions = []
    for cliname in actions:
        optname = cliname.replace("-", "_")
        if getattr(options, optname) not in [False, -1]:
            collisions.append(cliname)

    if len(collisions) == 0:
        fail(_("One of %s must be specified.") %
             ", ".join(["--" + c for c in actions]))
    if len(collisions) > 1:
        fail(_("Conflicting options %s") %
             ", ".join(["--" + c for c in collisions]))


def check_xmlopt_collision(options):
    collisions = []
    for parserclass in cli.VIRT_PARSERS + [cli.ParserXML]:
        if getattr(options, parserclass.cli_arg_name):
            collisions.append(parserclass)

    if len(collisions) == 0:
        fail(_("No change specified."))
    if len(collisions) != 1:
        fail(_("Only one change operation may be specified "
               "(conflicting options %s)") %
               [c.cli_flag_name() for c in collisions])

    return collisions[0]


def action_edit(guest, options, parserclass):
    if parserclass.guest_propname:
        inst = _find_objects_to_edit(guest, "edit", options.edit, parserclass)
    else:
        inst = guest
        if options.edit and options.edit != '1' and options.edit != 'all':
            fail(_("'--edit %(option)s' doesn't make sense with "
                   "--%(objecttype)s, just use empty '--edit'") %
                 {"option": options.edit,
                  "objecttype": parserclass.cli_arg_name})
    if options.os_variant is not None:
        fail(_("--os-variant/--osinfo is not supported with --edit"))

    devs = []
    for editinst in xmlutil.listify(inst):
        devs += cli.run_parser(options, guest, parserclass, editinst=editinst)
    return devs


def action_add_device(guest, options, parserclass, devs):
    if not parserclass.prop_is_list(guest):
        fail(_("Cannot use --add-device with --%s") % parserclass.cli_arg_name)
    set_os_variant(options, guest)

    if devs:
        for dev in devs:
            guest.add_device(dev)
    else:
        devs = cli.run_parser(options, guest, parserclass)
        for dev in devs:
            dev.set_defaults(guest)

    return devs


def action_remove_device(guest, options, parserclass):
    if not parserclass.prop_is_list(guest):
        fail(_("Cannot use --remove-device with --%s") %
             parserclass.cli_arg_name)
    if options.os_variant is not None:
        fail(_("--os-variant/--osinfo is not supported with --remove-device"))

    devs = _find_objects_to_edit(guest, "remove-device",
        getattr(options, parserclass.cli_arg_name)[-1], parserclass)
    devs = xmlutil.listify(devs)

    # Check for console duplicate devices
    for dev in devs[:]:
        condup = DeviceConsole.get_console_duplicate(guest, dev)
        if condup:
            log.debug("Found duplicate console device:\n%s", condup.get_xml())
            devs.append(condup)

    for dev in devs:
        guest.remove_device(dev)
    return devs


def action_build_xml(options, parserclass, guest):
    if not parserclass.guest_propname:
        fail(_("--build-xml not supported for --%s") %
             parserclass.cli_arg_name)
    if options.os_variant is not None:
        fail(_("--os-variant/--osinfo is not supported with --build-xml"))

    devs = cli.run_parser(options, guest, parserclass)
    for dev in devs:
        dev.set_defaults(guest)
    return devs


def setup_device(dev):
    if getattr(dev, "DEVICE_TYPE", None) != "disk":
        return

    log.debug("Doing setup for disk=%s", dev)
    dev.build_storage(cli.get_meter())


def define_changes(conn, inactive_xmlobj, devs, action, confirm):
    if confirm:
        if not prompt_yes_or_no(
                _("Define '%s' with the changed XML?") % inactive_xmlobj.name):
            return False

    if action == "hotplug":
        for dev in devs:
            setup_device(dev)

    dom = conn.defineXML(inactive_xmlobj.get_xml())
    print_stdout(_("Domain '%s' defined successfully.") % inactive_xmlobj.name)
    return dom


def start_domain_transient(conn, xmlobj, devs, action, confirm):
    if confirm:
        if not prompt_yes_or_no(
                _("Start '%s' with the changed XML?") % xmlobj.name):
            return False

    if action == "hotplug":
        for dev in devs:
            setup_device(dev)

    try:
        dom = conn.createXML(xmlobj.get_xml())
    except libvirt.libvirtError as e:
        fail(_("Failed starting domain '%(domain)s': %(error)s") % {
                 "domain": xmlobj.name,
                 "error": e,
             })
    else:
        print_stdout(_("Domain '%s' started successfully.") % xmlobj.name)
        return dom


def update_changes(domain, devs, action, confirm):
    if action == "hotplug":
        msg_confirm = _("%(xml)s\n\nHotplug this device to the guest "
                        "'%(domain)s'?")
        msg_success = _("Device hotplug successful.")
        msg_fail = _("Error attempting device hotplug: %(error)s")
    elif action == "hotunplug":
        msg_confirm = _("%(xml)s\n\nHotunplug this device from the guest "
                        "'%(domain)s'?")
        msg_success = _("Device hotunplug successful.")
        msg_fail = _("Error attempting device hotunplug: %(error)s")
    elif action == "update":
        msg_confirm = _("%(xml)s\n\nUpdate this device for the guest "
                        "'%(domain)s'?")
        msg_success = _("Device update successful.")
        msg_fail = _("Error attempting device update: %(error)s")

    for dev in devs:
        xml = dev.get_xml()

        if confirm:
            msg = msg_confirm % {
                "xml": xml,
                "domain": domain.name(),
            }
            if not prompt_yes_or_no(msg):
                continue

        if action == "hotplug":
            setup_device(dev)

        try:
            if action == "hotplug":
                domain.attachDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
            elif action == "hotunplug":
                domain.detachDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
            elif action == "update":
                domain.updateDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
        except libvirt.libvirtError as e:
            if "VIRTXML_TESTSUITE_UPDATE_IGNORE_FAIL" not in os.environ:
                fail(msg_fail % {"error": e})

        print_stdout(msg_success)
        if confirm:
            print_stdout("")


def prepare_changes(orig_xmlobj, options, parserclass, devs=None):
    """
    Parse the command line device/XML arguments, and apply the changes to
    a copy of the passed in xmlobj.

    :returns: (list of device objects, action string, altered xmlobj)
    """
    origxml = orig_xmlobj.get_xml()
    xmlobj = orig_xmlobj.__class__(conn=orig_xmlobj.conn, parsexml=origxml)
    has_edit = options.edit != -1
    is_xmlcli = parserclass is cli.ParserXML

    if is_xmlcli and not has_edit:
        fail(_("--xml can only be used with --edit"))

    if has_edit:
        if is_xmlcli:
            devs = []
            cli.parse_xmlcli(xmlobj, options)
        else:
            devs = action_edit(xmlobj, options, parserclass)
        action = "update"

    elif options.add_device:
        devs = action_add_device(xmlobj, options, parserclass, devs)
        action = "hotplug"

    elif options.remove_device:
        devs = action_remove_device(xmlobj, options, parserclass)
        action = "hotunplug"

    newxml = xmlobj.get_xml()
    diff = get_diff(origxml, newxml)

    if not diff:
        log.warning(_("No XML diff was generated. The requested "
            "changes will have no effect."))

    if options.print_diff:
        if diff:
            print_stdout(diff)
    elif options.print_xml:
        print_stdout(newxml)

    return devs, action, xmlobj


#######################
# CLI option handling #
#######################

def parse_args():
    parser = cli.setupParser(
        "%(prog)s [options]",
        _("Edit libvirt XML using command line options."),
        introspection_epilog=True)

    cli.add_connect_option(parser, "virt-xml")

    parser.add_argument("domain", nargs='?',
        help=_("Domain name, id, or uuid"))

    actg = parser.add_argument_group(_("XML actions"))
    actg.add_argument("--edit", nargs='?', default=-1,
        help=_("Edit VM XML. Examples:\n"
        "--edit --disk ...     (edit first disk device)\n"
        "--edit 2 --disk ...   (edit second disk device)\n"
        "--edit all --disk ... (edit all disk devices)\n"
        "--edit target=hda --disk ... (edit disk 'hda')\n"))
    actg.add_argument("--remove-device", action="store_true",
        help=_("Remove specified device. Examples:\n"
        "--remove-device --disk 1 (remove first disk)\n"
        "--remove-device --disk all (remove all disks)\n"
        "--remove-device --disk /some/path"))
    actg.add_argument("--add-device", action="store_true",
        help=_("Add specified device. Example:\n"
        "--add-device --disk ..."))
    actg.add_argument("--build-xml", action="store_true",
        help=_("Output built device XML. Domain is optional but "
               "recommended to ensure optimal defaults."))

    outg = parser.add_argument_group(_("Output options"))
    outg.add_argument("--update", action="store_true",
        help=_("Apply changes to the running VM.\n"
               "With --add-device, this is a hotplug operation.\n"
               "With --remove-device, this is a hotunplug operation.\n"
               "With --edit, this is an update device operation."))
    define_g = outg.add_mutually_exclusive_group()
    define_g.add_argument("--define", action="store_true",
                          help=_("Force defining the domain. Only required if a --print "
                                 "option was specified."))
    define_g.add_argument("--no-define", dest='define', action="store_false",
                          help=_("Force not defining the domain."))
    define_g.set_defaults(define=None)
    outg.add_argument("--start", action="store_true",
                      help=_("Start the domain."))
    outg.add_argument("--print-diff", action="store_true",
        help=_("Only print the requested change, in diff format"))
    outg.add_argument("--print-xml", action="store_true",
        help=_("Only print the requested change, in full XML format"))
    outg.add_argument("--confirm", action="store_true",
        help=_("Require confirmation before saving any results."))

    cli.add_os_variant_option(parser, virtinstall=False)

    g = parser.add_argument_group(_("XML options"))
    cli.add_disk_option(g, editexample=True)
    cli.add_net_option(g)
    cli.add_gfx_option(g)
    cli.add_metadata_option(g)
    cli.add_memory_option(g)
    cli.vcpu_cli_options(g, editexample=True)
    cli.add_xml_option(g)
    cli.add_guest_xml_options(g)
    cli.add_boot_options(g)
    cli.add_device_options(g)

    misc = parser.add_argument_group(_("Miscellaneous Options"))
    cli.add_misc_options(misc, prompt=False, printxml=False, dryrun=False)

    cli.autocomplete(parser)

    return parser.parse_args()


###################
# main() handling #
###################

def main(conn=None):
    cli.earlyLogging()
    options = parse_args()

    if (options.confirm or options.print_xml or
        options.print_diff or options.build_xml):
        options.quiet = False
    cli.setupLogging("virt-xml", options.debug, options.quiet)

    if cli.check_option_introspection(options):
        return 0
    if cli.check_osinfo_list(options):
        return 0

    options.stdinxml = None
    if not options.domain and not options.build_xml:
        if not sys.stdin.closed and not sys.stdin.isatty():
            if options.confirm:
                fail(_("Can't use --confirm with stdin input."))
            if options.update:
                fail(_("Can't use --update with stdin input."))
            options.stdinxml = sys.stdin.read()
        else:
            fail(_("A domain must be specified"))

    # Default to --define, unless:
    #  --no-define explicitly specified
    #  --print-* option is used
    #  XML input came from stdin
    if not options.print_xml and not options.print_diff:
        if options.stdinxml:
            if not options.define:
                options.print_xml = True
        else:
            if options.define is None:
                options.define = True
    if options.confirm and not options.print_xml:
        options.print_diff = True

    # Ensure only one of these actions wash specified
    #   --edit
    #   --remove-device
    #   --add-device
    #   --build-xml
    check_action_collision(options)

    # Ensure there wasn't more than one device/xml config option
    # specified. So reject '--disk X --network X'
    parserclass = check_xmlopt_collision(options)

    if options.update and not parserclass.guest_propname:
        fail(_("Don't know how to --update for --%s") %
             (parserclass.cli_arg_name))

    conn = cli.getConnection(options.connect, conn)

    domain = None
    active_xmlobj = None
    inactive_xmlobj = None
    if options.domain:
        domain, inactive_xmlobj, active_xmlobj = cli.get_domain_and_guest(
            conn, options.domain)
    else:
        inactive_xmlobj = Guest(conn, parsexml=options.stdinxml)
    vm_is_running = bool(active_xmlobj)

    if options.build_xml:
        devs = action_build_xml(options, parserclass, inactive_xmlobj)
        for dev in devs:
            # pylint: disable=no-member
            print_stdout(xmlutil.unindent_device_xml(dev.get_xml()))
        return 0

    devs = None
    performed_update = False
    if options.update:
        if options.update and options.start:
            fail_conflicting("--update", "--start")
        if vm_is_running:
            devs, action, dummy = prepare_changes(
                    active_xmlobj, options, parserclass)
            update_changes(domain, devs, action, options.confirm)
            performed_update = True
        else:
            log.warning(
                _("The VM is not running, --update is inapplicable."))
        if not options.define:
            # --update and --no-define passed, so we are done
            return 0

    original_xml = inactive_xmlobj.get_xml()
    devs, action, xmlobj_to_define = prepare_changes(
            inactive_xmlobj, options, parserclass, devs=devs)
    if not options.define:
        if options.start:
            start_domain_transient(conn, xmlobj_to_define, devs,
                                   action, options.confirm)
        return 0

    dom = define_changes(conn, xmlobj_to_define,
                         devs, action, options.confirm)
    if not dom:
        # --confirm user said 'no'
        return 0

    if options.start:
        try:
            dom.create()
        except libvirt.libvirtError as e:  # pragma: no cover
            fail(_("Failed starting domain '%(domain)s': %(error)s") % {
                     "domain": inactive_xmlobj.name,
                     "error": e,
                 })
        print_stdout(_("Domain '%s' started successfully.") %
                     inactive_xmlobj.name)

    elif vm_is_running and not performed_update:
        print_stdout(
            _("Changes will take effect after the domain is fully powered off."))
    elif defined_xml_is_unchanged(conn, domain, original_xml):
        log.warning(_("XML did not change after domain define. You may "
            "have changed a value that libvirt is setting by default."))

    return 0


def runcli():  # pragma: no cover
    try:
        sys.exit(main())
    except SystemExit as sys_e:
        sys.exit(sys_e.code)
    except KeyboardInterrupt:
        log.debug("", exc_info=True)
        print_stderr(_("Aborted at user request"))
    except Exception as main_e:
        fail(main_e)
