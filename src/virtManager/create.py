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

import threading
import logging

import gtk

import virtinst

import virtManager.uihelpers as uihelpers
from virtManager import util
from virtManager.mediadev import MEDIA_CDROM
from virtManager.baseclass import vmmGObjectUI
from virtManager.asyncjob import vmmAsyncJob
from virtManager.storagebrowse import vmmStorageBrowser
from virtManager.details import vmmDetails
from virtManager.domain import vmmDomainVirtinst

# Number of seconds to wait for media detection
DETECT_TIMEOUT = 20

DEFAULT_MEM = 1024

PAGE_NAME = 0
PAGE_INSTALL = 1
PAGE_MEM = 2
PAGE_STORAGE = 3
PAGE_FINISH = 4

INSTALL_PAGE_ISO = 0
INSTALL_PAGE_URL = 1
INSTALL_PAGE_PXE = 2
INSTALL_PAGE_IMPORT = 3
INSTALL_PAGE_CONTAINER_APP = 4
INSTALL_PAGE_CONTAINER_OS = 5

RHEL6_OS_SUPPORT = [
    "rhel3", "rhel4", "rhel5.4", "rhel6",
    "win2k3", "winxp", "win2k8", "vista", "win7",
]

_comboentry_xml = """
<interface>
    <object class="GtkComboBoxEntry" id="install-local-box">
        <property name="visible">True</property>
        <signal name="changed" handler="on_install_local_box_changed"/>
    </object>
    <object class="GtkComboBoxEntry" id="install-url-box">
        <property name="visible">True</property>
        <signal name="changed" handler="on_install_url_box_changed"/>
    </object>
    <object class="GtkComboBoxEntry" id="install-ks-box">
        <property name="visible">True</property>
    </object>
</interface>
"""

class vmmCreate(vmmGObjectUI):
    def __init__(self, engine):
        vmmGObjectUI.__init__(self, "vmm-create.ui", "vmm-create")
        self.engine = engine

        self.conn = None
        self.caps = None
        self.capsguest = None
        self.capsdomain = None

        self.guest = None
        self.disk = None
        self.nic = None

        self.storage_browser = None
        self.conn_signals = []

        # Distro detection state variables
        self.detectedDistro = None
        self.detecting = False
        self.mediaDetected = False
        self.show_all_os = False

        # 'Guest' class from the previous failed install
        self.failed_guest = None

        # Whether there was an error at dialog startup
        self.have_startup_error = False

        # Host space polling
        self.host_storage_timer = None

        # 'Configure before install' window
        self.config_window = None
        self.config_window_signals = []

        self.window.add_from_string(_comboentry_xml)
        self.widget("table2").attach(self.widget("install-url-box"),
                                     1, 2, 0, 1)
        self.widget("table7").attach(self.widget("install-ks-box"),
                                     1, 2, 0, 1)
        self.widget("alignment8").add(self.widget("install-local-box"))

        self.window.connect_signals({
            "on_vmm_newcreate_delete_event" : self.close,

            "on_create_cancel_clicked": self.close,
            "on_create_back_clicked" : self.back,
            "on_create_forward_clicked" : self.forward,
            "on_create_finish_clicked" : self.finish,
            "on_create_help_clicked": self.show_help,
            "on_create_pages_switch_page": self.page_changed,

            "on_create_vm_name_activate": self.forward,
            "on_create_conn_changed": self.conn_changed,
            "on_method_changed": self.method_changed,

            "on_install_url_box_changed": self.url_box_changed,
            "on_install_local_cdrom_toggled": self.toggle_local_cdrom,
            "on_install_local_cdrom_combo_changed": self.detect_media_os,
            "on_install_local_box_changed": self.detect_media_os,
            "on_install_local_browse_clicked": self.browse_iso,
            "on_install_import_browse_clicked": self.browse_import,
            "on_install_app_browse_clicked": self.browse_app,
            "on_install_oscontainer_browse_clicked": self.browse_oscontainer,

            "on_install_detect_os_toggled": self.toggle_detect_os,
            "on_install_os_type_changed": self.change_os_type,
            "on_install_os_version_changed": self.change_os_version,
            "on_install_local_iso_toggled": self.toggle_local_iso,
            "on_install_detect_os_box_show": self.detect_visibility_changed,
            "on_install_detect_os_box_hide": self.detect_visibility_changed,

            "on_enable_storage_toggled": self.toggle_enable_storage,
            "on_config_storage_browse_clicked": self.browse_storage,
            "on_config_storage_select_toggled": self.toggle_storage_select,

            "on_config_netdev_changed": self.netdev_changed,
            "on_config_set_macaddr_toggled": self.toggle_macaddr,

            "on_config_hv_changed": self.hv_changed,
            "on_config_arch_changed": self.arch_changed,
        })
        self.bind_escape_key_close()

        self.set_initial_state()

    def is_visible(self):
        if self.topwin.flags() & gtk.VISIBLE:
            return True
        return False

    def show(self, parent, uri=None):
        logging.debug("Showing new vm wizard")

        if not self.is_visible():
            self.reset_state(uri)
            self.topwin.set_transient_for(parent)

        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing new vm wizard")
        self.topwin.hide()
        self.remove_timers()

        if self.config_window:
            self.config_window.close()
        if self.storage_browser:
            self.storage_browser.close()

        return 1

    def _cleanup(self):
        self.close()
        self.remove_conn()

        self.conn = None
        self.caps = None
        self.capsguest = None
        self.capsdomain = None

        self.guest = None
        self.disk = None
        self.nic = None

        if self.storage_browser:
            self.storage_browser.cleanup()
            self.storage_browser = None

    def remove_timers(self):
        try:
            if self.host_storage_timer:
                self.remove_gobject_timeout(self.host_storage_timer)
                self.host_storage_timer = None
        except:
            pass

    def remove_conn(self):
        if not self.conn:
            return

        for signal in self.conn_signals:
            self.conn.disconnect(signal)
        self.conn_signals = []
        self.conn = None

    def set_conn(self, newconn, force_validate=False):
        if self.conn == newconn and not force_validate:
            return

        self.remove_conn()
        self.conn = newconn
        if self.conn:
            self.set_conn_state()


    # State init methods
    def startup_error(self, error, hideinstall=True):
        self.have_startup_error = True
        self.widget("startup-error-box").show()
        self.widget("create-forward").set_sensitive(False)
        if hideinstall:
            self.widget("install-box").hide()

        self.widget("startup-error").set_text("Error: %s" % error)
        return False

    def startup_warning(self, error):
        self.widget("startup-error-box").show()
        self.widget("startup-error").set_text("Warning: %s" % error)

    def set_initial_state(self):
        self.widget("create-pages").set_show_tabs(False)
        self.widget("install-method-pages").set_show_tabs(False)

        # FIXME: Unhide this when we make some documentation
        self.widget("create-help").hide()
        finish_img = gtk.image_new_from_stock(gtk.STOCK_QUIT,
                                              gtk.ICON_SIZE_BUTTON)
        self.widget("create-finish").set_image(finish_img)

        blue = gtk.gdk.color_parse("#0072A8")
        self.widget("create-header").modify_bg(gtk.STATE_NORMAL,
                                                          blue)

        box = self.widget("create-vm-icon-box")
        image = gtk.image_new_from_icon_name("vm_new_wizard",
                                             gtk.ICON_SIZE_DIALOG)
        image.show()
        box.pack_end(image, False)

        # Connection list
        self.widget("create-conn-label").set_text("")
        self.widget("startup-error").set_text("")
        conn_list = self.widget("create-conn")
        conn_model = gtk.ListStore(str, str)
        conn_list.set_model(conn_model)
        text = gtk.CellRendererText()
        conn_list.pack_start(text, True)
        conn_list.add_attribute(text, 'text', 1)

        # ISO media list
        iso_list = self.widget("install-local-box")
        iso_model = gtk.ListStore(str)
        iso_list.set_model(iso_model)
        iso_list.set_text_column(0)
        self.widget("install-local-box").child.connect("activate",
                                                    self.detect_media_os)

        # Lists for the install urls
        media_url_list = self.widget("install-url-box")
        media_url_model = gtk.ListStore(str)
        media_url_list.set_model(media_url_model)
        media_url_list.set_text_column(0)
        self.widget("install-url-box").child.connect("activate",
                                                    self.detect_media_os)

        ks_url_list = self.widget("install-ks-box")
        ks_url_model = gtk.ListStore(str)
        ks_url_list.set_model(ks_url_model)
        ks_url_list.set_text_column(0)

        def sep_func(model, it, combo):
            ignore = combo
            return model[it][2]

        # Lists for distro type + variant
        # [os value, os label, is seperator, is 'show all'
        os_type_list = self.widget("install-os-type")
        os_type_model = gtk.ListStore(str, str, bool, bool)
        os_type_list.set_model(os_type_model)
        text = gtk.CellRendererText()
        os_type_list.pack_start(text, True)
        os_type_list.add_attribute(text, 'text', 1)
        os_type_list.set_row_separator_func(sep_func, os_type_list)

        os_variant_list = self.widget("install-os-version")
        os_variant_model = gtk.ListStore(str, str, bool, bool)
        os_variant_list.set_model(os_variant_model)
        text = gtk.CellRendererText()
        os_variant_list.pack_start(text, True)
        os_variant_list.add_attribute(text, 'text', 1)
        os_variant_list.set_row_separator_func(sep_func, os_variant_list)


        # Physical CD-ROM model
        cd_list = self.widget("install-local-cdrom-combo")
        uihelpers.init_mediadev_combo(cd_list)

        # Networking
        # [ interface type, device name, label, sensitive ]
        net_list = self.widget("config-netdev")
        bridge_box = self.widget("config-netdev-bridge-box")
        uihelpers.init_network_list(net_list, bridge_box)

        # Archtecture
        archModel = gtk.ListStore(str)
        archList = self.widget("config-arch")
        text = gtk.CellRendererText()
        archList.pack_start(text, True)
        archList.add_attribute(text, 'text', 0)
        archList.set_model(archModel)

        hyperModel = gtk.ListStore(str, str, str, bool)
        hyperList = self.widget("config-hv")
        text = gtk.CellRendererText()
        hyperList.pack_start(text, True)
        hyperList.add_attribute(text, 'text', 0)
        hyperList.add_attribute(text, 'sensitive', 3)
        hyperList.set_model(hyperModel)

        # Sparse tooltip
        sparse_info = self.widget("config-storage-nosparse-info")
        uihelpers.set_sparse_tooltip(sparse_info)

    def reset_state(self, urihint=None):
        self.failed_guest = None
        self.have_startup_error = False
        self.guest = None
        self.disk = None
        self.nic = None
        self.show_all_os = False

        self.widget("create-pages").set_current_page(PAGE_NAME)
        self.page_changed(None, None, PAGE_NAME)
        self.widget("startup-error-box").hide()
        self.widget("install-box").show()

        # Name page state
        self.widget("create-vm-name").set_text("")
        self.widget("create-vm-name").grab_focus()
        self.widget("method-local").set_active(True)
        self.widget("create-conn").set_active(-1)
        activeconn = self.populate_conn_list(urihint)

        try:
            self.set_conn(activeconn, force_validate=True)
        except Exception, e:
            logging.exception("Error setting create wizard conn state.")
            return self.startup_error(str(e))

        if not activeconn:
            return self.startup_error(
                                _("No active connection to install on."))

        # Everything from this point forward should be connection independent

        # Distro/Variant
        self.toggle_detect_os(self.widget("install-detect-os"))
        self.populate_os_type_model()
        self.widget("install-os-type").set_active(0)

        self.widget("install-local-box").child.set_text("")
        iso_model = self.widget("install-local-box").get_model()
        self.populate_media_model(iso_model, self.conn.config_get_iso_paths())

        # Install URL
        self.widget("install-urlopts-entry").set_text("")
        self.widget("install-ks-box").child.set_text("")
        self.widget("install-url-box").child.set_text("")
        self.widget("install-url-options").set_expanded(False)
        urlmodel = self.widget("install-url-box").get_model()
        ksmodel  = self.widget("install-ks-box").get_model()
        self.populate_media_model(urlmodel, self.config.get_media_urls())
        self.populate_media_model(ksmodel, self.config.get_kickstart_urls())

        # Install import
        self.widget("install-import-entry").set_text("")

        # Install container app
        self.widget("install-app-entry").set_text("/bin/sh")

        # Install container OS
        self.widget("install-oscontainer-fs").set_text("")

        # Mem / CPUs
        self.widget("config-mem").set_value(DEFAULT_MEM)
        self.widget("config-cpus").set_value(1)

        # Storage
        label_widget = self.widget("phys-hd-label")
        label_widget.set_markup("")
        if not self.host_storage_timer:
            self.host_storage_timer = self.timeout_add(3 * 1000,
                                                    uihelpers.host_space_tick,
                                                    self.conn,
                                                    label_widget)
        self.widget("enable-storage").set_active(True)
        self.widget("config-storage-create").set_active(True)
        self.widget("config-storage-size").set_value(8)
        self.widget("config-storage-entry").set_text("")
        self.widget("config-storage-nosparse").set_active(True)

        # Final page
        self.widget("summary-customize").set_active(False)

        # Make sure window is a sane size
        self.topwin.resize(1, 1)

    def set_conn_state(self):
        # Update all state that has some dependency on the current connection

        self.widget("create-forward").set_sensitive(True)

        if self.conn.is_read_only():
            return self.startup_error(_("Connection is read only."))

        if self.conn.no_install_options():
            error = _("No hypervisor options were found for this "
                      "connection.")

            if self.conn.is_qemu():
                error += "\n\n"
                error += _("This usually means that QEMU or KVM is not "
                           "installed on your machine, or the KVM kernel "
                           "modules are not loaded.")
            return self.startup_error(error)

        # A bit out of order, but populate arch + hv lists so we can
        # determine a default
        self.conn.invalidate_caps()
        self.caps = self.conn.get_capabilities()
        self.change_caps()
        self.populate_hv()

        if self.conn.is_xen():
            if self.conn.hw_virt_supported():
                if self.conn.is_bios_virt_disabled():
                    error = _("Host supports full virtualization, but "
                              "no related install options are available. "
                              "This may mean support is disabled in your "
                              "system BIOS.")
                    self.startup_warning(error)

            else:
                error = _("Host does not appear to support hardware "
                          "virtualization. Install options may be limited.")
                self.startup_warning(error)

        elif self.conn.is_qemu():
            if not self.conn.is_kvm_supported():
                error = _("KVM is not available. This may mean the KVM "
                 "package is not installed, or the KVM kernel modules "
                 "are not loaded. Your virtual machines may perform poorly.")
                self.startup_warning(error)

        # Helper state
        is_local = not self.conn.is_remote()
        is_storage_capable = self.conn.is_storage_capable()
        can_storage = (is_local or is_storage_capable)
        is_pv = (self.capsguest.os_type == "xen")
        is_container = self.conn.is_container()
        can_remote_url = virtinst.support.check_stream_support(self.conn.vmm,
                            virtinst.support.SUPPORT_STREAM_UPLOAD)

        # Install Options
        method_tree = self.widget("method-tree")
        method_pxe = self.widget("method-pxe")
        method_local = self.widget("method-local")
        method_import = self.widget("method-import")
        method_container_app = self.widget("method-container-app")

        method_tree.set_sensitive(is_local or can_remote_url)
        method_local.set_sensitive(not is_pv and can_storage)
        method_pxe.set_sensitive(not is_pv)
        method_import.set_sensitive(can_storage)
        virt_methods = [method_local, method_tree, method_pxe, method_import]

        pxe_tt = None
        local_tt = None
        tree_tt = None
        import_tt = None

        if not is_local:
            if not can_remote_url:
                tree_tt = _("Libvirt version does not "
                            "support remote URL installs.")
            if not is_storage_capable:
                local_tt = _("Connection does not support storage management.")
                import_tt = local_tt

        if is_pv:
            base = _("%s installs not available for paravirt guests.")
            pxe_tt = base % "PXE"
            local_tt = base % "CDROM/ISO"

        for w in virt_methods:
            if w.get_property("sensitive"):
                w.set_active(True)
                break

        if not (is_container or
                filter(lambda w: w.get_property("sensitive"), virt_methods)):
            return self.startup_error(
                    _("No install methods available for this connection."),
                    hideinstall=False)

        util.tooltip_wrapper(method_tree, tree_tt)
        util.tooltip_wrapper(method_local, local_tt)
        util.tooltip_wrapper(method_pxe, pxe_tt)
        util.tooltip_wrapper(method_import, import_tt)

        # Container install options
        method_container_app.set_active(True)
        self.widget("virt-install-box").set_property("visible",
                                                     not is_container)
        self.widget("container-install-box").set_property("visible",
                                                     is_container)

        # Install local
        iso_option = self.widget("install-local-iso")
        cdrom_option = self.widget("install-local-cdrom")
        cdrom_list = self.widget("install-local-cdrom-combo")
        cdrom_warn = self.widget("install-local-cdrom-warn")

        sigs = uihelpers.populate_mediadev_combo(self.conn, cdrom_list,
                                                 MEDIA_CDROM)
        self.conn_signals.extend(sigs)

        if self.conn.mediadev_error:
            cdrom_warn.show()
            cdrom_option.set_sensitive(False)
            util.tooltip_wrapper(cdrom_warn, self.conn.mediadev_error)
        else:
            cdrom_warn.hide()

        # Don't select physical CDROM if no valid media is present
        use_cd = (cdrom_list.get_active() >= 0)
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
        mem_label = (_("Up to %(maxmem)s available on the host") %
                     {'maxmem': self.pretty_memory(memory)})
        mem_label = ("<span size='small' color='#484848'>%s</span>" %
                     mem_label)
        self.widget("config-mem").set_range(50, memory / 1024)
        self.widget("phys-mem-label").set_markup(mem_label)

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
        util.tooltip_wrapper(self.widget("config-cpus"), cpu_tooltip)

        cmax = int(cmax)
        if cmax <= 0:
            cmax = 1
        cpu_label = (_("Up to %(numcpus)d available") %
                     {'numcpus': int(phys_cpus)})
        cpu_label = ("<span size='small' color='#484848'>%s</span>" %
                     cpu_label)
        self.widget("config-cpus").set_range(1, cmax)
        self.widget("phys-cpu-label").set_markup(cpu_label)

        # Storage
        storage_tooltip = None

        use_storage = self.widget("config-storage-select")
        storage_area = self.widget("config-storage-area")

        storage_area.set_sensitive(can_storage)
        if not can_storage:
            storage_tooltip = _("Connection does not support storage"
                                " management.")
            use_storage.set_sensitive(True)
        util.tooltip_wrapper(storage_area, storage_tooltip)

        # Networking
        net_list        = self.widget("config-netdev")
        net_expander    = self.widget("config-advanced-expander")
        net_warn_icon   = self.widget("config-netdev-warn-icon")
        net_warn_box    = self.widget("config-netdev-warn-box")
        net_expander.hide()
        net_warn_icon.hide()
        net_warn_box.hide()
        net_expander.set_expanded(False)

        do_warn = uihelpers.populate_network_list(net_list, self.conn, False)
        self.set_net_warn(self.conn.netdev_error or do_warn,
                          self.conn.netdev_error, True)

        newmac = uihelpers.generate_macaddr(self.conn)
        self.widget("config-set-macaddr").set_active(bool(newmac))
        self.widget("config-macaddr").set_text(newmac)

    def set_net_warn(self, show_warn, msg, do_tooltip):
        net_warn_icon   = self.widget("config-netdev-warn-icon")
        net_warn_box    = self.widget("config-netdev-warn-box")
        net_warn_label  = self.widget("config-netdev-warn-label")
        net_expander    = self.widget("config-advanced-expander")

        if show_warn:
            net_expander.set_expanded(True)

        if do_tooltip:
            net_warn_icon.set_property("visible", show_warn)
            if msg:
                util.tooltip_wrapper(net_warn_icon, show_warn and msg or "")
        else:
            net_warn_box.set_property("visible", show_warn)
            markup = show_warn and ("<small>%s</small>" % msg) or ""
            net_warn_label.set_markup(markup)

    def populate_hv(self):
        hv_list = self.widget("config-hv")
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
                sensitive = True

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
                        sensitive = False
                        tooltip = _("Only URL or import installs are supported "
                                    "for paravirt.")

                model.append([label, gtype, domtype, sensitive])

        hv_info = self.widget("config-hv-info")
        if tooltip:
            hv_info.show()
            util.tooltip_wrapper(hv_info, tooltip)
        else:
            hv_info.hide()

        hv_list.set_active(default)

    def populate_arch(self):
        arch_list = self.widget("config-arch")
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

    def populate_conn_list(self, urihint=None):
        conn_list = self.widget("create-conn")
        model = conn_list.get_model()
        model.clear()

        default = -1
        for c in self.engine.conns.values():
            connobj = c["conn"]
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
            activeconn = self.engine.conns[activeuri]["conn"]

        self.widget("create-conn-label").set_text(activedesc)
        if len(model) <= 1:
            self.widget("create-conn").hide()
            self.widget("create-conn-label").show()
        else:
            self.widget("create-conn").show()
            self.widget("create-conn-label").hide()

        return activeconn

    def _add_os_row(self, model, name="", label="", supported=False,
                      sep=False, action=False):
        visible = self.show_all_os or supported
        if sep or action:
            visible = not self.show_all_os

        if not visible:
            return

        model.append([name, label, sep, action])

    def populate_os_type_model(self):
        widget = self.widget("install-os-type")
        model = widget.get_model()
        model.clear()
        filtervars = (not self._rhel6_defaults() and
                      RHEL6_OS_SUPPORT or
                      None)
        types = virtinst.FullVirtGuest.list_os_types()
        supportl = virtinst.FullVirtGuest.list_os_types(supported=True,
                                                        filtervars=filtervars)

        self._add_os_row(model, None, _("Generic"), True)

        for t in types:
            label = virtinst.FullVirtGuest.get_os_type_label(t)
            supported = (t in supportl)
            self._add_os_row(model, t, label, supported)

        # Add sep
        self._add_os_row(model, sep=True)
        # Add action option
        self._add_os_row(model, label=_("Show all OS options"), action=True)
        widget.set_active(0)


    def populate_os_variant_model(self, _type):
        model = self.widget("install-os-version").get_model()
        model.clear()
        if _type == None:
            self._add_os_row(model, None, _("Generic"), True)
            return

        filtervars = (not self._rhel6_defaults() and
                      RHEL6_OS_SUPPORT or
                      None)
        preferred = self.config.preferred_distros
        variants = virtinst.FullVirtGuest.list_os_variants(_type, preferred)
        supportl = virtinst.FullVirtGuest.list_os_variants(
                                            _type, preferred, supported=True,
                                            filtervars=filtervars)

        for v in variants:
            label = virtinst.FullVirtGuest.get_os_variant_label(_type, v)
            supported = v in supportl
            self._add_os_row(model, v, label, supported)

        # Add sep
        self._add_os_row(model, sep=True)
        # Add action option
        self._add_os_row(model, label=_("Show all OS options"), action=True)

    def populate_media_model(self, model, urls):
        model.clear()
        for url in urls:
            model.append([url])


    def change_caps(self, gtype=None, dtype=None, arch=None):
        if gtype == None:
            # If none specified, prefer HVM. This way, the default install
            # options won't be limited because we default to PV. If hvm not
            # supported, differ to guest_lookup
            for g in self.caps.guests:
                if g.os_type == "hvm":
                    gtype = "hvm"
                    break

        (newg, newdom) = virtinst.CapabilitiesParser.guest_lookup(
                                                        conn=self.conn.vmm,
                                                        caps=self.caps,
                                                        os_type=gtype,
                                                        type=dtype,
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
        logging.debug("Guest type set to os_type=%s, arch=%s, dom_type=%s",
                      self.capsguest.os_type,
                      self.capsguest.arch,
                      self.capsdomain.hypervisor_type)

    def populate_summary(self):
        distro, version, dlabel, vlabel = self.get_config_os_info()
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
        elif instmethod == INSTALL_PAGE_IMPORT:
            install = _("Import existing OS image")
        elif instmethod == INSTALL_PAGE_CONTAINER_APP:
            install = _("Application container")
        elif instmethod == INSTALL_PAGE_CONTAINER_OS:
            install = _("Operating system container")

        storagetmpl = "<span size='small' color='#484848'>%s</span>"
        if len(self.guest.disks):
            disk = self.guest.disks[0]
            storage = "%s" % self.pretty_storage(disk.size)
            storage += " " + (storagetmpl % disk.path)
        elif len(self.guest.get_devices("filesystem")):
            fs = self.guest.get_devices("filesystem")[0]
            storage = storagetmpl % fs.source
        elif self.guest.installer.is_container():
            storage = _("Host filesystem")
        else:
            storage = _("None")

        osstr = ""
        have_os = True
        if self.guest.installer.is_container():
            osstr = _("Linux")
        elif not distro:
            osstr = _("Generic")
            have_os = False
        elif not version:
            osstr = _("Generic") + " " + dlabel
            have_os = False
        else:
            osstr = vlabel

        title = "Ready to begin installation of <b>%s</b>" % self.guest.name

        self.widget("finish-warn-os").set_property("visible", not have_os)
        self.widget("summary-title").set_markup(title)
        self.widget("summary-os").set_text(osstr)
        self.widget("summary-install").set_text(install)
        self.widget("summary-mem").set_text(mem)
        self.widget("summary-cpu").set_text(cpu)
        self.widget("summary-storage").set_markup(storage)


    # get_* methods
    def get_config_name(self):
        return self.widget("create-vm-name").get_text()

    def is_install_page(self):
        notebook = self.widget("create-pages")
        curpage = notebook.get_current_page()
        return curpage == PAGE_INSTALL

    def get_config_install_page(self):
        if self.widget("virt-install-box").get_property("visible"):
            if self.widget("method-local").get_active():
                return INSTALL_PAGE_ISO
            elif self.widget("method-tree").get_active():
                return INSTALL_PAGE_URL
            elif self.widget("method-pxe").get_active():
                return INSTALL_PAGE_PXE
            elif self.widget("method-import").get_active():
                return INSTALL_PAGE_IMPORT
        else:
            if self.widget("method-container-app").get_active():
                return INSTALL_PAGE_CONTAINER_APP
            if self.widget("method-container-os").get_active():
                return INSTALL_PAGE_CONTAINER_OS

    def get_config_os_info(self):
        d_list = self.widget("install-os-type")
        d_idx = d_list.get_active()
        v_list = self.widget("install-os-version")
        v_idx = v_list.get_active()
        distro = None
        dlabel = None
        variant = None
        vlabel = None

        if d_idx >= 0:
            row = d_list.get_model()[d_idx]
            distro = row[0]
            dlabel = row[1]
        if v_idx >= 0:
            row = v_list.get_model()[v_idx]
            variant = row[0]
            vlabel = row[1]

        return (distro, variant, dlabel, vlabel)

    def get_config_local_media(self, store_media=False):
        if self.widget("install-local-cdrom").get_active():
            return self.widget("install-local-cdrom-combo").get_active_text()
        else:
            ret = self.widget("install-local-box").child.get_text()
            if ret and store_media:
                self.conn.config_add_iso_path(ret)
            return ret

    def get_config_detectable_media(self):
        instpage = self.get_config_install_page()
        media = ""

        if instpage == INSTALL_PAGE_ISO:
            media = self.get_config_local_media()
        elif instpage == INSTALL_PAGE_URL:
            media = self.widget("install-url-box").get_active_text()
        elif instpage == INSTALL_PAGE_IMPORT:
            media = self.widget("install-import-entry").get_text()

        return media

    def get_config_url_info(self, store_media=False):
        media = self.widget("install-url-box").get_active_text().strip()
        extra = self.widget("install-urlopts-entry").get_text().strip()
        ks = self.widget("install-ks-box").get_active_text().strip()

        if media and store_media:
            self.config.add_media_url(media)
        if ks and store_media:
            self.config.add_kickstart_url(ks)

        return (media.strip(), extra.strip(), ks.strip())

    def get_config_import_path(self):
        return self.widget("install-import-entry").get_text()

    def get_config_container_app_path(self):
        return self.widget("install-app-entry").get_text()

    def get_config_container_fs_path(self):
        return self.widget("install-oscontainer-fs").get_text()

    def get_default_path(self, name):
        # Don't generate a new path if the install failed
        if self.failed_guest:
            if len(self.failed_guest.disks) > 0:
                return self.failed_guest.disks[0].path

        return util.get_default_path(self.conn, name)

    def is_default_storage(self):
        usedef = self.widget("config-storage-create").get_active()
        isimport = (self.get_config_install_page() == INSTALL_PAGE_IMPORT)
        return usedef and not isimport

    def get_storage_info(self):
        path = None
        size = uihelpers.spin_get_helper(self.widget("config-storage-size"))
        sparse = not self.widget("config-storage-nosparse").get_active()

        if self.get_config_install_page() == INSTALL_PAGE_IMPORT:
            path = self.get_config_import_path()
            size = None
            sparse = False

        elif self.is_default_storage():
            path = self.get_default_path(self.guest.name)
            logging.debug("Default storage path is: %s", path)
        else:
            path = self.widget("config-storage-entry").get_text()

        return (path, size, sparse)

    def get_config_network_info(self):
        net_list = self.widget("config-netdev")
        bridge_ent = self.widget("config-netdev-bridge")
        macaddr = self.widget("config-macaddr").get_text()

        net_type, net_src = uihelpers.get_network_selection(net_list,
                                                            bridge_ent)

        return net_type, net_src, macaddr.strip()

    def get_config_sound(self):
        if self.conn.is_remote():
            return self.config.get_remote_sound()
        return self.config.get_local_sound()

    def get_config_graphics_type(self):
        return self.config.get_graphics_type()

    def get_config_customize(self):
        return self.widget("summary-customize").get_active()

    def is_detect_active(self):
        return self.widget("install-detect-os").get_active()


    # Listeners
    def conn_changed(self, src):
        idx = src.get_active()
        model = src.get_model()

        if idx < 0:
            conn = None
        else:
            uri = model[idx][0]
            conn = self.engine.conns[uri]["conn"]

        # If we aren't visible, let reset_state handle this for us, which
        # has a better chance of reporting error
        if not self.is_visible():
            return

        self.set_conn(conn)

    def method_changed(self, src):
        ignore = src
        self.set_page_num_text(0)

    def netdev_changed(self, ignore):
        self.check_network_selection()

    def check_network_selection(self):
        src = self.widget("config-netdev")
        idx = src.get_active()
        show_pxe_warn = True
        pxe_install = (self.get_config_install_page() == INSTALL_PAGE_PXE)

        if not idx < 0:
            row = src.get_model()[idx]
            ntype = row[0]
            key = row[6]

            if (ntype == None or
                ntype == virtinst.VirtualNetworkInterface.TYPE_USER):
                show_pxe_warn = True
            elif ntype != virtinst.VirtualNetworkInterface.TYPE_VIRTUAL:
                show_pxe_warn = False
            else:
                obj = self.conn.get_net(key)
                show_pxe_warn = not obj.can_pxe()

        if not (show_pxe_warn and pxe_install):
            return

        self.set_net_warn(True,
                          _("Network selection does not support PXE"), False)

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
        self.mediaDetected = False
        if (self.widget("install-url-box").child.flags() &
            gtk.HAS_FOCUS):
            return
        self.detect_media_os()

    def should_detect_media(self):
        return (self.is_detect_active() and not self.mediaDetected)

    def detect_media_os(self, ignore1=None, forward=False):
        if not self.should_detect_media():
            return
        if not self.is_install_page():
            return
        self.start_detection(forward=forward)

    def toggle_detect_os(self, src):
        dodetect = src.get_active()

        if dodetect:
            self.widget("install-os-type-label").show()
            self.widget("install-os-version-label").show()
            self.widget("install-os-type").hide()
            self.widget("install-os-version").hide()
            self.mediaDetected = False
            self.detect_media_os() # Run detection
        else:
            self.widget("install-os-type-label").hide()
            self.widget("install-os-version-label").hide()
            self.widget("install-os-type").show()
            self.widget("install-os-version").show()

    def _selected_os_row(self):
        box = self.widget("install-os-type")
        model = box.get_model()
        idx = box.get_active()
        if idx == -1:
            return None

        return model[idx]

    def change_os_type(self, box):
        ignore = box
        row = self._selected_os_row()
        if row:
            _type = row[0]
            self.populate_os_variant_model(_type)
            if row[3]:
                self.show_all_os = True
                self.populate_os_type_model()
                return

        variant = self.widget("install-os-version")
        variant.set_active(0)

    def change_os_version(self, box):
        model = box.get_model()
        idx = box.get_active()
        if idx == -1:
            return

        # Get previous
        os_type_list = self.widget("install-os-type")
        os_type_model = os_type_list.get_model()
        type_row = self._selected_os_row()
        if not type_row:
            return
        os_type = type_row[0]

        show_all = model[idx][3]
        if not show_all:
            return

        self.show_all_os = True
        self.populate_os_type_model()

        for idx in range(len(os_type_model)):
            if os_type_model[idx][0] == os_type:
                os_type_list.set_active(idx)
                break

    def toggle_local_cdrom(self, src):
        combo = self.widget("install-local-cdrom-combo")
        is_active = src.get_active()
        if is_active:
            if combo.get_active() != -1:
                # Local CDROM was selected with media preset, detect distro
                self.detect_media_os()

        self.widget("install-local-cdrom-combo").set_sensitive(is_active)

    def toggle_local_iso(self, src):
        uselocal = src.get_active()
        self.widget("install-local-box").set_sensitive(uselocal)
        self.widget("install-local-browse").set_sensitive(uselocal)

    def detect_visibility_changed(self, src, ignore=None):
        is_visible = src.get_property("visible")
        detect_chkbox = self.widget("install-detect-os")
        nodetect_label = self.widget("install-nodetect-label")

        detect_chkbox.set_active(is_visible)
        detect_chkbox.toggled()

        if is_visible:
            nodetect_label.hide()
        else:
            nodetect_label.show()

    def browse_oscontainer(self, ignore1=None, ignore2=None):
        def set_path(ignore, path):
            self.widget("install-oscontainer-fs").set_text(path)
        self._browse_file(set_path, is_media=False, is_dir=True)

    def browse_app(self, ignore1=None, ignore2=None):
        def set_path(ignore, path):
            self.widget("install-app-entry").set_text(path)
        self._browse_file(set_path, is_media=False)

    def browse_import(self, ignore1=None, ignore2=None):
        def set_path(ignore, path):
            self.widget("install-import-entry").set_text(path)
        self._browse_file(set_path, is_media=False)

    def browse_iso(self, ignore1=None, ignore2=None):
        def set_path(ignore, path):
            self.widget("install-local-box").child.set_text(path)
        self._browse_file(set_path, is_media=True)
        self.widget("install-local-box").activate()

    def browse_storage(self, ignore1):
        def set_path(ignore, path):
            self.widget("config-storage-entry").set_text(path)
        self._browse_file(set_path, is_media=False)

    def toggle_enable_storage(self, src):
        self.widget("config-storage-box").set_sensitive(src.get_active())


    def toggle_storage_select(self, src):
        act = src.get_active()
        self.widget("config-storage-browse-box").set_sensitive(act)

    def toggle_macaddr(self, src):
        self.widget("config-macaddr").set_sensitive(src.get_active())

    # Navigation methods
    def set_install_page(self):
        instnotebook = self.widget("install-method-pages")
        detectbox = self.widget("install-detect-os-box")
        osbox = self.widget("install-os-distro-box")
        instpage = self.get_config_install_page()

        # Setting OS value for a container guest doesn't really matter
        # at the moment
        iscontainer = instpage in [INSTALL_PAGE_CONTAINER_APP,
                                   INSTALL_PAGE_CONTAINER_OS]
        osbox.set_property("visible", iscontainer)

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

    def container_install(self):
        return self.get_config_install_page() in [INSTALL_PAGE_CONTAINER_APP,
                                                  INSTALL_PAGE_CONTAINER_OS]
    def skip_disk_page(self):
        return self.get_config_install_page() in [INSTALL_PAGE_IMPORT,
                                                  INSTALL_PAGE_CONTAINER_APP,
                                                  INSTALL_PAGE_CONTAINER_OS]

    def back(self, src_ignore):
        notebook = self.widget("create-pages")
        curpage = notebook.get_current_page()
        next_page = curpage - 1

        if curpage == PAGE_INSTALL:
            self.reset_guest_type()
        elif curpage == PAGE_FINISH and self.skip_disk_page():
            # Skip over storage page
            next_page -= 1

        notebook.set_current_page(next_page)

    def _get_next_pagenum(self, curpage):
        next_page = curpage + 1

        if next_page == PAGE_STORAGE and self.skip_disk_page():
            # Skip storage page for import installs
            next_page += 1

        return next_page

    def forward(self, src_ignore=None):
        notebook = self.widget("create-pages")
        curpage = notebook.get_current_page()

        if self.have_startup_error:
            return

        if curpage == PAGE_INSTALL and self.should_detect_media():
            # Make sure we have detected the OS before validating the page
            self.detect_media_os(forward=True)
            return

        if self.validate(notebook.get_current_page()) != True:
            return

        if curpage == PAGE_NAME:
            self.set_install_page()
            # See if we need to alter our default HV based on install method
            self.guest_from_install_type()

        next_page = self._get_next_pagenum(curpage)

        self.widget("create-forward").grab_focus()
        notebook.set_current_page(next_page)

    def set_page_num_text(self, cur):
        cur += 1
        final = PAGE_FINISH + 1
        if self.skip_disk_page():
            final -= 1
            cur = min(cur, final)

        page_lbl = ("<span color='#59B0E2'>%s</span>" %
                    _("Step %(current_page)d of %(max_page)d") %
                    {'current_page': cur, 'max_page': final})

        self.widget("config-pagenum").set_markup(page_lbl)

    def page_changed(self, ignore1, ignore2, pagenum):
        # Update page number
        self.set_page_num_text(pagenum)

        if pagenum == PAGE_NAME:
            self.widget("create-back").set_sensitive(False)
        else:
            self.widget("create-back").set_sensitive(True)

        if pagenum == PAGE_INSTALL:
            self.detect_media_os()
            self.widget("install-os-distro-box").set_property(
                                                "visible",
                                                not self.container_install())

        if pagenum != PAGE_FINISH:
            self.widget("create-forward").show()
            self.widget("create-finish").hide()
            return

        # PAGE_FINISH
        # This is hidden in reset_state, so that it doesn't distort
        # the size of the wizard if it is expanded by default due to
        # error
        self.widget("config-advanced-expander").show()

        self.widget("create-forward").hide()
        self.widget("create-finish").show()
        self.widget("create-finish").grab_focus()
        self.populate_summary()

        # Repopulate the HV list, so we can make install method relevant
        # changes
        self.populate_hv()

        # Make sure the networking selection takes into account
        # the install method, so we can warn if trying to PXE boot with
        # insufficient network option
        self.check_network_selection()

    def get_graphics_device(self, guest):
        if guest.installer.is_container():
            return

        support_spice = virtinst.support.check_conn_support(guest.conn,
                            virtinst.support.SUPPORT_CONN_HV_GRAPHICS_SPICE)
        if not self._rhel6_defaults():
            support_spice = True

        gtype = self.get_config_graphics_type()
        if (gtype == virtinst.VirtualGraphics.TYPE_SPICE and
            not support_spice):
            logging.debug("Spice requested but HV doesn't support it. "
                          "Using VNC graphics.")
            gtype = virtinst.VirtualGraphics.TYPE_VNC

        return virtinst.VirtualGraphics(conn=guest.conn, type=gtype)

    def get_video_device(self, guest):
        if guest.installer.is_container():
            return
        return virtinst.VirtualVideoDevice(conn=guest.conn)

    def get_sound_device(self, guest):
        if not self.get_config_sound() or guest.installer.is_container():
            return
        return virtinst.VirtualAudio(conn=guest.conn)

    def build_guest(self, installer, name):
        guest = installer.guest_from_installer()
        guest.name = name

        # Generate UUID (makes customize dialog happy)
        try:
            guest.uuid = virtinst.util.uuidToString(virtinst.util.randomUUID())
        except Exception, e:
            self.err.show_err(_("Error setting UUID: %s") % str(e))
            return None

        # Set up default devices
        try:
            devs = []
            devs.append(self.get_graphics_device(guest))
            devs.append(self.get_video_device(guest))
            devs.append(self.get_sound_device(guest))
            for dev in devs:
                if dev:
                    guest.add_device(dev)

        except Exception, e:
            self.err.show_err(_("Error setting up default devices:") + str(e))
            return None

        return guest

    def validate(self, pagenum, oldguest=None):
        try:
            if pagenum == PAGE_NAME:
                return self.validate_name_page()
            elif pagenum == PAGE_INSTALL:
                return self.validate_install_page(oldguest=oldguest)
            elif pagenum == PAGE_MEM:
                return self.validate_mem_page()
            elif pagenum == PAGE_STORAGE:
                return self.validate_storage_page(oldguest=oldguest)
            elif pagenum == PAGE_FINISH:
                return self.validate_final_page()

        except Exception, e:
            self.err.show_err(_("Uncaught error validating install "
                                "parameters: %s") % str(e))
            return

    def validate_name_page(self):
        name = self.get_config_name()

        try:
            g = virtinst.Guest(conn=self.conn.vmm)
            g.name = name
        except Exception, e:
            return self.err.val_err(_("Invalid System Name"), e)

        return True

    def validate_install_page(self, oldguest=None):
        instmethod = self.get_config_install_page()
        installer = None
        location = None
        extra = None
        ks = None
        cdrom = False
        is_import = False
        init = None
        fs = None
        distro, variant, ignore1, ignore2 = self.get_config_os_info()

        if instmethod == INSTALL_PAGE_ISO:
            instclass = virtinst.DistroInstaller
            media = self.get_config_local_media()

            if not media:
                return self.err.val_err(
                                _("An install media selection is required."))

            location = media
            cdrom = True

        elif instmethod == INSTALL_PAGE_URL:
            instclass = virtinst.DistroInstaller
            media, extra, ks = self.get_config_url_info()

            if not media:
                return self.err.val_err(_("An install tree is required."))

            location = media

        elif instmethod == INSTALL_PAGE_PXE:
            instclass = virtinst.PXEInstaller

        elif instmethod == INSTALL_PAGE_IMPORT:
            instclass = virtinst.ImportInstaller
            is_import = True

            import_path = self.get_config_import_path()
            if not import_path:
                return self.err.val_err(
                                _("A storage path to import is required."))

        elif instmethod == INSTALL_PAGE_CONTAINER_APP:
            instclass = virtinst.ContainerInstaller

            init = self.get_config_container_app_path()
            if not init:
                return self.err.val_err(_("An application path is required."))

        elif instmethod == INSTALL_PAGE_CONTAINER_OS:
            instclass = virtinst.ContainerInstaller

            fs = self.get_config_container_fs_path()
            if not fs:
                return self.err.val_err(_("An OS directory path is required."))

        # Build the installer and Guest instance
        try:
            installer = self.build_installer(instclass)
            name = self.get_config_name()
            self.guest = self.build_guest(installer, name)
            if not self.guest:
                return False
        except Exception, e:
            return self.err.val_err(
                        _("Error setting installer parameters."), e)

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

            if init:
                self.guest.installer.init = init

            if fs:
                fsdev = virtinst.VirtualFilesystem(conn=self.guest.conn)
                fsdev.target = "/"
                fsdev.source = fs
                self.guest.add_device(fsdev)

        except Exception, e:
            return self.err.val_err(
                                _("Error setting install media location."), e)

        # OS distro/variant validation
        try:
            if distro:
                self.guest.os_type = distro
            if variant:
                self.guest.os_variant = variant
        except ValueError, e:
            return self.err.val_err(_("Error setting OS information."), e)

        # Kind of wonky, run storage validation now, which will assign
        # the import path. Import installer skips the storage page.
        if is_import:
            if not self.validate_storage_page(oldguest=oldguest):
                return False

        if not oldguest:
            if self.guest.installer.scratchdir_required():
                path = self.guest.installer.scratchdir
            elif instmethod == INSTALL_PAGE_ISO:
                path = self.guest.installer.location
            else:
                path = None

            if path:
                uihelpers.check_path_search_for_qemu(self.topwin,
                                                     self.conn, path)

        # Validation passed, store the install path (if there is one) in
        # gconf
        self.get_config_local_media(store_media=True)
        self.get_config_url_info(store_media=True)
        return True

    def validate_mem_page(self):
        cpus = self.widget("config-cpus").get_value()
        mem  = self.widget("config-mem").get_value()

        # VCPUS
        try:
            self.guest.vcpus = int(cpus)
        except Exception, e:
            return self.err.val_err(_("Error setting CPUs."), e)

        # Memory
        try:
            self.guest.memory = int(mem)
            self.guest.maxmemory = int(mem)
        except Exception, e:
            return self.err.val_err(_("Error setting guest memory."), e)

        return True

    def validate_storage_page(self, oldguest=None):
        use_storage = self.widget("enable-storage").get_active()
        instcd = self.get_config_install_page() == INSTALL_PAGE_ISO

        # CD/ISO install and no disks implies LiveCD
        if instcd:
            self.guest.installer.livecd = not use_storage

        usepath = None
        if oldguest and self.disk:
            usepath = self.disk.path

        if self.disk and self.disk in self.guest.get_devices("disk"):
            self.guest.remove_device(self.disk)
        self.disk = None

        # Validate storage
        if not use_storage:
            return True

        # Make sure default pool is running
        if self.is_default_storage():
            ret = uihelpers.check_default_pool_active(self.topwin, self.conn)
            if not ret:
                return False

        try:
            # This can error out
            diskpath, disksize, sparse = self.get_storage_info()

            if usepath:
                diskpath = usepath
            elif self.is_default_storage() and not oldguest:
                # See if the ideal disk path (/default/pool/vmname.img)
                # exists, and if unused, prompt the use for using it
                ideal = util.get_ideal_path(self.conn,
                                            self.guest.name)
                do_exist = False
                ret = True

                try:
                    do_exist = virtinst.VirtualDisk.path_exists(
                                                        self.conn.vmm, ideal)

                    ret = virtinst.VirtualDisk.path_in_use_by(self.conn.vmm,
                                                              ideal)
                except:
                    logging.exception("Error checking default path usage")

                if do_exist and not ret:
                    do_use = self.err.yes_no(
                        _("The following storage already exists, but is not\n"
                          "in use by any virtual machine:\n\n%s\n\n"
                          "Would you like to reuse this storage?") % ideal)

                    if do_use:
                        diskpath = ideal

            if not diskpath:
                return self.err.val_err(_("A storage path must be specified."))

            disk = virtinst.VirtualDisk(conn=self.conn.vmm,
                                        path=diskpath,
                                        size=disksize,
                                        sparse=sparse)

            fmt = self.config.get_storage_format()
            if (self.is_default_storage() and
                disk.vol_install and
                fmt in disk.vol_install.formats):
                logging.debug("Setting disk format from prefs: %s", fmt)
                disk.vol_install.format = fmt

        except Exception, e:
            return self.err.val_err(_("Storage parameter error."), e)

        isfatal, errmsg = disk.is_size_conflict()
        if not oldguest and not isfatal and errmsg:
            # Fatal errors are reported when setting 'size'
            res = self.err.ok_cancel(_("Not Enough Free Space"), errmsg)
            if not res:
                return False

        # Disk collision
        if not oldguest and disk.is_conflict_disk(self.guest.conn):
            res = self.err.yes_no(_('Disk "%s" is already in use by another '
                                    'guest!' % disk.path),
                                  _("Do you really want to use the disk?"))
            if not res:
                return False

        if not oldguest:
            uihelpers.check_path_search_for_qemu(self.topwin,
                                                 self.conn, disk.path)

        self.disk = disk
        self.guest.add_device(self.disk)

        return True

    def validate_final_page(self):
        # HV + Arch selection
        self.guest.installer.type = self.capsdomain.hypervisor_type
        self.guest.installer.os_type = self.capsguest.os_type
        self.guest.installer.arch = self.capsguest.arch

        nettype, devname, macaddr = self.get_config_network_info()

        if nettype is None:
            # No network device available
            instmethod = self.get_config_install_page()
            methname = None
            if instmethod == INSTALL_PAGE_PXE:
                methname  = "PXE"
            elif instmethod == INSTALL_PAGE_URL:
                methname = "URL"

            if methname:
                return self.err.val_err(
                            _("Network device required for %s install.") %
                            methname)

        nic = uihelpers.validate_network(self.topwin,
                                         self.conn, nettype, devname, macaddr)
        if nic == False:
            return False

        if self.nic and self.nic in self.guest.get_devices("interface"):
            self.guest.remove_device(self.nic)
        if nic:
            self.nic = nic
            self.guest.add_device(self.nic)

        return True


    # Interesting methods
    def build_installer(self, instclass):
        installer = instclass(conn=self.conn.vmm,
                              type=self.capsdomain.hypervisor_type,
                              os_type=self.capsguest.os_type)
        installer.arch = self.capsguest.arch

        return installer

    def guest_from_install_type(self):
        instmeth = self.get_config_install_page()

        if not self.conn.is_xen() and not self.conn.is_test_conn():
            return

        # FIXME: some things are dependent on domain type (vcpu max)
        if instmeth in [INSTALL_PAGE_URL, INSTALL_PAGE_IMPORT]:
            self.change_caps(gtype="xen")

    def reset_guest_type(self):
        self.change_caps()

    def rebuild_guest(self):
        pagenum = 0
        guest = self.guest
        while True:
            self.validate(pagenum, oldguest=guest)
            if pagenum >= PAGE_FINISH:
                break
            pagenum = self._get_next_pagenum(pagenum)

    def finish(self, src_ignore):
        # Validate the final page
        page = self.widget("create-pages").get_current_page()
        if self.validate(page) != True:
            return False

        self.rebuild_guest()
        guest = self.guest
        disk = len(guest.disks) and guest.disks[0]

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

        def start_install():
            if not self.get_config_customize():
                self.start_install(guest)
                return

            self.customize(guest)

        self._check_start_error(start_install)

    def _undo_finish(self, ignore=None):
        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

    def _check_start_error(self, cb, *args, **kwargs):
        try:
            cb(*args, **kwargs)
        except Exception, e:
            self._undo_finish()
            self.err.show_err(_("Error starting installation: ") + str(e))

    def customize(self, guest):
        virtinst_guest = vmmDomainVirtinst(self.conn, guest, self.guest.uuid)

        def cleanup_config_window():
            if self.config_window:
                for s in self.config_window_signals:
                    self.config_window.disconnect(s)
                self.config_window.cleanup()
                self.config_window = None

        def start_install_wrapper(ignore, guest):
            cleanup_config_window()
            if not self.is_visible():
                return
            self._check_start_error(self.start_install, guest)

        def details_closed(ignore):
            cleanup_config_window()
            self._undo_finish()
            self.widget("summary-customize").set_active(False)

        cleanup_config_window()
        self.config_window = vmmDetails(virtinst_guest, self.topwin)
        self.config_window_signals = []
        self.config_window_signals.append(self.config_window.connect(
                                                        "customize-finished",
                                                        start_install_wrapper,
                                                        guest))
        self.config_window_signals.append(self.config_window.connect(
                                                        "details-closed",
                                                         details_closed))
        self.config_window.show()

    def start_install(self, guest):
        progWin = vmmAsyncJob(self.do_install, [guest],
                              _("Creating Virtual Machine"),
                              _("The virtual machine is now being "
                                "created. Allocation of disk storage "
                                "and retrieval of the installation "
                                "images may take a few minutes to "
                                "complete."),
                              self.topwin)
        error, details = progWin.run()

        self.topwin.set_sensitive(True)
        self.topwin.window.set_cursor(gtk.gdk.Cursor(gtk.gdk.TOP_LEFT_ARROW))

        if error:
            error = (_("Unable to complete install: '%s'") % error)
            self.err.show_err(error,
                              details=details)
            self.failed_guest = self.guest
            return

        self.close()

        # Launch details dialog for new VM
        self.emit("action-show-vm", self.conn.get_uri(), guest.uuid)

    def do_install(self, asyncjob, guest):
        meter = asyncjob.get_meter()

        logging.debug("Starting background install process")

        guest.conn = util.dup_conn(self.conn).vmm
        for dev in guest.get_all_devices():
            dev.conn = guest.conn

        guest.start_install(False, meter=meter)
        logging.debug("Install completed")

        # Make sure we pick up the domain object
        self.conn.tick(noStatsUpdate=True)
        vm = self.conn.get_vm(guest.uuid)
        vm.tick()

        if vm.is_shutoff():
            # Domain is already shutdown, but no error was raised.
            # Probably means guest had no 'install' phase, as in
            # for live cds. Try to restart the domain.
            vm.startup()
        elif guest.installer.has_install_phase():
            # Register a status listener, which will restart the
            # guest after the install has finished
            def cb():
                vm.connect_opt_out("status-changed",
                                   self.check_install_status, guest)
                return False
            self.idle_add(cb)


    def check_install_status(self, vm, ignore1, ignore2, virtinst_guest=None):
        if vm.is_crashed():
            logging.debug("VM crashed, cancelling install plans.")
            return True

        if not vm.is_shutoff():
            return

        try:
            if virtinst_guest:
                continue_inst = virtinst_guest.get_continue_inst()

                if continue_inst:
                    logging.debug("VM needs a 2 stage install, continuing.")
                    # Continue the install, then reconnect this opt
                    # out handler, removing the virtinst_guest which
                    # will force one final restart.
                    virtinst_guest.continue_install()

                    vm.connect_opt_out("status-changed",
                                       self.check_install_status, None)
                    return True

            if vm.get_install_abort():
                logging.debug("User manually shutdown VM, not restarting "
                              "guest after install.")
                return True

            logging.debug("Install should be completed, starting VM.")
            vm.startup()
        except Exception, e:
            self.err.show_err(_("Error continue install: %s") % str(e))

        return True

    def pretty_storage(self, size):
        return "%.1f GB" % float(size)

    def pretty_memory(self, mem):
        return "%d MB" % (mem / 1024.0)


    # Distro detection methods

    def set_distro_labels(self, distro, ver):
        # Helper to set auto detect result labels
        if not self.is_detect_active():
            return

        self.widget("install-os-type-label").set_text(distro)
        self.widget("install-os-version-label").set_text(ver)

    def set_os_val(self, os_widget, value):
        # Helper method to set the OS Type/Variant selections to the passed
        # values, or -1 if not present.
        model = os_widget.get_model()

        def set_val():
            idx = 0
            for idx in range(0, len(model)):
                row = model[idx]
                if value and row[0] == value:
                    break

                if idx == len(os_widget.get_model()) - 1:
                    idx = -1

            os_widget.set_active(idx)
            if idx == -1:
                os_widget.set_active(0)

            if idx >= 0:
                return row[1]
            if self.show_all_os:
                return None

        ret = set_val()
        if ret:
            return ret

        # Trigger the last element in the list, which turns on show_all_os
        os_widget.set_active(len(model) - 1)
        ret = set_val()
        if ret:
            return ret
        return _("Unknown")

    def set_distro_selection(self, distro, ver):
        # Wrapper to change OS Type/Variant values, and update the distro
        # detection labels
        if not self.is_detect_active():
            return

        dl = self.set_os_val(self.widget("install-os-type"), distro)
        vl = self.set_os_val(self.widget("install-os-version"), ver)
        self.set_distro_labels(dl, vl)

    def check_detection(self, idx, forward):
        results = None
        try:
            base = _("Detecting")

            if not self.detectedDistro or (idx >= (DETECT_TIMEOUT * 2)):
                detect_str = base + ("." * ((idx % 3) + 1))
                self.set_distro_labels(detect_str, detect_str)

                self.timeout_add(500, self.check_detection,
                                      idx + 1, forward)
                return

            results = self.detectedDistro
        except:
            logging.exception("Error in distro detect timeout")

        results = results or (None, None)
        self.widget("create-forward").set_sensitive(True)
        self.mediaDetected = True
        self.detecting = False
        logging.debug("Finished OS detection.")
        self.set_distro_selection(*results)
        if forward:
            self.idle_add(self.forward, ())

    def start_detection(self, forward):
        if self.detecting:
            return

        media = self.get_config_detectable_media()
        if not media:
            return

        self.detectedDistro = None

        logging.debug("Starting OS detection thread for media=%s", media)
        self.widget("create-forward").set_sensitive(False)

        detectThread = threading.Thread(target=self.actually_detect,
                                        name="Actual media detection",
                                        args=(media,))
        detectThread.setDaemon(True)
        detectThread.start()

        self.check_detection(0, forward)

    def actually_detect(self, media):
        try:
            installer = self.build_installer(virtinst.DistroInstaller)
            installer.location = media

            self.detectedDistro = installer.detect_distro()
        except:
            logging.exception("Error detecting distro.")
            self.detectedDistro = (None, None)

    def _rhel6_defaults(self):
        emu = None
        if self.guest:
            emu = self.guest.emulator
        elif self.capsdomain:
            emu = self.capsdomain.emulator

        ret = self.conn.rhel6_defaults(emu)
        return ret

    def _browse_file(self, callback, is_media=False, is_dir=False):
        if is_media:
            reason = self.config.CONFIG_DIR_ISO_MEDIA
        elif is_dir:
            reason = self.config.CONFIG_DIR_FS
        else:
            reason = self.config.CONFIG_DIR_IMAGE

        if self.storage_browser == None:
            self.storage_browser = vmmStorageBrowser(self.conn)

        self.storage_browser.rhel6_defaults = self._rhel6_defaults()

        self.storage_browser.set_vm_name(self.get_config_name())
        self.storage_browser.set_finish_cb(callback)
        self.storage_browser.set_browse_reason(reason)
        self.storage_browser.show(self.topwin, self.conn)

    def show_help(self, ignore):
        # No help available yet.
        pass

vmmGObjectUI.type_register(vmmCreate)
vmmCreate.signal_new(vmmCreate, "action-show-vm", [str, str])
vmmCreate.signal_new(vmmCreate, "action-show-help", [str])
