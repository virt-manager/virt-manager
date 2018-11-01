# Copyright (C) 2008, 2013, 2014, 2015 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import io
import logging
import pkgutil
import os
import threading
import time

from gi.repository import Gdk
from gi.repository import Gtk
from gi.repository import Pango

import virtinst
from virtinst import util

from . import uiutil
from .addstorage import vmmAddStorage
from .asyncjob import vmmAsyncJob
from .connmanager import vmmConnectionManager
from .baseclass import vmmGObjectUI
from .details import vmmDetails
from .domain import vmmDomainVirtinst
from .engine import vmmEngine
from .mediacombo import vmmMediaCombo
from .netlist import vmmNetworkList
from .oslist import vmmOSList
from .storagebrowse import vmmStorageBrowser

# Number of seconds to wait for media detection
DETECT_TIMEOUT = 20

DEFAULT_MEM = 1024

(PAGE_NAME,
 PAGE_INSTALL,
 PAGE_MEM,
 PAGE_STORAGE,
 PAGE_FINISH) = range(5)

(INSTALL_PAGE_ISO,
 INSTALL_PAGE_URL,
 INSTALL_PAGE_PXE,
 INSTALL_PAGE_IMPORT,
 INSTALL_PAGE_CONTAINER_APP,
 INSTALL_PAGE_CONTAINER_OS,
 INSTALL_PAGE_VZ_TEMPLATE) = range(7)

# Column numbers for os type/version list models
(OS_COL_ID,
 OS_COL_LABEL,
 OS_COL_IS_SEP,
 OS_COL_IS_SHOW_ALL) = range(4)


#####################
# Pretty UI helpers #
#####################

def _pretty_arch(_a):
    if _a == "armv7l":
        return "arm"
    return _a


def _pretty_storage(size):
    return _("%.1f GiB") % float(size)


def _pretty_memory(mem):
    return _("%d MiB") % (mem / 1024.0)


###########################################################
# Helpers for tracking devices we create from this wizard #
###########################################################

def _mark_vmm_device(dev):
    setattr(dev, "vmm_create_wizard_device", True)


def _get_vmm_device(guest, devkey):
    for dev in getattr(guest.devices, devkey):
        if hasattr(dev, "vmm_create_wizard_device"):
            return dev


def _remove_vmm_device(guest, devkey):
    dev = _get_vmm_device(guest, devkey)
    if dev:
        guest.remove_device(dev)


def is_virt_bootstrap_installed():
    return pkgutil.find_loader('virtBootstrap') is not None


##############
# Main class #
##############

class vmmCreate(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj, uri=None):
        try:
            if not cls._instance:
                cls._instance = vmmCreate()
            cls._instance.show(parentobj and parentobj.topwin or None, uri=uri)
        except Exception as e:
            if not parentobj:
                raise
            parentobj.err.show_err(
                    _("Error launching create dialog: %s") % str(e))

    def __init__(self):
        vmmGObjectUI.__init__(self, "create.ui", "vmm-create")
        self._cleanup_on_app_close()

        self.conn = None
        self._capsinfo = None

        self._guest = None
        self._failed_guest = None

        # Distro detection state variables
        self._detect_os_in_progress = False
        self._os_already_detected_for_media = False

        self._customize_window = None

        self._storage_browser = None
        self._netlist = None

        self._addstorage = vmmAddStorage(self.conn, self.builder, self.topwin)
        self.widget("storage-align").add(self._addstorage.top_box)
        def _browse_file_cb(ignore, widget):
            self._browse_file(widget)
        self._addstorage.connect("browse-clicked", _browse_file_cb)

        self._mediacombo = vmmMediaCombo(self.conn, self.builder, self.topwin)
        self._mediacombo.connect("changed", self._iso_changed_cb)
        self._mediacombo.connect("activate", self._iso_activated_cb)
        self._mediacombo.set_mnemonic_label(
                self.widget("install-iso-label"))
        self.widget("install-iso-align").add(self._mediacombo.top_box)

        self.builder.connect_signals({
            "on_vmm_newcreate_delete_event": self._close_requested,

            "on_create_cancel_clicked": self._close_requested,
            "on_create_back_clicked": self._back_clicked,
            "on_create_forward_clicked": self._forward_clicked,
            "on_create_finish_clicked": self._finish_clicked,
            "on_create_pages_switch_page": self._page_changed,

            "on_create_conn_changed": self._conn_changed,
            "on_method_changed": self._method_changed,
            "on_xen_type_changed": self._xen_type_changed,
            "on_arch_changed": self._arch_changed,
            "on_virt_type_changed": self._virt_type_changed,
            "on_machine_changed": self._machine_changed,
            "on_vz_virt_type_changed": self._vz_virt_type_changed,

            "on_install_iso_browse_clicked": self._browse_iso,
            "on_install_url_entry_changed": self._url_changed,
            "on_install_url_entry_activate": self._url_activated,
            "on_install_import_browse_clicked": self._browse_import,
            "on_install_app_browse_clicked": self._browse_app,
            "on_install_oscontainer_browse_clicked": self._browse_oscontainer,
            "on_install_container_source_toggle": self._container_source_toggle,

            "on_install_detect_os_toggled": self._detect_os_toggled_cb,

            "on_kernel_browse_clicked": self._browse_kernel,
            "on_initrd_browse_clicked": self._browse_initrd,
            "on_dtb_browse_clicked": self._browse_dtb,

            "on_enable_storage_toggled": self._toggle_enable_storage,

            "on_create_vm_name_changed": self._name_changed,
        })
        self.bind_escape_key_close()

        self._init_state()



    ###########################
    # Standard window methods #
    ###########################

    def is_visible(self):
        return self.topwin.get_visible()

    def show(self, parent, uri):
        logging.debug("Showing new vm wizard")

        if not self.is_visible():
            self._reset_state(uri)
            self.topwin.set_transient_for(parent)
            vmmEngine.get_instance().increment_window_counter()

        self.topwin.present()

    def _close(self, ignore1=None, ignore2=None):
        if self.is_visible():
            logging.debug("Closing new vm wizard")
            vmmEngine.get_instance().decrement_window_counter()

        self.topwin.hide()

        self._cleanup_customize_window()
        if self._storage_browser:
            self._storage_browser.close()
        self._set_conn(None)

    def _cleanup(self):
        if self._storage_browser:
            self._storage_browser.cleanup()
            self._storage_browser = None
        if self._netlist:
            self._netlist.cleanup()
            self._netlist = None
        if self._mediacombo:
            self._mediacombo.cleanup()
            self._mediacombo = None
        if self._addstorage:
            self._addstorage.cleanup()
            self._addstorage = None

        self.conn = None
        self._capsinfo = None
        self._guest = None


    ##########################
    # Initial state handling #
    ##########################

    def _show_startup_error(self, error, hideinstall=True):
        self.widget("startup-error-box").show()
        self.widget("create-forward").set_sensitive(False)
        if hideinstall:
            self.widget("install-box").hide()
            self.widget("arch-expander").hide()

        self.widget("startup-error").set_text("%s: %s" % (_("Error"), error))
        return False

    def _show_startup_warning(self, error):
        self.widget("startup-error-box").show()
        self.widget("startup-error").set_markup(
            "<span size='small'>%s: %s</span>" % (_("Warning"), error))

    def _show_arch_warning(self, error):
        self.widget("arch-warning-box").show()
        self.widget("arch-warning").set_markup(
            "<span size='small'>%s: %s</span>" % (_("Warning"), error))


    def _init_state(self):
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
        text = uiutil.init_combo_text_column(conn_list, 1)
        text.set_property("ellipsize", Pango.EllipsizeMode.MIDDLE)

        def set_model_list(widget_id):
            lst = self.widget(widget_id)
            model = Gtk.ListStore(str)
            lst.set_model(model)
            lst.set_entry_text_column(0)

        # Lists for the install urls
        set_model_list("install-url-combo")

        # Lists for OS container bootstrap
        set_model_list("install-oscontainer-source-url-combo")

        # Architecture
        archList = self.widget("arch")
        # [label, guest.os.arch value]
        archModel = Gtk.ListStore(str, str)
        archList.set_model(archModel)
        uiutil.init_combo_text_column(archList, 0)
        archList.set_row_separator_func(
            lambda m, i, ignore: m[i][0] is None, None)

        # guest.os.type value for xen (hvm vs. xen)
        hyperList = self.widget("xen-type")
        # [label, guest.os_type value]
        hyperModel = Gtk.ListStore(str, str)
        hyperList.set_model(hyperModel)
        uiutil.init_combo_text_column(hyperList, 0)

        # guest.os.machine value
        lst = self.widget("machine")
        # [machine ID]
        model = Gtk.ListStore(str)
        lst.set_model(model)
        uiutil.init_combo_text_column(lst, 0)
        lst.set_row_separator_func(lambda m, i, ignore: m[i][0] is None, None)

        # guest.type value for xen (qemu vs kvm)
        lst = self.widget("virt-type")
        # [label, guest.type value]
        model = Gtk.ListStore(str, str)
        lst.set_model(model)
        uiutil.init_combo_text_column(lst, 0)

        # OS distro list
        self._os_list = vmmOSList()
        self.widget("install-os-align").add(self._os_list.search_entry)
        self.widget("os-label").set_mnemonic_widget(self._os_list.search_entry)

    def _reset_state(self, urihint=None):
        """
        Reset all UI state to default values. Conn specific state is
        populated in _populate_conn_state
        """
        self._failed_guest = None
        self._guest = None
        self.reset_finish_cursor()

        self.widget("create-pages").set_current_page(PAGE_NAME)
        self._page_changed(None, None, PAGE_NAME)

        # Name page state
        self.widget("create-vm-name").set_text("")
        self.widget("method-local").set_active(True)
        self.widget("create-conn").set_active(-1)
        activeconn = self._populate_conn_list(urihint)
        self.widget("arch-expander").set_expanded(False)
        self.widget("vz-virt-type-hvm").set_active(True)

        if self._set_conn(activeconn) is False:
            return False


        # Everything from this point forward should be connection independent

        # Distro/Variant
        self._os_list.reset_state()
        self._os_already_detected_for_media = False

        def _populate_media_model(media_model, urls):
            media_model.clear()
            if urls is None:
                return
            for url in urls:
                media_model.append([url])

        # Install local
        self._mediacombo.reset_state()

        # Install URL
        self.widget("install-urlopts-entry").set_text("")
        self.widget("install-url-entry").set_text("")
        self.widget("install-url-options").set_expanded(False)
        urlmodel = self.widget("install-url-combo").get_model()
        _populate_media_model(urlmodel, self.config.get_media_urls())

        # Install import
        self.widget("install-import-entry").set_text("")
        self.widget("kernel").set_text("")
        self.widget("initrd").set_text("")
        self.widget("dtb").set_text("")

        # Install container app
        self.widget("install-app-entry").set_text("/bin/sh")

        # Install container OS
        self.widget("install-oscontainer-fs").set_text("")
        self.widget("install-oscontainer-source-url-entry").set_text("")
        self.widget("install-oscontainer-source-user").set_text("")
        self.widget("install-oscontainer-source-passwd").set_text("")
        self.widget("install-oscontainer-source-insecure").set_active(False)
        self.widget("install-oscontainer-bootstrap").set_active(False)
        self.widget("install-oscontainer-auth-options").set_expanded(False)
        self.widget("install-oscontainer-rootpw").set_text("")
        src_model = (self.widget("install-oscontainer-source-url-combo")
                         .get_model())
        _populate_media_model(src_model, self.config.get_container_urls())

        # Install VZ container from template
        self.widget("install-container-template").set_text("centos-7-x86_64")

        # Storage
        self.widget("enable-storage").set_active(True)
        self._addstorage.reset_state()
        self._addstorage.widget("storage-create").set_active(True)
        self._addstorage.widget("storage-entry").set_text("")

        # Final page
        self.widget("summary-customize").set_active(False)


    def _set_caps_state(self):
        """
        Set state that is dependent on when capsinfo changes
        """
        self.widget("arch-warning-box").hide()
        guest = self._build_guest(None)

        # Helper state
        is_local = not self.conn.is_remote()
        is_storage_capable = self.conn.is_storage_capable()
        can_storage = (is_local or is_storage_capable)
        is_pv = guest.os.is_xenpv()
        is_container = self.conn.is_container()
        is_vz = self.conn.is_vz()
        is_vz_container = is_vz and guest.os.is_container()
        can_remote_url = self.conn.get_backend().support_remote_url_install()

        installable_arch = bool(guest.os.is_x86() or
                guest.os.is_ppc64() or
                guest.os.is_s390x())

        if guest.prefers_uefi():
            try:
                guest.set_uefi_path(guest.get_uefi_path())
                installable_arch = True
                logging.debug("UEFI found, setting it as default.")
            except Exception as e:
                installable_arch = False
                logging.debug("Error checking for UEFI default", exc_info=True)
                msg = _("Failed to setup UEFI: %s\n"
                        "Install options are limited.") % e
                self._show_arch_warning(msg)

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
                   guest.os.arch)
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
            return self._show_startup_error(
                    _("No install methods available for this connection."),
                    hideinstall=False)

        method_tree.set_tooltip_text(tree_tt or "")
        method_local.set_tooltip_text(local_tt or "")
        method_pxe.set_tooltip_text(pxe_tt or "")
        method_import.set_tooltip_text(import_tt or "")

        # Container install options
        method_container_app.set_active(True)
        self.widget("container-install-box").set_visible(is_container)
        self.widget("vz-install-box").set_visible(is_vz)
        self.widget("virt-install-box").set_visible(
            not is_container and not is_vz_container)

        show_dtb = ("arm" in guest.os.arch or
                    "microblaze" in guest.os.arch or
                    "ppc" in guest.os.arch)
        self.widget("kernel-box").set_visible(not installable_arch)
        uiutil.set_grid_row_visible(self.widget("dtb"), show_dtb)

    def _populate_conn_state(self):
        """
        Update all state that has some dependency on the current connection
        """
        self.conn.schedule_priority_tick(pollnet=True,
                                         pollpool=True, polliface=True,
                                         pollnodedev=True)

        self.widget("install-box").show()
        self.widget("create-forward").set_sensitive(True)

        self._capsinfo = None
        self.conn.invalidate_caps()
        self._change_caps()
        is_local = not self.conn.is_remote()

        if not self._capsinfo.guest.has_install_options():
            error = _("No hypervisor options were found for this "
                      "connection.")

            if self.conn.is_qemu():
                error += "\n\n"
                error += _("This usually means that QEMU or KVM is not "
                           "installed on your machine, or the KVM kernel "
                           "modules are not loaded.")
            return self._show_startup_error(error)

        # A bit out of order, but populate the xen/virt/arch/machine lists
        # so we can work with a default.
        self._populate_xen_type()
        self._populate_arch()
        self._populate_virt_type()

        show_arch = (self.widget("xen-type").get_visible() or
                     self.widget("virt-type").get_visible() or
                     self.widget("arch").get_visible() or
                     self.widget("machine").get_visible())
        uiutil.set_grid_row_visible(self.widget("arch-expander"), show_arch)

        if self.conn.is_xen():
            has_hvm_guests = False
            for g in self.conn.caps.guests:
                if g.os_type == "hvm":
                    has_hvm_guests = True

            if not has_hvm_guests:
                error = _("Host is not advertising support for full "
                          "virtualization. Install options may be limited.")
                self._show_startup_warning(error)

        elif self.conn.is_qemu():
            if not self._capsinfo.guest.is_kvm_available():
                error = _("KVM is not available. This may mean the KVM "
                 "package is not installed, or the KVM kernel modules "
                 "are not loaded. Your virtual machines may perform poorly.")
                self._show_startup_warning(error)

        elif self.conn.is_vz():
            has_hvm_guests = False
            has_exe_guests = False
            for g in self.conn.caps.guests:
                if g.os_type == "hvm":
                    has_hvm_guests = True
                if g.os_type == "exe":
                    has_exe_guests = True

            self.widget("vz-virt-type-hvm").set_sensitive(has_hvm_guests)
            self.widget("vz-virt-type-exe").set_sensitive(has_exe_guests)
            self.widget("vz-virt-type-hvm").set_active(has_hvm_guests)
            self.widget("vz-virt-type-exe").set_active(
                not has_hvm_guests and has_exe_guests)

        # ISO media
        # Dependent on connection so we need to do this here
        self._mediacombo.set_conn(self.conn)
        self._mediacombo.reset_state()

        # Allow container bootstrap only for local connection and
        # only if virt-bootstrap is installed. Otherwise, show message.
        vb_installed = is_virt_bootstrap_installed()
        vb_enabled = is_local and vb_installed

        oscontainer_widget_conf = {
            "install-oscontainer-notsupport-conn": not is_local,
            "install-oscontainer-notsupport": not vb_installed,
            "install-oscontainer-bootstrap": vb_enabled,
            "install-oscontainer-source": vb_enabled,
            "install-oscontainer-rootpw-box": vb_enabled
            }
        for w in oscontainer_widget_conf:
            self.widget(w).set_visible(oscontainer_widget_conf[w])

        # Memory
        memory = int(self.conn.host_memory_size())
        mem_label = (_("Up to %(maxmem)s available on the host") %
                     {'maxmem': _pretty_memory(memory)})
        mem_label = ("<span size='small' color='#484848'>%s</span>" %
                     mem_label)
        self.widget("mem").set_range(50, memory // 1024)
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
        self.widget("cpus").set_range(1, cmax)
        self.widget("phys-cpu-label").set_markup(cpu_label)

        # Storage
        self._addstorage.conn = self.conn
        self._addstorage.reset_state()

        # Networking
        self.widget("advanced-expander").set_expanded(False)

        self._netlist = vmmNetworkList(self.conn, self.builder, self.topwin)
        self.widget("netdev-ui-align").add(self._netlist.top_box)
        self._netlist.connect("changed", self._netdev_changed)
        self._netlist.reset_state()

    def _conn_state_changed(self, conn):
        if conn.is_disconnected():
            self._close()

    def _set_conn(self, newconn):
        self.widget("startup-error-box").hide()
        self.widget("arch-warning-box").hide()

        oldconn = self.conn
        self.conn = newconn
        if oldconn:
            oldconn.disconnect_by_obj(self)
        if self._netlist:
            self.widget("netdev-ui-align").remove(self._netlist.top_box)
            self._netlist.cleanup()
            self._netlist = None

        if not self.conn:
            return self._show_startup_error(
                                _("No active connection to install on."))
        self.conn.connect("state-changed", self._conn_state_changed)

        try:
            self._populate_conn_state()
        except Exception as e:
            logging.exception("Error setting create wizard conn state.")
            return self._show_startup_error(str(e))


    def _change_caps(self, gtype=None, arch=None, domtype=None):
        """
        Change the cached capsinfo for the passed values, and trigger
        all needed UI refreshing
        """
        if gtype is None:
            # If none specified, prefer HVM so install options aren't limited
            # with a default PV choice.
            for g in self.conn.caps.guests:
                if g.os_type == "hvm":
                    gtype = "hvm"
                    break

        capsinfo = self.conn.caps.guest_lookup(os_type=gtype,
                                               arch=arch,
                                               typ=domtype)

        if self._capsinfo:
            if (self._capsinfo.guest == capsinfo.guest and
                self._capsinfo.domain == capsinfo.domain):
                return

        self._capsinfo = capsinfo
        logging.debug("Guest type set to os_type=%s, arch=%s, dom_type=%s",
                      self._capsinfo.os_type,
                      self._capsinfo.arch,
                      self._capsinfo.hypervisor_type)
        self._populate_machine()
        self._set_caps_state()


    ##################################################
    # Helpers for populating hv/arch/machine/conn UI #
    ##################################################

    def _populate_xen_type(self):
        model = self.widget("xen-type").get_model()
        model.clear()

        default = 0
        guests = []
        if self.conn.is_xen() or self.conn.is_test():
            guests = self.conn.caps.guests[:]

        for guest in guests:
            if not guest.domains:
                continue

            gtype = guest.os_type
            dom = guest.domains[0]
            domtype = dom.hypervisor_type
            label = self.conn.pretty_hv(gtype, domtype)

            # Don't add multiple rows for each arch
            for m in model:
                if m[0] == label:
                    label = None
                    break
            if label is None:
                continue

            # Determine if this is the default given by guest_lookup
            if (gtype == self._capsinfo.os_type and
                domtype == self._capsinfo.hypervisor_type):
                default = len(model)

            model.append([label, gtype])

        show = bool(len(model))
        uiutil.set_grid_row_visible(self.widget("xen-type"), show)
        if show:
            self.widget("xen-type").set_active(default)

    def _populate_arch(self):
        model = self.widget("arch").get_model()
        model.clear()

        default = 0
        archs = []
        for guest in self.conn.caps.guests:
            if guest.os_type == self._capsinfo.os_type:
                archs.append(guest.arch)

        # Combine x86/i686 to avoid confusion
        if (self.conn.caps.host.cpu.arch == "x86_64" and
            "x86_64" in archs and "i686" in archs):
            archs.remove("i686")
        archs.sort()

        prios = ["x86_64", "i686", "aarch64", "armv7l", "ppc64", "ppc64le",
            "s390x"]
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
        if self._capsinfo.arch in archs:
            default = archs.index(self._capsinfo.arch)

        for arch in archs:
            model.append([_pretty_arch(arch), arch])

        show = not (len(archs) < 2)
        uiutil.set_grid_row_visible(self.widget("arch"), show)
        self.widget("arch").set_active(default)

    def _populate_virt_type(self):
        model = self.widget("virt-type").get_model()
        model.clear()

        # Allow choosing between qemu and kvm for archs that traditionally
        # have a decent amount of TCG usage, like armv7l. Also include
        # aarch64 which can be used for arm32 VMs as well
        domains = [d.hypervisor_type for d in self._capsinfo.guest.domains[:]]
        if not self.conn.is_qemu():
            domains = []
        elif self._capsinfo.arch in ["i686", "x86_64", "ppc64", "ppc64le"]:
            domains = []

        default = 0
        if self._capsinfo.hypervisor_type in domains:
            default = domains.index(self._capsinfo.hypervisor_type)

        prios = ["kvm"]
        for domain in prios:
            if domain not in domains:
                continue
            domains.remove(domain)
            domains.insert(0, domain)

        for domain in domains:
            label = self.conn.pretty_hv(self._capsinfo.os_type, domain)
            model.append([label, domain])

        show = bool(len(model) > 1)
        uiutil.set_grid_row_visible(self.widget("virt-type"), show)
        self.widget("virt-type").set_active(default)

    def _populate_machine(self):
        model = self.widget("machine").get_model()

        machines = self._capsinfo.machines[:]
        if self._capsinfo.arch in ["i686", "x86_64"]:
            machines = []
        machines.sort()

        defmachine = None
        prios = []
        recommended_machine = virtinst.Guest.get_recommended_machine(
                self._capsinfo)
        if recommended_machine:
            defmachine = recommended_machine
            prios = [defmachine]

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

        self.widget("machine").disconnect_by_func(self._machine_changed)
        try:
            model.clear()
            for m in machines:
                model.append([m])

            show = (len(machines) > 1)
            uiutil.set_grid_row_visible(self.widget("machine"), show)
            if show:
                self.widget("machine").set_active(default)
        finally:
            self.widget("machine").connect("changed", self._machine_changed)

    def _populate_conn_list(self, urihint=None):
        conn_list = self.widget("create-conn")
        model = conn_list.get_model()
        model.clear()

        default = -1
        connmanager = vmmConnectionManager.get_instance()
        for connobj in connmanager.conns.values():
            if not connobj.is_active():
                continue

            if connobj.get_uri() == urihint:
                default = len(model)
            elif default < 0 and not connobj.is_remote():
                # Favor local connections over remote connections
                default = len(model)

            model.append([connobj.get_uri(), connobj.get_pretty_desc()])

        no_conns = (len(model) == 0)

        if default < 0 and not no_conns:
            default = 0

        activeuri = ""
        activedesc = ""
        activeconn = None
        if not no_conns:
            conn_list.set_active(default)
            activeuri, activedesc = model[default]
            activeconn = connmanager.conns[activeuri]

        self.widget("create-conn-label").set_text(activedesc)
        if len(model) <= 1:
            self.widget("create-conn").hide()
            self.widget("create-conn-label").show()
        else:
            self.widget("create-conn").show()
            self.widget("create-conn-label").hide()

        return activeconn


    ###############################
    # Misc UI populating routines #
    ###############################

    def _populate_summary_storage(self, path=None):
        storagetmpl = "<span size='small' color='#484848'>%s</span>"
        storagesize = ""
        storagepath = ""

        disk = _get_vmm_device(self._guest, "disk")
        if disk:
            if disk.wants_storage_creation():
                storagesize = "%s" % _pretty_storage(disk.get_size())
            if not path:
                path = disk.path
            storagepath = (storagetmpl % path)
        elif len(self._guest.devices.filesystem):
            fs = self._guest.devices.filesystem[0]
            storagepath = storagetmpl % fs.source
        elif self._guest.os.is_container():
            storagepath = _("Host filesystem")
        else:
            storagepath = _("None")

        self.widget("summary-storage").set_markup(storagesize)
        self.widget("summary-storage").set_visible(bool(storagesize))
        self.widget("summary-storage-path").set_markup(storagepath)

    def _populate_summary(self):
        mem = _pretty_memory(int(self._guest.memory))
        cpu = str(int(self._guest.vcpus))

        instmethod = self._get_config_install_page()
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
        elif instmethod == INSTALL_PAGE_VZ_TEMPLATE:
            install = _("Virtuozzo container")

        self.widget("summary-os").set_text(self._guest.osinfo.label)
        self.widget("summary-install").set_text(install)
        self.widget("summary-mem").set_text(mem)
        self.widget("summary-cpu").set_text(cpu)
        self._populate_summary_storage()

        self._netdev_changed(None)


    ################################
    # UI state getters and helpers #
    ################################

    def _get_config_name(self):
        return self.widget("create-vm-name").get_text()

    def _get_config_machine(self):
        return uiutil.get_list_selection(self.widget("machine"),
            check_visible=True)

    def _get_config_install_page(self):
        if self.widget("vz-install-box").get_visible():
            if self.widget("vz-virt-type-exe").get_active():
                return INSTALL_PAGE_VZ_TEMPLATE
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

    def _is_container_install(self):
        return self._get_config_install_page() in [INSTALL_PAGE_CONTAINER_APP,
                                                   INSTALL_PAGE_CONTAINER_OS,
                                                   INSTALL_PAGE_VZ_TEMPLATE]


    def _get_config_oscontainer_bootstrap(self):
        return self.widget("install-oscontainer-bootstrap").get_active()


    def _get_config_oscontainer_source_url(self, store_media=False):
        src_url = (self.widget("install-oscontainer-source-url-entry")
                       .get_text().strip())

        if src_url and store_media:
            self.config.add_container_url(src_url)

        return src_url


    def _get_config_oscontainer_source_username(self):
        return (self.widget("install-oscontainer-source-user")
                    .get_text().strip())


    def _get_config_oscontainer_source_password(self):
        return self.widget("install-oscontainer-source-passwd").get_text()


    def _get_config_oscontainer_isecure(self):
        return self.widget("install-oscontainer-source-insecure").get_active()


    def _get_config_oscontainer_root_password(self):
        return self.widget("install-oscontainer-rootpw").get_text()


    def _should_skip_disk_page(self):
        return self._get_config_install_page() in [INSTALL_PAGE_IMPORT,
                                                   INSTALL_PAGE_CONTAINER_APP,
                                                   INSTALL_PAGE_CONTAINER_OS,
                                                   INSTALL_PAGE_VZ_TEMPLATE]

    def _get_config_local_media(self, store_media=False):
        return self._mediacombo.get_path(store_media=store_media)

    def _get_config_detectable_media(self):
        instpage = self._get_config_install_page()
        media = None

        if instpage == INSTALL_PAGE_ISO:
            media = self._get_config_local_media()
        elif instpage == INSTALL_PAGE_URL:
            media = self.widget("install-url-entry").get_text()

        return media

    def _get_config_url_info(self, store_media=False):
        media = self.widget("install-url-entry").get_text().strip()
        extra = self.widget("install-urlopts-entry").get_text().strip()

        if media and store_media:
            self.config.add_media_url(media)

        return (media, extra)

    def _get_config_import_path(self):
        return self.widget("install-import-entry").get_text()

    def _is_default_storage(self):
        return (self._addstorage.is_default_storage() and
                not self._should_skip_disk_page())

    def _is_os_detect_active(self):
        return self.widget("install-detect-os").get_active()


    ################
    # UI Listeners #
    ################

    def _close_requested(self, *ignore1, **ignore2):
        """
        When user tries to close the dialog, check for any disks that
        we should auto cleanup
        """
        if (self._failed_guest and
            self._failed_guest.installer_instance.get_created_disks(
                self._failed_guest)):

            def _cleanup_disks(asyncjob):
                meter = asyncjob.get_meter()
                self._failed_guest.installer_instance.cleanup_created_disks(
                        self._failed_guest, meter)

            def _cleanup_disks_finished(error, details):
                if error:
                    logging.debug("Error cleaning up disk images:"
                        "\nerror=%s\ndetails=%s", error, details)
                self.idle_add(self._close)

            progWin = vmmAsyncJob(
                _cleanup_disks, [],
                _cleanup_disks_finished, [],
                _("Removing disk images"),
                _("Removing disk images we created for this virtual machine."),
                self.topwin)
            progWin.run()

        else:
            self._close()

        return 1


    # Intro page listeners
    def _conn_changed(self, src):
        uri = uiutil.get_list_selection(src)
        newconn = None
        connmanager = vmmConnectionManager.get_instance()
        if uri:
            newconn = connmanager.conns[uri]

        # If we aren't visible, let reset_state handle this for us, which
        # has a better chance of reporting error
        if not self.is_visible():
            return

        if self.conn is not newconn:
            self._set_conn(newconn)

    def _method_changed(self, src):
        ignore = src
        # Reset the page number, since the total page numbers depend
        # on the chosen install method
        self._set_page_num_text(0)

    def _machine_changed(self, ignore):
        self._set_caps_state()

    def _xen_type_changed(self, ignore):
        os_type = uiutil.get_list_selection(self.widget("xen-type"), column=1)
        if not os_type:
            return

        self._change_caps(os_type)
        self._populate_arch()

    def _arch_changed(self, ignore):
        arch = uiutil.get_list_selection(self.widget("arch"), column=1)
        if not arch:
            return

        self._change_caps(self._capsinfo.os_type, arch)
        self._populate_virt_type()

    def _virt_type_changed(self, ignore):
        domtype = uiutil.get_list_selection(self.widget("virt-type"), column=1)
        if not domtype:
            return

        self._change_caps(self._capsinfo.os_type, self._capsinfo.arch, domtype)

    def _vz_virt_type_changed(self, ignore):
        is_hvm = self.widget("vz-virt-type-hvm").get_active()
        if is_hvm:
            self._change_caps("hvm")
        else:
            self._change_caps("exe")

    # Install page listeners
    def _detectable_media_widget_changed(self, widget, checkfocus=True):
        self._os_already_detected_for_media = False

        # If the text entry widget has focus, don't fire detect_media_os,
        # it means the user is probably typing. It will be detected
        # when the user activates the widget, or we try to switch pages
        if (checkfocus and
            hasattr(widget, "get_text") and widget.has_focus()):
            return

        self._start_detect_os_if_needed()

    def _url_changed(self, src):
        self._detectable_media_widget_changed(src)
    def _url_activated(self, src):
        self._detectable_media_widget_changed(src, checkfocus=False)
    def _iso_changed_cb(self, mediacombo, entry):
        self._detectable_media_widget_changed(entry)
    def _iso_activated_cb(self, mediacombo, entry):
        self._detectable_media_widget_changed(entry, checkfocus=False)

    def _detect_os_toggled_cb(self, src):
        if not src.is_visible():
            return

        # We are only here if the user explicitly changed detection UI
        dodetect = src.get_active()
        self._change_os_detect(not dodetect)
        if dodetect:
            self._os_already_detected_for_media = False
            self._start_detect_os_if_needed()

    def _browse_oscontainer(self, ignore):
        self._browse_file("install-oscontainer-fs", is_dir=True)
    def _browse_app(self, ignore):
        self._browse_file("install-app-entry")
    def _browse_import(self, ignore):
        self._browse_file("install-import-entry")
    def _browse_iso(self, ignore):
        def set_path(ignore, path):
            self._mediacombo.set_path(path)
        self._browse_file(None, cb=set_path, is_media=True)
    def _browse_kernel(self, ignore):
        self._browse_file("kernel")
    def _browse_initrd(self, ignore):
        self._browse_file("initrd")
    def _browse_dtb(self, ignore):
        self._browse_file("dtb")


    # Storage page listeners
    def _toggle_enable_storage(self, src):
        self.widget("storage-align").set_sensitive(src.get_active())


    # Summary page listeners
    def _name_changed(self, src):
        newname = src.get_text()
        if not src.is_visible():
            return
        if not newname:
            return

        try:
            path, ignore = self._get_storage_path(newname, do_log=False)
            self._populate_summary_storage(path=path)
        except Exception:
            logging.debug("Error generating storage path on name change "
                "for name=%s", newname, exc_info=True)


    def _netdev_changed(self, ignore):
        row = self._netlist.get_network_row()
        pxe_install = (self._get_config_install_page() == INSTALL_PAGE_PXE)

        ntype = row[0]
        connkey = row[6]
        expand = (ntype != "network" and ntype != "bridge")
        no_network = ntype is None

        if (no_network or ntype == virtinst.DeviceInterface.TYPE_USER):
            can_pxe = False
        elif ntype != virtinst.DeviceInterface.TYPE_VIRTUAL:
            can_pxe = True
        else:
            can_pxe = self.conn.get_net(connkey).can_pxe()

        if expand:
            self.widget("advanced-expander").set_expanded(True)

        self.widget("netdev-warn-box").set_visible(False)
        def _show_netdev_warn(msg):
            self.widget("advanced-expander").set_expanded(True)
            self.widget("netdev-warn-box").set_visible(True)
            self.widget("netdev-warn-label").set_markup(
                "<small>%s</small>" % msg)

        if no_network:
            _show_netdev_warn(_("No network selected"))
        elif not can_pxe and pxe_install:
            _show_netdev_warn(_("Network selection does not support PXE"))


    # Enable/Disable container source URL entry on checkbox click
    def _container_source_toggle(self, ignore):
        enable_src = self.widget("install-oscontainer-bootstrap").get_active()
        self.widget("install-oscontainer-source").set_sensitive(enable_src)
        self.widget("install-oscontainer-rootpw-box").set_sensitive(enable_src)

        # Auto-generate a path if not specified
        if enable_src and not self.widget("install-oscontainer-fs").get_text():
            if os.geteuid() == 0:
                fs_dir = ['/var/lib/libvirt/filesystems/']
            else:
                fs_dir = [os.environ['HOME'],
                          '.local/share/libvirt/filesystems/']

            fs = fs_dir + [self._generate_default_name(None)]
            self.widget("install-oscontainer-fs").set_text(os.path.join(*fs))


    ########################
    # Misc helper routines #
    ########################

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
                widget = cbwidget
                if isinstance(cbwidget, str):
                    widget = self.widget(cbwidget)
                widget.set_text(text)

        if self._storage_browser and self._storage_browser.conn != self.conn:
            self._storage_browser.cleanup()
            self._storage_browser = None
        if self._storage_browser is None:
            self._storage_browser = vmmStorageBrowser(self.conn)

        self._storage_browser.set_vm_name(self._get_config_name())
        self._storage_browser.set_finish_cb(callback)
        self._storage_browser.set_browse_reason(reason)
        self._storage_browser.show(self.topwin)


    ######################
    # Navigation methods #
    ######################

    def _set_page_num_text(self, cur):
        """
        Set the 'page 1 of 4' style text in the wizard header
        """
        cur += 1
        final = PAGE_FINISH + 1
        if self._should_skip_disk_page():
            final -= 1
            cur = min(cur, final)

        page_lbl = ("<span color='#59B0E2'>%s</span>" %
                    _("Step %(current_page)d of %(max_page)d") %
                    {'current_page': cur, 'max_page': final})

        self.widget("header-pagenum").set_markup(page_lbl)

    def _change_os_detect(self, sensitive):
        self._os_list.set_sensitive(sensitive)
        if not sensitive and not self._os_list.get_selected_os():
            self._os_list.search_entry.set_text(
                    _("Waiting for install media / source"))

    def _set_install_page(self):
        instpage = self._get_config_install_page()

        # Setting OS value for container doesn't matter presently
        self.widget("install-os-distro-box").set_visible(
                not self._is_container_install())

        enabledetect = False
        if instpage == INSTALL_PAGE_URL:
            enabledetect = True
        elif instpage == INSTALL_PAGE_ISO and not self.conn.is_remote():
            enabledetect = True

        self.widget("install-detect-os-box").set_visible(enabledetect)
        dodetect = (enabledetect and
                self.widget("install-detect-os").get_active())
        self._change_os_detect(not dodetect)

        # PXE installs have nothing to ask for
        self.widget("install-method-pages").set_visible(
                instpage != INSTALL_PAGE_PXE)
        self.widget("install-method-pages").set_current_page(instpage)

    def _back_clicked(self, src_ignore):
        notebook = self.widget("create-pages")
        curpage = notebook.get_current_page()
        next_page = curpage - 1

        if curpage == PAGE_FINISH and self._should_skip_disk_page():
            # Skip over storage page
            next_page -= 1

        notebook.set_current_page(next_page)

    def _get_next_pagenum(self, curpage):
        next_page = curpage + 1

        if next_page == PAGE_STORAGE and self._should_skip_disk_page():
            # Skip storage page for import installs
            next_page += 1

        return next_page

    def _forward_clicked(self, src_ignore=None):
        notebook = self.widget("create-pages")
        curpage = notebook.get_current_page()

        if curpage == PAGE_INSTALL:
            # Make sure we have detected the OS before validating the page
            did_start = self._start_detect_os_if_needed(
                forward_after_finish=True)
            if did_start:
                return

        if self._validate(curpage) is not True:
            return

        if curpage == PAGE_NAME:
            self._set_install_page()

        next_page = self._get_next_pagenum(curpage)

        self.widget("create-forward").grab_focus()
        notebook.set_current_page(next_page)


    def _page_changed(self, ignore1, ignore2, pagenum):
        if pagenum == PAGE_FINISH:
            try:
                self._populate_summary()
            except Exception as e:
                self.err.show_err(_("Error populating summary page: %s") %
                    str(e))
                return

            self.widget("create-finish").grab_focus()

        self._set_page_num_text(pagenum)
        self.widget("create-back").set_sensitive(pagenum != PAGE_NAME)
        self.widget("create-forward").set_visible(pagenum != PAGE_FINISH)
        self.widget("create-finish").set_visible(pagenum == PAGE_FINISH)

        # Hide all other pages, so the dialog isn't all stretched out
        # because of one large page.
        for nr in range(self.widget("create-pages").get_n_pages()):
            page = self.widget("create-pages").get_nth_page(nr)
            page.set_visible(nr == pagenum)


    ############################
    # Page validation routines #
    ############################

    def _build_guest(self, variant):
        guest = virtinst.Guest(self.conn.get_backend())
        guest.set_capabilities_defaults(self._capsinfo)

        # If no machine was selected don't clear recommended machine
        machine = self._get_config_machine()
        if machine:
            guest.os.machine = machine

        # Validation catches user manually typing an invalid value
        try:
            if variant:
                guest.set_os_name(variant)
        except ValueError as e:
            self.err.val_err(_("Error setting OS information."), str(e))
            return None

        guest.default_graphics_type = self.config.get_graphics_type()
        guest.skip_default_sound = not self.config.get_new_vm_sound()
        guest.skip_default_usbredir = (
            self.config.get_add_spice_usbredir() == "no")
        guest.x86_cpu_default = self.config.get_default_cpu_setting()

        return guest

    def _validate(self, pagenum):
        try:
            if pagenum == PAGE_NAME:
                return self._validate_intro_page()
            elif pagenum == PAGE_INSTALL:
                return self._validate_install_page()
            elif pagenum == PAGE_MEM:
                return self._validate_mem_page()
            elif pagenum == PAGE_STORAGE:
                return self._validate_storage_page()
            elif pagenum == PAGE_FINISH:
                return self._validate_final_page()
        except Exception as e:
            self.err.show_err(_("Uncaught error validating install "
                                "parameters: %s") % str(e))
            return

    def _validate_intro_page(self):
        # We just set this here because it's needed soon after for distro
        # detection. But the 'real' self._guest is created in validate_install,
        # and it just uses _build_guest, so don't ever add any other guest
        # altering here.
        self._guest = self._build_guest(None)
        if not self._guest:
            return False
        return True

    def _generate_default_name(self, osobj):
        force_num = False
        if self._guest.os.is_container():
            basename = "container"
            force_num = True
        elif not osobj:
            basename = "vm"
            force_num = True
        else:
            basename = osobj.name

        if self._guest.os.arch != self.conn.caps.host.cpu.arch:
            basename += "-%s" % _pretty_arch(self._guest.os.arch)
            force_num = False

        return util.generate_name(basename,
            self.conn.get_backend().lookupByName,
            start_num=force_num and 1 or 2, force_num=force_num,
            sep=not force_num and "-" or "",
            collidelist=[vm.get_name() for vm in self.conn.list_vms()])


    def _validate_install_page(self):
        instmethod = self._get_config_install_page()
        installer = None
        location = None
        extra = None
        cdrom = None
        install_bootdev = None
        is_import = False
        init = None
        fs = None
        template = None
        osobj = self._os_list.get_selected_os()

        if not self._is_container_install() and not osobj:
            return self.err.val_err(_("You must select an OS.") +
                    "\n\n" + self._os_list.eol_text)

        if instmethod == INSTALL_PAGE_ISO:
            media = self._get_config_local_media()
            if not media:
                return self.err.val_err(
                                _("An install media selection is required."))
            cdrom = media

        elif instmethod == INSTALL_PAGE_URL:
            media, extra = self._get_config_url_info()

            if not media:
                return self.err.val_err(_("An install tree is required."))

            location = media

        elif instmethod == INSTALL_PAGE_PXE:
            install_bootdev = "network"

        elif instmethod == INSTALL_PAGE_IMPORT:
            is_import = True
            import_path = self._get_config_import_path()
            if not import_path:
                return self.err.val_err(
                                _("A storage path to import is required."))

            if not virtinst.DeviceDisk.path_definitely_exists(
                                                self.conn.get_backend(),
                                                import_path):
                return self.err.val_err(_("The import path must point to "
                                          "an existing storage."))

        elif instmethod == INSTALL_PAGE_CONTAINER_APP:
            init = self.widget("install-app-entry").get_text()
            if not init:
                return self.err.val_err(_("An application path is required."))

        elif instmethod == INSTALL_PAGE_CONTAINER_OS:
            fs = self.widget("install-oscontainer-fs").get_text()
            if not fs:
                return self.err.val_err(_("An OS directory path is required."))

            if self._get_config_oscontainer_bootstrap():
                src_url = self._get_config_oscontainer_source_url()
                user = self._get_config_oscontainer_source_username()
                passwd = self._get_config_oscontainer_source_password()

                # Check if the source path was provided
                if not src_url:
                    return self.err.val_err(_("Source URL is required"))

                # Require username and password when authenticate
                # to source registry.
                if user and not passwd:
                    return self.err.val_err(_("Please specify password "
                                              "for accessing source registry"))

                # Validate destination path
                if os.path.exists(fs):
                    if not os.path.isdir(fs):
                        return self.err.val_err(_("Destination path "
                                                  "is not directory: %s") % fs)
                    if not os.access(fs, os.W_OK):
                        return self.err.val_err(_("No write permissions for "
                                                  "directory path: %s") % fs)
                    if os.listdir(fs) != []:
                        # Show Yes/No dialog if the destination is not empty
                        res = self.err.yes_no(
                            _("OS root directory is not empty"),
                            _("Creating root file system in a non-empty "
                              "directory might fail due to file conflicts.\n"
                              "Would you like to continue?"))
                        if not res:
                            return False


        elif instmethod == INSTALL_PAGE_VZ_TEMPLATE:
            template = self.widget("install-container-template").get_text()
            if not template:
                return self.err.val_err(_("A template name is required."))

        # Build the installer and Guest instance
        try:
            # Overwrite the guest
            installer = virtinst.Installer(
                    self.conn.get_backend(),
                    location=location, cdrom=cdrom,
                    install_bootdev=install_bootdev)
            variant = osobj and osobj.name or None
            self._guest = self._build_guest(variant)
            if not self._guest:
                return False
        except Exception as e:
            return self.err.val_err(
                        _("Error setting installer parameters."), e)

        # Validate media location
        try:
            if extra:
                installer.extra_args = [extra]
            if init:
                self._guest.os.init = init

            if fs:
                fsdev = virtinst.DeviceFilesystem(self._guest.conn)
                fsdev.target = "/"
                fsdev.source = fs
                self._guest.add_device(fsdev)

            if template:
                fsdev = virtinst.DeviceFilesystem(self._guest.conn)
                fsdev.target = "/"
                fsdev.type = "template"
                fsdev.source = template
                self._guest.add_device(fsdev)

        except Exception as e:
            return self.err.val_err(
                                _("Error setting install media location."), e)

        # Setting kernel
        if instmethod == INSTALL_PAGE_IMPORT:
            kernel = self.widget("kernel").get_text() or None
            kargs = self.widget("kernel-args").get_text() or None
            initrd = self.widget("initrd").get_text() or None
            dtb = self.widget("dtb").get_text() or None

            if not self.widget("dtb").get_visible():
                dtb = None
            if not self.widget("kernel").get_visible():
                kernel = None
                initrd = None
                kargs = None

            self._guest.os.kernel = kernel
            self._guest.os.initrd = initrd
            self._guest.os.dtb = dtb
            self._guest.os.kernel_args = kargs

        try:
            name = self._generate_default_name(self._guest.osinfo)
            self.widget("create-vm-name").set_text(name)
            self._guest.validate_name(self._guest.conn, name)
            self._guest.name = name
        except Exception as e:
            return self.err.val_err(_("Error setting default name."), e)

        # Kind of wonky, run storage validation now, which will assign
        # the import path. Import installer skips the storage page.
        if is_import:
            if not self._validate_storage_page():
                return False

        if installer.scratchdir_required():
            path = util.make_scratchdir(self._guest.conn, self._guest.type)
        elif instmethod == INSTALL_PAGE_ISO:
            path = installer.cdrom or installer.location
        else:
            path = None

        if path:
            self._addstorage.check_path_search(
                self, self.conn, path)

        res = self._guest.osinfo.get_recommended_resources(self._guest)
        logging.debug("Recommended resources for os=%s: %s",
            self._guest.osinfo.name, res)

        # Change the default values suggested to the user.
        ram_size = DEFAULT_MEM
        if res and res.get("ram") > 0:
            ram_size = res["ram"] // (1024 ** 2)
        self.widget("mem").set_value(ram_size)

        n_cpus = 1
        if res and res.get("n-cpus") > 0:
            n_cpus = res["n-cpus"]
        self.widget("cpus").set_value(n_cpus)

        if res and res.get("storage"):
            storage_size = int(res["storage"]) // (1024 ** 3)
            self._addstorage.widget("storage-size").set_value(storage_size)

        # Stash the installer in the _guest instance so we don't need
        # to cache both objects individually
        self._guest.installer_instance = installer

        # Validation passed, store the install path (if there is one) in
        # gsettings
        self._get_config_oscontainer_source_url(store_media=True)
        self._get_config_local_media(store_media=True)
        self._get_config_url_info(store_media=True)
        return True

    def _validate_mem_page(self):
        cpus = self.widget("cpus").get_value()
        mem  = self.widget("mem").get_value()

        # VCPUS
        try:
            self._guest.vcpus = int(cpus)
        except Exception as e:
            return self.err.val_err(_("Error setting CPUs."), e)

        # Memory
        try:
            self._guest.memory = int(mem) * 1024
            self._guest.maxmemory = int(mem) * 1024
        except Exception as e:
            return self.err.val_err(_("Error setting guest memory."), e)

        return True

    def _get_storage_path(self, vmname, do_log):
        failed_disk = None
        if self._failed_guest:
            failed_disk = _get_vmm_device(self._failed_guest, "disk")

        path = None
        path_already_created = False

        if self._get_config_install_page() == INSTALL_PAGE_IMPORT:
            path = self._get_config_import_path()

        elif self._is_default_storage():
            if failed_disk:
                # Don't generate a new path if the install failed
                path = failed_disk.path
                path_already_created = failed_disk.storage_was_created
                if do_log:
                    logging.debug("Reusing failed disk path=%s "
                        "already_created=%s", path, path_already_created)
            else:
                path = self._addstorage.get_default_path(vmname)
                if do_log:
                    logging.debug("Default storage path is: %s", path)

        return path, path_already_created

    def _validate_storage_page(self):
        path, path_already_created = self._get_storage_path(
            self._guest.name, do_log=True)

        disk = None
        storage_enabled = self.widget("enable-storage").get_active()
        try:
            if storage_enabled:
                disk = self._addstorage.validate_storage(self._guest.name,
                    path=path)
        except Exception as e:
            return self.err.val_err(_("Storage parameter error."), e)

        if disk is False:
            return False

        if self._get_config_install_page() == INSTALL_PAGE_ISO:
            # CD/ISO install and no disks implies LiveCD
            self._guest.installer_instance.livecd = not storage_enabled

        if disk and self._addstorage.validate_disk_object(disk) is False:
            return False

        _remove_vmm_device(self._guest, "disk")

        if not storage_enabled:
            return True

        disk.storage_was_created = path_already_created
        _mark_vmm_device(disk)
        self._guest.add_device(disk)

        return True


    def _validate_final_page(self):
        # HV + Arch selection
        name = self._get_config_name()
        if name != self._guest.name:
            try:
                self._guest.validate_name(self._guest.conn, name)
                self._guest.name = name
            except Exception as e:
                return self.err.val_err(_("Invalid guest name"), str(e))
            if self._is_default_storage():
                logging.debug("User changed VM name and using default "
                    "storage, re-validating with new default storage path.")
                # User changed the name and we are using default storage
                # which depends on the VM name. Revalidate things
                if not self._validate_storage_page():
                    return False

        nettype = self._netlist.get_network_selection()[0]
        if nettype is None:
            # No network device available
            instmethod = self._get_config_install_page()
            methname = None
            if instmethod == INSTALL_PAGE_PXE:
                methname  = "PXE"
            elif instmethod == INSTALL_PAGE_URL:
                methname = "URL"

            if methname:
                return self.err.val_err(
                            _("Network device required for %s install.") %
                            methname)

        macaddr = virtinst.DeviceInterface.generate_mac(
            self.conn.get_backend())
        nic = self._netlist.validate_network(macaddr)
        if nic is False:
            return False

        _remove_vmm_device(self._guest, "interface")
        if nic:
            _mark_vmm_device(nic)
            self._guest.add_device(nic)

        return True


    #############################
    # Distro detection handling #
    #############################

    def _start_detect_os_if_needed(self, forward_after_finish=False):
        """
        Will kick off the OS detection thread if all conditions are met,
        like we actually have media to detect, detection isn't already
        in progress, etc.

        Returns True if we actually start the detection process
        """
        is_install_page = (self.widget("create-pages").get_current_page() ==
            PAGE_INSTALL)
        media = self._get_config_detectable_media()

        if self._detect_os_in_progress:
            return
        if not is_install_page:
            return
        if not media:
            return
        if not self._is_os_detect_active():
            return
        if self._os_already_detected_for_media:
            return

        self._do_start_detect_os(media, forward_after_finish)
        return True

    def _do_start_detect_os(self, media, forward_after_finish):
        self._detect_os_in_progress = False

        logging.debug("Starting OS detection thread for media=%s", media)
        self.widget("create-forward").set_sensitive(False)

        class ThreadResults(object):
            """
            Helper object to track results from the detection thread
            """
            _DETECT_FAILED = 1
            _DETECT_INPROGRESS = 2
            def __init__(self):
                self._results = self._DETECT_INPROGRESS

            def in_progress(self):
                return self._results == self._DETECT_INPROGRESS

            def set_failed(self):
                self._results = self._DETECT_FAILED

            def set_distro(self, distro):
                self._results = distro
            def get_distro(self):
                if self._results == self._DETECT_FAILED:
                    return None
                return self._results

        thread_results = ThreadResults()
        detectThread = threading.Thread(target=self._detect_thread_cb,
                                        name="Actual media detection",
                                        args=(media, thread_results))
        detectThread.setDaemon(True)
        detectThread.start()

        self._os_list.search_entry.set_text(_("Detecting..."))
        spin = self.widget("install-detect-os-spinner")
        spin.start()

        self._report_detect_os_progress(0, thread_results,
                forward_after_finish)

    def _detect_thread_cb(self, media, thread_results):
        """
        Thread callback that does the actual detection
        """
        try:
            installer = virtinst.Installer(self.conn.get_backend(),
                                           location=media)
            distro = installer.detect_distro(self._guest)
            thread_results.set_distro(distro)
        except Exception:
            logging.exception("Error detecting distro.")
            thread_results.set_failed()

    def _report_detect_os_progress(self, idx, thread_results,
            forward_after_finish):
        """
        Checks detection progress via the _detect_os_results variable
        and updates the UI labels, counts the number of iterations,
        etc.

        We set a hard time limit on the distro detection to avoid the
        chance of the detection hanging (like slow URL lookup)
        """
        try:
            if (thread_results.in_progress() and
                (idx < (DETECT_TIMEOUT * 2))):
                # Thread is still going and we haven't hit the timeout yet,
                # so update the UI labels and reschedule this function
                self.timeout_add(500, self._report_detect_os_progress,
                    idx + 1, thread_results, forward_after_finish)
                return

            distro = thread_results.get_distro()
        except Exception:
            distro = None
            logging.exception("Error in distro detect timeout")

        spin = self.widget("install-detect-os-spinner")
        spin.stop()
        logging.debug("Finished UI OS detection.")

        self.widget("create-forward").set_sensitive(True)
        self._os_already_detected_for_media = True
        self._detect_os_in_progress = False

        if not self._is_os_detect_active():
            # If the user changed the OS detect checkbox in the meantime,
            # don't update the UI
            return

        if distro:
            self._os_list.select_os(virtinst.OSDB.lookup_os(distro))
        else:
            self._os_list.reset_state()
            self._os_list.search_entry.set_text(_("None detected"))

        if forward_after_finish:
            self.idle_add(self._forward_clicked, ())


    ##########################
    # Guest install routines #
    ##########################

    def _finish_clicked(self, src_ignore):
        # Validate the final page
        page = self.widget("create-pages").get_current_page()
        if self._validate(page) is not True:
            return False

        logging.debug("Starting create finish() sequence")
        self._failed_guest = None

        try:
            self.set_finish_cursor()

            # This encodes all the virtinst defaults up front, so the customize
            # dialog actually shows disk buses, cache values, default devices,
            # etc. Not required for straight start_install but doesn't hurt.
            self._guest.installer_instance.set_install_defaults(self._guest)

            if not self.widget("summary-customize").get_active():
                self._start_install(self._guest)
                return

            logging.debug("User requested 'customize', launching dialog")
            self._show_customize_dialog()
        except Exception as e:
            self.reset_finish_cursor()
            self.err.show_err(_("Error starting installation: ") + str(e))
            return

    def _cleanup_customize_window(self):
        if not self._customize_window:
            return

        # We can re-enter this: cleanup() -> close() -> "details-closed"
        window = self._customize_window
        self._customize_window = None
        window.cleanup()

    def _show_customize_dialog(self):
        guest = self._guest
        virtinst_guest = vmmDomainVirtinst(self.conn, guest, guest.uuid)

        def start_install_wrapper(ignore, guest):
            if not self.is_visible():
                return
            logging.debug("User finished customize dialog, starting install")
            self._failed_guest = None
            self._start_install(guest)

        def config_canceled(ignore):
            logging.debug("User closed customize window, closing wizard")
            self._close_requested()

        # We specifically don't use vmmDetails.get_instance here since
        # it's not a top level Details window
        self._cleanup_customize_window()
        self._customize_window = vmmDetails(virtinst_guest, self.topwin)
        self._customize_window.connect(
                "customize-finished", start_install_wrapper, guest)
        self._customize_window.connect("closed", config_canceled)
        self._customize_window.show()

    def _install_finished_cb(self, error, details, parentobj):
        self.reset_finish_cursor(parentobj.topwin)

        if error:
            error = (_("Unable to complete install: '%s'") % error)
            parentobj.err.show_err(error, details=details)
            self._failed_guest = self._guest
            return

        foundvm = None
        for vm in self.conn.list_vms():
            if vm.get_uuid() == self._guest.uuid:
                foundvm = vm
                break

        self._close()

        # Launch details dialog for new VM
        vmmDetails.get_instance(self, foundvm).show()


    def _start_install(self, guest):
        """
        Launch the async job to start the install
        """
        bootstrap_args = {}
        # If creating new container and "container bootstrap" is enabled
        if (self._guest.os.is_container() and
            self._get_config_oscontainer_bootstrap()):
            bootstrap_arg_keys = {
                'src': self._get_config_oscontainer_source_url,
                'dest': self.widget("install-oscontainer-fs").get_text,
                'user': self._get_config_oscontainer_source_username,
                'passwd': self._get_config_oscontainer_source_password,
                'insecure': self._get_config_oscontainer_isecure,
                'root_password': self._get_config_oscontainer_root_password,
            }
            for key, getter in bootstrap_arg_keys.items():
                bootstrap_args[key] = getter()

        parentobj = self._customize_window or self
        progWin = vmmAsyncJob(self._do_async_install, [guest, bootstrap_args],
                              self._install_finished_cb, [parentobj],
                              _("Creating Virtual Machine"),
                              _("The virtual machine is now being "
                                "created. Allocation of disk storage "
                                "and retrieval of the installation "
                                "images may take a few minutes to "
                                "complete."),
                              parentobj.topwin)
        progWin.run()

    def _do_async_install(self, asyncjob, guest, bootstrap_args):
        """
        Kick off the actual install
        """
        meter = asyncjob.get_meter()

        if bootstrap_args:
            # Start container bootstrap
            self._create_directory_tree(asyncjob, meter, bootstrap_args)
            if asyncjob.has_error():
                # Do not continue if virt-bootstrap failed
                return

        # Build a list of pools we should refresh, if we are creating storage
        refresh_pools = []
        for disk in guest.devices.disk:
            if not disk.wants_storage_creation():
                continue

            pool = disk.get_parent_pool()
            if not pool:
                continue

            poolname = pool.name()
            if poolname not in refresh_pools:
                refresh_pools.append(poolname)

        logging.debug("Starting background install process")
        guest.installer_instance.start_install(guest, meter=meter)
        logging.debug("Install completed")

        # Wait for VM to show up
        self.conn.schedule_priority_tick(pollvm=True)
        count = 0
        foundvm = None
        while count < 200:
            for vm in self.conn.list_vms():
                if vm.get_uuid() == guest.uuid:
                    foundvm = vm
            if foundvm:
                break
            count += 1
            time.sleep(.1)

        if not foundvm:
            raise RuntimeError(
                _("VM '%s' didn't show up after expected time.") % guest.name)
        vm = foundvm

        if vm.is_shutoff():
            # Domain is already shutdown, but no error was raised.
            # Probably means guest had no 'install' phase, as in
            # for live cds. Try to restart the domain.
            vm.startup()
        elif guest.installer_instance.has_install_phase():
            # Register a status listener, which will restart the
            # guest after the install has finished
            def cb():
                vm.connect_opt_out("state-changed",
                                   self._check_install_status)
                return False
            self.idle_add(cb)

        # Kick off pool updates
        for poolname in refresh_pools:
            try:
                pool = self.conn.get_pool(poolname)
                self.idle_add(pool.refresh)
            except Exception:
                logging.debug("Error looking up pool=%s for refresh after "
                    "VM creation.", poolname, exc_info=True)


    def _check_install_status(self, vm):
        """
        Watch the domain that we are installing, waiting for the state
        to change, so we can restart it as needed
        """
        if vm.is_crashed():
            logging.debug("VM crashed, cancelling install plans.")
            return True

        if not vm.is_shutoff():
            return

        if vm.get_install_abort():
            logging.debug("User manually shutdown VM, not restarting "
                          "guest after install.")
            return True

        try:
            logging.debug("Install should be completed, starting VM.")
            vm.startup()
        except Exception as e:
            self.err.show_err(_("Error continue install: %s") % str(e))

        return True


    def _create_directory_tree(self, asyncjob, meter, bootstrap_args):
        """
        Call bootstrap method from virtBootstrap and show logger messages
        as state/details.
        """
        import virtBootstrap

        meter.start(text=_("Bootstraping container"), size=100)
        def progress_update_cb(prog):
            meter.text = _(prog['status'])
            meter.update(prog['value'])

        asyncjob.details_enable()
        # Use logging filter to show messages of the progreess on the GUI
        class SetStateFilter(logging.Filter):
            def filter(self, record):
                asyncjob.details_update("%s\n" % record.getMessage())
                return True

        # Use string buffer to store log messages
        log_stream = io.StringIO()

        # Get virt-bootstrap logger
        vbLogger = logging.getLogger('virtBootstrap')
        vbLogger.setLevel(logging.DEBUG)
        # Create handler to store log messages in the string buffer
        hdlr = logging.StreamHandler(log_stream)
        hdlr.setFormatter(logging.Formatter('%(message)s'))
        # Use logging filter to show messages on GUI
        hdlr.addFilter(SetStateFilter())
        vbLogger.addHandler(hdlr)

        # Key word arguments to be passed
        kwargs = {'uri': bootstrap_args['src'],
                  'dest': bootstrap_args['dest'],
                  'not_secure': bootstrap_args['insecure'],
                  'progress_cb': progress_update_cb}
        if bootstrap_args['user'] and bootstrap_args['passwd']:
            kwargs['username'] = bootstrap_args['user']
            kwargs['password'] = bootstrap_args['passwd']
        if bootstrap_args['root_password']:
            kwargs['root_password'] = bootstrap_args['root_password']
        logging.debug('Start container bootstrap')
        try:
            virtBootstrap.bootstrap(**kwargs)
            # Success - uncheck the 'install-oscontainer-bootstrap' checkbox

            def cb():
                self.widget("install-oscontainer-bootstrap").set_active(False)
            self.idle_add(cb)
        except Exception as err:
            asyncjob.set_error("virt-bootstrap did not complete successfully",
                               '%s\n%s' % (err, log_stream.getvalue()))
