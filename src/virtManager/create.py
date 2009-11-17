#
# Copyright (C) 2008 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
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
import gtk
import gtk.glade

import os, sys, statvfs
import time
import traceback
import threading
import logging

import virtinst
from virtinst import VirtualNetworkInterface

import virtManager.opticalhelper
from virtManager import util
from virtManager.error import vmmErrorDialog
from virtManager.asyncjob import vmmAsyncJob
from virtManager.createmeter import vmmCreateMeter
from virtManager.storagebrowse import vmmStorageBrowser

OS_GENERIC = "generic"

# Number of seconds to wait for media detection
DETECT_TIMEOUT = 20

PAGE_NAME = 0
PAGE_INSTALL = 1
PAGE_MEM = 2
PAGE_STORAGE = 3
PAGE_FINISH = 4

INSTALL_PAGE_ISO = 0
INSTALL_PAGE_URL = 1
INSTALL_PAGE_PXE = 2

class vmmCreate(gobject.GObject):
    __gsignals__ = {
        "action-show-console": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str)),
        "action-show-help": (gobject.SIGNAL_RUN_FIRST,
                             gobject.TYPE_NONE, [str]),
    }

    def __init__(self, config, engine):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + \
                                    "/vmm-create.glade",
                                    "vmm-create", domain="virt-manager")
        self.config = config
        self.engine = engine

        self.conn = None
        self.caps = None
        self.capsguest = None
        self.capsdomain = None
        self.guest = None
        self.usepool = False
        self.storage_browser = None

        self.topwin = self.window.get_widget("vmm-create")
        self.err = vmmErrorDialog(self.topwin,
                                  0, gtk.MESSAGE_ERROR, gtk.BUTTONS_CLOSE,
                                  _("Unexpected Error"),
                                  _("An unexpected error occurred"))

        # Distro detection state variables
        self.detectThread = None
        self.detectedDistro = None
        self.detectThreadLock = threading.Lock()

        # 'Guest' class from the previous failed install
        self.failed_guest = None

        # Host space polling
        self.host_storage_timer = None
        self.host_storage = None

        self.window.signal_autoconnect({
            "on_vmm_newcreate_delete_event" : self.close,

            "on_create_cancel_clicked": self.close,
            "on_create_back_clicked" : self.back,
            "on_create_forward_clicked" : self.forward,
            "on_create_finish_clicked" : self.finish,
            "on_create_help_clicked": self.show_help,
            "on_create_pages_switch_page": self.page_changed,

            "on_create_conn_changed": self.conn_changed,

            "on_install_url_box_changed": self.url_box_changed,
            "on_install_local_cdrom_toggled": self.toggle_local_cdrom,
            "on_install_local_cdrom_combo_changed": self.detect_media_os,
            "on_install_local_box_changed": self.detect_media_os,
            "on_install_local_browse_clicked": self.browse_iso,

            "on_install_detect_os_toggled": self.toggle_detect_os,
            "on_install_os_type_changed": self.change_os_type,
            "on_install_local_iso_toggled": self.toggle_local_iso,
            "on_install_detect_os_box_show": self.detect_visibility_changed,
            "on_install_detect_os_box_hide": self.detect_visibility_changed,

            "on_enable_storage_toggled": self.toggle_enable_storage,
            "on_config_storage_browse_clicked": self.browse_storage,
            "on_config_storage_select_toggled": self.toggle_storage_select,

            "on_config_set_macaddr_toggled": self.toggle_macaddr,

            "on_config_hv_changed": self.hv_changed,
            "on_config_arch_changed": self.arch_changed,
        })

        self.set_initial_state()

    def show(self, uri=None):
        self.reset_state(uri)
        self.topwin.show()
        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        self.topwin.hide()
        self.remove_timers()

        return 1

    def remove_timers(self):
        try:
            if self.host_storage_timer:
                gobject.source_remove(self.host_storage_timer)
                self.host_storage_timer = None
        except:
            pass

    def set_conn(self, newconn):
        if self.conn == newconn:
            return

        self.conn = newconn
        if self.conn:
            self.set_conn_state()


    # State init methods
    def startup_error(self, error):
        self.window.get_widget("startup-error").show()
        self.window.get_widget("install-box").hide()
        self.window.get_widget("create-forward").set_sensitive(False)

        self.window.get_widget("startup-error").set_text("Error: %s" % error)
        return False

    def set_initial_state(self):

        self.window.get_widget("create-pages").set_show_tabs(False)
        self.window.get_widget("install-method-pages").set_show_tabs(False)

        # FIXME: Unhide this when we make some documentation
        self.window.get_widget("create-help").hide()
        finish_img = gtk.image_new_from_stock(gtk.STOCK_QUIT,
                                              gtk.ICON_SIZE_BUTTON)
        self.window.get_widget("create-finish").set_image(finish_img)

        blue = gtk.gdk.color_parse("#0072A8")
        self.window.get_widget("create-header").modify_bg(gtk.STATE_NORMAL,
                                                          blue)

        box = self.window.get_widget("create-vm-icon-box")
        image = gtk.image_new_from_icon_name("vm_new_wizard",
                                             gtk.ICON_SIZE_DIALOG)
        image.show()
        box.pack_end(image, False)

        # Connection list
        self.window.get_widget("create-conn-label").set_text("")
        self.window.get_widget("startup-error").set_text("")
        conn_list = self.window.get_widget("create-conn")
        conn_model = gtk.ListStore(str, str)
        conn_list.set_model(conn_model)
        text = gtk.CellRendererText()
        conn_list.pack_start(text, True)
        conn_list.add_attribute(text, 'text', 1)

        # ISO media list
        iso_list = self.window.get_widget("install-local-box")
        iso_model = gtk.ListStore(str)
        iso_list.set_model(iso_model)
        iso_list.set_text_column(0)
        self.window.get_widget("install-local-box").child.connect("activate", self.detect_media_os)

        # Lists for the install urls
        media_url_list = self.window.get_widget("install-url-box")
        media_url_model = gtk.ListStore(str)
        media_url_list.set_model(media_url_model)
        media_url_list.set_text_column(0)
        self.window.get_widget("install-url-box").child.connect("activate", self.detect_media_os)

        ks_url_list = self.window.get_widget("install-ks-box")
        ks_url_model = gtk.ListStore(str)
        ks_url_list.set_model(ks_url_model)
        ks_url_list.set_text_column(0)

        # Lists for distro type + variant
        os_type_list = self.window.get_widget("install-os-type")
        os_type_model = gtk.ListStore(str, str)
        os_type_list.set_model(os_type_model)
        text = gtk.CellRendererText()
        os_type_list.pack_start(text, True)
        os_type_list.add_attribute(text, 'text', 1)

        os_variant_list = self.window.get_widget("install-os-version")
        os_variant_model = gtk.ListStore(str, str)
        os_variant_list.set_model(os_variant_model)
        text = gtk.CellRendererText()
        os_variant_list.pack_start(text, True)
        os_variant_list.add_attribute(text, 'text', 1)

        # Physical CD-ROM model
        cd_list = self.window.get_widget("install-local-cdrom-combo")
        cd_radio = self.window.get_widget("install-local-cdrom")

        # FIXME: We should disable all this if on a remote connection
        try:
            virtManager.opticalhelper.init_optical_combo(cd_list)
        except Exception, e:
            logging.error("Unable to create optical-helper widget: '%s'", e)
            cd_radio.set_sensitive(False)
            cd_list.set_sensitive(False)
            util.tooltip_wrapper(self.window.get_widget("install-local-cdrom-box"), _("Error listing CD-ROM devices."))

        # Networking
        # [ interface type, device name, label, sensitive ]
        net_list = self.window.get_widget("config-netdev")
        net_model = gtk.ListStore(str, str, str, bool)
        net_list.set_model(net_model)
        text = gtk.CellRendererText()
        net_list.pack_start(text, True)
        net_list.add_attribute(text, 'text', 2)
        net_list.add_attribute(text, 'sensitive', 3)

        # Archtecture
        archModel = gtk.ListStore(str)
        archList = self.window.get_widget("config-arch")
        text = gtk.CellRendererText()
        archList.pack_start(text, True)
        archList.add_attribute(text, 'text', 0)
        archList.set_model(archModel)

        hyperModel = gtk.ListStore(str, str, str, bool)
        hyperList = self.window.get_widget("config-hv")
        text = gtk.CellRendererText()
        hyperList.pack_start(text, True)
        hyperList.add_attribute(text, 'text', 0)
        hyperList.add_attribute(text, 'sensitive', 3)
        hyperList.set_model(hyperModel)

        sparse_info = self.window.get_widget("config-storage-nosparse-info")
        sparse_str = _("Fully allocating storage will take longer now, "
                       "but the OS install phase will be quicker. \n\n"
                       "Skipping allocation can also cause space issues on "
                       "the host machine, if the maximum image size exceeds "
                       "available storage space.")
        util.tooltip_wrapper(sparse_info, sparse_str)

    def reset_state(self, urihint=None):

        self.failed_guest = None
        self.window.get_widget("create-pages").set_current_page(PAGE_NAME)
        self.page_changed(None, None, PAGE_NAME)
        self.window.get_widget("startup-error").hide()
        self.window.get_widget("install-box").show()

        # Name page state
        self.window.get_widget("create-vm-name").set_text("")
        self.window.get_widget("method-local").set_active(True)
        self.window.get_widget("create-conn").set_active(-1)
        activeconn = self.populate_conn_list(urihint)
        self.set_conn(activeconn)
        if not activeconn:
            return self.startup_error(_("No active connection to install on."))

        # Everything from this point forward should be connection independent

        # Distro/Variant
        self.toggle_detect_os(self.window.get_widget("install-detect-os"))
        self.populate_os_type_model()
        self.window.get_widget("install-os-type").set_active(0)

        # Install local/iso
        self.window.get_widget("install-local-box").child.set_text("")
        iso_model = self.window.get_widget("install-local-box").get_model()
        self.populate_media_model(iso_model, self.conn.config_get_iso_paths())

        # Install URL
        self.window.get_widget("install-urlopts-entry").set_text("")
        self.window.get_widget("install-ks-box").child.set_text("")
        self.window.get_widget("install-url-box").child.set_text("")
        urlmodel = self.window.get_widget("install-url-box").get_model()
        ksmodel  = self.window.get_widget("install-ks-box").get_model()
        self.populate_media_model(urlmodel, self.config.get_media_urls())
        self.populate_media_model(ksmodel, self.config.get_kickstart_urls())

        # Mem / CPUs
        self.window.get_widget("config-mem").set_value(512)
        self.window.get_widget("config-cpus").set_value(1)

        # Storage
        if not self.host_storage_timer:
            self.host_storage_timer = gobject.timeout_add(3 * 1000,
                                                          self.host_space_tick)
        self.window.get_widget("enable-storage").set_active(True)
        self.window.get_widget("config-storage-create").set_active(True)
        self.window.get_widget("config-storage-size").set_value(8)
        self.window.get_widget("config-storage-entry").set_text("")
        self.window.get_widget("config-storage-nosparse").set_active(True)

        # Final page
        self.window.get_widget("config-advanced-expander").set_expanded(False)

    def set_conn_state(self):
        # Update all state that has some dependency on the current connection

        self.window.get_widget("create-forward").set_sensitive(True)

        if self.conn.is_read_only():
            return self.startup_error(_("Connection is read only."))

        # A bit out of order, but populate arch + hv lists so we can
        # determine a default
        self.caps = self.conn.get_capabilities()

        try:
            self.change_caps()
        except Exception, e:
            logging.exception("Error determining default hypervisor")
            return self.startup_error(_("No guests are supported for this"
                                        " connection."))
        self.populate_hv()

        is_local = not self.conn.is_remote()
        is_storage_capable = self.conn.is_storage_capable()
        is_pv = (self.capsguest.os_type == "xen")

        # Install Options
        method_tree = self.window.get_widget("method-tree")
        method_pxe = self.window.get_widget("method-pxe")
        method_local = self.window.get_widget("method-local")

        method_tree.set_sensitive(is_local)
        method_local.set_sensitive(not is_pv)
        method_pxe.set_sensitive(not is_pv)

        pxe_tt = None
        local_tt = None
        tree_tt = None

        if is_pv:
            base = _("%s installs not available for paravirt guests.")
            pxe_tt = base % "PXE"
            local_tt = base % "CDROM/ISO"
        if not is_local:
            tree_tt = _("URL installs not available for remote connections.")
            if not is_storage_capable and not local_tt:
                local_tt = _("Connection does not support storage management.")

        if not is_local and not is_storage_capable:
            method_local.set_sensitive(False)
        if method_tree.get_active() and not is_local:
            method_local.set_active(True)
        elif is_pv:
            method_tree.set_active(True)

        if not (method_tree.get_property("sensitive") or
                method_local.get_property("sensitive") or
                method_pxe.get_property("sensitive")):
            self.startup_error(_("No install options available for this "
                                 "connection."))

        util.tooltip_wrapper(method_tree, tree_tt)
        util.tooltip_wrapper(method_local, local_tt)
        util.tooltip_wrapper(method_pxe, pxe_tt)

        # Attempt to create the default pool
        self.usepool = False
        try:
            if is_storage_capable:
                # FIXME: Emit 'pool-added' or something?
                util.build_default_pool(self.conn.vmm)
                self.usepool = True
        except Exception, e:
            logging.debug("Building default pool failed: %s" % str(e))


        # Install local
        iso_option = self.window.get_widget("install-local-iso")
        cdrom_option = self.window.get_widget("install-local-cdrom")

        self.window.get_widget("install-local-cdrom-box").set_sensitive(is_local)
        # Don't select physical CDROM if no valid media is present
        use_cd = (self.window.get_widget("install-local-cdrom-combo").get_active() >= 0)
        if use_cd:
            cdrom_option.set_active(True)
        else:
            iso_option.set_active(True)

        # Only allow ISO option for remote VM
        if not is_local:
            iso_option.set_active(True)

        self.toggle_local_cdrom(cdrom_option)
        self.toggle_local_iso(iso_option)

        # Memory
        memory = int(self.conn.host_memory_size())
        mem_label = _("Up to %(maxmem)s available on the host") % {'maxmem': \
                    self.pretty_memory(memory) }
        mem_label = ("<span size='small' color='#484848'>%s</span>" %
                     mem_label)
        self.window.get_widget("config-mem").set_range(50, memory/1024)
        self.window.get_widget("phys-mem-label").set_markup(mem_label)

        # CPU
        phys_cpus = self.conn.host_active_processor_count()

        max_v = self.conn.get_max_vcpus(_type=self.capsdomain.hypervisor_type)
        cmax = phys_cpus
        if int(max_v) < int(phys_cpus):
            cmax = max_v
            cpu_tooltip = (_("Hypervisor only supports %d virtual CPUs.") %
                           max_v)
        else:
            cpu_tooltip = None
        util.tooltip_wrapper(self.window.get_widget("config-cpus"),
                             cpu_tooltip)

        cmax = int(cmax)
        if cmax <= 0:
            cmax = 1
        cpu_label = _("Up to %(numcpus)d available") % { 'numcpus': \
                                                            int(phys_cpus)}
        cpu_label = ("<span size='small' color='#484848'>%s</span>" %
                     cpu_label)
        self.window.get_widget("config-cpus").set_range(1, cmax)
        self.window.get_widget("phys-cpu-label").set_markup(cpu_label)

        # Storage
        have_storage = (is_local or is_storage_capable)
        storage_tooltip = None

        use_storage = self.window.get_widget("config-storage-select")
        storage_area = self.window.get_widget("config-storage-area")

        storage_area.set_sensitive(have_storage)
        if not have_storage:
            storage_tooltip = _("Connection does not support storage"
                                " management.")
            use_storage.set_sensitive(True)
        util.tooltip_wrapper(storage_area, storage_tooltip)

        # Networking
        # This function will take care of all the remote stuff for us
        self.populate_network_model()
        self.window.get_widget("config-set-macaddr").set_active(True)
        newmac = ""
        try:
            net = VirtualNetworkInterface(conn=self.conn.vmm)
            net.setup(self.conn.vmm)
            newmac = net.macaddr
        except Exception, e:
            logging.exception("Generating macaddr failed: %s" % str(e))
        self.window.get_widget("config-macaddr").set_text(newmac)

    def populate_hv(self):
        hv_list = self.window.get_widget("config-hv")
        model = hv_list.get_model()
        model.clear()

        default = 0
        tooltip = None
        instmethod = self.get_config_install_page()
        for guest in self.caps.guests:
            gtype = guest.os_type
            for dom in guest.domains:
                domtype = dom.hypervisor_type
                label = util.pretty_hv(gtype, domtype)

                # Don't add multiple rows for each arch
                for m in model:
                    if m[0] == label:
                        label = None
                        break
                if label == None:
                    continue

                # Determine if this is the default given by guest_lookup
                if (gtype == self.capsguest.os_type and
                    self.capsdomain.hypervisor_type == domtype):
                    default = len(model)

                if gtype == "xen":
                    if (instmethod == INSTALL_PAGE_PXE or
                        instmethod == INSTALL_PAGE_ISO):
                        tooltip = _("Only URL installs are supported for "
                                    "paravirt.")

                model.append([label, gtype, domtype, not bool(tooltip)])

        hv_info = self.window.get_widget("config-hv-info")
        if tooltip:
            hv_info.show()
            util.tooltip_wrapper(hv_info, tooltip)
        else:
            hv_info.hide()

        hv_list.set_active(default)

    def populate_arch(self):
        arch_list = self.window.get_widget("config-arch")
        model = arch_list.get_model()
        model.clear()

        default = 0
        for guest in self.caps.guests:
            for dom in guest.domains:
                if (guest.os_type == self.capsguest.os_type and
                    dom.hypervisor_type == self.capsdomain.hypervisor_type):

                    arch = guest.arch
                    if arch == self.capsguest.arch:
                        default = len(model)
                    model.append([guest.arch])

        arch_list.set_active(default)

    def populate_conn_list(self, urihint = None):
        conn_list = self.window.get_widget("create-conn")
        model = conn_list.get_model()
        model.clear()

        default = -1
        for c in self.engine.connections.values():
            connobj = c["connection"]
            if not connobj.is_active():
                continue

            if connobj.get_uri() == urihint:
                default = len(model)
            elif default < 0 and not connobj.is_remote():
                # Favor local connections over remote connections
                default = len(model)

            model.append([connobj.get_uri(), connobj.get_pretty_desc_active()])

        no_conns = (len(model) == 0)

        if default < 0 and not no_conns:
            default = 0

        activeuri = ""
        activedesc = ""
        activeconn = None
        if not no_conns:
            conn_list.set_active(default)
            activeuri, activedesc = model[default]
            activeconn = self.engine.connections[activeuri]["connection"]

        self.window.get_widget("create-conn-label").set_text(activedesc)
        if len(model) <= 1:
            self.window.get_widget("create-conn").hide()
            self.window.get_widget("create-conn-label").show()
        else:
            self.window.get_widget("create-conn").show()
            self.window.get_widget("create-conn-label").hide()

        return activeconn

    def populate_os_type_model(self):
        model = self.window.get_widget("install-os-type").get_model()
        model.clear()
        model.append([OS_GENERIC, _("Generic")])
        types = virtinst.FullVirtGuest.list_os_types()
        for t in types:
            model.append([t, virtinst.FullVirtGuest.get_os_type_label(t)])

    def populate_os_variant_model(self, _type):
        model = self.window.get_widget("install-os-version").get_model()
        model.clear()
        if _type == OS_GENERIC:
            model.append([OS_GENERIC, _("Generic")])
            return

        variants = virtinst.FullVirtGuest.list_os_variants(_type)
        for variant in variants:
            model.append([variant,
                          virtinst.FullVirtGuest.get_os_variant_label(_type,
                                                                      variant)])
    def populate_media_model(self, model, urls):
        model.clear()
        for url in urls:
            model.append([url])

    def populate_network_model(self):
        net_list = self.window.get_widget("config-netdev")
        model = net_list.get_model()
        model.clear()

        # For qemu:///session
        if self.conn.is_qemu_session():
            model.append([VirtualNetworkInterface.TYPE_USER, None,
                          _("Usermode Networking"), True])
            net_list.set_active(0)
            return

        hasNet = False
        netIdx = 0
        # Virtual Networks
        for uuid in self.conn.list_net_uuids():
            net = self.conn.get_net(uuid)

            # FIXME: Should we use 'default' even if it's inactive?
            label = _("Virtual network") + " '%s'" % net.get_name()
            if not net.is_active():
                label +=  " (%s)" % _("Inactive")

            desc = net.pretty_forward_mode()
            label += ": %s" % desc

            model.append([ VirtualNetworkInterface.TYPE_VIRTUAL,
                           net.get_name(), label, True])
            hasNet = True
            # FIXME: This preference should be configurable
            if net.get_name() == "default":
                netIdx = len(model) - 1

        if not hasNet:
            model.append([None, None, _("No virtual networks available"),
                          False])

        # Physical devices
        hasShared = False
        brIndex = -1
        if not self.conn.is_remote():
            for name in self.conn.list_net_device_paths():
                br = self.conn.get_net_device(name)

                if br.is_shared():
                    hasShared = True
                    if brIndex < 0:
                        brIndex = len(model)

                    brlabel =  "(%s %s)" % (_("Bridge"), br.get_bridge())
                    sensitive = True
                else:
                    brlabel = "(%s)" %  _("Not bridged")
                    sensitive = False

                model.append([VirtualNetworkInterface.TYPE_BRIDGE,
                              br.get_bridge(),
                              _("Host device %s %s") % (br.get_name(), brlabel),
                              sensitive])

        # If there is a bridge device, default to that
        # If not, use 'default' network
        # If not present, use first list entry
        # If list empty, use no network devices
        if hasShared:
            default = brIndex
        elif hasNet:
            default = netIdx
        else:
            model.insert(0, [None, None, _("No networking."), True])
            default = 0

        net_list.set_active(default)

    def change_caps(self, gtype=None, dtype=None, arch=None):

        if gtype == None:
            # If none specified, prefer HVM. This way, the default install
            # options won't be limited because we default to PV. If hvm not
            # supported, differ to guest_lookup
            for g in self.caps.guests:
                if g.os_type == "hvm":
                    gtype = "hvm"
                    break

        (newg,
         newdom) = virtinst.CapabilitiesParser.guest_lookup(conn=self.conn.vmm,
                                                            caps=self.caps,
                                                            os_type = gtype,
                                                            type = dtype,
                                                            accelerated=True,
                                                            arch=arch)

        if (self.capsguest and self.capsdomain and
            (newg.arch == self.capsguest.arch and
            newg.os_type == self.capsguest.os_type and
            newdom.hypervisor_type == self.capsdomain.hypervisor_type)):
            # No change
            return

        self.capsguest = newg
        self.capsdomain = newdom
        logging.debug("Guest type set to os_type=%s, arch=%s, dom_type=%s" %
                      (self.capsguest.os_type, self.capsguest.arch,
                       self.capsdomain.hypervisor_type))

    def populate_summary(self):
        ignore, ignore, dlabel, vlabel = self.get_config_os_info()
        mem = self.pretty_memory(int(self.guest.memory) * 1024)
        cpu = str(int(self.guest.vcpus))

        instmethod = self.get_config_install_page()
        install = ""
        if instmethod == INSTALL_PAGE_ISO:
            install = _("Local CDROM/ISO")
        elif instmethod == INSTALL_PAGE_URL:
            install = _("URL Install Tree")
        elif instmethod == INSTALL_PAGE_PXE:
            install = _("PXE Install")

        if len(self.guest.disks) == 0:
            storage = _("None")
        else:
            disk = self.guest.disks[0]
            storage = "%s" % self.pretty_storage(disk.size)
            storage += (" <span size='small' color='#484848'>%s</span>" %
                         disk.path)

        osstr = ""
        if not dlabel:
            osstr = _("Generic")
        elif not vlabel:
            osstr = _("Generic") + " " + dlabel
        else:
            osstr = vlabel

        title = "Ready to begin installation of <b>%s</b>" % self.guest.name

        self.window.get_widget("summary-title").set_markup(title)
        self.window.get_widget("summary-os").set_text(osstr)
        self.window.get_widget("summary-install").set_text(install)
        self.window.get_widget("summary-mem").set_text(mem)
        self.window.get_widget("summary-cpu").set_text(cpu)
        self.window.get_widget("summary-storage").set_markup(storage)


    # get_* methods
    def get_config_name(self):
        return self.window.get_widget("create-vm-name").get_text()

    def get_config_install_page(self):
        if self.window.get_widget("method-local").get_active():
            return INSTALL_PAGE_ISO
        elif self.window.get_widget("method-tree").get_active():
            return INSTALL_PAGE_URL
        elif self.window.get_widget("method-pxe").get_active():
            return INSTALL_PAGE_PXE

    def get_config_os_info(self):
        d_list = self.window.get_widget("install-os-type")
        d_idx = d_list.get_active()
        v_list = self.window.get_widget("install-os-version")
        v_idx = v_list.get_active()
        distro = None
        dlabel = None
        variant = None
        vlabel = None

        if d_idx >= 0:
            distro, dlabel = d_list.get_model()[d_idx]
        if v_idx >= 0:
            variant, vlabel = v_list.get_model()[v_idx]

        return (distro, variant, dlabel, vlabel)

    def get_config_local_media(self, store_media=False):
        if self.window.get_widget("install-local-cdrom").get_active():
            return self.window.get_widget("install-local-cdrom-combo").get_active_text()
        else:
            ret = self.window.get_widget("install-local-box").child.get_text()
            if ret and store_media:
                self.conn.config_add_iso_path(ret)
            return ret

    def get_config_detectable_media(self):
        instpage = self.get_config_install_page()
        media = ""

        if instpage == INSTALL_PAGE_ISO:
            media = self.get_config_local_media()
        elif instpage == INSTALL_PAGE_URL:
            media = self.window.get_widget("install-url-box").get_active_text()

        return media

    def get_config_url_info(self, store_media=False):
        media = self.window.get_widget("install-url-box").get_active_text().strip()
        extra = self.window.get_widget("install-urlopts-entry").get_text().strip()
        ks = self.window.get_widget("install-ks-box").get_active_text().strip()

        if media and store_media:
            self.config.add_media_url(media)
        if ks and store_media:
            self.config.add_kickstart_url(ks)

        return (media.strip(), extra.strip(), ks.strip())

    def get_storage_info(self):
        path = None
        size = self.window.get_widget("config-storage-size").get_value()
        sparse = not self.window.get_widget("config-storage-nosparse").get_active()
        if self.window.get_widget("config-storage-create").get_active():
            path = self.get_default_path(self.guest.name)
            logging.debug("Default storage path is: %s" % path)
        else:
            path = self.window.get_widget("config-storage-entry").get_text()

        return (path, size, sparse)

    def get_default_path(self, name):
        path = ""

        # Don't generate a new path if the install failed
        if self.failed_guest:
            if len(self.failed_guest.disks) > 0:
                return self.failed_guest.disks[0].path

        if not self.usepool:

            # Use old generating method
            d = self.config.get_default_image_dir(self.conn)
            origf = os.path.join(d, name + ".img")
            f = origf

            n = 1
            while os.path.exists(f) and n < 100:
                f = os.path.join(d, self.get_config_name() +
                                    "-" + str(n) + ".img")
                n += 1
            if os.path.exists(f):
                f = origf

            path = f
        else:
            pool = self.conn.vmm.storagePoolLookupByName(util.DEFAULT_POOL_NAME)
            path = virtinst.Storage.StorageVolume.find_free_name(name,
                            pool_object=pool, suffix=".img")

            path = os.path.join(util.DEFAULT_POOL_PATH, path)

        return path

    def host_disk_space(self, path=None):
        if not path:
            path = util.DEFAULT_POOL_PATH

        avail = 0
        if self.usepool:
            # FIXME: make sure not inactive?
            # FIXME: use a conn specific function after we send pool-added
            pool = virtinst.util.lookup_pool_by_path(self.conn.vmm, path)
            if pool:
                pool.refresh(0)
                avail = int(virtinst.util.get_xml_path(pool.XMLDesc(0),
                                                       "/pool/available"))

        if not avail and not self.conn.is_remote():
            vfs = os.statvfs(os.path.dirname(path))
            avail = vfs[statvfs.F_FRSIZE] * vfs[statvfs.F_BAVAIL]

        return float(avail / 1024.0 / 1024.0 / 1024.0)

    def host_space_tick(self):
        max_storage = self.host_disk_space()
        if self.host_storage == max_storage:
            return 1
        self.host_storage = max_storage

        hd_label = ("%s available in the default location" %
                    self.pretty_storage(max_storage))
        hd_label = ("<span color='#484848'>%s</span>" % hd_label)
        self.window.get_widget("phys-hd-label").set_markup(hd_label)
        self.window.get_widget("config-storage-size").set_range(1, self.host_storage)

        return 1

    def get_config_network_info(self):
        netidx = self.window.get_widget("config-netdev").get_active()
        netinfo = self.window.get_widget("config-netdev").get_model()[netidx]
        macaddr = self.window.get_widget("config-macaddr").get_text()

        return netinfo[0], netinfo[1], macaddr.strip()

    def get_config_sound(self):
        if self.conn.is_remote():
            return self.config.get_remote_sound()
        return self.config.get_local_sound()

    def is_detect_active(self):
        return self.window.get_widget("install-detect-os").get_active()


    # Listeners
    def conn_changed(self, src):
        idx = src.get_active()
        model = src.get_model()

        if idx < 0:
            self.set_conn(None)
            return

        uri = model[idx][0]
        conn = self.engine.connections[uri]["connection"]
        self.set_conn(conn)

    def hv_changed(self, src):
        idx = src.get_active()
        if idx < 0:
            return

        row = src.get_model()[idx]

        self.change_caps(row[1], row[2])
        self.populate_arch()

    def arch_changed(self, src):
        idx = src.get_active()
        if idx < 0:
            return

        arch = src.get_model()[idx][0]
        self.change_caps(self.capsguest.os_type,
                         self.capsdomain.hypervisor_type,
                         arch)

    def url_box_changed(self, ignore):
        # If the url_entry has focus, don't fire detect_media_os, it means
        # the user is probably typing
        if self.window.get_widget("install-url-box").child.flags() & gtk.HAS_FOCUS:
            return
        self.detect_media_os()

    def detect_media_os(self, ignore1=None):
        curpage = self.window.get_widget("create-pages").get_current_page()
        if self.is_detect_active() and curpage == PAGE_INSTALL:
            self.detect_os_distro()

    def toggle_detect_os(self, src):
        dodetect = src.get_active()

        if dodetect:
            self.window.get_widget("install-os-type-label").show()
            self.window.get_widget("install-os-version-label").show()
            self.window.get_widget("install-os-type").hide()
            self.window.get_widget("install-os-version").hide()
            self.detect_media_os() # Run detection
        else:
            self.window.get_widget("install-os-type-label").hide()
            self.window.get_widget("install-os-version-label").hide()
            self.window.get_widget("install-os-type").show()
            self.window.get_widget("install-os-version").show()

    def change_os_type(self, box):
        model = box.get_model()
        if box.get_active_iter() != None:
            _type = model.get_value(box.get_active_iter(), 0)
            self.populate_os_variant_model(_type)

        variant = self.window.get_widget("install-os-version")
        variant.set_active(0)

    def toggle_local_cdrom(self, src):
        combo = self.window.get_widget("install-local-cdrom-combo")
        is_active = src.get_active()
        if is_active:
            if combo.get_active() != -1:
                # Local CDROM was selected with media preset, detect distro
                self.detect_media_os()

        self.window.get_widget("install-local-cdrom-combo").set_sensitive(is_active)

    def toggle_local_iso(self, src):
        uselocal = src.get_active()
        self.window.get_widget("install-local-box").set_sensitive(uselocal)
        self.window.get_widget("install-local-browse").set_sensitive(uselocal)

    def detect_visibility_changed(self, src, ignore=None):
        is_visible = src.get_property("visible")
        detect_chkbox = self.window.get_widget("install-detect-os")
        nodetect_label = self.window.get_widget("install-nodetect-label")

        detect_chkbox.set_active(is_visible)
        detect_chkbox.toggled()

        if is_visible:
            nodetect_label.hide()
        else:
            nodetect_label.show()

    def browse_iso(self, ignore1=None, ignore2=None):
        self._browse_file(self.set_iso_storage_path,
                          is_media=True)
        self.window.get_widget("install-local-box").activate()

    def toggle_enable_storage(self, src):
        self.window.get_widget("config-storage-box").set_sensitive(src.get_active())

    def browse_storage(self, ignore1):
        self._browse_file(self.set_disk_storage_path,
                          is_media=False)

    def toggle_storage_select(self, src):
        act = src.get_active()
        self.window.get_widget("config-storage-browse-box").set_sensitive(act)

    def toggle_macaddr(self, src):
        self.window.get_widget("config-macaddr").set_sensitive(src.get_active())

    def set_iso_storage_path(self, ignore, path):
        self.window.get_widget("install-local-box").child.set_text(path)

    def set_disk_storage_path(self, ignore, path):
        self.window.get_widget("config-storage-entry").set_text(path)

    # Navigation methods
    def set_install_page(self):
        instnotebook = self.window.get_widget("install-method-pages")
        detectbox = self.window.get_widget("install-detect-os-box")
        instpage = self.get_config_install_page()

        # Detection only works/ is valid for URL,
        # FIXME: Also works for CDROM if running as root (since we need to
        # mount the iso/cdrom), but we should probably make this work for
        # more distros (like windows) before we enable it
        if (instpage == INSTALL_PAGE_URL):
            detectbox.show()
        else:
            detectbox.hide()

        if instpage == INSTALL_PAGE_PXE:
            # Hide the install notebook for pxe, since there isn't anything
            # to ask for
            instnotebook.hide()
        else:
            instnotebook.show()

        instnotebook.set_current_page(instpage)

    def back(self, src):
        notebook = self.window.get_widget("create-pages")
        curpage = notebook.get_current_page()

        if curpage == PAGE_INSTALL:
            self.reset_guest_type()

        notebook.set_current_page(curpage - 1)

    def forward(self, src):
        notebook = self.window.get_widget("create-pages")
        curpage = notebook.get_current_page()

        if self.validate(notebook.get_current_page()) != True:
            return

        if curpage == PAGE_NAME:
            self.set_install_page()
            # See if we need to alter our default HV based on install method
            # FIXME: URL installs also come into play with whether we want
            # PV or FV
            self.guest_from_install_type()


        notebook.set_current_page(curpage + 1)

    def page_changed(self, ignore1, ignore2, pagenum):

        # Update page number
        page_lbl = ("<span color='#59B0E2'>%s</span>" %
                    _("Step %(current_page)d of %(max_page)d") %
                    {'current_page': pagenum+1, 'max_page': PAGE_FINISH+1})

        self.window.get_widget("config-pagenum").set_markup(page_lbl)

        if pagenum == PAGE_NAME:
            self.window.get_widget("create-back").set_sensitive(False)
        else:
            self.window.get_widget("create-back").set_sensitive(True)

        if pagenum == PAGE_INSTALL:
            self.detect_media_os()

        if pagenum == PAGE_FINISH:
            self.window.get_widget("create-forward").hide()
            self.window.get_widget("create-finish").show()
            self.populate_summary()

            # Repopulate the HV list, so we can make install method relevant
            # changes
            self.populate_hv()
        else:
            self.window.get_widget("create-forward").show()
            self.window.get_widget("create-finish").hide()

    def validate(self, pagenum):
        try:
            if pagenum == PAGE_NAME:
                return self.validate_name_page()
            elif pagenum == PAGE_INSTALL:
                return self.validate_install_page(revalidate=False)
            elif pagenum == PAGE_MEM:
                return self.validate_mem_page()
            elif pagenum == PAGE_STORAGE:
                # If the user selects 'no storage' and they used cd/iso install
                # media, we want to go back and change the installer to
                # LiveCDInstaller, which means re-validate everything
                if not self.validate_name_page():
                    return False
                elif not self.validate_install_page():
                    return False
                elif not self.validate_mem_page():
                    return False
                return self.validate_storage_page(revalidate=False)

            elif pagenum == PAGE_FINISH:
                # Since we allow the user to change to change HV type + arch
                # on the last page, we need to revalidate everything
                if not self.validate_name_page():
                    return False
                elif not self.validate_install_page():
                    return False
                elif not self.validate_mem_page():
                    return False
                elif not self.validate_storage_page():
                    return False
                return self.validate_final_page()

        except Exception, e:
            self.err.show_err(_("Uncaught error validating install "
                                "parameters: %s") % str(e),
                                "".join(traceback.format_exc()))
            return

    def validate_name_page(self):
        name = self.get_config_name()

        self.guest = None

        try:
            g = virtinst.Guest(connection=self.conn.vmm)
            g.name = name
        except Exception, e:
            return self.verr(_("Invalid System Name"), str(e))

        return True

    def validate_install_page(self, revalidate=True):
        instmethod = self.get_config_install_page()
        installer = None
        location = None
        extra = None
        ks = None
        cdrom = False
        distro, variant, ignore1, ignore2 = self.get_config_os_info()


        if instmethod == INSTALL_PAGE_ISO:
            if self.window.get_widget("enable-storage").get_active():
                instclass = virtinst.DistroInstaller
            else:
                # CD/ISO install and no disks implies LiveCD
                instclass = virtinst.LiveCDInstaller

            media = self.get_config_local_media()

            if not media:
                return self.verr(_("An install media selection is required."))

            location = media
            cdrom = True

        elif instmethod == INSTALL_PAGE_URL:
            instclass = virtinst.DistroInstaller
            media, extra, ks = self.get_config_url_info()

            if not media:
                return self.verr(_("An install tree is required."))

            location = media

        elif instmethod == INSTALL_PAGE_PXE:
            instclass = virtinst.PXEInstaller


        # Build the installer and Guest instance
        try:
            installer = self.build_installer(instclass)

            self.guest = installer.guest_from_installer()
            self.guest.name = self.get_config_name()
        except Exception, e:
            return self.verr(_("Error setting installer parameters."), str(e))

        # Validate media location
        try:
            if location is not None:
                self.guest.installer.location = location
            if cdrom:
                self.guest.installer.cdrom = True

            extraargs = ""
            if extra:
                extraargs += extra
            if ks:
                extraargs += " ks=%s" % ks

            if extraargs:
                self.guest.installer.extraargs = extraargs
        except Exception, e:
            return self.verr(_("Error setting install media location."),
                             str(e))

        # OS distro/variant validation
        try:
            if distro and distro != OS_GENERIC:
                self.guest.os_type = distro
            if variant and variant != OS_GENERIC:
                self.guest.os_variant = variant
        except ValueError, e:
            return self.err.val_err(_("Error setting OS information."),
                                    str(e))

        # Validation passed, store the install path (if there is one) in
        # gconf
        self.get_config_local_media(store_media=True)
        self.get_config_url_info(store_media=True)
        return True

    def validate_mem_page(self):
        cpus = self.window.get_widget("config-cpus").get_value()
        mem  = self.window.get_widget("config-mem").get_value()

        # VCPUS
        try:
            self.guest.vcpus = int(cpus)
        except Exception, e:
            return self.verr(_("Error setting CPUs."), str(e))

        # Memory
        try:
            self.guest.memory = int(mem)
            self.guest.maxmemory = int(mem)
        except Exception, e:
            return self.verr(_("Error setting guest memory."), str(e))

        return True

    def validate_storage_page(self, revalidate=True):
        use_storage = self.window.get_widget("enable-storage").get_active()

        self.guest.disks = []

        # Validate storage
        if not use_storage:
            return True

        try:
            # This can error out
            diskpath, disksize, sparse = self.get_storage_info()

            if not diskpath:
                return self.verr(_("A storage path must be specified."))

            disk = virtinst.VirtualDisk(conn = self.conn.vmm,
                                        path = diskpath,
                                        size = disksize,
                                        sparse = sparse)

            self.guest.disks.append(disk)
        except Exception, e:
            return self.verr(_("Storage parameter error."), str(e))

        isfatal, errmsg = disk.is_size_conflict()
        if not revalidate and not isfatal and errmsg:
            # Fatal errors are reported when setting 'size'
            res = self.err.ok_cancel(_("Not Enough Free Space"), errmsg)
            if not res:
                return False

        # Disk collision
        if not revalidate and disk.is_conflict_disk(self.guest.conn):
            res = self.err.yes_no(_('Disk "%s" is already in use by another '
                                    'guest!' % disk.path),
                                  _("Do you really want to use the disk?"))
            if not res:
                return False

        return True

    def validate_final_page(self):
        nettype, devname, macaddr = self.get_config_network_info()

        self.guest.nics = []

        # Make sure VirtualNetwork is running
        if (nettype == VirtualNetworkInterface.TYPE_VIRTUAL and
            devname not in self.conn.vmm.listNetworks()):

            res = self.err.yes_no(_("Virtual Network is not active."),
                                  _("Virtual Network '%s' is not active. "
                                    "Would you like to start the network "
                                    "now?") % devname)
            if not res:
                return False

            # Try to start the network
            try:
                net = self.conn.vmm.networkLookupByName(devname)
                net.create()
                logging.info("Started network '%s'." % devname)
            except Exception, e:
                return self.err.show_err(_("Could not start virtual network "
                                           "'%s': %s") % (devname, str(e)),
                                         "".join(traceback.format_exc()))

        if nettype is None:
            # No network device available
            instmethod = self.get_config_install_page()
            methname = None
            if instmethod == INSTALL_PAGE_PXE:
                methname  = "PXE"
            elif instmethod == INSTALL_PAGE_URL:
                methname = "URL"

            if methname:
                return self.verr(_("Network device required for %s install.") %
                                 methname)
            return True

        # Create network device
        try:
            bridge = None
            netname = None
            if nettype == VirtualNetworkInterface.TYPE_VIRTUAL:
                netname = devname
            elif nettype == VirtualNetworkInterface.TYPE_BRIDGE:
                bridge = devname
            elif nettype == VirtualNetworkInterface.TYPE_USER:
                pass

            net = VirtualNetworkInterface(type = nettype,
                                          bridge = bridge,
                                          network = netname,
                                          macaddr = macaddr)

            self.guest.nics.append(net)
        except Exception, e:
            return self.verr(_("Error with network parameters."), str(e))

        # Make sure there is no mac address collision
        isfatal, errmsg = net.is_conflict_net(self.guest.conn)
        if isfatal:
            return self.err.val_err(_("Mac address collision."), errmsg)
        elif errmsg is not None:
            return self.err.yes_no(_("Mac address collision."),
                                   _("%s Are you sure you want to use this "
                                     "address?") % errmsg)
        return True


    # Interesting methods
    def build_installer(self, instclass):
        installer = instclass(conn = self.conn.vmm,
                              type = self.capsdomain.hypervisor_type,
                              os_type = self.capsguest.os_type)
        installer.arch = self.capsguest.arch

        return installer

    def guest_from_install_type(self):
        instmeth = self.get_config_install_page()

        conntype = self.conn.get_type().lower()
        if conntype not in ["xen", "test"]:
            return

        # FIXME: some things are dependent on domain type (vcpu max)
        if instmeth == INSTALL_PAGE_URL:
            self.change_caps(gtype = "xen", dtype = conntype)
        else:
            self.change_caps(gtype = "hvm", dtype = conntype)

    def reset_guest_type(self):
        self.change_caps()

    def finish(self, src):

        # Validate the final page
        if self.validate(self.window.get_widget("create-pages").get_current_page()) != True:
            return False

        guest = self.guest
        disk = len(guest.disks) and guest.disks[0]

        # Generate UUID
        try:
            guest.uuid = virtinst.util.uuidToString(virtinst.util.randomUUID())
        except Exception, e:
            self.err.show_err(_("Error setting UUID: %s") % str(e),
                              "".join(traceback.format_exc()))
            return False

        # Set up graphics device
        try:
            guest._graphics_dev = virtinst.VirtualGraphics(type=virtinst.VirtualGraphics.TYPE_VNC)
        except Exception, e:
            self.err.show_err(_("Error setting up graphics device:") + str(e),
                              "".join(traceback.format_exc()))
            return False

        # Set up sound device (if present)
        guest.sound_devs = []
        try:
            if self.get_config_sound():
                guest.sound_devs.append(virtinst.VirtualAudio(model="es1370"))
        except Exception, e:
            self.err.show_err(_("Error setting up sound device:") + str(e),
                              "".join(traceback.format_exc()))
            return False

        logging.debug("Creating a VM %s" % guest.name +
                      "\n  Type: %s,%s" % (guest.type,
                                           guest.installer.os_type) +
                      "\n  UUID: %s" % guest.uuid +
                      "\n  Install Source: %s" % guest.location +
                      "\n  OS: %s:%s" % (guest.os_type, guest.os_variant) +
                      "\n  Kernel args: %s" % guest.extraargs +
                      "\n  Memory: %s" % guest.memory +
                      "\n  Max Memory: %s" % guest.maxmemory +
                      "\n  # VCPUs: %s" % str(guest.vcpus) +
                      "\n  Filesize: %s" % (disk and disk.size) or "None" +
                      "\n  Disk image: %s" % (disk and disk.path) or "None" +
                      "\n  Audio?: %s" % str(self.get_config_sound()))

        # Start the install
        self.failed_guest = None
        self.topwin.set_sensitive(False)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.WATCH))

        progWin = vmmAsyncJob(self.config, self.do_install, [guest],
                              title=_("Creating Virtual Machine"),
                              text=_("The virtual machine is now being "
                                     "created. Allocation of disk storage "
                                     "and retrieval of the installation "
                                     "images may take a few minutes to "
                                     "complete."))
        progWin.run()
        error, details = progWin.get_error()

        if error != None:
            self.err.show_err(error, details)

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        if error:
            self.failed_guest = self.guest
            return

        # Ensure new VM is loaded
        # FIXME: Hmm, shouldn't we emit a signal here rather than do this?
        self.conn.tick(noStatsUpdate=True)

        if self.config.get_console_popup() == 1:
            # user has requested console on new created vms only
            vm = self.conn.get_vm(guest.uuid)
            (gtype, ignore, ignore, ignore, ignore) = vm.get_graphics_console()
            if gtype == "vnc":
                self.emit("action-show-console", self.conn.get_uri(),
                          guest.uuid)
            else:
                self.emit("action-show-terminal", self.conn.get_uri(),
                          guest.uuid)
        self.close()


    def do_install(self, guest, asyncjob):
        meter = vmmCreateMeter(asyncjob)
        error = None
        details = None
        try:
            logging.debug("Starting background install process")

            guest.conn = util.dup_conn(self.config, self.conn)
            # FIXME: This is why we need a more unified virtinst device API: so
            #        we can do things like swap out the connection on all
            #        devices for a forked one. At least we should get a helper
            #        method in the Guest API.
            for disk in guest.disks:
                disk.conn = guest.conn

            dom = guest.start_install(False, meter = meter)
            if dom == None:
                error = _("Guest installation failed to complete")
                details = error
                logging.error("Guest install did not return a domain")
            else:
                logging.debug("Install completed")
        except:
            (_type, value, stacktrace) = sys.exc_info ()

            # Detailed error message, in English so it can be Googled.
            details = ("Unable to complete install '%s'" %
                       (str(_type) + " " + str(value) + "\n" +
                       traceback.format_exc (stacktrace)))
            error = (_("Unable to complete install: '%s'") % str(value))

        if error:
            asyncjob.set_error(error, details)

    def pretty_storage(self, size):
        return "%.1f Gb" % float(size)

    def pretty_memory(self, mem):
        return "%d MB" % (mem/1024.0)

    # Distro detection methods

    # Clear global detection thread state
    def _clear_detect_thread(self):
        self.detectThreadLock.acquire()
        self.detectThread = None
        self.detectThreadLock.release()

    # Create and launch a detection thread (if no detection already running)
    def detect_os_distro(self):
        self.detectThreadLock.acquire()
        if self.detectThread is not None:
            # We are already checking (some) media, so let that continue
            self.detectThreadLock.release()
            return

        self.detectThread = threading.Thread(target=self.do_detect,
                                             name="Detect OS")
        self.detectThread.setDaemon(True)
        self.detectThreadLock.release()

        self.detectThread.start()

    def set_distro_labels(self, distro, ver):
        # Helper to set auto detect result labels
        if not self.is_detect_active():
            return

        self.window.get_widget("install-os-type-label").set_text(distro)
        self.window.get_widget("install-os-version-label").set_text(ver)

    def set_os_val(self, os_widget, value):
        # Helper method to set the OS Type/Variant selections to the passed
        # values, or -1 if not present.
        model = os_widget.get_model()
        idx = 0

        for idx in range(0, len(model)):
            row = model[idx]
            if row[0] == value:
                break

            if idx == len(os_widget.get_model()) - 1:
                idx = -1

        os_widget.set_active(idx)

        if idx >= 0:
            return row[1]
        else:
            return value

    def set_distro_selection(self, distro, ver):
        # Wrapper to change OS Type/Variant values, and update the distro
        # detection labels
        if not self.is_detect_active():
            return

        if not distro:
            distro = _("Unknown")
            ver = _("Unknown")
        elif not ver:
            ver = _("Unknown")

        dl = self.set_os_val(self.window.get_widget("install-os-type"),
                             distro)
        vl = self.set_os_val(self.window.get_widget("install-os-version"),
                             ver)
        self.set_distro_labels(dl, vl)

    def _safe_wrapper(self, func, args):
        gtk.gdk.threads_enter()
        try:
            return func(*args)
        finally:
            gtk.gdk.threads_leave()

    def _set_forward_sensitive(self, val):
        self.window.get_widget("create-forward").set_sensitive(val)

    # The actual detection routine
    def do_detect(self):
        try:
            media = self._safe_wrapper(self.get_config_detectable_media, ())
            if not media:
                return

            self.detectedDistro = None

            logging.debug("Starting OS detection thread for media=%s" % media)
            self._safe_wrapper(self._set_forward_sensitive, (False,))

            detectThread = threading.Thread(target=self.actually_detect,
                                            name="Actual media detection",
                                            args=(media,))
            detectThread.setDaemon(True)
            detectThread.start()

            base = _("Detecting")
            for i in range(1, DETECT_TIMEOUT * 2):
                if self.detectedDistro != None:
                    break
                detect_str = base + ("." * (((i + 2) % 3) + 1))
                self._safe_wrapper(self.set_distro_labels,
                                   (detect_str, detect_str))
                time.sleep(.5)

            results = self.detectedDistro
            if results == None:
                results = (None, None)

            self._safe_wrapper(self.set_distro_selection, results)
        finally:
            self._clear_detect_thread()
            self._safe_wrapper(self._set_forward_sensitive, (True,))
            logging.debug("Leaving OS detection thread.")

        return

    def actually_detect(self, media):
        try:
            installer = self.build_installer(virtinst.DistroInstaller)
            installer.location = media

            self.detectedDistro = installer.detect_distro()
        except:
            logging.exception("Error detecting distro.")
            self.detectedDistro = (None, None)

    def _browse_file(self, callback, is_media=False):
        if is_media:
            reason = self.config.CONFIG_DIR_MEDIA
        else:
            reason = self.config.CONFIG_DIR_IMAGE

        if self.storage_browser == None:
            self.storage_browser = vmmStorageBrowser(self.config, self.conn)

        self.storage_browser.set_vm_name(self.get_config_name())
        self.storage_browser.set_finish_cb(callback)
        self.storage_browser.set_browse_reason(reason)
        self.storage_browser.show(self.conn)

    def show_help(self, ignore):
        # No help available yet.
        pass

    def verr(self, msg, extra=None):
        return self.err.val_err(msg, extra)

gobject.type_register(vmmCreate)
