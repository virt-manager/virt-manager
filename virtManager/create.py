#
# Copyright (C) 2008, 2013, 2014 Red Hat, Inc.
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

import logging
import threading
import time

# pylint: disable=E0611
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk
# pylint: enable=E0611

import virtinst
from virtinst import util

from virtManager import uihelpers
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

STABLE_OS_SUPPORT = [
    "rhel3", "rhel4", "rhel5.4", "rhel6",
    "win2k3", "winxp", "win2k8", "vista", "win7",
]


def pretty_arch(_a):
    if _a == "armv7l":
        return "arm"
    return _a


class vmmCreate(vmmGObjectUI):
    __gsignals__ = {
        "action-show-domain": (GObject.SignalFlags.RUN_FIRST, None, [str, str]),
    }

    def __init__(self, engine):
        vmmGObjectUI.__init__(self, "create.ui", "vmm-create")
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
        self.detectedDistro = -1
        self.detecting = False
        self.mediaDetected = False
        self.show_all_os = False

        # 'Guest' class from the previous failed install
        self.failed_guest = None

        # Whether there was an error at dialog startup
        self.have_startup_error = False

        # 'Configure before install' window
        self.config_window = None
        self.config_window_signals = []

        self.builder.connect_signals({
            "on_vmm_newcreate_delete_event" : self.close,

            "on_create_cancel_clicked": self.close,
            "on_create_back_clicked" : self.back,
            "on_create_forward_clicked" : self.forward,
            "on_create_finish_clicked" : self.finish,
            "on_create_pages_switch_page": self.page_changed,

            "on_create_vm_name_activate": self.forward,
            "on_create_conn_changed": self.conn_changed,
            "on_method_changed": self.method_changed,
            "on_config_machine_changed": self.machine_changed,

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

            "on_config_kernel_browse_clicked": self.browse_kernel,
            "on_config_initrd_browse_clicked": self.browse_initrd,
            "on_config_dtb_browse_clicked": self.browse_dtb,

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
        return self.topwin.get_visible()

    def show(self, parent, uri=None):
        logging.debug("Showing new vm wizard")

        if not self.is_visible():
            self.reset_state(uri)
            self.topwin.set_transient_for(parent)

        self.topwin.present()

    def close(self, ignore1=None, ignore2=None):
        logging.debug("Closing new vm wizard")
        self.topwin.hide()

        if self.config_window:
            self.config_window.close()
        if self.storage_browser:
            self.storage_browser.close()

        return 1

    def _cleanup(self):
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
            self.widget("arch-expander").hide()

        self.widget("startup-error").set_text("Error: %s" % error)
        return False

    def startup_warning(self, error):
        self.widget("startup-error-box").show()
        self.widget("startup-error").set_text("Warning: %s" % error)

    def set_initial_state(self):
        self.widget("create-pages").set_show_tabs(False)
        self.widget("install-method-pages").set_show_tabs(False)

        blue = Gdk.Color.parse("#0072A8")[1]
        self.widget("header").modify_bg(Gtk.StateType.NORMAL, blue)

        # Connection list
        self.widget("create-conn-label").set_text("")
        self.widget("startup-error").set_text("")
        conn_list = self.widget("create-conn")
        conn_model = Gtk.ListStore(str, str)
        conn_list.set_model(conn_model)
        text = Gtk.CellRendererText()
        conn_list.pack_start(text, True)
        conn_list.add_attribute(text, 'text', 1)

        # ISO media list
        iso_list = self.widget("install-local-box")
        iso_model = Gtk.ListStore(str)
        iso_list.set_model(iso_model)
        iso_list.set_entry_text_column(0)
        self.widget("install-local-box").get_child().connect("activate",
                                                    self.detect_media_os)

        # Lists for the install urls
        media_url_list = self.widget("install-url-box")
        media_url_model = Gtk.ListStore(str)
        media_url_list.set_model(media_url_model)
        media_url_list.set_entry_text_column(0)
        self.widget("install-url-box").get_child().connect("activate",
                                                    self.detect_media_os)

        ks_url_list = self.widget("install-ks-box")
        ks_url_model = Gtk.ListStore(str)
        ks_url_list.set_model(ks_url_model)
        ks_url_list.set_entry_text_column(0)

        def sep_func(model, it, combo):
            ignore = combo
            return model[it][2]

        # Lists for distro type + variant
        # [os value, os label, is seperator, is 'show all'
        os_type_list = self.widget("install-os-type")
        os_type_model = Gtk.ListStore(str, str, bool, bool)
        os_type_list.set_model(os_type_model)
        text = Gtk.CellRendererText()
        os_type_list.pack_start(text, True)
        os_type_list.add_attribute(text, 'text', 1)
        os_type_list.set_row_separator_func(sep_func, os_type_list)

        os_variant_list = self.widget("install-os-version")
        os_variant_model = Gtk.ListStore(str, str, bool, bool)
        os_variant_list.set_model(os_variant_model)
        text = Gtk.CellRendererText()
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
        # [value, label]
        archModel = Gtk.ListStore(str, str)
        archList = self.widget("config-arch")
        text = Gtk.CellRendererText()
        archList.pack_start(text, True)
        archList.add_attribute(text, 'text', 1)
        archList.set_model(archModel)
        archList.set_row_separator_func(
            lambda m, i, ignore: m[i][0] is None, None)

        hyperModel = Gtk.ListStore(str, str)
        hyperList = self.widget("config-hv")
        text = Gtk.CellRendererText()
        hyperList.pack_start(text, True)
        hyperList.add_attribute(text, 'text', 0)
        hyperList.set_model(hyperModel)

        model = Gtk.ListStore(str)
        lst = self.widget("config-machine")
        text = Gtk.CellRendererText()
        lst.pack_start(text, True)
        lst.add_attribute(text, 'text', 0)
        lst.set_model(model)
        lst.set_row_separator_func(lambda m, i, ignore: m[i][0] is None, None)

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

        # Name page state
        self.widget("create-vm-name").set_text("")
        self.widget("method-local").set_active(True)
        self.widget("create-conn").set_active(-1)
        activeconn = self.populate_conn_list(urihint)
        self.widget("arch-expander").set_expanded(False)

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

        self.widget("install-local-box").get_child().set_text("")
        iso_model = self.widget("install-local-box").get_model()
        self.populate_media_model(iso_model, self.config.get_iso_paths())

        # Install URL
        self.widget("install-urlopts-entry").set_text("")
        self.widget("install-ks-box").get_child().set_text("")
        self.widget("install-url-box").get_child().set_text("")
        self.widget("install-url-options").set_expanded(False)
        urlmodel = self.widget("install-url-box").get_model()
        ksmodel  = self.widget("install-ks-box").get_model()
        self.populate_media_model(urlmodel, self.config.get_media_urls())
        self.populate_media_model(ksmodel, self.config.get_kickstart_urls())
        self.set_distro_labels("-", "-", force=True)

        # Install import
        self.widget("install-import-entry").set_text("")
        self.widget("config-kernel").set_text("")
        self.widget("config-initrd").set_text("")
        self.widget("config-dtb").set_text("")

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
        uihelpers.update_host_space(self.conn, label_widget)
        self.widget("enable-storage").set_active(True)
        self.widget("config-storage-create").set_active(True)
        self.widget("config-storage-size").set_value(8)
        self.widget("config-storage-entry").set_text("")
        self.widget("config-storage-nosparse").set_active(True)

        fmt = self.conn.get_default_storage_format()
        can_alloc = fmt in ["raw"]
        self.widget("config-storage-nosparse").set_active(can_alloc)
        self.widget("config-storage-nosparse").set_sensitive(can_alloc)
        self.widget("config-storage-nosparse").set_tooltip_text(
            not can_alloc and
            (_("Disk format '%s' does not support full allocation.") % fmt) or
            "")

        # Final page
        self.widget("summary-customize").set_active(False)

        # Make sure window is a sane size
        self.topwin.resize(1, 1)

    def set_caps_state(self):
        # State that is dependent on when capsguest changes

        # Helper state
        is_local = not self.conn.is_remote()
        is_storage_capable = self.conn.is_storage_capable()
        can_storage = (is_local or is_storage_capable)
        is_pv = (self.capsguest.os_type == "xen")
        is_container = self.conn.is_container()
        can_remote_url = self.conn.get_backend().support_remote_url_install()

        installable_arch = (self.capsguest.arch in
                            ["i686", "x86_64", "ppc64", "ia64"])

        # Install Options
        method_tree = self.widget("method-tree")
        method_pxe = self.widget("method-pxe")
        method_local = self.widget("method-local")
        method_import = self.widget("method-import")
        method_container_app = self.widget("method-container-app")

        method_tree.set_sensitive((is_local or can_remote_url) and
                                  installable_arch)
        method_local.set_sensitive(not is_pv and can_storage and
                                   installable_arch)
        method_pxe.set_sensitive(not is_pv and installable_arch)
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

        if not installable_arch:
            msg = (_("Architecture '%s' is not installable") %
                   self.capsguest.arch)
            tree_tt = msg
            local_tt = msg
            pxe_tt = msg

        if not any([w.get_active() and w.get_sensitive()
                    for w in virt_methods]):
            for w in virt_methods:
                if w.get_sensitive():
                    w.set_active(True)
                    break

        if not (is_container or
                [w for w in virt_methods if w.get_sensitive()]):
            return self.startup_error(
                    _("No install methods available for this connection."),
                    hideinstall=False)

        method_tree.set_tooltip_text(tree_tt or "")
        method_local.set_tooltip_text(local_tt or "")
        method_pxe.set_tooltip_text(pxe_tt or "")
        method_import.set_tooltip_text(import_tt or "")

        # Container install options
        method_container_app.set_active(True)
        self.widget("virt-install-box").set_visible(not is_container)
        self.widget("container-install-box").set_visible(is_container)

        show_kernel = (self.capsguest.arch not in ["x86_64", "i686"])
        show_dtb = ("arm" in self.capsguest.arch or
                    "microblaze" in self.capsguest.arch or
                    "ppc" in self.capsguest.arch)
        self.widget("config-kernel-box").set_visible(show_kernel)
        uihelpers.set_grid_row_visible(self.widget("config-dtb"), show_dtb)

    def set_conn_state(self):
        # Update all state that has some dependency on the current connection
        self.conn.schedule_priority_tick(pollnet=True,
                                         pollpool=True, polliface=True,
                                         pollnodedev=True, pollmedia=True)

        self.widget("install-box").show()
        self.widget("startup-error-box").hide()
        self.widget("create-forward").set_sensitive(True)

        if self.conn.caps.no_install_options():
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
        self.caps = self.conn.caps
        self.change_caps()
        self.populate_hv()
        self.populate_arch()

        show_arch = (self.widget("config-hv").get_visible() or
                     self.widget("config-arch").get_visible() or
                     self.widget("config-machine").get_visible())
        uihelpers.set_grid_row_visible(self.widget("arch-expander"), show_arch)

        if self.conn.is_xen():
            if self.conn.caps.hw_virt_supported():
                if self.conn.caps.is_bios_virt_disabled():
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
            if not self.conn.caps.is_kvm_available():
                error = _("KVM is not available. This may mean the KVM "
                 "package is not installed, or the KVM kernel modules "
                 "are not loaded. Your virtual machines may perform poorly.")
                self.startup_warning(error)

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
            cdrom_warn.set_tooltip_text(self.conn.mediadev_error)
        else:
            cdrom_warn.hide()

        # Don't select physical CDROM if no valid media is present
        use_cd = (cdrom_list.get_active() >= 0)
        if use_cd:
            cdrom_option.set_active(True)
        else:
            iso_option.set_active(True)

        # Only allow ISO option for remote VM
        is_local = not self.conn.is_remote()
        is_storage_capable = self.conn.is_storage_capable()
        can_storage = (is_local or is_storage_capable)
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
        phys_cpus = int(self.conn.host_active_processor_count())
        cmax = phys_cpus
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
        storage_area.set_tooltip_text(storage_tooltip or "")

        # Networking
        net_list        = self.widget("config-netdev")
        net_warn_icon   = self.widget("config-netdev-warn-icon")
        net_warn_box    = self.widget("config-netdev-warn-box")
        net_expander    = self.widget("config-advanced-expander")
        net_warn_icon.hide()
        net_warn_box.hide()
        net_expander.set_expanded(False)

        do_warn = uihelpers.populate_network_list(net_list, self.conn, False)
        self.set_net_warn(self.conn.netdev_error or do_warn,
                          self.conn.netdev_error, True)

        newmac = virtinst.VirtualNetworkInterface.generate_mac(
                self.conn.get_backend())
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
            net_warn_icon.set_visible(bool(show_warn))
            if msg:
                net_warn_icon.set_tooltip_text(show_warn and msg or "")
        else:
            net_warn_box.set_visible(show_warn)
            markup = show_warn and ("<small>%s</small>" % msg) or ""
            net_warn_label.set_markup(markup)

    def populate_hv(self):
        hv_list = self.widget("config-hv")
        model = hv_list.get_model()
        model.clear()

        default = 0
        guests = self.caps.guests[:]
        if not (self.conn.is_xen() or self.conn.is_test_conn()):
            guests = []

        for guest in self.caps.guests:
            gtype = guest.os_type
            if not guest.domains:
                continue
            dom = guest.domains[0]
            domtype = dom.hypervisor_type
            label = uihelpers.pretty_hv(gtype, domtype)

            # Don't add multiple rows for each arch
            for m in model:
                if m[0] == label:
                    label = None
                    break
            if label is None:
                continue

            # Determine if this is the default given by guest_lookup
            if (gtype == self.capsguest.os_type and
                self.capsdomain.hypervisor_type == domtype):
                default = len(model)

            model.append([label, gtype])

        show = bool(guests)
        uihelpers.set_grid_row_visible(hv_list, show)
        if show:
            hv_list.set_active(default)

    def populate_arch(self):
        arch_list = self.widget("config-arch")
        model = arch_list.get_model()
        model.clear()

        default = 0
        archs = []
        for guest in self.caps.guests:
            if guest.os_type == self.capsguest.os_type:
                archs.append(guest.arch)

        # Combine x86/i686 to avoid confusion
        if (self.conn.caps.host.cpu.arch == "x86_64" and
            "x86_64" in archs and "i686" in archs):
            archs.remove("i686")
        archs.sort()

        prios = ["x86_64", "i686", "armv7l", "ppc64"]
        if self.conn.caps.host.cpu.arch not in prios:
            prios = []
        else:
            for p in prios[:]:
                if p not in archs:
                    prios.remove(p)
                else:
                    archs.remove(p)
        if prios:
            if archs:
                prios += [None]
            archs = prios + archs

        default = 0
        if self.capsguest.arch in archs:
            default = archs.index(self.capsguest.arch)

        for arch in archs:
            model.append([arch, pretty_arch(arch)])

        show = not (len(archs) < 2)
        uihelpers.set_grid_row_visible(arch_list, show)
        arch_list.set_active(default)

    def populate_machine(self):
        lst = self.widget("config-machine")
        model = lst.get_model()
        model.clear()

        machines = self.capsdomain.machines
        if self.capsguest.arch in ["i686", "x86_64"]:
            machines = []
        machines.sort()

        defmachine = None
        prios = []
        if self.capsguest.arch == "armv7l":
            defmachine = "vexpress-a9"
            prios = ["vexpress-a9", "vexpress-a15", "highbank", "midway"]
        elif self.capsguest.arch == "ppc64":
            defmachine = "pseries"
            prios = ["pseries"]

        for p in prios[:]:
            if p not in machines:
                prios.remove(p)
            else:
                machines.remove(p)
        if prios:
            machines = prios + [None] + machines

        default = 0
        if defmachine and defmachine in machines:
            default = machines.index(defmachine)

        for m in machines:
            model.append([m])

        show = (len(machines) > 1)
        uihelpers.set_grid_row_visible(lst, show)
        if show:
            lst.set_active(default)
        else:
            lst.emit("changed")

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
        filtervars = (self._stable_defaults() and
                      STABLE_OS_SUPPORT or
                      None)

        types = virtinst.osdict.list_os(list_types=True)
        if not filtervars:
            # Kind of a hack, just show linux + windows by default since
            # that's all 98% of people care about
            supportl = ["linux", "windows"]
        else:
            supportl = []
            for t in types:
                l = virtinst.osdict.list_os(typename=t.name,
                                            only_supported=True,
                                            filtervars=filtervars)
                if l:
                    supportl.append(t.name)

        self._add_os_row(model, None, _("Generic"), True)

        for t in types:
            supported = (t.name in supportl)
            self._add_os_row(model, t.name, t.label, supported)

        # Add sep
        self._add_os_row(model, sep=True)
        # Add action option
        self._add_os_row(model, label=_("Show all OS options"), action=True)
        widget.set_active(0)


    def populate_os_variant_model(self, _type):
        model = self.widget("install-os-version").get_model()
        model.clear()
        if not _type:
            self._add_os_row(model, None, _("Generic"), True)
            return

        filtervars = (self._stable_defaults() and
                      STABLE_OS_SUPPORT or
                      None)
        preferred = self.config.preferred_distros

        variants = virtinst.osdict.list_os(typename=_type,
                                           sortpref=preferred)
        supportl = virtinst.osdict.list_os(typename=_type,
                                           sortpref=preferred,
                                           only_supported=True,
                                           filtervars=filtervars)

        for v in variants:
            supported = v in supportl
            self._add_os_row(model, v.name, v.label, supported)

        # Add sep
        self._add_os_row(model, sep=True)
        # Add action option
        self._add_os_row(model, label=_("Show all OS options"), action=True)

    def populate_media_model(self, model, urls):
        model.clear()
        if urls is not None:
            for url in urls:
                model.append([url])


    def change_caps(self, gtype=None, arch=None):
        if gtype is None:
            # If none specified, prefer HVM. This way, the default install
            # options won't be limited because we default to PV. If hvm not
            # supported, differ to guest_lookup
            for g in self.caps.guests:
                if g.os_type == "hvm":
                    gtype = "hvm"
                    break

        (newg, newdom) = self.caps.guest_lookup(os_type=gtype,
                                                accelerated=True,
                                                arch=arch)

        if (self.capsguest and self.capsdomain and
            (newg.arch == self.capsguest.arch and
            newg.os_type == self.capsguest.os_type)):
            # No change
            return

        self.capsguest = newg
        self.capsdomain = newdom
        logging.debug("Guest type set to os_type=%s, arch=%s, dom_type=%s",
                      self.capsguest.os_type,
                      self.capsguest.arch,
                      self.capsdomain.hypervisor_type)
        self.populate_machine()
        self.set_caps_state()

    def populate_summary(self):
        distro, version, dlabel, vlabel = self.get_config_os_info()
        mem = self.pretty_memory(int(self.guest.memory))
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
        disks = self.guest.get_devices("disk")
        if disks:
            disk = disks[0]
            storage = "%s" % self.pretty_storage(disk.get_size())
            storage += " " + (storagetmpl % disk.path)
        elif len(self.guest.get_devices("filesystem")):
            fs = self.guest.get_devices("filesystem")[0]
            storage = storagetmpl % fs.source
        elif self.guest.os.is_container():
            storage = _("Host filesystem")
        else:
            storage = _("None")

        osstr = ""
        have_os = True
        if self.guest.os.is_container():
            osstr = _("Linux")
        elif not distro:
            osstr = _("Generic")
            have_os = False
        elif not version:
            osstr = _("Generic") + " " + dlabel
            have_os = False
        else:
            osstr = vlabel

        self.widget("finish-warn-os").set_visible(not have_os)
        self.widget("summary-os").set_text(osstr)
        self.widget("summary-install").set_text(install)
        self.widget("summary-mem").set_text(mem)
        self.widget("summary-cpu").set_text(cpu)
        self.widget("summary-storage").set_markup(storage)

    # get_* methods
    def get_config_name(self):
        return self.widget("create-vm-name").get_text()

    def get_config_machine(self):
        lst = self.widget("config-machine")
        idx = lst.get_active()
        if not lst.get_visible() or idx == -1:
            return None
        return lst.get_model()[idx][0]

    def is_install_page(self):
        notebook = self.widget("create-pages")
        curpage = notebook.get_current_page()
        return curpage == PAGE_INSTALL

    def get_config_install_page(self):
        if self.widget("virt-install-box").get_visible():
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

        return (distro and str(distro),
                variant and str(variant),
                str(dlabel), str(vlabel))

    def get_config_local_media(self, store_media=False):
        if self.widget("install-local-cdrom").get_active():
            cd = self.widget("install-local-cdrom-combo")
            idx = cd.get_active()
            model = cd.get_model()
            if idx != -1:
                return model[idx][uihelpers.OPTICAL_DEV_PATH]
            return None
        else:
            ret = self.widget("install-local-box").get_child().get_text()
            if ret and store_media:
                self.config.add_iso_path(ret)
            return ret

    def get_config_detectable_media(self):
        instpage = self.get_config_install_page()
        media = ""

        if instpage == INSTALL_PAGE_ISO:
            media = self.get_config_local_media()
        elif instpage == INSTALL_PAGE_URL:
            media = self.widget("install-url-box").get_child().get_text()
        elif instpage == INSTALL_PAGE_IMPORT:
            media = self.widget("install-import-entry").get_text()

        return media

    def get_config_url_info(self, store_media=False):
        media = self.widget("install-url-box").get_child().get_text().strip()
        extra = self.widget("install-urlopts-entry").get_text().strip()
        ks = self.widget("install-ks-box").get_child().get_text().strip()

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
            disks = self.failed_guest.get_devices("disk")
            if disks:
                return disks[0].path

        return uihelpers.get_default_path(self.conn, name)

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

    def machine_changed(self, ignore):
        machine = self.get_config_machine()
        show_dtb_virtio = (self.capsguest.arch == "armv7l" and
                           machine in ["vexpress-a9", "vexpress-15"])
        uihelpers.set_grid_row_visible(
            self.widget("config-dtb-warn-virtio"), show_dtb_virtio)

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

            if (ntype is None or
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

        self.change_caps(row[1])
        self.populate_arch()

    def arch_changed(self, src):
        idx = src.get_active()
        if idx < 0:
            return

        arch = src.get_model()[idx][0]
        self.change_caps(self.capsguest.os_type, arch)

    def url_box_changed(self, ignore):
        # If the url_entry has focus, don't fire detect_media_os, it means
        # the user is probably typing
        self.mediaDetected = False
        if self.widget("install-url-box").get_child().has_focus():
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

        self.widget("install-os-type-label").set_visible(dodetect)
        self.widget("install-os-version-label").set_visible(dodetect)
        self.widget("install-os-type").set_visible(not dodetect)
        self.widget("install-os-version").set_visible(not dodetect)

        if dodetect:
            self.mediaDetected = False
            self.detect_media_os()

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
        is_visible = src.get_visible()
        detect_chkbox = self.widget("install-detect-os")
        nodetect_label = self.widget("install-nodetect-label")

        detect_chkbox.set_active(is_visible)
        detect_chkbox.toggled()

        if is_visible:
            nodetect_label.hide()
        else:
            nodetect_label.show()

    def browse_oscontainer(self, ignore):
        self._browse_file("install-oscontainer-fs", is_dir=True)
    def browse_app(self, ignore):
        self._browse_file("install-app-entry")
    def browse_import(self, ignore):
        self._browse_file("install-import-entry")
    def browse_iso(self, ignore):
        def set_path(ignore, path):
            self.widget("install-local-box").get_child().set_text(path)
        self._browse_file(None, cb=set_path, is_media=True)
        self.widget("install-local-box").activate()
    def browse_storage(self, ignore):
        self._browse_file("config-storage-entry")
    def browse_kernel(self, ignore):
        self._browse_file("config-kernel")
    def browse_initrd(self, ignore):
        self._browse_file("config-initrd")
    def browse_dtb(self, ignore):
        self._browse_file("config-dtb")

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
        osbox.set_visible(iscontainer)

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

        if curpage == PAGE_FINISH and self.skip_disk_page():
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

        if self.validate(curpage) is not True:
            return

        if curpage == PAGE_NAME:
            self.set_install_page()

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

        self.widget("header-pagenum").set_markup(page_lbl)

    def page_changed(self, ignore1, ignore2, pagenum):
        # Update page number
        self.set_page_num_text(pagenum)

        self.widget("create-back").set_sensitive(pagenum != PAGE_NAME)
        self.widget("create-forward").set_visible(pagenum != PAGE_FINISH)
        self.widget("create-finish").set_visible(pagenum == PAGE_FINISH)

        if pagenum == PAGE_INSTALL:
            self.detect_media_os()
            self.widget("install-os-distro-box").set_visible(
                not self.container_install())
        elif pagenum == PAGE_FINISH:
            self.widget("create-finish").grab_focus()
            self.populate_summary()
            self.widget("config-netdev").emit("changed")

        for nr in range(self.widget("create-pages").get_n_pages()):
            page = self.widget("create-pages").get_nth_page(nr)
            page.set_visible(nr == pagenum)

    def get_graphics_device(self, guest):
        if guest.os.is_container():
            return
        if guest.os.arch not in ["x86_64", "i686", "ppc64"]:
            return

        guest.default_graphics_type = self.config.get_graphics_type()
        return virtinst.VirtualGraphics(guest.conn)

    def build_guest(self, variant):
        guest = self.conn.caps.build_virtinst_guest(
            self.conn.get_backend(), self.capsguest, self.capsdomain)
        guest.os.machine = self.get_config_machine()

        # Generate UUID (makes customize dialog happy)
        try:
            guest.uuid = util.randomUUID(guest.conn)
        except Exception, e:
            self.err.show_err(_("Error setting UUID: %s") % str(e))
            return None

        # OS distro/variant validation
        try:
            if variant:
                guest.os_variant = variant
        except ValueError, e:
            self.err.show_err(_("Error setting OS information."), e)
            return None

        # Set up default devices
        try:
            gdev = self.get_graphics_device(guest)
            if gdev:
                guest.add_device(gdev)

            guest.add_default_video_device()
            guest.add_default_input_device()
            guest.add_default_console_device()
            guest.add_default_usb_controller()
            guest.add_default_channels()

            if self.config.get_new_vm_sound():
                guest.add_default_sound_device()

            if (guest.conn.is_qemu() and
                guest.type == "kvm" and
                guest.os.is_x86() and
                guest.os.arch == guest.conn.caps.host.cpu.arch):
                cpu_type = self.config.get_default_cpu_setting()

                if cpu_type == "hv-default":
                    pass
                elif cpu_type == "host-cpu-model":
                    if guest.conn.caps.host.cpu.model:
                        guest.cpu.model = guest.conn.caps.host.cpu.model
                elif cpu_type == "host-model":
                    # host-model has known issues, so use our 'copy cpu'
                    # behavior until host-model does what we need
                    guest.cpu.copy_host_cpu()
                else:
                    raise RuntimeError("Unknown cpu default '%s'" % cpu_type)

        except Exception, e:
            self.err.show_err(_("Error setting up default devices:") + str(e))
            return None

        return guest

    def validate(self, pagenum):
        try:
            if pagenum == PAGE_NAME:
                return self.validate_name_page()
            elif pagenum == PAGE_INSTALL:
                return self.validate_install_page()
            elif pagenum == PAGE_MEM:
                return self.validate_mem_page()
            elif pagenum == PAGE_STORAGE:
                return self.validate_storage_page()
            elif pagenum == PAGE_FINISH:
                return self.validate_final_page()
        except Exception, e:
            self.err.show_err(_("Uncaught error validating install "
                                "parameters: %s") % str(e))
            return

    def validate_name_page(self):
        # We just set this here because it's needed soon after for distro
        # detction. But the 'real' self.guest is created in validate_install,
        # and it just uses build_guest, so don't ever add any other guest
        # altering here.
        self.guest = self.build_guest(None)
        if not self.guest:
            return False
        return True

    def _generate_default_name(self, distro, variant):
        force_num = False
        if self.guest.os.is_container():
            basename = "container"
            force_num = True
        elif not distro:
            basename = "vm"
            force_num = True
        elif not variant:
            basename = distro
        else:
            basename = variant

        if self.guest.os.arch != self.conn.caps.host.cpu.arch:
            basename += "-%s" % pretty_arch(self.guest.os.arch)
            force_num = False

        return util.generate_name(basename,
            self.conn.get_backend().lookupByName,
            start_num=force_num and 1 or 2, force_num=force_num,
            sep=not force_num and "-" or "",
            collidelist=[vm.get_name() for vm in self.conn.vms.values()])

    def validate_install_page(self):
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
            # Overwrite the guest
            installer = instclass(self.conn.get_backend())
            self.guest = self.build_guest(variant or distro)
            if not self.guest:
                return False
            self.guest.installer = installer
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
                self.guest.os.init = init

            if fs:
                fsdev = virtinst.VirtualFilesystem(self.guest.conn)
                fsdev.target = "/"
                fsdev.source = fs
                self.guest.add_device(fsdev)
        except Exception, e:
            return self.err.val_err(
                                _("Error setting install media location."), e)

        # Setting kernel
        if instmethod == INSTALL_PAGE_IMPORT:
            kernel = self.widget("config-kernel").get_text() or None
            kargs = self.widget("config-kernel-args").get_text() or None
            initrd = self.widget("config-initrd").get_text() or None
            dtb = self.widget("config-dtb").get_text() or None

            if not self.widget("config-dtb").get_visible():
                dtb = None
            if not self.widget("config-kernel").get_visible():
                kernel = None
                initrd = None
                kargs = None

            self.guest.os.kernel = kernel
            self.guest.os.initrd = initrd
            self.guest.os.dtb = dtb
            self.guest.os.kernel_args = kargs

            require_kernel = ("arm" in self.capsguest.arch)
            if require_kernel and not kernel:
                return self.err.val_err(
                    _("A kernel is required for %s guests.") %
                    self.capsguest.arch)

        try:
            name = self._generate_default_name(distro, variant)
            self.widget("create-vm-name").set_text(name)
            self.guest.name = name
        except Exception, e:
            return self.err.val_err(_("Error setting default name."), e)

        # Kind of wonky, run storage validation now, which will assign
        # the import path. Import installer skips the storage page.
        if is_import:
            if not self.validate_storage_page():
                return False

        if self.guest.installer.scratchdir_required():
            path = util.make_scratchdir(self.guest.conn, self.guest.type)
        elif instmethod == INSTALL_PAGE_ISO:
            path = self.guest.installer.location
        else:
            path = None

        if path:
            uihelpers.check_path_search_for_qemu(self.err, self.conn, path)

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
            self.guest.memory = int(mem) * 1024
            self.guest.maxmemory = int(mem) * 1024
        except Exception, e:
            return self.err.val_err(_("Error setting guest memory."), e)

        return True

    def validate_storage_page(self):
        use_storage = self.widget("enable-storage").get_active()
        instcd = self.get_config_install_page() == INSTALL_PAGE_ISO
        conn = self.conn.get_backend()

        # CD/ISO install and no disks implies LiveCD
        if instcd:
            self.guest.installer.livecd = not use_storage

        if self.disk and self.disk in self.guest.get_devices("disk"):
            self.guest.remove_device(self.disk)
        self.disk = None

        # Validate storage
        if not use_storage:
            return True

        # Make sure default pool is running
        if self.is_default_storage():
            ret = uihelpers.check_default_pool_active(self.err, self.conn)
            if not ret:
                return False

        try:
            # This can error out
            diskpath, disksize, sparse = self.get_storage_info()

            if self.is_default_storage():
                # See if the ideal disk path (/default/pool/vmname.img)
                # exists, and if unused, prompt the use for using it
                ideal = uihelpers.get_ideal_path(self.conn,
                                                 self.guest.name)
                do_exist = False
                ret = True

                try:
                    do_exist = virtinst.VirtualDisk.path_exists(conn, ideal)
                    ret = virtinst.VirtualDisk.path_in_use_by(conn, ideal)
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

            disk = virtinst.VirtualDisk(conn)
            disk.path = diskpath
            disk.set_create_storage(size=disksize, sparse=sparse)

            fmt = self.conn.get_default_storage_format()
            if (self.is_default_storage() and
                disk.get_vol_install() and
                fmt in disk.get_vol_install().list_formats()):
                logging.debug("Setting disk format from prefs: %s", fmt)
                disk.get_vol_install().format = fmt
            disk.validate()

        except Exception, e:
            return self.err.val_err(_("Storage parameter error."), e)

        isfatal, errmsg = disk.is_size_conflict()
        if not isfatal and errmsg:
            # Fatal errors are reported when setting 'size'
            res = self.err.ok_cancel(_("Not Enough Free Space"), errmsg)
            if not res:
                return False

        # Disk collision
        names = disk.is_conflict_disk()
        if names:
            res = self.err.yes_no(
                    _('Disk "%s" is already in use by other guests %s') %
                     (disk.path, names),
                    _("Do you really want to use the disk?"))
            if not res:
                return False

        uihelpers.check_path_search_for_qemu(self.err, self.conn, disk.path)

        self.disk = disk
        self.guest.add_device(self.disk)

        return True

    def validate_final_page(self):
        # HV + Arch selection
        name = self.get_config_name()
        if name != self.guest.name:
            self.guest.name = name
            if self.is_default_storage():
                # User changed the name and we are using default storage
                # which depends on the VM name. Revalidate things
                if not self.validate_storage_page():
                    return False

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

        nic = uihelpers.validate_network(self.err,
                                         self.conn, nettype, devname, macaddr)
        if nic is False:
            return False

        if self.nic and self.nic in self.guest.get_devices("interface"):
            self.guest.remove_device(self.nic)
        if nic:
            self.nic = nic
            self.guest.add_device(self.nic)

        return True

    def _undo_finish_cursor(self):
        self.topwin.set_sensitive(True)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.TOP_LEFT_ARROW))

    def finish(self, src_ignore):
        # Validate the final page
        page = self.widget("create-pages").get_current_page()
        if self.validate(page) is not True:
            return False

        guest = self.guest

        # Start the install
        self.failed_guest = None
        self.topwin.set_sensitive(False)
        self.topwin.get_window().set_cursor(
            Gdk.Cursor.new(Gdk.CursorType.WATCH))

        if self.get_config_customize():
            try:
                self.customize(guest)
            except Exception, e:
                self._undo_finish_cursor()
                self.err.show_err(_("Error starting installation: ") + str(e))
                return
        else:
            self.start_install(guest)

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
            self.start_install(guest)

        def details_closed(ignore):
            cleanup_config_window()
            self._undo_finish_cursor()
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

    def _install_finished_cb(self, error, details):
        self._undo_finish_cursor()

        if error:
            error = (_("Unable to complete install: '%s'") % error)
            self.err.show_err(error,
                              details=details)
            self.failed_guest = self.guest
            return

        self.close()

        # Launch details dialog for new VM
        self.emit("action-show-domain", self.conn.get_uri(), self.guest.uuid)


    def start_install(self, guest):
        progWin = vmmAsyncJob(self.do_install, [guest],
                              self._install_finished_cb, [],
                              _("Creating Virtual Machine"),
                              _("The virtual machine is now being "
                                "created. Allocation of disk storage "
                                "and retrieval of the installation "
                                "images may take a few minutes to "
                                "complete."),
                              self.topwin)
        progWin.run()

    def do_install(self, asyncjob, guest):
        meter = asyncjob.get_meter()

        logging.debug("Starting background install process")
        guest.start_install(meter=meter)
        logging.debug("Install completed")

        # Make sure we pick up the domain object

        # Wait for VM to show up
        self.conn.schedule_priority_tick(pollvm=True)
        count = 0
        while (guest.uuid not in self.conn.vms) and (count < 100):
            count += 1
            time.sleep(.1)

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
    def set_distro_labels(self, distro, ver, force=False):
        # Helper to set auto detect result labels
        if not force and not self.is_detect_active():
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

    def set_distro_selection(self, variant):
        # Wrapper to change OS Type/Variant values, and update the distro
        # detection labels
        if not self.is_detect_active():
            return

        distro_type = None
        distro_var = None
        if variant:
            osclass = virtinst.osdict.lookup_os(variant)
            distro_type = osclass.typename
            distro_var = osclass.name

        dl = self.set_os_val(self.widget("install-os-type"), distro_type)
        vl = self.set_os_val(self.widget("install-os-version"), distro_var)
        self.set_distro_labels(dl, vl)

    def check_detection(self, idx, forward):
        results = None
        try:
            base = _("Detecting")

            if (self.detectedDistro == -1) or (idx >= (DETECT_TIMEOUT * 2)):
                detect_str = base + ("." * ((idx % 3) + 1))
                self.set_distro_labels(detect_str, detect_str)

                self.timeout_add(500, self.check_detection,
                                      idx + 1, forward)
                return

            results = self.detectedDistro
        except:
            logging.exception("Error in distro detect timeout")

        if results == -1:
            results = None
        self.widget("create-forward").set_sensitive(True)
        self.mediaDetected = True
        self.detecting = False
        logging.debug("Finished OS detection.")
        self.set_distro_selection(results)
        if forward:
            self.idle_add(self.forward, ())

    def start_detection(self, forward):
        if self.detecting:
            return

        media = self.get_config_detectable_media()
        if not media:
            return

        self.detectedDistro = -1

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
            installer = virtinst.DistroInstaller(self.conn)
            installer.location = media

            self.detectedDistro = installer.detect_distro(self.guest)
        except:
            logging.exception("Error detecting distro.")
            self.detectedDistro = -1

    def _stable_defaults(self):
        emu = None
        if self.guest:
            emu = self.guest.emulator
        elif self.capsdomain:
            emu = self.capsdomain.emulator

        ret = self.conn.stable_defaults(emu)
        return ret

    def _browse_file(self, cbwidget, cb=None, is_media=False, is_dir=False):
        if is_media:
            reason = self.config.CONFIG_DIR_ISO_MEDIA
        elif is_dir:
            reason = self.config.CONFIG_DIR_FS
        else:
            reason = self.config.CONFIG_DIR_IMAGE

        if cb:
            callback = cb
        else:
            def callback(ignore, text):
                self.widget(cbwidget).set_text(text)

        if self.storage_browser is None:
            self.storage_browser = vmmStorageBrowser(self.conn)

        self.storage_browser.stable_defaults = self._stable_defaults()

        self.storage_browser.set_vm_name(self.get_config_name())
        self.storage_browser.set_finish_cb(callback)
        self.storage_browser.set_browse_reason(reason)
        self.storage_browser.show(self.topwin, self.conn)
