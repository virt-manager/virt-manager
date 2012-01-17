# libvirtworker.py - Copyright (C) 2009 Red Hat, Inc.
# Written by Darryl L. Pierce <dpierce@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.  A copy of the GNU General Public License is
# also available at http://www.gnu.org/copyleft/gpl.html.

import os
import logging

import virtinst
import libvirt

from virtManager.connection import vmmConnection

from domainconfig import DomainConfig

DEFAULT_POOL_TARGET_PATH = "/var/lib/libvirt/images"
DEFAULT_URL = "qemu:///system"

default_url = DEFAULT_URL

def set_default_url(url):
    logging.info("Changing DEFAULT_URL to %s", url)
    global default_url

    default_url = url

def get_default_url():
    logging.info("Returning default URL of %s", default_url)
    return default_url

class VirtManagerConfig:
    def __init__(self, filename=None):
        if filename is None:
            filename = os.path.expanduser("~/.virt-manager/virt-manager-tui.conf")
        self.__filename = filename

    def get_connection_list(self):
        result = []
        if os.path.exists(self.__filename):
            inp = file(self.__filename, "r")
            for entry in inp:
                result.append(entry[0:-1])
        return result

    def add_connection(self, connection):
        connections = self.get_connection_list()
        if connections.count(connection) is 0:
            connections.append(connection)
            self._save_connections(connections)

    def remove_connection(self, connection):
        connections = self.get_connection_list()
        if connections.count(connection) > 0:
            connections.remove(connection)
            self._save_connections(connections)

    def _save_connections(self, connections):
        output = file(self.__filename, "w")
        for entry in connections:
            print >> output, entry
        output.close()

class LibvirtWorker:
    '''Provides utilities for interfacing with libvirt.'''
    def __init__(self, url=None):
        if url is None:
            url = get_default_url()
        logging.info("Connecting to libvirt: %s", url)
        self.__url  = None
        self.__conn = None
        self.__vmmconn = None
        self.__guest = None
        self.__domain = None

        self.open_connection(url)

        self.__capabilities = self.__vmmconn.get_capabilities()
        self.__net = virtinst.VirtualNetworkInterface(conn=self.__conn)
        self.__net.setup(self.__conn)
        (self.__new_guest, self.__new_domain) = virtinst.CapabilitiesParser.guest_lookup(conn=self.__conn)

    def get_connection(self):
        '''Returns the underlying connection.'''
        return self.__conn

    def get_url(self):
        return self.__url

    def open_connection(self, url):
        '''Lets the user change the url for the connection.'''
        old_conn = self.__conn
        old_url  = self.__url
        old_vmmconn = self.__vmmconn

        try:
            self.__vmmconn = vmmConnection(url)
            self.__vmmconn.open(sync=True)

            self.__conn = self.__vmmconn.vmm
            self.__url  = url
            set_default_url(url)
        except Exception, error:
            self.__conn = old_conn
            self.__url  = old_url
            self.__vmmconn = old_vmmconn
            raise error

    def get_capabilities(self):
        '''Returns the capabilities for this libvirt host.'''
        return self.__capabilities

    def list_installable_volumes(self):
        '''
        Return a list of host CDROM devices that have media in them
        XXX: virt-manager code provides other info here: can list all
             CDROM devices and whether them are empty, or report an error
             if HAL missing and libvirt is too old
        '''
        devs = self.__vmmconn.mediadevs.values()
        ret = []
        for dev in devs:
            if dev.has_media() and dev.media_type == "cdrom":
                ret.append(dev)
        return ret

    def list_network_devices(self):
        '''
        Return a list of physical network devices on the host
        '''
        ret = []
        for path in self.__vmmconn.list_net_device_paths():
            net = self.__vmmconn.get_net_device(path)
            ret.append(net.get_name())
        return ret

    def list_domains(self, defined=True, created=True):
        '''Lists all domains.'''
        self.__vmmconn.tick()
        uuids = self.__vmmconn.list_vm_uuids()
        result = []
        for uuid in uuids:
            include = False
            domain = self.get_domain(uuid)
            if domain.status() in [libvirt.VIR_DOMAIN_RUNNING]:
                if created:
                    include = True
            else:
                if defined:
                    include = True
            if include:
                result.append(uuid)
        return result

    def get_domain(self, uuid):
        '''Returns the specified domain.'''
        return self.__vmmconn.get_vm(uuid)

    def domain_exists(self, name):
        '''Returns whether a domain with the specified node exists.'''
        domains = self.list_domains()
        if name in domains:
            return True
        return False

    def undefine_domain(self, name):
        '''Undefines the specified domain.'''
        domain = self.get_domain(name)
        domain.undefine()

    def migrate_domain(self, name, target):
        '''Migrates the specified domain to the target machine.'''
        target_conn = libvirt.open(target)
        virtmachine = self.get_domain(name)
        virtmachine.migrate(target_conn, libvirt.VIR_MIGRATE_LIVE, None, None, 0)

    def list_networks(self, defined=True, started=True):
        '''Lists all networks that meet the given criteria.

        Keyword arguments:
        defined -- Include defined, but not started, networks. (default True)
        started -- Include only started networks. (default True)

        '''
        self.__vmmconn.tick()
        uuids = self.__vmmconn.list_net_uuids()
        result = []
        for uuid in uuids:
            include = False
            net = self.__vmmconn.get_net(uuid)
            if net.is_active():
                if started:
                    include = True
            else:
                if defined:
                    include = True
            if include:
                result.append(uuid)
        return result

    def get_network(self, uuid):
        '''Returns the specified network. Raises an exception if the netowrk does not exist.

        Keyword arguments:
        uuid -- the network's identifier

        '''
        self.__vmmconn.tick()
        result = self.__vmmconn.get_net(uuid)
        if result is None:
            raise Exception("No such network exists: uuid=%s" % uuid)

        return result

    def network_exists(self, name):
        '''Returns True if the specified network exists.

        Keyword arguments:
        name -- the name of the network

        '''
        networks = self.list_networks()
        if name in networks:
            return True
        return False

    def define_network(self, config):
        '''Defines a new network.

        Keyword arguments:
        config -- the network descriptor

        '''
        # since there's no other way currently, we'll have to use XML
        name = config.get_name()
        ip = config.get_ipv4_address_raw()
        start = config.get_ipv4_start_address()
        end = config.get_ipv4_end_address()
        fw = config.get_physical_device()

        xml = "<network>" + \
              "  <name>%s</name>\n" % name
        if not config.is_public_ipv4_network():
            if fw is not "":
                xml += "  <forward dev='%s'/>\n" % fw[1]
            else:
                xml += "  <forward/>\n"

        xml += "  <ip address='%s' netmask='%s'>\n" % (str(ip[1]), str(ip.netmask()))
        xml += "    <dhcp>\n"
        xml += "      <range start='%s' end='%s'/>\n" % (str(start), str(end))
        xml += "    </dhcp>\n"
        xml += "  </ip>\n"
        xml += "</network>\n"

        self.__vmmconn.create_network(xml)

    def undefine_network(self, name):
        '''Undefines the specified network.'''
        network = self.get_network(name)
        network.undefine()

    def list_storage_pools(self, defined=True, created=True):
        '''Returns the list of all defined storage pools.'''
        pools = []
        if defined:
            pools.extend(self.__conn.listDefinedStoragePools())
        if created:
            pools.extend(self.__conn.listStoragePools())
        return pools

    def storage_pool_exists(self, name):
        '''Returns whether a storage pool exists.'''
        pools = self.list_storage_pools()
        if name in pools:
            return True
        return False

    def create_storage_pool(self, name):
        '''Starts the named storage pool if it is not currently started.'''
        if name not in self.list_storage_pools(defined=False):
            pool = self.get_storage_pool(name)
            pool.create(0)

    def destroy_storage_pool(self, name):
        '''Stops the specified storage pool.'''
        if name in self.list_storage_pools(defined=False):
            pool = self.get_storage_pool(name)
            pool.destroy()

    def define_storage_pool(self, name, config=None, meter=None):
        '''Defines a storage pool with the given name.'''
        if config is None:
            pool = virtinst.Storage.DirectoryPool(conn=self.__conn,
                                                  name=name,
                                                  target_path=DEFAULT_POOL_TARGET_PATH)
            newpool = pool.install(build=True, create=True, meter=meter)
            newpool.setAutostart(True)
        else:
            pool = config.get_pool()
            pool.target_path = config.get_target_path()
            if config.needs_hostname():
                pool.host = config.get_hostname()
            if config.needs_source_path():
                pool.source_path = config.get_source_path()
            if config.needs_format():
                pool.format = config.get_format()
            pool.conn = self.__conn
            pool.get_xml_config()
            newpool = pool.install(meter=meter,
                                   build=True, # config.get_build_pool(),
                                   create=True)
            newpool.setAutostart(True)

    def undefine_storage_pool(self, name):
        '''Undefines the specified storage pool.'''
        pool = self.get_storage_pool(name)
        pool.undefine()

    def get_storage_pool(self, name):
        '''Returns the storage pool with the specified name.'''
        return self.__conn.storagePoolLookupByName(name)

    def list_storage_volumes(self, poolname):
        '''Returns the list of all defined storage volumes for a given pool.'''
        pool = self.get_storage_pool(poolname)
        return pool.listVolumes()

    def define_storage_volume(self, config, meter):
        '''Defines a new storage volume.'''
        self.create_storage_pool(config.get_pool().name())
        volume = config.create_volume()
        volume.install(meter=meter)

    def remove_storage_volume(self, poolname, volumename):
        '''Removes the specified storage volume.'''
        volume = self.get_storage_volume(poolname, volumename)
        volume.delete(0)

    def get_storage_volume(self, poolname, volumename):
        '''Returns a reference to the specified storage volume.'''
        pool = self.get_storage_pool(poolname)
        volume = pool.storageVolLookupByName(volumename)
        return volume

    def list_bridges(self):
        '''Lists all defined and active bridges.'''
        bridges = self.__conn.listNetworks()
        bridges.extend(self.__conn.listDefinedNetworks())
        result = []
        for name in bridges:
            bridge = self.__conn.networkLookupByName(name)
            result.append(bridge)
        return result

    def generate_mac_address(self):
        return self.__net.macaddr

    def get_storage_size(self, poolname, volumename):
        '''Returns the size of the specified storage volume.'''
        volume = self.get_storage_volume(poolname, volumename)
        return volume.info()[1] / (1024.0 ** 3)

    def get_virt_types(self):
        result = []
        for guest in self.__capabilities.guests:
            guest_type = guest.os_type
            for domain in guest.domains:
                domain_type = domain.hypervisor_type
                label = domain_type

                if domain_type is "kvm" and guest_type is "xen":
                    label = "xenner"
                elif domain_type is "xen":
                    if guest_type is "xen":
                        label = "xen (paravirt)"
                    elif guest_type is "kvm":
                        label = "xen (fullvirt)"
                elif domain_type is "test":
                    if guest_type is "xen":
                        label = "test (xen)"
                    elif guest_type is "hvm":
                        label = "test (hvm)"

                for row in result:
                    if row[0] == label:
                        label = None
                        break
                if label is None:
                    continue

                result.append([label, domain_type, guest_type])
        return result

    def list_virt_types(self):
        virt_types = self.get_virt_types()
        result = []
        for typ in virt_types:
            result.append(typ[0])
        return result

    def get_default_architecture(self):
        '''Returns a default hypervisor type for new domains.'''
        return self.__new_guest.arch

    def get_hypervisor(self, virt_type):
        virt_types = self.get_virt_types()
        for typ in virt_types:
            if typ[0] is virt_type:
                return typ[1]
        return None

    def get_default_virt_type(self):
        '''Returns the default virtualization type for new domains.'''
        return self.__new_domain.hypervisor_type

    def get_os_type(self, virt_type):
        virt_types = self.get_virt_types()
        for typ in virt_types:
            if typ[0] is virt_type:
                return typ[2]
        return None

    def list_architectures(self):
        result = []
        for guest in self.__capabilities.guests:
            for domain in guest.domains:
                ignore = domain
                label = guest.arch
                for row in result:
                    if row == label:
                        label = None
                        break
                if label is None:
                    continue

                result.append(label)
        return result

    def define_domain(self, config, meter):
        location = None
        extra = None
        kickstart = None

        if config.get_install_type() == DomainConfig.LOCAL_INSTALL:
            if config.get_use_cdrom_source():
                iclass = virtinst.DistroInstaller
                location = config.get_install_media()
            else:
                iclass = virtinst.LiveCDInstaller
                location = config.get_iso_path()
        elif config.get_install_type() == DomainConfig.NETWORK_INSTALL:
            iclass = virtinst.DistroInstaller
            location = config.get_install_url()
            extra = config.get_kernel_options()
            kickstart = config.get_kickstart_url()
        elif config.get_install_type() == DomainConfig.PXE_INSTALL:
            iclass = virtinst.PXEInstaller

        installer = iclass(conn=self.__conn,
                           type=self.get_hypervisor(config.get_virt_type()),
                           os_type=self.get_os_type(config.get_virt_type()))
        self.__guest = installer.guest_from_installer()
        self.__guest.name = config.get_guest_name()
        self.__guest.vcpus = config.get_cpus()
        self.__guest.memory = config.get_memory()
        self.__guest.maxmemory = config.get_memory()

        self.__guest.installer.location = location
        if config.get_use_cdrom_source():
            self.__guest.installer.cdrom = True
        extraargs = ""
        if extra:
            extraargs += extra
        if kickstart:
            extraargs += " ks=%s" % kickstart
        if extraargs:
            self.__guest.installer.extraarags = extraargs

        self.__guest.uuid = virtinst.util.uuidToString(virtinst.util.randomUUID())

        if config.get_os_type() != "generic":
            self.__guest.os_type = config.get_os_type()
        if config.get_os_variant() != "generic":
            self.__guest.os_variant = config.get_os_variant()

        self.__guest._graphics_dev = virtinst.VirtualGraphics(type=virtinst.VirtualGraphics.TYPE_VNC)
        self.__guest.sound_devs = []
        self.__guest.sound_devs.append(virtinst.VirtualAudio(model="es1370"))

        self._setup_nics(config)
        self._setup_disks(config)

        self.__guest.conn = self.__conn
        self.__domain = self.__guest.start_install(False, meter=meter)

    def _setup_nics(self, config):
        self.__guest.nics = []
        nic = virtinst.VirtualNetworkInterface(type=virtinst.VirtualNetworkInterface.TYPE_VIRTUAL,
                                               bridge=config.get_network_bridge(),
                                               network=config.get_network_bridge(),
                                               macaddr=config.get_mac_address())
        self.__guest.nics.append(nic)
        # ensure the network is running
        if config.get_network_bridge() not in self.__conn.listNetworks():
            network = self.__conn.networkLookupByName(config.get_network_bridge())
            network.create()

    def _setup_disks(self, config):
        self.__guest.disks = []
        if config.get_enable_storage():
            path = None
            if config.get_use_local_storage():
                if self.storage_pool_exists("default") is False:
                    self.define_storage_pool("default")
                pool = self.__conn.storagePoolLookupByName("default")
                path = virtinst.Storage.StorageVolume.find_free_name(config.get_guest_name(),
                                                                     pool_object=pool,
                                                                     suffix=".img")
                path = os.path.join(DEFAULT_POOL_TARGET_PATH, path)
            else:
                volume = self.get_storage_volume(config.get_storage_pool(),
                                                 config.get_storage_volume())
                path = volume.path()

            if path is not None:
                storage = virtinst.VirtualDisk(conn=self.__conn,
                                               path=path,
                                               size=config.get_storage_size())
                self.__guest.disks.append(storage)
        self.__guest.conn = self.__conn
