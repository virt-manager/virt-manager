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

import gobject
import libvirt
import logging
import os, sys
import glob
import traceback
from time import time
import logging
from socket import gethostbyaddr, gethostname
import dbus
import threading
import gtk
import string
import virtinst

from virtManager.domain import vmmDomain
from virtManager.network import vmmNetwork
from virtManager.netdev import vmmNetDevice
from virtManager.storagepool import vmmStoragePool

LIBVIRT_POLICY_FILES = [
    "/usr/share/PolicyKit/policy/libvirtd.policy",
    "/usr/share/PolicyKit/policy/org.libvirt.unix.policy"
]

def get_local_hostname():
    try:
        (host, aliases, ipaddrs) = gethostbyaddr(gethostname())
        return host
    except:
        logging.warning("Unable to resolve local hostname for machine")
        return "localhost"

# Standard python urlparse is utterly braindead - refusing to parse URIs
# in any useful fashion unless the 'scheme' is in some pre-defined white
# list. Theis functions is a hacked version of urlparse

def uri_split(uri):
    username = netloc = query = fragment = ''
    i = uri.find(":")
    if i > 0:
        scheme, uri = uri[:i].lower(), uri[i+1:]
        if uri[:2] == '//':
            netloc, uri = _splitnetloc(uri, 2)
            offset = netloc.find("@")
            if offset > 0:
                username = netloc[0:offset]
                netloc = netloc[offset+1:]
        if '#' in uri:
            uri, fragment = uri.split('#', 1)
        if '?' in uri:
            uri, query = uri.split('?', 1)
    else:
        scheme = uri.lower()

    return scheme, username, netloc, uri, query, fragment

def _splitnetloc(url, start=0):
    for c in '/?#': # the order is important!
        delim = url.find(c, start)
        if delim >= 0:
            break
    else:
        delim = len(url)
    return url[start:delim], url[delim:]


class vmmConnection(gobject.GObject):
    __gsignals__ = {
        "vm-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                     [str, str]),
        "vm-started": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                     [str, str]),
        "vm-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                       [str, str]),
        "net-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                      [str, str]),
        "net-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                        [str, str]),
        "net-started": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                        [str, str]),
        "net-stopped": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                        [str, str]),
        "pool-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                       [str, str]),
        "pool-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                         [str, str]),
        "pool-started": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                         [str, str]),
        "pool-stopped": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                         [str, str]),
        "netdev-added": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                         [str]),
        "netdev-removed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                           [str]),
        "resources-sampled": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                              []),
        "state-changed": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                          []),
        "connect-error": (gobject.SIGNAL_RUN_FIRST, gobject.TYPE_NONE,
                          [str]),
        }

    STATE_DISCONNECTED = 0
    STATE_CONNECTING = 1
    STATE_ACTIVE = 2
    STATE_INACTIVE = 3

    def __init__(self, config, uri, readOnly = None):
        self.__gobject_init__()
        self.config = config

        self.connectThread = None
        self.connectThreadEvent = threading.Event()
        self.connectThreadEvent.set()
        self.connectError = None
        self.uri = uri
        if self.uri is None or self.uri.lower() == "xen":
            self.uri = "xen:///"

        self.readOnly = readOnly
        if not self.is_remote() and os.getuid() != 0 and self.uri != "qemu:///session":
            hasPolkit = False
            for f in LIBVIRT_POLICY_FILES:
                if os.path.exists(f):
                    hasPolkit = True

            if not hasPolkit:
                self.readOnly = True

        self.state = self.STATE_DISCONNECTED
        self.vmm = None

        # Connection Storage pools: UUID -> vmmStoragePool
        self.pools = {}
        # Host network devices. name -> vmmNetDevice object
        self.netdevs = {}
        # Virtual networks UUUID -> vmmNetwork object
        self.nets = {}
        # Virtual machines. UUID -> vmmDomain object
        self.vms = {}
        # Running virtual machines. UUID -> vmmDomain object
        self.activeUUIDs = []
        # Resource utilization statistics
        self.record = []
        self.hostinfo = None
        self.autoconnect = self.config.get_conn_autoconnect(self.get_uri())

        # Probe for network devices
        try:
            # Get a connection to the SYSTEM bus
            self.bus = dbus.SystemBus()
            # Get a handle to the HAL service
            hal_object = self.bus.get_object('org.freedesktop.Hal', '/org/freedesktop/Hal/Manager')
            self.hal_iface = dbus.Interface(hal_object, 'org.freedesktop.Hal.Manager')

            # Track device add/removes so we can detect newly inserted CD media
            self.hal_iface.connect_to_signal("DeviceAdded", self._net_phys_device_added)
            self.hal_iface.connect_to_signal("DeviceRemoved", self._net_phys_device_removed)

            # find all bonding master devices and register them
            # XXX bonding stuff is linux specific
            bondMasters = self._net_get_bonding_masters()
            logging.debug("Bonding masters are: %s" % bondMasters)
            for bond in bondMasters:
                sysfspath = "/sys/class/net/" + bond
                mac = self._net_get_mac_address(bond, sysfspath)
                if mac:
                    self._net_device_added(bond, mac, sysfspath)
                    # Add any associated VLANs
                    self._net_tag_device_added(bond, sysfspath)

            # Find info about all current present physical net devices
            # This is OS portable...
            for path in self.hal_iface.FindDeviceByCapability("net"):
                self._net_phys_device_added(path)
        except:
            (type, value, stacktrace) = sys.exc_info ()
            logging.error("Unable to connect to HAL to list network devices: '%s'" + \
                          str(type) + " " + str(value) + "\n" + \
                          traceback.format_exc (stacktrace))
            self.bus = None
            self.hal_iface = None

    def _net_phys_device_added(self, path):
        logging.debug("Got physical device %s" % path)
        obj = self.bus.get_object("org.freedesktop.Hal", path)
        objif = dbus.Interface(obj, "org.freedesktop.Hal.Device")
        if objif.QueryCapability("net"):
            name = objif.GetPropertyString("net.interface")
            # XXX ...but this is Linux specific again - patches welcomed
            #sysfspath = objif.GetPropertyString("linux.sysfs_path")
            # XXX hal gives back paths to /sys/devices/pci0000:00/0000:00:1e.0/0000:01:00.0/net/eth0
            # which doesnt' work so well - we want this:
            sysfspath = "/sys/class/net/" + name

            # If running a device in bridged mode, there's a reasonable
            # chance that the actual ethernet device has been renamed to
            # something else. ethN -> pethN
            psysfspath = sysfspath[0:len(sysfspath)-len(name)] + "p" + name
            if os.path.exists(psysfspath):
                logging.debug("Device %s named to p%s" % (name, name))
                name = "p" + name
                sysfspath = psysfspath

            # Ignore devices that are slaves of a bond
            if self._net_is_bonding_slave(name, sysfspath):
                logging.debug("Skipping device %s in bonding slave" % name)
                return

            mac = objif.GetPropertyString("net.address")

            # Add the main NIC
            self._net_device_added(name, mac, sysfspath)

            # Add any associated VLANs
            self._net_tag_device_added(name, sysfspath)

    def _net_tag_device_added(self, name, sysfspath):
        logging.debug("Checking for VLANs on %s" % sysfspath)
        for vlanpath in glob.glob(sysfspath + ".*"):
            if os.path.exists(vlanpath):
                logging.debug("Process VLAN %s" % vlanpath)
                vlanmac = self._net_get_mac_address(name, vlanpath)
                if vlanmac:
                    (ignore,vlanname) = os.path.split(vlanpath)

                    # If running a device in bridged mode, there's areasonable
                    # chance that the actual ethernet device has beenrenamed to
                    # something else. ethN -> pethN
                    pvlanpath = vlanpath[0:len(vlanpath)-len(vlanname)] + "p" + vlanname
                    if os.path.exists(pvlanpath):
                        logging.debug("Device %s named to p%s" % (vlanname, vlanname))
                        vlanname = "p" + vlanname
                        vlanpath = pvlanpath
                    self._net_device_added(vlanname, vlanmac, vlanpath)

    def _net_device_added(self, name, mac, sysfspath):
        # Race conditions mean we can occassionally see device twice
        if self.netdevs.has_key(name):
            return

        bridge = self._net_get_bridge_owner(name, sysfspath)
        shared = False
        if bridge is not None:
            shared = True

        logging.debug("Adding net device %s %s %s (bridge: %s)" % (name, mac, sysfspath, str(bridge)))

        dev = vmmNetDevice(self.config, self, name, mac, shared, bridge)
        self.netdevs[name] = dev
        self.emit("netdev-added", dev.get_name())

    def _net_phys_device_removed(self, path):
        obj = self.bus.get_object("org.freedesktop.Hal", path)
        objif = dbus.Interface(obj, "org.freedesktop.Hal.Device")
        if objif.QueryCapability("net"):
            name = objif.GetPropertyString("net.interface")

            if self.netdevs.has_key(name):
                logging.debug("Removing physical net device %s from list." % name)
                dev = self.netdevs[name]
                self.emit("netdev-removed", dev.get_name())
                del self.netdevs[name]

    def is_read_only(self):
        return self.readOnly

    def get_type(self):
        if self.vmm is None:
            return None
        return self.vmm.getType()

    def get_short_hostname(self):
        hostname = self.get_hostname()
        offset = hostname.find(".")
        if offset > 0 and not hostname[0].isdigit():
            return hostname[0:offset]
        return hostname

    def get_hostname(self, resolveLocal=False):
        try:
            (scheme, username, netloc, path, query, fragment) = uri_split(self.uri)

            if netloc != "":
                return netloc
        except Exception, e:
            logging.warning("Cannot parse URI %s: %s" % (self.uri, str(e)))

        if resolveLocal:
            return get_local_hostname()
        return "localhost"

    def get_transport(self):
        try:
            (scheme, username, netloc, path, query, fragment) = uri_split(self.uri)
            if scheme:
                offset = scheme.index("+")
                if offset > 0:
                    return [scheme[offset+1:], username]
        except:
            pass
        return [None, None]

    def get_driver(self):
        try:
            (scheme, username, netloc, path, query, fragment) = uri_split(self.uri)
            if scheme:
                offset = scheme.find("+")
                if offset > 0:
                    return scheme[:offset]
                return scheme
        except Exception, e:
            pass
        return "xen"

    def get_capabilities(self):
        return virtinst.CapabilitiesParser.parse(self.vmm.getCapabilities())

    def is_remote(self):
        try:
            (scheme, username, netloc, path, query, fragment) = uri_split(self.uri)
            if netloc == "":
                return False
            return True
        except:
            return True

    def get_uri(self):
        return self.uri

    def get_vm(self, uuid):
        return self.vms[uuid]

    def get_net(self, uuid):
        return self.nets[uuid]

    def get_net_device(self, path):
        return self.netdevs[path]

    def get_pool(self, uuid):
        return self.pools[uuid]

    def open(self):
        if self.state != self.STATE_DISCONNECTED:
            return

        self.state = self.STATE_CONNECTING
        self.emit("state-changed")

        logging.debug("Scheduling background open thread for " + self.uri)
        self.connectThreadEvent.clear()
        self.connectThread = threading.Thread(target = self._open_thread, name="Connect " + self.uri)
        self.connectThread.setDaemon(True)
        self.connectThread.start()

    def _do_creds_polkit(self, action):
        logging.debug("Doing policykit for %s" % action)
        bus = dbus.SessionBus()

        try:
            # First try to use org.freedesktop.PolicyKit.AuthenticationAgent
            # which is introduced with PolicyKit-0.7
            obj = bus.get_object("org.freedesktop.PolicyKit.AuthenticationAgent", "/")
            pkit = dbus.Interface(obj, "org.freedesktop.PolicyKit.AuthenticationAgent")
            pkit.ObtainAuthorization(action, 0, os.getpid())
        except dbus.exceptions.DBusException, e:
            if e.get_dbus_name() != "org.freedesktop.DBus.Error.ServiceUnknown":
                raise e
            logging.debug("Falling back to org.gnome.PolicyKit")
            # If PolicyKit < 0.7, fallback to org.gnome.PolicyKit
            obj = bus.get_object("org.gnome.PolicyKit", "/org/gnome/PolicyKit/Manager")
            pkit = dbus.Interface(obj, "org.gnome.PolicyKit.Manager")
            pkit.ShowDialog(action, 0)
        return 0

    def _do_creds_dialog(self, creds):
        try:
            gtk.gdk.threads_enter()
            return self._do_creds_dialog_main(creds)
        finally:
            gtk.gdk.threads_leave()

    def _do_creds_dialog_main(self, creds):
        dialog = gtk.Dialog("Authentication required", None, 0, (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL, gtk.STOCK_OK, gtk.RESPONSE_OK))
        label = []
        entry = []

        box = gtk.Table(2, len(creds))

        row = 0
        for cred in creds:
            if cred[0] == libvirt.VIR_CRED_AUTHNAME or cred[0] == libvirt.VIR_CRED_PASSPHRASE:
                label.append(gtk.Label(cred[1]))
            else:
                return -1

            ent = gtk.Entry()
            if cred[0] == libvirt.VIR_CRED_PASSPHRASE:
                ent.set_visibility(False)
            entry.append(ent)

            box.attach(label[row], 0, 1, row, row+1, 0, 0, 3, 3)
            box.attach(entry[row], 1, 2, row, row+1, 0, 0, 3, 3)
            row = row + 1

        vbox = dialog.get_child()
        vbox.add(box)

        dialog.show_all()
        res = dialog.run()
        dialog.hide()

        if res == gtk.RESPONSE_OK:
            row = 0
            for cred in creds:
                cred[4] = entry[row].get_text()
                row = row + 1
            dialog.destroy()
            return 0
        else:
            dialog.destroy()
            return -1

    def _do_creds(self, creds, cbdata):
        try:
            if len(creds) == 1 and creds[0][0] == libvirt.VIR_CRED_EXTERNAL and creds[0][2] == "PolicyKit":
                return self._do_creds_polkit(creds[0][1])

            for cred in creds:
                if cred[0] == libvirt.VIR_CRED_EXTERNAL:
                    return -1

            return self._do_creds_dialog(creds)
        except:
            (type, value, stacktrace) = sys.exc_info ()
            # Detailed error message, in English so it can be Googled.
            self.connectError = \
                ("Failed to get credentials '%s':\n" %
                 str(self.uri)) + \
                 str(type) + " " + str(value) + "\n" + \
                 traceback.format_exc (stacktrace)
            logging.error(self.connectError)
            return -1

    def _open_thread(self):
        logging.debug("Background thread is running")
        try:
            flags = 0
            if self.readOnly:
                logging.info("Caller requested read only connection")
                flags = libvirt.VIR_CONNECT_RO

            self.vmm = libvirt.openAuth(self.uri,
                                        [[libvirt.VIR_CRED_AUTHNAME,
                                          libvirt.VIR_CRED_PASSPHRASE,
                                          libvirt.VIR_CRED_EXTERNAL],
                                         self._do_creds,
                                         None], flags)

            self.state = self.STATE_ACTIVE
        except:
            self.state = self.STATE_DISCONNECTED

            (type, value, stacktrace) = sys.exc_info ()
            # Detailed error message, in English so it can be Googled.
            self.connectError = \
                    ("Unable to open connection to hypervisor URI '%s':\n" %
                     str(self.uri)) + \
                    str(type) + " " + str(value) + "\n" + \
                    traceback.format_exc (stacktrace)
            logging.error(self.connectError)

        # We want to kill off this thread asap, so schedule a gobject
        # idle even to inform the UI of result
        logging.debug("Background open thread complete, scheduling notify")
        gtk.gdk.threads_enter()
        try:
            gobject.idle_add(self._open_notify)
        finally:
            gtk.gdk.threads_leave()
        self.connectThread = None

    def _open_notify(self):
        logging.debug("Notifying open result")
        gtk.gdk.threads_enter()
        try:
            if self.state == self.STATE_ACTIVE:
                self.tick()
            self.emit("state-changed")

            if self.state == self.STATE_DISCONNECTED:
                self.emit("connect-error", self.connectError)
                self.connectError = None
        finally:
            self.connectThreadEvent.set()
            gtk.gdk.threads_leave()


    def pause(self):
        if self.state != self.STATE_ACTIVE:
            return
        self.state = self.STATE_INACTIVE
        self.emit("state-changed")

    def resume(self):
        if self.state != self.STATE_INACTIVE:
            return
        self.state = self.STATE_ACTIVE
        self.emit("state-changed")

    def close(self):
        if self.vmm == None:
            return

        #self.vmm.close()
        self.vmm = None
        self.nets = {}
        self.pools = {}
        self.vms = {}
        self.activeUUIDs = []
        self.record = []
        self.state = self.STATE_DISCONNECTED
        self.emit("state-changed")

    def list_vm_uuids(self):
        return self.vms.keys()

    def list_net_uuids(self):
        return self.nets.keys()

    def list_net_device_paths(self):
        return self.netdevs.keys()

    def list_pool_uuids(self):
        return self.pools.keys()

    def get_host_info(self):
        return self.hostinfo

    def get_max_vcpus(self, type=None):
        return virtinst.util.get_max_vcpus(self.vmm, type)

    def get_autoconnect(self):
        # Use a local variable to cache autoconnect so we don't repeatedly
        # have to poll gconf
        return self.autoconnect

    def toggle_autoconnect(self):
        if self.is_remote():
            return
        self.config.toggle_conn_autoconnect(self.get_uri())
        self.autoconnect = (not self.autoconnect)

    def connect(self, name, callback):
        handle_id = gobject.GObject.connect(self, name, callback)

        if name == "vm-added":
            for uuid in self.vms.keys():
                self.emit("vm-added", self.uri, uuid)

        return handle_id

    def pretty_host_memory_size(self):
        if self.vmm is None:
            return ""
        mem = self.host_memory_size()
        if mem > (1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.2f MB" % (mem/1024.0)


    def host_memory_size(self):
        if self.vmm is None:
            return 0
        return self.hostinfo[1]*1024

    def host_architecture(self):
        if self.vmm is None:
            return ""
        return self.hostinfo[0]

    def host_active_processor_count(self):
        if self.vmm is None:
            return 0
        return self.hostinfo[2]

    def host_maximum_processor_count(self):
        if self.vmm is None:
            return 0
        return self.hostinfo[4] * self.hostinfo[5] * self.hostinfo[6] * self.hostinfo[7]

    def create_network(self, xml, start=True, autostart=True):
        net = self.vmm.networkDefineXML(xml)
        uuid = self.uuidstr(net.UUID())
        self.nets[uuid] = vmmNetwork(self.config, self, net, uuid, False)
        self.nets[uuid].start()
        self.nets[uuid].set_active(True)
        self.nets[uuid].set_autostart(True)
        self.emit("net-added", self.uri, uuid)
        self.emit("net-started", self.uri, uuid)
        return self.nets[uuid]

    def define_domain(self, xml):
        self.vmm.defineXML(xml)

    def restore(self, frm):
        status = self.vmm.restore(frm)
        if(status == 0):
            os.remove(frm)
        return status

    def _update_nets(self):
        """Return lists of start/stopped/new networks"""

        origNets = self.nets
        currentNets = {}
        startNets = []
        stopNets = []
        newNets = []
        newActiveNetNames = []
        newInactiveNetNames = []
        try:
            newActiveNetNames = self.vmm.listNetworks()
        except:
            logging.warn("Unable to list active networks")
        try:
            newInactiveNetNames = self.vmm.listDefinedNetworks()
        except:
            logging.warn("Unable to list inactive networks")

        for name in newActiveNetNames:
            try:
                net = self.vmm.networkLookupByName(name)
                uuid = self.uuidstr(net.UUID())
                if not origNets.has_key(uuid):
                    # Brand new network
                    currentNets[uuid] = vmmNetwork(self.config, self, net,
                                                   uuid, True)
                    newNets.append(uuid)
                    startNets.append(uuid)
                else:
                    # Already present network, see if it changed state
                    currentNets[uuid] = origNets[uuid]
                    if not currentNets[uuid].is_active():
                        currentNets[uuid].set_active(True)
                        startNets.append(uuid)
                    del origNets[uuid]
            except libvirt.libvirtError:
                logging.warn("Couldn't fetch active network name '%s'" % name)

        for name in newInactiveNetNames:
            try:
                net = self.vmm.networkLookupByName(name)
                uuid = self.uuidstr(net.UUID())
                if not origNets.has_key(uuid):
                    currentNets[uuid] = vmmNetwork(self.config, self, net,
                                                 uuid, False)
                    newNets.append(uuid)
                else:
                    currentNets[uuid] = origNets[uuid]
                    if currentNets[uuid].is_active():
                        currentNets[uuid].set_active(False)
                        stopNets.append(uuid)
                    del origNets[uuid]
            except libvirt.libvirtError:
                logging.warn("Couldn't fetch inactive network name '%s'" % name)

        return (startNets, stopNets, newNets, origNets, currentNets)

    def _update_pools(self):
        origPools = self.pools
        currentPools = {}
        startPools = []
        stopPools = []
        newPools = []
        newActivePoolNames = []
        newInactivePoolNames = []

        try:
            newActivePoolNames = self.vmm.listStoragePools()
        except:
            logging.warn("Unable to list active pools")
        try:
            newInactivePoolNames = self.vmm.listDefinedStoragePools()
        except:
            logging.warn("Unable to list inactive pools")

        for name in newActivePoolNames:
            try:
                pool = self.vmm.storagePoolLookupByName(name)
                uuid = self.uuidstr(pool.UUID())
                if not origPools.has_key(uuid):
                    currentPools[uuid] = vmmStoragePool(self.config, self,
                                                        pool, uuid, True)
                    newPools.append(uuid)
                    startPools.append(uuid)
                else:
                    currentPools[uuid] = origPools[uuid]
                    if not currentPools[uuid].is_active():
                        currentPools[uuid].set_active(True)
                        startPools.append(uuid)
                    del origPools[uuid]
            except libvirt.libvirtError:
                logging.warn("Couldn't fetch active pool '%s'" % name)

        for name in newInactivePoolNames:
            try:
                pool = self.vmm.storagePoolLookupByName(name)
                uuid = self.uuidstr(pool.UUID())
                if not origPools.has_key(uuid):
                    currentPools[uuid] = vmmStoragePool(self.config, self,
                                                        pool, uuid, False)
                    newPools.append(uuid)
                else:
                    currentPools[uuid] = origPools[uuid]
                    if currentPools[uuid].is_active():
                        currentPools[uuid].set_active(False)
                        stopPools.append(uuid)
                    del origPools[uuid]
            except libvirt.libvirtError:
                logging.warn("Couldn't fetch inactive pool '%s'" % name)
        return (stopPools, startPools, origPools, newPools, currentPools)

    def _update_vms(self):
        """returns lists of changed VM states"""

        oldActiveIDs = {}
        oldInactiveNames = {}
        for uuid in self.vms.keys():
            # first pull out all the current inactive VMs we know about
            vm = self.vms[uuid]
            if vm.get_id() == -1:
                oldInactiveNames[vm.get_name()] = vm
        for uuid in self.activeUUIDs:
            # Now get all the vms that were active the last time around
            # and are still active
            vm = self.vms[uuid]
            if vm.get_id() != -1:
                oldActiveIDs[vm.get_id()] = vm

        newActiveIDs = []
        try:
            newActiveIDs = self.vmm.listDomainsID()
        except:
            logging.warn("Unable to list active domains")

        newInactiveNames = []
        try:
            newInactiveNames = self.vmm.listDefinedDomains()
        except:
            logging.warn("Unable to list inactive domains")

        curUUIDs = {}       # new master list of vms
        maybeNewUUIDs = {}  # list of vms that changed state or are brand new
        oldUUIDs = {}       # no longer present vms
        newUUIDs = []       # brand new vms
        startedUUIDs = []   # previously present vms that are now running
        activeUUIDs = []    # all running vms

        # NB in these first 2 loops, we go to great pains to
        # avoid actually instantiating a new VM object so that
        # the common case of 'no new/old VMs' avoids hitting
        # XenD too much & thus slowing stuff down.

        # Filter out active domains which haven't changed
        if newActiveIDs != None:
            for id in newActiveIDs:
                if oldActiveIDs.has_key(id):
                    # No change, copy across existing VM object
                    vm = oldActiveIDs[id]
                    curUUIDs[vm.get_uuid()] = vm
                    activeUUIDs.append(vm.get_uuid())
                else:
                    # May be a new VM, we have no choice but
                    # to create the wrapper so we can see
                    # if its a previously inactive domain.
                    try:
                        vm = self.vmm.lookupByID(id)
                        uuid = self.uuidstr(vm.UUID())
                        maybeNewUUIDs[uuid] = vm
                        startedUUIDs.append(uuid)
                        activeUUIDs.append(uuid)
                    except libvirt.libvirtError:
                        logging.debug("Couldn't fetch domain id '%s'" % str(id)
                                      + ": it probably went away")

        # Filter out inactive domains which haven't changed
        if newInactiveNames != None:
            for name in newInactiveNames:
                if oldInactiveNames.has_key(name):
                    # No change, copy across existing VM object
                    vm = oldInactiveNames[name]
                    curUUIDs[vm.get_uuid()] = vm
                else:
                    # May be a new VM, we have no choice but
                    # to create the wrapper so we can see
                    # if its a previously inactive domain.
                    try:
                        vm = self.vmm.lookupByName(name)
                        uuid = self.uuidstr(vm.UUID())
                        maybeNewUUIDs[uuid] = vm
                    except libvirt.libvirtError:
                        logging.debug("Couldn't fetch domain id '%s'" % str(id)
                                      + ": it probably went away")

        # At this point, maybeNewUUIDs has domains which are
        # either completely new, or changed state.

        # Filter out VMs which merely changed state, leaving
        # only new domains
        for uuid in maybeNewUUIDs.keys():
            rawvm = maybeNewUUIDs[uuid]
            if not(self.vms.has_key(uuid)):
                vm = vmmDomain(self.config, self, rawvm, uuid)
                newUUIDs.append(uuid)
                curUUIDs[uuid] = vm
            else:
                vm = self.vms[uuid]
                vm.release_handle()
                vm.set_handle(rawvm)
                curUUIDs[uuid] = vm

        # Finalize list of domains which went away altogether
        for uuid in self.vms.keys():
            vm = self.vms[uuid]
            if not(curUUIDs.has_key(uuid)):
                oldUUIDs[uuid] = vm

        return (startedUUIDs, newUUIDs, oldUUIDs, curUUIDs, activeUUIDs)

    def tick(self, noStatsUpdate=False):
        """ main update function: polls for new objects, updates stats, ..."""
        if self.state != self.STATE_ACTIVE:
            return

        # Poll for new virtual network objects
        (startNets, stopNets, newNets,
         oldNets, self.nets) = self._update_nets()

        # Update pools
        (stopPools, startPools, oldPools,
         newPools, self.pools) = self._update_pools()

        # Poll for changed/new/removed VMs
        (startVMs, newVMs, oldVMs,
         self.vms, self.activeUUIDs) = self._update_vms()

        # Update VM states
        for uuid in oldVMs:
            self.emit("vm-removed", self.uri, uuid)
            oldVMs[uuid].release_handle()
        for uuid in newVMs:
            self.emit("vm-added", self.uri, uuid)
        for uuid in startVMs:
            self.emit("vm-started", self.uri, uuid)

        # Update virtual network states
        for uuid in oldNets:
            self.emit("net-removed", self.uri, uuid)
        for uuid in newNets:
            self.emit("net-added", self.uri, uuid)
        for uuid in startNets:
            self.emit("net-started", self.uri, uuid)
        for uuid in stopNets:
            self.emit("net-stopped", self.uri, uuid)

        for uuid in oldPools:
            self.emit("pool-removed", self.uri, uuid)
        for uuid in newPools:
            self.emit("pool-added", self.uri, uuid)
        for uuid in startPools:
            self.emit("pool-started", self.uri, uuid)
        for uuid in stopPools:
            self.emit("pool-stopped", self.uri, uuid)

        # Finally, we sample each domain
        now = time()
        try:
            self.hostinfo = self.vmm.getInfo()
        except:
            logging.warn("Unable to get host information")

        updateVMs = self.vms
        if noStatsUpdate:
            updateVMs = newVMs

        for uuid in updateVMs:
            self.vms[uuid].tick(now)

        if not noStatsUpdate:
            self._recalculate_stats(now)

        return 1

    def _recalculate_stats(self, now):
        expected = self.config.get_stats_history_length()
        current = len(self.record)
        if current > expected:
            del self.record[expected:current]

        mem = 0
        cpuTime = 0

        for uuid in self.vms:
            vm = self.vms[uuid]
            if vm.get_id() != -1:
                cpuTime = cpuTime + vm.get_cputime()
                mem = mem + vm.get_memory()


        pcentCpuTime = 0
        if len(self.record) > 0:
            prevTimestamp = self.record[0]["timestamp"]

            pcentCpuTime = (cpuTime) * 100.0 / ((now - prevTimestamp)*1000.0*1000.0*1000.0*self.host_active_processor_count())
            # Due to timing diffs between getting wall time & getting
            # the domain's time, its possible to go a tiny bit over
            # 100% utilization. This freaks out users of the data, so
            # we hard limit it.
            if pcentCpuTime > 100.0:
                pcentCpuTime = 100.0
            # Enforce >= 0 just in case
            if pcentCpuTime < 0.0:
                pcentCpuTime = 0.0

        pcentMem = mem * 100.0 / self.host_memory_size()

        newStats = {
            "timestamp": now,
            "memory": mem,
            "memoryPercent": pcentMem,
            "cpuTime": cpuTime,
            "cpuTimePercent": pcentCpuTime
        }

        self.record.insert(0, newStats)
        self.emit("resources-sampled")

    def cpu_time_vector(self):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["cpuTimePercent"]/100.0)
            else:
                vector.append(0)
        return vector

    def cpu_time_vector_limit(self, limit):
        cpudata = self.cpu_time_vector()
        if len(cpudata) > limit:
            cpudata = cpudata[0:limit]
        return cpudata

    def cpu_time_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["cpuTimePercent"]

    def current_memory(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["memory"]

    def pretty_current_memory(self):
        mem = self.current_memory()
        if mem > (1024*1024):
            return "%2.2f GB" % (mem/(1024.0*1024.0))
        else:
            return "%2.2f MB" % (mem/1024.0)

    def current_memory_percentage(self):
        if len(self.record) == 0:
            return 0
        return self.record[0]["memoryPercent"]

    def current_memory_vector(self):
        vector = []
        stats = self.record
        for i in range(self.config.get_stats_history_length()+1):
            if i < len(stats):
                vector.append(stats[i]["memoryPercent"]/100.0)
            else:
                vector.append(0)
        return vector

    def uuidstr(self, rawuuid):
        hex = ['0','1','2','3','4','5','6','7','8','9','a','b','c','d','e','f']
        uuid = []
        for i in range(16):
            uuid.append(hex[((ord(rawuuid[i]) >> 4) & 0xf)])
            uuid.append(hex[(ord(rawuuid[i]) & 0xf)])
            if i == 3 or i == 5 or i == 7 or i == 9:
                uuid.append('-')
        return "".join(uuid)

    def get_state(self):
        return self.state

    def get_state_text(self):
        if self.state == self.STATE_DISCONNECTED:
            return _("Disconnected")
        elif self.state == self.STATE_CONNECTING:
            return _("Connecting")
        elif self.state == self.STATE_ACTIVE:
            if self.is_read_only():
                return _("Active (RO)")
            else:
                return _("Active")
        elif self.state == self.STATE_INACTIVE:
            return _("Inactive")
        else:
            return _("Unknown")

    def _net_get_bridge_owner(self, name, sysfspath):
        # Now magic to determine if the device is part of a bridge
        brportpath = os.path.join(sysfspath, "brport")
        try:
            if os.path.exists(brportpath):
                brlinkpath = os.path.join(brportpath, "bridge")
                dest = os.readlink(brlinkpath)
                (ignore,bridge) = os.path.split(dest)
                return bridge
        except:
            (type, value, stacktrace) = sys.exc_info ()
            logging.error("Unable to determine if device is shared:" +
                            str(type) + " " + str(value) + "\n" + \
                            traceback.format_exc (stacktrace))

        return None

    def _net_get_mac_address(self, name, sysfspath):
        mac = None
        addrpath = sysfspath + "/address"
        if os.path.exists(addrpath):
            df = open(addrpath, 'r')
            mac = df.readline().strip(" \n\t")
            df.close()
        return mac

    def _net_get_bonding_masters(self):
        masters = []
        if os.path.exists("/sys/class/net/bonding_masters"):
            f = open("/sys/class/net/bonding_masters")
            while True:
                rline = f.readline()
                if not rline: break
                if rline == "\x00": continue
                rline = rline.strip("\n\t")
                masters = rline[:].split(' ')
        return masters

    def _net_is_bonding_slave(self, name, sysfspath):
        masterpath = sysfspath + "/master"
        if os.path.exists(masterpath):
            return True
        return False

gobject.type_register(vmmConnection)

