# Copyright (C) 2020 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

# This file is a collection of code used for testing
# code paths primarily via our uitests/

import os


def fake_job_info():
    import random
    total = 1024 * 1024 * 1024
    fakepcent = random.choice(range(1, 100))
    remaining = ((total / 100) * fakepcent)
    return [None, None, None, total, None, remaining]


def fake_interface_addresses(iface, source):
    import libvirt
    mac = iface.macaddr
    if source == libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_AGENT:
        ret = {
            'enp1s0': {'hwaddr': mac, 'addrs': [
                {'addr': '10.0.0.1', 'prefix': 24, 'type': 0},
                {'addr': 'fd00:beef::1', 'prefix': 128, 'type': 1},
                {'addr': 'fe80::1', 'prefix': 64, 'type': 1}],
            },
            'lo': {'hwaddr': '00:00:00:00:00:00', 'addrs': [
                {'addr': '127.0.0.1', 'prefix': 8, 'type': 0},
                {'addr': '::1', 'prefix': 128, 'type': 1}],
            },
        }
    else:
        ret = {'vnet0': {'hwaddr': mac, 'addrs': [
            {'addr': '10.0.0.3', 'prefix': 0, 'type': 0}],
        }}
    return ret


def fake_dhcp_leases():
    ret = [{
        'clientid': 'XXX',
        'expirytime': 1598570993,
        'hostname': None,
        'iaid': '1448103320',
        'iface': 'virbr1',
        'ipaddr': 'fd00:beef::2',
        'mac': 'BAD',
        'prefix': 64,
        'type': 1}, {
        'clientid': 'YYY',
        'expirytime': 1598570993,
        'hostname': None,
        'iaid': None,
        'iface': 'virbr1',
        'ipaddr': '10.0.0.2',
        'mac': 'NOPE',
        'prefix': 24,
        'type': 0}]
    return ret


class CLITestOptionsClass:
    """
    Helper class for parsing and tracking --test-* options.
    The suboptions are:

    * first-run: Run the app with fresh gsettings values saved to
        a keyfile, mimicking a first app run. Also sets
        GSETTINGS to use memory backend, in case any other app
        preferences would be affected. The ui testsuite sets this
        for most tests.

    * xmleditor-enabled: Force the xmleditor gsettings preference on.

    * gsettings-keyfile: Override the gsettings values with those
        from the passed in keyfile, to test with different default
        settings.

    * leak-debug: Enabling this will tell us, at app exit time,
        which vmmGObjects were not garbage collected. This is caused
        by circular references to other objects, like a signal that
        wasn't disconnected. It's not a big deal, but if we have objects
        that can be created and destroyed a lot over the course of
        the app lifecycle, every non-garbage collected class is a
        memory leak. So it's nice to poke at this every now and then
        and try to track down what we need to add to class _cleanup handling.

    * no-events: Force disable libvirt event APIs for testing fallback

    * break_setfacl: For setfacl calls to fail, for test scenarios.
        This is hit via the directory search permissions checking
        for disk image usage for qemu

    * enable-libguestfs: Force enable the libguestfs gsetting
    * disable-libguestfs: Force disable the libguestfs gsetting

    * test-managed-save: Triggers a couple conditions for testing
        managed save issues

    * test-vm-run-fail: Make VM run fail, so we can test the error path

    * spice-agent: Make spice-agent detection return true in viewer.py

    * firstrun-uri: If set, use this as the initial connection URI
        if we are doing firstrun testing
    * fake-systemd-success: If doing firstrun testing, fake that
        systemd checks for libvirtd succeeded
    * fake-vnc-username: Fake VNC username auth request
    * fake-console-resolution: Fake viewer console resolution response.
        Spice doesn't return values here when we are just testing
        against seabios in uitests, this fakes it to hit more code paths
    * fake-systray: Enable the fake systray window
    * object-blacklist=NAME: Make object initialize for that name
        fail to test some connection code paths
    * conn-crash: Test connection abruptly closing like when
        libvirtd is restarted.
    """
    def __init__(self, test_options_str):
        optset = set()
        for optstr in test_options_str:
            optset.update(set(optstr.split(",")))

        first_run = self._parse(optset)
        self._process(first_run)

    def _parse(self, optset):
        def _get(optname):
            if optname not in optset:
                return False
            optset.remove(optname)
            return True

        def _get_value(optname):
            for opt in optset:
                if opt.startswith(optname + "="):
                    optset.remove(opt)
                    return opt.split("=", 1)[1]

        first_run = _get("first-run")
        self.leak_debug = _get("leak-debug")
        self.no_events = _get("no-events")
        self.xmleditor_enabled = _get("xmleditor-enabled")
        self.gsettings_keyfile = _get_value("gsettings-keyfile")
        self.break_setfacl = _get("break-setfacl")
        self.disable_libguestfs = _get("disable-libguestfs")
        self.enable_libguestfs = _get("enable-libguestfs")
        self.test_managed_save = _get("test-managed-save")
        self.test_vm_run_fail = _get("test-vm-run-fail")
        self.spice_agent = _get("spice-agent")
        self.firstrun_uri = _get_value("firstrun-uri")
        self.fake_systemd_success = _get("fake-systemd-success")
        self.fake_vnc_username = _get("fake-vnc-username")
        self.fake_console_resolution = _get("fake-console-resolution")
        self.fake_systray = _get("fake-systray")
        self.object_blacklist = _get_value("object-blacklist")
        self.conn_crash = _get("conn-crash")

        if optset:  # pragma: no cover
            raise RuntimeError("Unknown --test-options keys: %s" % optset)

        return first_run

    def _process(self, first_run):
        if first_run:
            # So other settings like gtk are reset and not affected
            os.environ["GSETTINGS_BACKEND"] = "memory"

        if first_run and not self.gsettings_keyfile:
            import atexit
            import tempfile
            filename = tempfile.mktemp(prefix="virtmanager-firstrun-keyfile")
            self.gsettings_keyfile = filename
            atexit.register(lambda: os.unlink(filename))

        if self.break_setfacl:
            import virtinst.diskbackend
            def fake_search(*args, **kwargs):
                raise RuntimeError("Fake search fix fail from test suite")
            virtinst.diskbackend.SETFACL = "getfacl"
            # pylint: disable=protected-access
            virtinst.diskbackend._fix_perms_chmod = fake_search
