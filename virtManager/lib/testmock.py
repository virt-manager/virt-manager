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


def schedule_fake_agent_event(conn, cb):
    import libvirt
    vmname = conn.config.CLITestOptions.fake_agent_event
    backend = conn.get_backend()
    state = libvirt.VIR_CONNECT_DOMAIN_EVENT_AGENT_LIFECYCLE_STATE_CONNECTED
    reason = libvirt.VIR_CONNECT_DOMAIN_EVENT_AGENT_LIFECYCLE_REASON_CHANNEL

    def time_cb():
        dom = backend.lookupByName(vmname)
        cb(backend, dom, state, reason, None)

    conn.timeout_add(500, time_cb)


def schedule_fake_nodedev_event(conn, lifecycle_cb, update_cb):
    import libvirt
    nodename = conn.config.CLITestOptions.fake_nodedev_event
    backend = conn.get_backend()

    def lifecycle_cb_wrapper():
        nodedev = backend.nodeDeviceLookupByName(nodename)
        state = libvirt.VIR_NODE_DEVICE_EVENT_CREATED
        reason = 0
        lifecycle_cb(backend, nodedev, state, reason, None)

    def update_cb_wrapper():
        nodedev = backend.nodeDeviceLookupByName(nodename)
        update_cb(backend, nodedev, None)

    conn.timeout_add(500, lifecycle_cb_wrapper)
    conn.timeout_add(1000, update_cb_wrapper)


def fake_openauth(conn, cb, data):
    ignore = conn
    import libvirt
    creds = [
        [libvirt.VIR_CRED_USERNAME, "Username", None, None, None],
        [libvirt.VIR_CRED_PASSPHRASE, "Password", None, None, None],
    ]
    cb(creds, data)
    assert all([bool(cred[4]) for cred in creds])


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
    * fake-no-libvirtd: If doing firstrun testing, fake that
        libvirtd is not installed
    * fake-vnc-username: Fake VNC username auth request
    * fake-console-resolution: Fake viewer console resolution response.
        Spice doesn't return values here when we are just testing
        against seabios in uitests, this fakes it to hit more code paths
    * fake-systray: Enable the fake systray window
    * object-denylist=NAME: Make object initialize for that name
        fail to test some connection code paths
    * conn-crash: Test connection abruptly closing like when
        libvirtd is restarted.
    * fake-agent-event: Fake a qemu guest agent API event
    * fake-nodedev-event: Fake nodedev API events
    * fake-openauth: Fake user+pass response from libvirt openauth,
        for testing the TCP URI auth dialog
    * fake-session-error: Fake a connection open error that
        triggers logind session lookup
    * short-poll: Use a polling interval of only .1 seconds to speed
        up the uitests a bit
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
        self.fake_no_libvirtd = _get("fake-no-libvirtd")
        self.fake_vnc_username = _get("fake-vnc-username")
        self.fake_console_resolution = _get("fake-console-resolution")
        self.fake_systray = _get("fake-systray")
        self.object_denylist = _get_value("object-denylist")
        self.conn_crash = _get("conn-crash")
        self.fake_agent_event = _get_value("fake-agent-event")
        self.fake_nodedev_event = _get_value("fake-nodedev-event")
        self.fake_openauth = _get("fake-openauth")
        self.fake_session_error = _get("fake-session-error")
        self.short_poll = _get("short-poll")

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
