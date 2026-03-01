# Copyright (C) 2008, 2013, 2014, 2015 Red Hat, Inc.
# Copyright (C) 2008 Cole Robinson <crobinso@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

import importlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

from gi.repository import Gtk
from gi.repository import Pango

import virtinst
import virtinst.generatename
from virtinst import log

from .lib import uiutil
from .asyncjob import vmmAsyncJob
from .baseclass import vmmGObjectUI
from .connmanager import vmmConnectionManager
from .device.addstorage import vmmAddStorage
from .device.mediacombo import vmmMediaCombo
from .device.netlist import vmmNetworkList
from .engine import vmmEngine
from .object.domain import vmmDomainVirtinst
from .oslist import vmmOSList
from .storagebrowse import vmmStorageBrowser
from .vmwindow import vmmVMWindow

# Number of seconds to wait for media detection
DETECT_TIMEOUT = 20

DEFAULT_MEM = 1024

(PAGE_NAME, PAGE_INSTALL, PAGE_MEM, PAGE_STORAGE, PAGE_FINISH) = range(5)

(
    INSTALL_PAGE_ISO,
    INSTALL_PAGE_URL,
    INSTALL_PAGE_MANUAL,
    INSTALL_PAGE_IMPORT,
    INSTALL_PAGE_CONTAINER_APP,
    INSTALL_PAGE_CONTAINER_OS,
    INSTALL_PAGE_VZ_TEMPLATE,
    INSTALL_PAGE_OVA,
) = range(8)

# Column numbers for os type/version list models
(OS_COL_ID, OS_COL_LABEL, OS_COL_IS_SEP, OS_COL_IS_SHOW_ALL) = range(4)


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


def is_virt_bootstrap_installed(conn):
    ret = importlib.util.find_spec("virtBootstrap") is not None
    return ret or conn.config.CLITestOptions.fake_virtbootstrap


class _GuestData:
    """
    Wrapper to hold all data that will go into the Guest object,
    so we can rebuild it as needed.
    """

    def __init__(self, conn, capsinfo):
        self.conn = conn
        self.capsinfo = capsinfo
        self.failed_guest = None

        self.default_graphics_type = None
        self.skip_default_sound = None
        self.x86_cpu_default = None

        self.disk = None
        self.filesystem = None
        self.interface = None
        self.init = None

        self.machine = None
        self.osinfo = None
        self.uefi_requested = None
        self.name = None

        self.vcpus = None
        self.memory = None
        self.currentMemory = None

        self.location = None
        self.cdrom = None
        self.extra_args = None
        self.livecd = False

    def build_installer(self):
        kwargs = {}
        if self.location:
            kwargs["location"] = self.location
        if self.cdrom:
            kwargs["cdrom"] = self.cdrom

        installer = virtinst.Installer(self.conn, **kwargs)
        if self.extra_args:
            installer.set_extra_args([self.extra_args])
        if self.livecd:
            installer.livecd = True
        return installer

    def build_guest(self):
        guest = virtinst.Guest(self.conn)
        guest.set_capabilities_defaults(self.capsinfo)

        if self.machine:
            # If no machine was explicitly selected, we don't overwrite
            # it, because we want to
            guest.os.machine = self.machine
        if self.osinfo:
            guest.set_os_name(self.osinfo)
        if self.uefi_requested:
            guest.uefi_requested = self.uefi_requested

        if self.filesystem:
            guest.add_device(self.filesystem)
        if self.disk:
            guest.add_device(self.disk)
        if self.interface:
            guest.add_device(self.interface)

        if self.init:
            guest.os.init = self.init
        if self.name:
            guest.name = self.name
        if self.vcpus:
            guest.vcpus = self.vcpus
        if self.currentMemory:
            guest.currentMemory = self.currentMemory
        if self.memory:
            guest.memory = self.memory

        return guest


##############
# Main class #
##############


class vmmCreateVM(vmmGObjectUI):
    @classmethod
    def show_instance(cls, parentobj, uri=None):
        try:
            if not cls._instance:
                cls._instance = vmmCreateVM()
            cls._instance.show(parentobj and parentobj.topwin or None, uri=uri)
        except Exception as e:  # pragma: no cover
            if not parentobj:
                raise
            parentobj.err.show_err(_("Error launching create dialog: %s") % str(e))

    def __init__(self):
        vmmGObjectUI.__init__(self, "createvm.ui", "vmm-create")
        self._cleanup_on_app_close()

        self.conn = None
        self._capsinfo = None

        self._gdata = None

        # Distro detection state variables
        self._detect_os_in_progress = False
        self._os_already_detected_for_media = False

        self._customize_window = None

        self._storage_browser = None
        self._netlist = None
        self._ova_ovf_info = None
        self._ova_vm_name = None

        self._addstorage = vmmAddStorage(self.conn, self.builder, self.topwin)
        self.widget("storage-align").add(self._addstorage.top_box)

        def _browse_file_cb(ignore, widget):
            self._browse_file(widget)

        self._addstorage.connect("browse-clicked", _browse_file_cb)

        self._mediacombo = vmmMediaCombo(self.conn, self.builder, self.topwin)
        self._mediacombo.connect("changed", self._iso_changed_cb)
        self._mediacombo.connect("activate", self._iso_activated_cb)
        self._mediacombo.set_mnemonic_label(self.widget("install-iso-label"))
        self.widget("install-iso-align").add(self._mediacombo.top_box)

        self.builder.connect_signals(
            {
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
                "on_install_ova_browse_clicked": self._browse_ova,
                "on_install_ova_outputdir_browse_clicked": self._browse_ova_outputdir,
                "on_install_app_browse_clicked": self._browse_app,
                "on_install_oscontainer_browse_clicked": self._browse_oscontainer,
                "on_install_container_source_toggle": self._container_source_toggle,
                "on_install_detect_os_toggled": self._detect_os_toggled_cb,
                "on_enable_storage_toggled": self._toggle_enable_storage,
                "on_create_vm_name_changed": self._name_changed,
            }
        )
        self.bind_escape_key_close()

        self._init_state()

    ###########################
    # Standard window methods #
    ###########################

    def show(self, parent, uri):
        log.debug("Showing new vm wizard")

        if not self.is_visible():
            self._reset_state(uri)
            self.topwin.set_transient_for(parent)
            vmmEngine.get_instance().increment_window_counter()

        self.topwin.present()

    def _close(self, ignore1=None, ignore2=None):
        if self.is_visible():
            log.debug("Closing new vm wizard")
            vmmEngine.get_instance().decrement_window_counter()

        self.topwin.hide()

        self._cleanup_customize_window()
        if self._storage_browser:
            self._storage_browser.close()
        self._set_conn(None)
        self._gdata = None
        self._ova_ovf_info = None
        self._ova_vm_name = None

    def _cleanup(self):
        if self._storage_browser:
            self._storage_browser.cleanup()
            self._storage_browser = None
        if self._netlist:  # pragma: no cover
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
        self._gdata = None
        self._ova_ovf_info = None
        self._ova_vm_name = None

    ##########################
    # Initial state handling #
    ##########################

    def _show_startup_error(self, error, hideinstall=True):
        self.widget("startup-error-box").show()
        self.widget("create-forward").set_sensitive(False)
        if hideinstall:
            self.widget("install-box").hide()
            self.widget("arch-expander").hide()

        self.widget("startup-error").set_text(_("Error: %s") % error)
        return False

    def _show_startup_warning(self, error):
        self.widget("startup-error-box").show()
        self.widget("startup-error").set_markup(_("<span size='small'>Warning: %s</span>") % error)

    def _show_arch_warning(self, error):
        self.widget("arch-warning-box").show()
        self.widget("arch-warning").set_markup(_("<span size='small'>Warning: %s</span>") % error)

    def _init_state(self):
        self.widget("create-pages").set_show_tabs(False)
        self.widget("install-method-pages").set_show_tabs(False)

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
        archList.set_row_separator_func(lambda m, i, ignore: m[i][0] is None, None)

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
            for url in urls or []:
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

        # Install OVA
        self.widget("install-ova-entry").set_text("")
        self.widget("install-ova-outputdir").set_text("/var/lib/libvirt/images")
        self._ova_ovf_info = None
        self._ova_vm_name = None

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
        src_model = self.widget("install-oscontainer-source-url-combo").get_model()
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
        self._gdata = self._build_guestdata()
        guest = self._gdata.build_guest()

        # Helper state
        is_local = not self.conn.is_remote()
        is_storage_capable = self.conn.support.conn_storage()
        can_storage = is_local or is_storage_capable
        is_pv = guest.os.is_xenpv()
        is_container_only = self.conn.is_container_only()
        is_vz = self.conn.is_vz()
        is_vz_container = is_vz and guest.os.is_container()
        can_remote_url = self.conn.get_backend().support_remote_url_install()

        installable_arch = bool(guest.os.is_x86() or guest.os.is_ppc64() or guest.os.is_s390x())

        default_efi = (
            self.config.get_default_firmware_setting() == "uefi"
            and guest.os.is_x86()
            and guest.os.is_hvm()
        )
        if default_efi:
            log.debug("UEFI default requested via app preferences")

        if guest.prefers_uefi() or default_efi:
            try:
                # We call this for validation
                guest.enable_uefi()
                self._gdata.uefi_requested = True
                installable_arch = True
                log.debug("UEFI found, setting it as default.")
            except Exception as e:
                installable_arch = False
                log.debug("Error checking for UEFI default", exc_info=True)
                msg = _("Failed to setup UEFI: %s\nInstall options are limited.") % e
                self._show_arch_warning(msg)

        # Install Options
        method_tree = self.widget("method-tree")
        method_manual = self.widget("method-manual")
        method_local = self.widget("method-local")
        method_import = self.widget("method-import")
        method_container_app = self.widget("method-container-app")

        method_tree.set_sensitive((is_local or can_remote_url) and installable_arch)
        method_local.set_sensitive(not is_pv and can_storage and installable_arch)
        method_manual.set_sensitive(not is_container_only)
        method_import.set_sensitive(can_storage)
        method_ova = self.widget("method-ova")
        method_ova.set_sensitive(can_storage)
        virt_methods = [method_local, method_tree, method_manual, method_import, method_ova]

        local_tt = None
        tree_tt = None
        import_tt = None

        if not is_local:
            if not can_remote_url:
                tree_tt = _("Libvirt version does not support remote URL installs.")
            if not is_storage_capable:  # pragma: no cover
                local_tt = _("Connection does not support storage management.")
                import_tt = local_tt

        if is_pv:
            local_tt = _("CDROM/ISO installs not available for paravirt guests.")

        if not installable_arch:
            msg = _("Architecture '%s' is not installable") % guest.os.arch
            tree_tt = msg
            local_tt = msg

        if not any([w.get_active() and w.get_sensitive() for w in virt_methods]):
            for w in virt_methods:
                if w.get_sensitive():
                    w.set_active(True)
                    break

        if not (is_container_only or [w for w in virt_methods if w.get_sensitive()]):
            return self._show_startup_error(  # pragma: no cover
                _("No install methods available for this connection."), hideinstall=False
            )

        method_tree.set_tooltip_text(tree_tt or "")
        method_local.set_tooltip_text(local_tt or "")
        method_import.set_tooltip_text(import_tt or "")
        method_ova.set_tooltip_text(import_tt or "")

        # Container install options
        method_container_app.set_active(True)
        self.widget("container-install-box").set_visible(is_container_only)
        self.widget("vz-install-box").set_visible(is_vz)
        self.widget("virt-install-box").set_visible(not is_container_only and not is_vz_container)

        self.widget("kernel-info-box").set_visible(not installable_arch)

    def _populate_conn_state(self):
        """
        Update all state that has some dependency on the current connection
        """
        self.conn.schedule_priority_tick(pollnet=True, pollpool=True, pollnodedev=True)

        self.widget("install-box").show()
        self.widget("create-forward").set_sensitive(True)

        self._capsinfo = None
        self.conn.invalidate_caps()

        if not self.conn.caps.has_install_options():
            error = _("No hypervisor options were found for this connection.")

            if self.conn.is_qemu():
                error += "\n\n"
                error += _(
                    "This usually means that QEMU or KVM is not "
                    "installed on your machine, or the KVM kernel "
                    "modules are not loaded."
                )
            return self._show_startup_error(error)

        self._change_caps()

        # A bit out of order, but populate the xen/virt/arch/machine lists
        # so we can work with a default.
        self._populate_xen_type()
        self._populate_arch()
        self._populate_virt_type()

        show_arch = (
            self.widget("xen-type").get_visible()
            or self.widget("virt-type").get_visible()
            or self.widget("arch").get_visible()
            or self.widget("machine").get_visible()
        )
        uiutil.set_grid_row_visible(self.widget("arch-expander"), show_arch)

        if self.conn.is_qemu():
            if not self._capsinfo.guest.is_kvm_available():
                error = _(
                    "KVM is not available. This may mean the KVM "
                    "package is not installed, or the KVM kernel modules "
                    "are not loaded. Your virtual machines may perform poorly."
                )
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
            self.widget("vz-virt-type-exe").set_active(not has_hvm_guests and has_exe_guests)

        # ISO media
        # Dependent on connection so we need to do this here
        self._mediacombo.set_conn(self.conn)
        self._mediacombo.reset_state()

        # Allow container bootstrap only for local connection and
        # only if virt-bootstrap is installed. Otherwise, show message.
        is_local = not self.conn.is_remote()
        vb_installed = is_virt_bootstrap_installed(self.conn)
        vb_enabled = is_local and vb_installed

        oscontainer_widget_conf = {
            "install-oscontainer-notsupport-conn": not is_local,
            "install-oscontainer-notsupport": not vb_installed,
            "install-oscontainer-bootstrap": vb_enabled,
            "install-oscontainer-source": vb_enabled,
            "install-oscontainer-rootpw-box": vb_enabled,
        }
        for wname, val in oscontainer_widget_conf.items():
            self.widget(wname).set_visible(val)

        # Memory
        memory = int(self.conn.host_memory_size())
        mem_label = _("Up to %(maxmem)s available on the host") % {"maxmem": _pretty_memory(memory)}
        mem_label = "<span size='small'>%s</span>" % mem_label
        self.widget("mem").set_range(50, memory // 1024)
        self.widget("phys-mem-label").set_markup(mem_label)

        # CPU
        phys_cpus = int(self.conn.host_active_processor_count())
        cpu_label = ngettext(
            "Up to %(numcpus)d available", "Up to %(numcpus)d available", phys_cpus
        ) % {"numcpus": int(phys_cpus)}
        cpu_label = "<span size='small'>%s</span>" % cpu_label
        self.widget("cpus").set_range(1, max(phys_cpus, 1))
        self.widget("phys-cpu-label").set_markup(cpu_label)

        # Storage
        self._addstorage.conn = self.conn
        self._addstorage.reset_state()

        # Networking
        self.widget("advanced-expander").set_expanded(False)

        self._netlist = vmmNetworkList(self.conn, self.builder, self.topwin)
        self.widget("netdev-ui-align").add(self._netlist.top_box)
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
            return self._show_startup_error(_("No active connection to install on."))
        self.conn.connect("state-changed", self._conn_state_changed)

        try:
            return self._populate_conn_state()
        except Exception as e:  # pragma: no cover
            log.exception("Error setting create wizard conn state.")
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

        capsinfo = self.conn.caps.guest_lookup(os_type=gtype, arch=arch, typ=domtype)

        if self._capsinfo:
            if self._capsinfo.guest == capsinfo.guest and self._capsinfo.domain == capsinfo.domain:
                return

        self._capsinfo = capsinfo
        log.debug(
            "Guest type set to os_type=%s, arch=%s, dom_type=%s",
            self._capsinfo.os_type,
            self._capsinfo.arch,
            self._capsinfo.hypervisor_type,
        )
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
                continue  # pragma: no cover

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
            if gtype == self._capsinfo.os_type and domtype == self._capsinfo.hypervisor_type:
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
        if self.conn.caps.host.cpu.arch == "x86_64" and "x86_64" in archs and "i686" in archs:
            archs.remove("i686")
        archs.sort()

        prios = ["x86_64", "i686", "aarch64", "armv7l", "ppc64", "ppc64le", "riscv64", "s390x"]
        if self.conn.caps.host.cpu.arch not in prios:
            prios = []  # pragma: no cover
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
        recommended_machine = virtinst.Guest.get_recommended_machine(self._capsinfo)
        if recommended_machine:
            defmachine = recommended_machine
            prios = [defmachine]

        for p in prios[:]:
            if p not in machines:
                prios.remove(p)  # pragma: no cover
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

            show = len(machines) > 1
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

        no_conns = len(model) == 0

        if default < 0 and not no_conns:
            default = 0  # pragma: no cover

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
        storagetmpl = "<span size='small'>%s</span>"
        storagesize = ""
        storagepath = ""

        disk = self._gdata.disk
        fs = self._gdata.filesystem
        if disk:
            if disk.wants_storage_creation():
                storagesize = "%s" % _pretty_storage(disk.get_size())
            if not path:
                path = disk.get_source_path()
            storagepath = storagetmpl % path
        elif fs:
            storagepath = storagetmpl % fs.source
        else:
            storagepath = _("None")

        self.widget("summary-storage").set_markup(storagesize)
        self.widget("summary-storage").set_visible(bool(storagesize))
        self.widget("summary-storage-path").set_markup(storagepath)

    def _populate_summary(self):
        guest = self._gdata.build_guest()
        mem = _pretty_memory(int(guest.memory))
        cpu = str(int(guest.vcpus))

        instmethod = self._get_config_install_page()

        # OVA import summary: guest/mem/cpu were built from _gdata which
        # was updated by the mem page validation; just override OS/install text
        if instmethod == INSTALL_PAGE_OVA and self._ova_ovf_info:
            osobj = self._os_list.get_selected_os()
            os_label = osobj.label if osobj else _("Generic")
            self.widget("summary-os").set_text(os_label)
            self.widget("summary-install").set_text(_("Import OVA archive"))
            self.widget("summary-mem").set_text(mem)
            self.widget("summary-cpu").set_text(cpu)
            self._populate_summary_storage()
            return
        install = ""
        if instmethod == INSTALL_PAGE_ISO:
            install = _("Local CDROM/ISO")
        elif instmethod == INSTALL_PAGE_URL:
            install = _("URL Install Tree")
        elif instmethod == INSTALL_PAGE_IMPORT:
            install = _("Import existing OS image")
        elif instmethod == INSTALL_PAGE_MANUAL:
            install = _("Manual install")
        elif instmethod == INSTALL_PAGE_CONTAINER_APP:
            install = _("Application container")
        elif instmethod == INSTALL_PAGE_CONTAINER_OS:
            install = _("Operating system container")
        elif instmethod == INSTALL_PAGE_VZ_TEMPLATE:
            install = _("Virtuozzo container")
        elif instmethod == INSTALL_PAGE_OVA:
            install = _("Import OVA archive")

        self.widget("summary-os").set_text(guest.osinfo.label)
        self.widget("summary-install").set_text(install)
        self.widget("summary-mem").set_text(mem)
        self.widget("summary-cpu").set_text(cpu)
        self._populate_summary_storage()

        nsource = self._netlist.get_network_selection()[1]
        if not nsource:
            self.widget("advanced-expander").set_expanded(True)

    ################################
    # UI state getters and helpers #
    ################################

    def _get_config_name(self):
        return self.widget("create-vm-name").get_text()

    def _get_config_machine(self):
        return uiutil.get_list_selection(self.widget("machine"), check_visible=True)

    def _get_config_install_page(self):
        if self.widget("vz-install-box").get_visible():
            if self.widget("vz-virt-type-exe").get_active():
                return INSTALL_PAGE_VZ_TEMPLATE
        if self.widget("virt-install-box").get_visible():
            if self.widget("method-local").get_active():
                return INSTALL_PAGE_ISO
            elif self.widget("method-tree").get_active():
                return INSTALL_PAGE_URL
            elif self.widget("method-import").get_active():
                return INSTALL_PAGE_IMPORT
            elif self.widget("method-manual").get_active():
                return INSTALL_PAGE_MANUAL
            elif self.widget("method-ova").get_active():
                return INSTALL_PAGE_OVA
        else:
            if self.widget("method-container-app").get_active():
                return INSTALL_PAGE_CONTAINER_APP
            if self.widget("method-container-os").get_active():
                return INSTALL_PAGE_CONTAINER_OS

    def _is_container_install(self):
        return self._get_config_install_page() in [
            INSTALL_PAGE_CONTAINER_APP,
            INSTALL_PAGE_CONTAINER_OS,
            INSTALL_PAGE_VZ_TEMPLATE,
        ]

    def _get_config_oscontainer_bootstrap(self):
        return self.widget("install-oscontainer-bootstrap").get_active()

    def _get_config_oscontainer_source_url(self, store_media=False):
        src_url = self.widget("install-oscontainer-source-url-entry").get_text().strip()

        if src_url and store_media:
            self.config.add_container_url(src_url)

        return src_url

    def _get_config_oscontainer_source_username(self):
        return self.widget("install-oscontainer-source-user").get_text().strip()

    def _get_config_oscontainer_source_password(self):
        return self.widget("install-oscontainer-source-passwd").get_text()

    def _get_config_oscontainer_isecure(self):
        return self.widget("install-oscontainer-source-insecure").get_active()

    def _get_config_oscontainer_root_password(self):
        return self.widget("install-oscontainer-rootpw").get_text()

    def _should_skip_disk_page(self):
        return self._get_config_install_page() in [
            INSTALL_PAGE_IMPORT,
            INSTALL_PAGE_OVA,
            INSTALL_PAGE_CONTAINER_APP,
            INSTALL_PAGE_CONTAINER_OS,
            INSTALL_PAGE_VZ_TEMPLATE,
        ]

    def _get_config_ova_path(self):
        return self.widget("install-ova-entry").get_text()

    def _get_config_ova_output_dir(self):
        return self.widget("install-ova-outputdir").get_text()

    def _get_config_local_media(self, store_media=False):
        return self._mediacombo.get_path(store_media=store_media)

    def _get_config_detectable_media(self):
        instpage = self._get_config_install_page()
        cdrom = None
        location = None

        if instpage == INSTALL_PAGE_ISO:
            cdrom = self._get_config_local_media()
        elif instpage == INSTALL_PAGE_URL:
            location = self.widget("install-url-entry").get_text()

        return cdrom, location

    def _get_config_url_info(self, store_media=False):
        media = self.widget("install-url-entry").get_text().strip()
        extra = self.widget("install-urlopts-entry").get_text().strip()

        if media and store_media:
            self.config.add_media_url(media)

        return (media, extra)

    def _get_config_import_path(self):
        return self.widget("install-import-entry").get_text()

    def _is_default_storage(self):
        return self._addstorage.is_default_storage() and not self._should_skip_disk_page()

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
        if not self._gdata or not self._gdata.failed_guest:
            self._close()
            return 1

        def _cleanup_disks(asyncjob, _failed_guest):
            meter = asyncjob.get_meter()
            virtinst.Installer.cleanup_created_disks(_failed_guest, meter)

        def _cleanup_disks_finished(error, details):
            if error:  # pragma: no cover
                log.debug("Error cleaning up disk images:\nerror=%s\ndetails=%s", error, details)
            self.idle_add(self._close)

        progWin = vmmAsyncJob(
            _cleanup_disks,
            [self._gdata.failed_guest],
            _cleanup_disks_finished,
            [],
            _("Removing disk images"),
            _("Removing disk images we created for this virtual machine."),
            self.topwin,
        )
        progWin.run()

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
        if checkfocus and hasattr(widget, "get_text") and widget.has_focus():
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
            return  # pragma: no cover

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

    def _browse_ova(self, ignore):
        dialog = Gtk.FileChooserDialog(
            title=_("Choose an OVA file"),
            transient_for=self.topwin,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Open"), Gtk.ResponseType.ACCEPT)

        ova_filter = Gtk.FileFilter()
        ova_filter.set_name(_("OVA archives (*.ova)"))
        ova_filter.add_pattern("*.ova")
        ova_filter.add_pattern("*.OVA")
        dialog.add_filter(ova_filter)
        dialog.set_filter(ova_filter)

        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self.widget("install-ova-entry").set_text(dialog.get_filename())
        dialog.destroy()

    def _browse_ova_outputdir(self, ignore):
        self._browse_file("install-ova-outputdir", is_dir=True)

    def _browse_iso(self, ignore):
        def set_path(ignore, path):
            self._mediacombo.set_path(path)

        self._browse_file(None, cb=set_path, is_media=True)

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
        except Exception:  # pragma: no cover
            log.debug(
                "Error generating storage path on name change for name=%s",
                newname,
                exc_info=True,
            )

    # Enable/Disable container source URL entry on checkbox click
    def _container_source_toggle(self, ignore):
        enable_src = self.widget("install-oscontainer-bootstrap").get_active()
        self.widget("install-oscontainer-source").set_sensitive(enable_src)
        self.widget("install-oscontainer-rootpw-box").set_sensitive(enable_src)

        # Auto-generate a path if not specified
        if enable_src and not self.widget("install-oscontainer-fs").get_text():
            fs_dir = ["/var/lib/libvirt/filesystems/"]
            if os.geteuid() != 0:
                fs_dir = [os.path.expanduser("~"), ".local/share/libvirt/filesystems/"]

            guest = self._gdata.build_guest()
            default_name = virtinst.Guest.generate_name(guest)
            fs = fs_dir + [default_name]
            self.widget("install-oscontainer-fs").set_text(os.path.join(*fs))

    ########################
    # Misc helper routines #
    ########################

    def _browse_file(self, cbwidget, cb=None, is_media=False, is_dir=False):
        if is_media:
            reason = vmmStorageBrowser.REASON_ISO_MEDIA
        elif is_dir:
            reason = vmmStorageBrowser.REASON_FS
        else:
            reason = vmmStorageBrowser.REASON_IMAGE

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

        page_lbl = _("Step %(current_page)d of %(max_page)d") % {
            "current_page": cur,
            "max_page": final,
        }

        self.widget("header-pagenum").set_markup(page_lbl)

    def _change_os_detect(self, sensitive):
        self._os_list.set_sensitive(sensitive)
        if not sensitive and not self._os_list.get_selected_os():
            self._os_list.search_entry.set_text(_("Waiting for install media / source"))

    def _set_install_page(self):
        instpage = self._get_config_install_page()

        self.widget("install-os-distro-box").set_visible(
            not self._is_container_install()
        )

        enabledetect = False
        if instpage == INSTALL_PAGE_URL:
            enabledetect = True
        elif instpage == INSTALL_PAGE_ISO and not self.conn.is_remote():
            enabledetect = True

        self.widget("install-detect-os-box").set_visible(enabledetect)
        dodetect = enabledetect and self.widget("install-detect-os").get_active()
        self._change_os_detect(not dodetect)

        # Manual installs have nothing to ask for
        has_install = instpage != INSTALL_PAGE_MANUAL
        self.widget("install-method-pages").set_visible(has_install)
        if not has_install:
            self._os_list.search_entry.grab_focus()
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
            did_start = self._start_detect_os_if_needed(forward_after_finish=True)
            if did_start:
                return

        if self._validate(curpage) is not True:
            return

        self.widget("create-forward").grab_focus()
        if curpage == PAGE_NAME:
            self._set_install_page()

        next_page = self._get_next_pagenum(curpage)
        notebook.set_current_page(next_page)

    def _page_changed(self, ignore1, ignore2, pagenum):
        if pagenum == PAGE_FINISH:
            try:
                self._populate_summary()
            except Exception as e:  # pragma: no cover
                self.err.show_err(_("Error populating summary page: %s") % str(e))
                return

            self.widget("create-finish").grab_focus()

        self.widget("create-back").set_sensitive(pagenum != PAGE_NAME)
        self.widget("create-forward").set_visible(pagenum != PAGE_FINISH)
        self.widget("create-finish").set_visible(pagenum == PAGE_FINISH)

        # Hide all other pages, so the dialog isn't all stretched out
        # because of one large page.
        for nr in range(self.widget("create-pages").get_n_pages()):
            page = self.widget("create-pages").get_nth_page(nr)
            page.set_visible(nr == pagenum)

        self._set_page_num_text(pagenum)

    ############################
    # Page validation routines #
    ############################

    def _build_guestdata(self):
        gdata = _GuestData(self.conn.get_backend(), self._capsinfo)

        gdata.default_graphics_type = self.config.get_graphics_type()
        gdata.x86_cpu_default = self.config.get_default_cpu_setting()

        return gdata

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
        except Exception as e:  # pragma: no cover
            self.err.show_err(_("Uncaught error validating install parameters: %s") % str(e))
            return

    def _validate_intro_page(self):
        self._gdata.machine = self._get_config_machine()
        return bool(self._gdata.build_guest())

    def _validate_oscontainer_bootstrap(self, fs, src_url, user, passwd):
        # Check if the source path was provided
        if not src_url:
            return self.err.val_err(_("Source URL is required"))

        # Require username and password when authenticate
        # to source registry.
        if user and not passwd:
            msg = _("Please specify password for accessing source registry")
            return self.err.val_err(msg)

        # Validate destination path
        if not os.path.exists(fs):
            return  # pragma: no cover

        if not os.path.isdir(fs):
            msg = _("Destination path is not directory: %s") % fs
            return self.err.val_err(msg)
        if not os.access(fs, os.W_OK):
            msg = _("No write permissions for directory path: %s") % fs
            return self.err.val_err(msg)
        if os.listdir(fs) == []:
            return

        # Show Yes/No dialog if the destination is not empty
        return self.err.yes_no(
            _("OS root directory is not empty"),
            _(
                "Creating root file system in a non-empty "
                "directory might fail due to file conflicts.\n"
                "Would you like to continue?"
            ),
        )

    def _validate_install_page(self):
        instmethod = self._get_config_install_page()
        installer = None
        location = None
        extra = None
        cdrom = None
        is_import = False
        init = None
        fs = None
        template = None
        osobj = self._os_list.get_selected_os()

        if instmethod == INSTALL_PAGE_ISO:
            media = self._get_config_local_media()
            if not media:
                msg = _("An install media selection is required.")
                return self.err.val_err(msg)
            cdrom = media

        elif instmethod == INSTALL_PAGE_URL:
            media, extra = self._get_config_url_info()

            if not media:
                return self.err.val_err(_("An install tree is required."))

            location = media

        elif instmethod == INSTALL_PAGE_IMPORT:
            is_import = True
            import_path = self._get_config_import_path()
            if not import_path:
                msg = _("A storage path to import is required.")
                return self.err.val_err(msg)

            if not virtinst.DeviceDisk.path_definitely_exists(self.conn.get_backend(), import_path):
                msg = _("The import path must point to an existing storage.")
                return self.err.val_err(msg)

        elif instmethod == INSTALL_PAGE_OVA:
            if not self._validate_ova_page():
                return False
            # Re-read after _validate_ova_page() may have auto-selected an OS
            osobj = self._os_list.get_selected_os()
            self._gdata.osinfo = osobj and osobj.name or None
            return True

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
                ret = self._validate_oscontainer_bootstrap(fs, src_url, user, passwd)
                if ret is False:
                    return False

        elif instmethod == INSTALL_PAGE_VZ_TEMPLATE:
            template = self.widget("install-container-template").get_text()
            if not template:
                return self.err.val_err(_("A template name is required."))

        if not self._is_container_install() and not osobj:
            msg = _("You must select an OS.")
            msg += "\n\n" + self._os_list.eol_text
            return self.err.val_err(msg)

        # Build the installer and Guest instance
        try:
            if init:
                self._gdata.init = init

            if fs:
                fsdev = virtinst.DeviceFilesystem(self._gdata.conn)
                fsdev.target = "/"
                fsdev.source = fs
                self._gdata.filesystem = fsdev

            if template:
                fsdev = virtinst.DeviceFilesystem(self._gdata.conn)
                fsdev.target = "/"
                fsdev.type = "template"
                fsdev.source = template
                self._gdata.filesystem = fsdev

            self._gdata.location = location
            self._gdata.cdrom = cdrom
            self._gdata.extra_args = extra
            self._gdata.livecd = False
            self._gdata.osinfo = osobj and osobj.name or None
            guest = self._gdata.build_guest()
            installer = self._gdata.build_installer()
        except Exception as e:
            msg = _("Error setting installer parameters.")
            return self.err.val_err(msg, e)

        try:
            name = virtinst.Guest.generate_name(guest)
            virtinst.Guest.validate_name(self._gdata.conn, name)
            self._gdata.name = name
        except Exception as e:  # pragma: no cover
            return self.err.val_err(_("Error setting default name."), e)

        self.widget("create-vm-name").set_text(self._gdata.name)

        # Kind of wonky, run storage validation now, which will assign
        # the import path. Import installer skips the storage page.
        if is_import:
            if not self._validate_storage_page():
                return False

        for path in installer.get_search_paths(guest):
            self._addstorage.check_path_search(self, self.conn, path)

        res = guest.osinfo.get_recommended_resources()
        ram = res.get_recommended_ram(guest.os.arch)
        n_cpus = res.get_recommended_ncpus(guest.os.arch)
        storage = res.get_recommended_storage(guest.os.arch)
        log.debug(
            "Recommended resources for os=%s: ram=%s ncpus=%s storage=%s",
            guest.osinfo.name,
            ram,
            n_cpus,
            storage,
        )

        # Change the default values suggested to the user.
        ram_size = DEFAULT_MEM
        if ram:
            ram_size = ram // (1024**2)
        self.widget("mem").set_value(ram_size)

        self.widget("cpus").set_value(n_cpus or 1)

        if storage:
            storage_size = storage // (1024**3)
            self._addstorage.widget("storage-size").set_value(storage_size)

        # Validation passed, store the install path (if there is one) in
        # gsettings
        self._get_config_oscontainer_source_url(store_media=True)
        self._get_config_local_media(store_media=True)
        self._get_config_url_info(store_media=True)
        return True

    def _validate_mem_page(self):
        cpus = self.widget("cpus").get_value()
        mem = self.widget("mem").get_value()

        self._gdata.vcpus = int(cpus)
        self._gdata.currentMemory = int(mem) * 1024
        self._gdata.memory = int(mem) * 1024

        return True

    def _get_storage_path(self, vmname, do_log):
        failed_disk = None
        if self._gdata.failed_guest:
            failed_disk = self._gdata.disk

        path = None
        path_already_created = False

        if self._get_config_install_page() == INSTALL_PAGE_IMPORT:
            path = self._get_config_import_path()

        elif self._is_default_storage():
            if failed_disk:
                # Don't generate a new path if the install failed
                path = failed_disk.get_source_path()
                path_already_created = failed_disk.storage_was_created
                if do_log:
                    log.debug(
                        "Reusing failed disk path=%s already_created=%s",
                        path,
                        path_already_created,
                    )
            else:
                path = self._addstorage.get_default_path(vmname)
                if do_log:
                    log.debug("Default storage path is: %s", path)

        return path, path_already_created

    def _validate_storage_page(self):
        path, path_already_created = self._get_storage_path(self._gdata.name, do_log=True)

        disk = None
        storage_enabled = self.widget("enable-storage").get_active()
        try:
            if storage_enabled:
                disk = self._addstorage.build_device(self._gdata.name, path=path)

            if disk and self._addstorage.validate_device(disk) is False:
                return False
        except Exception as e:
            return self.err.val_err(_("Storage parameter error."), e)

        if self._get_config_install_page() == INSTALL_PAGE_ISO:
            # CD/ISO install and no disks implies LiveCD
            self._gdata.livecd = not storage_enabled

        self._gdata.disk = disk
        if not storage_enabled:
            return True

        disk.storage_was_created = path_already_created
        return True

    def _validate_final_page(self):
        # OVA import: just capture the (possibly edited) VM name
        if self._get_config_install_page() == INSTALL_PAGE_OVA:
            name = self._get_config_name().strip()
            if name:
                self._ova_vm_name = name
            return True

        # HV + Arch selection
        name = self._get_config_name()
        if name != self._gdata.name:
            try:
                virtinst.Guest.validate_name(self._gdata.conn, name)
                self._gdata.name = name
            except Exception as e:
                return self.err.val_err(_("Invalid guest name"), str(e))
            if self._is_default_storage():
                log.debug(
                    "User changed VM name and using default "
                    "storage, re-validating with new default storage path."
                )
                if not self._validate_storage_page():
                    return False  # pragma: no cover

        macaddr = virtinst.DeviceInterface.generate_mac(self.conn.get_backend())

        net = self._netlist.build_device(macaddr)

        self._netlist.validate_device(net)
        self._gdata.interface = net
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
        is_install_page = self.widget("create-pages").get_current_page() == PAGE_INSTALL
        cdrom, location = self._get_config_detectable_media()

        if self._detect_os_in_progress:
            return  # pragma: no cover
        if not is_install_page:
            return  # pragma: no cover
        if not cdrom and not location:
            return
        if not self._is_os_detect_active():
            return
        if self._os_already_detected_for_media:
            return

        self._do_start_detect_os(cdrom, location, forward_after_finish)
        return True

    def _do_start_detect_os(self, cdrom, location, forward_after_finish):
        self._detect_os_in_progress = False

        log.debug("Starting OS detection thread for cdrom=%s location=%s", cdrom, location)
        self.widget("create-forward").set_sensitive(False)

        class ThreadResults:
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
        detectThread = threading.Thread(
            target=self._detect_thread_cb,
            name="Actual media detection",
            args=(cdrom, location, thread_results),
        )
        detectThread.daemon = True
        detectThread.start()

        self._os_list.search_entry.set_text(_("Detecting..."))
        spin = self.widget("install-detect-os-spinner")
        spin.start()

        self._report_detect_os_progress(0, thread_results, forward_after_finish)

    def _detect_thread_cb(self, cdrom, location, thread_results):
        """
        Thread callback that does the actual detection
        """
        try:
            installer = virtinst.Installer(self.conn.get_backend(), cdrom=cdrom, location=location)
            distro = installer.detect_distro(self._gdata.build_guest())
            thread_results.set_distro(distro)
        except Exception:
            log.exception("Error detecting distro.")
            thread_results.set_failed()

    def _report_detect_os_progress(self, idx, thread_results, forward_after_finish):
        """
        Checks detection progress via the _detect_os_results variable
        and updates the UI labels, counts the number of iterations,
        etc.

        We set a hard time limit on the distro detection to avoid the
        chance of the detection hanging (like slow URL lookup)
        """
        try:
            if thread_results.in_progress() and (idx < (DETECT_TIMEOUT * 2)):
                # Thread is still going and we haven't hit the timeout yet,
                # so update the UI labels and reschedule this function
                self.timeout_add(
                    500,
                    self._report_detect_os_progress,
                    idx + 1,
                    thread_results,
                    forward_after_finish,
                )
                return

            distro = thread_results.get_distro()
        except Exception:  # pragma: no cover
            distro = None
            log.exception("Error in distro detect timeout")

        spin = self.widget("install-detect-os-spinner")
        spin.stop()
        log.debug("Finished UI OS detection.")

        self.widget("create-forward").set_sensitive(True)
        self._os_already_detected_for_media = True
        self._detect_os_in_progress = False

        if not self._is_os_detect_active():
            # If the user changed the OS detect checkbox in the meantime,
            # don't update the UI
            return  # pragma: no cover

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

    def _validate_ova_page(self):
        """
        Validate the OVA install page, parse the OVF descriptor,
        and pre-populate name/memory/CPU fields from it.
        """
        from .importova import _read_ovf_from_ova, _parse_ovf

        ova_path = self._get_config_ova_path()
        if not ova_path:
            return self.err.val_err(_("An OVA archive path is required."))
        if not os.path.exists(ova_path):
            return self.err.val_err(
                _("The path must point to an existing .ova file.")
            )
        if not ova_path.lower().endswith(".ova"):
            return self.err.val_err(
                _("Only .ova archive files are supported.\n\nThe selected file does not have a .ova extension.")
            )

        output_dir = self._get_config_ova_output_dir()
        if not output_dir:
            return self.err.val_err(
                _("An output directory for converted disk images is required.")
            )
        if not os.path.isdir(output_dir):
            return self.err.val_err(
                _("Output directory does not exist:\n%s\n\nEnter the target path of an active libvirt storage pool.") % output_dir
            )

        try:
            ovf_bytes = _read_ovf_from_ova(ova_path)
            ovf_info = _parse_ovf(ovf_bytes)
        except Exception as e:
            return self.err.val_err(
                _("Failed to read OVA file: %s") % str(e)
            )

        self._ova_ovf_info = ovf_info

        # Pre-populate name from OVF
        try:
            virtinst.Guest.validate_name(self._gdata.conn, ovf_info.name)
            name = ovf_info.name
        except Exception:
            try:
                name = virtinst.Guest.generate_name(self._gdata.build_guest())
            except Exception:
                name = "imported-vm"

        self.widget("create-vm-name").set_text(name)
        self._ova_vm_name = name
        self._gdata.name = name

        # Pre-populate memory and CPU from OVF
        mem_val = ovf_info.memory_mb
        mem_max = self.widget("mem").get_adjustment().get_upper()
        self.widget("mem").set_value(min(mem_val, mem_max))
        cpu_max = self.widget("cpus").get_adjustment().get_upper()
        self.widget("cpus").set_value(min(ovf_info.vcpus, cpu_max))

        # Pre-select OS from OVF hint — only when the user hasn't already
        # picked one, so a manual choice is never silently overridden.
        if not self._os_list.get_selected_os():
            osobj = virtinst.OSDB.guess_os_from_ovf_hint(
                vmw_type=ovf_info.ovf_vmw_type,
                vbox_type=ovf_info.ovf_vbox_type,
                cim_id=ovf_info.ovf_cim_id,
            )
            if osobj:
                self._os_list.select_os(osobj)
                log.debug("OVA import: pre-selected OS '%s' from OVF hints "
                          "vmw=%r vbox=%r cim=%r",
                          osobj.label, ovf_info.ovf_vmw_type,
                          ovf_info.ovf_vbox_type, ovf_info.ovf_cim_id)

        return True

    def _start_ova_import(self):
        """
        Launch an async job to convert VMDK disks to qcow2 and define
        the domain via libvirt.
        """
        ova_path = self._get_config_ova_path()
        output_dir = self._get_config_ova_output_dir()
        vm_name = (self._ova_vm_name or
                   self.widget("create-vm-name").get_text().strip() or
                   "imported-vm")
        ovf_info = self._ova_ovf_info
        conn = self.conn
        osname = self._gdata.osinfo
        # Use user-adjusted memory/CPU values if available from the mem page
        vcpus = self._gdata.vcpus or ovf_info.vcpus
        memory_kib = self._gdata.memory or (ovf_info.memory_mb * 1024)

        self.set_finish_cursor()
        progWin = vmmAsyncJob(
            self._do_ova_import,
            [ova_path, vm_name, output_dir, ovf_info, vcpus, memory_kib, osname, conn],
            self._ova_import_finished_cb,
            [],
            _("Importing OVA"),
            _("Converting and importing \"%s\"…") % vm_name,
            self.topwin,
        )
        progWin.run()

    def _do_ova_import(self, asyncjob, ova_path, vm_name, output_dir, ovf_info, vcpus, memory_kib, osname, conn):
        """
        Background thread: extract OVA, convert VMDK→qcow2 in /tmp, then
        upload into the libvirt storage pool via the daemon (no direct
        filesystem write to the pool directory required).
        """
        backend_conn = conn.get_backend()
        tmpdir = tempfile.mkdtemp(prefix="virt-manager-ova-")
        converted_disks = []  # final vol paths for domain XML

        try:
            # ── 1. Extract only the VMDK files we need ─────────────────────
            needed_vmdks = {d["vmdk"] for d in ovf_info.disks}
            asyncjob._pbar_pulse(stage=_("Extracting OVA archive…"))
            log.debug("Extracting VMDKs %s from %s → %s", needed_vmdks, ova_path, tmpdir)
            with tarfile.open(ova_path, "r:*") as tar:
                members = [m for m in tar.getmembers()
                           if os.path.basename(m.name) in needed_vmdks]
                if not members:
                    # Fallback: extract everything if name matching failed
                    log.debug("VMDK name match failed; extracting full archive")
                    members = tar.getmembers()
                try:
                    tar.extractall(tmpdir, members=members, filter="data")
                except TypeError:
                    tar.extractall(tmpdir, members=members)  # noqa: S202

            # ── 2. Find the libvirt pool matching output_dir ─────────────────
            pool = None
            try:
                for pname in (backend_conn.listStoragePools() +
                              backend_conn.listDefinedStoragePools()):
                    p = backend_conn.storagePoolLookupByName(pname)
                    pxml = ET.fromstring(p.XMLDesc(0))
                    tpath = (pxml.findtext("target/path") or "").rstrip("/")
                    if tpath == output_dir.rstrip("/"):
                        pool = p
                        log.debug("Using libvirt pool '%s' for OVA import", pname)
                        break
            except Exception:
                log.debug("Error looking up storage pool", exc_info=True)
            if pool is None:
                try:
                    pool = backend_conn.storagePoolLookupByName("default")
                    log.debug("Falling back to 'default' storage pool")
                except Exception:
                    log.debug("No default pool found; will write directly", exc_info=True)

            # ── 3. Convert each VMDK → qcow2 in tmpdir, then upload ─────────
            total = len(ovf_info.disks)
            for idx, disk_info in enumerate(ovf_info.disks, start=1):
                vmdk_name = disk_info["vmdk"]
                vmdk_path = os.path.join(tmpdir, vmdk_name)
                if not os.path.isfile(vmdk_path):
                    raise RuntimeError(
                        _("Disk file '%s' not found inside the extracted OVA.") % vmdk_name
                    )

                base = os.path.splitext(os.path.basename(vmdk_name))[0]
                qcow2_name = "%s-%s.qcow2" % (vm_name, base)
                tmp_qcow2 = os.path.join(tmpdir, qcow2_name)

                asyncjob._pbar_pulse(
                    stage=_("Converting disk %(n)d/%(total)d: %(src)s") % {
                        "n": idx, "total": total, "src": vmdk_name,
                    }
                )
                log.debug("qemu-img: %s → %s", vmdk_path, tmp_qcow2)
                result = subprocess.run(
                    ["qemu-img", "convert", "-f", "vmdk", "-O", "qcow2",
                     vmdk_path, tmp_qcow2],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        _("qemu-img failed converting '%(disk)s':\n%(err)s") % {
                            "disk": vmdk_name,
                            "err": (result.stderr or result.stdout).strip(),
                        }
                    )

                file_size = os.path.getsize(tmp_qcow2)
                virtual_size = file_size
                try:
                    info_r = subprocess.run(
                        ["qemu-img", "info", "--output=json", tmp_qcow2],
                        capture_output=True, text=True,
                    )
                    if info_r.returncode == 0:
                        virtual_size = json.loads(info_r.stdout).get(
                            "virtual-size", file_size
                        )
                except Exception:
                    pass

                if pool is not None:
                    asyncjob._pbar_pulse(
                        stage=_("Uploading disk %(n)d/%(total)d to storage pool…") % {
                            "n": idx, "total": total,
                        }
                    )
                    vol_xml = (
                        "<volume>"
                        "<name>%s</name>"
                        "<capacity unit='bytes'>%d</capacity>"
                        "<allocation unit='bytes'>%d</allocation>"
                        "<target><format type='qcow2'/></target>"
                        "</volume>" % (qcow2_name, virtual_size, file_size)
                    )
                    try:
                        # Delete any leftover volume from a previous failed import
                        try:
                            existing = pool.storageVolLookupByName(qcow2_name)
                            log.debug("Deleting pre-existing volume '%s'", qcow2_name)
                            existing.delete(0)
                        except Exception:
                            pass  # volume doesn't exist — that's fine
                        vol = pool.createXML(vol_xml, 0)
                        stream = backend_conn.newStream(0)
                        vol.upload(stream, 0, file_size, 0)
                        try:
                            with open(tmp_qcow2, "rb") as fh:
                                while True:
                                    chunk = fh.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    stream.send(chunk)
                            stream.finish()
                        except Exception:
                            # Abort the stream so the daemon releases the
                            # in-progress upload and the partial volume can
                            # be cleaned up.  Suppress secondary errors.
                            try:
                                stream.abort()
                            except Exception:
                                pass
                            raise
                        pool.refresh(0)
                        final_path = vol.path()
                    except Exception as exc:
                        raise RuntimeError(
                            _("Failed to upload disk to storage pool: %s") % str(exc)
                        ) from exc
                else:
                    # Last-resort: direct copy (user must have write access)
                    final_path = os.path.join(output_dir, qcow2_name)
                    shutil.copy2(tmp_qcow2, final_path)

                converted_disks.append(final_path)

            # ── 4. Define the domain ─────────────────────────────────────────
            asyncjob._pbar_pulse(stage=_("Defining virtual machine in libvirt…"))
            guest = virtinst.Guest(backend_conn)
            try:
                capsinfo = conn.caps.guest_lookup(
                    os_type="hvm", arch="x86_64", typ="kvm"
                )
                guest.set_capabilities_defaults(capsinfo)
            except Exception:
                log.debug("Could not look up KVM capsinfo", exc_info=True)

            if osname:
                guest.set_os_name(osname)
            guest.name = vm_name
            guest.vcpus = vcpus
            guest.memory = memory_kib
            guest.currentMemory = memory_kib

            for disk_idx, final_path in enumerate(converted_disks):
                disk = virtinst.DeviceDisk(backend_conn)
                disk.set_source_path(final_path)
                disk.driver_name = virtinst.DeviceDisk.DRIVER_NAME_QEMU
                disk.driver_type = "qcow2"
                disk.device = virtinst.DeviceDisk.DEVICE_DISK
                # Use the bus type the OVF declared for this disk's controller
                # (ide / scsi / sata), falling back to the VM-wide default.
                # "sata" is the safest fallback: it works on Windows and Linux
                # without extra paravirtual drivers, unlike "virtio".
                bus = ovf_info.disks[disk_idx].get("bus") or ovf_info.disk_bus
                disk.bus = bus
                # Assign a target device name appropriate for the bus:
                #   sata/ide/scsi → sd*; virtio → vd*
                if bus == "virtio":
                    disk.target = "vd" + chr(ord("a") + disk_idx)
                else:
                    disk.target = "sd" + chr(ord("a") + disk_idx)
                guest.add_device(disk)

            # Pick the best virtual network available on this host.
            # Prefer "default" if it is active.  If no virtual networks are
            # running (e.g. air-gapped systems, hardened servers), fall back
            # to TYPE_USER (SLIRP): userland NAT that needs no host network
            # infrastructure and works unconditionally.
            net_name = None
            try:
                active_nets = backend_conn.listNetworks()  # returns active only
                if "default" in active_nets:
                    net_name = "default"
                elif active_nets:
                    net_name = active_nets[0]
                    log.debug("OVA import: 'default' network not active; "
                              "using network '%s'", net_name)
            except Exception:
                log.debug("Could not enumerate libvirt networks; "
                          "will use SLIRP networking", exc_info=True)

            net_count = max(ovf_info.net_count, 1 if converted_disks else 0)
            for _i in range(net_count):
                iface = virtinst.DeviceInterface(backend_conn)
                if net_name:
                    iface.type = virtinst.DeviceInterface.TYPE_VIRTUAL
                    iface.source = net_name
                else:
                    # No active virtual network — use SLIRP (user-mode NAT).
                    # SLIRP needs no host bridge or network daemon and works
                    # in air-gapped and locked-down environments.
                    iface.type = virtinst.DeviceInterface.TYPE_USER
                    log.debug("OVA import: no active virtual network found; "
                              "using SLIRP (user) networking")
                # Do NOT hardcode iface.model here.  guest.set_defaults() will
                # consult libosinfo and pick the right model for the detected OS
                # (e.g. e1000e for Windows, virtio for Linux).
                guest.add_device(iface)

            # Graphics console — SPICE with no network listener (local only)
            gfx = virtinst.DeviceGraphics(backend_conn)
            gfx.type = virtinst.DeviceGraphics.TYPE_SPICE
            gfx.listen = "none"
            gfx.set_defaults(guest)
            guest.add_device(gfx)

            # Video device — QXL pairs well with SPICE
            vid = virtinst.DeviceVideo(backend_conn)
            vid.model = "qxl"
            vid.set_defaults(guest)
            guest.add_device(vid)

            # Add remaining defaults (input, console, USB, channels, RNG,
            # memballoon, TPM, …).  set_defaults() skips graphics/video since
            # both are already present on the guest.
            guest.skip_default_graphics = True
            guest.set_defaults(None)

            domain_xml = guest.get_xml()
            log.debug("Defining domain XML:\n%s", domain_xml)
            backend_conn.defineXML(domain_xml)
            log.debug("Domain '%s' defined", vm_name)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _ova_import_finished_cb(self, error, details):
        self.reset_finish_cursor()
        if error:
            self.err.show_err(
                _("Unable to complete OVA import: '%s'") % error,
                details=details,
            )
            return

        vm_name = self._ova_vm_name
        foundvm = None
        for vm in self.conn.list_vms():
            if vm.get_name() == vm_name:
                foundvm = vm
                break

        self._close()
        if foundvm:
            vmmVMWindow.get_instance(self, foundvm).show()

    def _finish_clicked(self, src_ignore):
        # Validate the final page
        page = self.widget("create-pages").get_current_page()
        if self._validate(page) is not True:
            return

        log.debug("Starting create finish() sequence")
        self._gdata.failed_guest = None

        # OVA import has its own async flow
        if self._get_config_install_page() == INSTALL_PAGE_OVA:
            self._start_ova_import()
            return

        try:
            guest = self._gdata.build_guest()
            installer = self._gdata.build_installer()
            self.set_finish_cursor()

            # This encodes all the virtinst defaults up front, so the customize
            # dialog actually shows disk buses, cache values, default devices,
            # etc. Not required for straight start_install but doesn't hurt.
            installer.set_install_defaults(guest)

            if not self.widget("summary-customize").get_active():
                self._start_install(guest, installer)
                return

            log.debug("User requested 'customize', launching dialog")
            self._show_customize_dialog(guest, installer)
        except Exception as e:  # pragma: no cover
            self.reset_finish_cursor()
            self.err.show_err(_("Error starting installation: %s") % str(e))
            return

    def _cleanup_customize_window(self):
        if not self._customize_window:
            return

        # We can re-enter this: cleanup() -> close() -> "details-closed"
        window = self._customize_window
        virtinst_domain = self._customize_window.vm
        self._customize_window = None
        window.cleanup()
        virtinst_domain.cleanup()
        virtinst_domain = None

    def _show_customize_dialog(self, origguest, installer):
        orig_vdomain = vmmDomainVirtinst(self.conn, origguest, origguest.uuid, installer)

        def customize_finished_cb(src, vdomain):
            if not self.is_visible():
                return  # pragma: no cover
            log.debug("User finished customize dialog, starting install")
            self._gdata.failed_guest = None
            self._start_install(vdomain.get_backend(), installer)

        def config_canceled_cb(src):
            log.debug("User closed customize window, closing wizard")
            self._close_requested()

        # We specifically don't use vmmVMWindow.get_instance here since
        # it's not a top level VM window
        self._cleanup_customize_window()
        self._customize_window = vmmVMWindow(orig_vdomain, self.topwin)
        self._customize_window.connect("customize-finished", customize_finished_cb)
        self._customize_window.connect("closed", config_canceled_cb)
        self._customize_window.show()

    def _install_finished_cb(self, error, details, guest, parentobj):
        self.reset_finish_cursor(parentobj.topwin)

        if error:
            error = _("Unable to complete install: '%s'") % error
            parentobj.err.show_err(error, details=details)
            self._gdata.failed_guest = guest
            return

        foundvm = None
        for vm in self.conn.list_vms():
            if vm.get_uuid() == guest.uuid:
                foundvm = vm
                break

        self._close()

        # Launch details dialog for new VM
        vmmVMWindow.get_instance(self, foundvm).show()

    def _start_install(self, guest, installer):
        """
        Launch the async job to start the install
        """
        bootstrap_args = {}
        # If creating new container and "container bootstrap" is enabled
        if guest.os.is_container() and self._get_config_oscontainer_bootstrap():
            bootstrap_arg_keys = {
                "src": self._get_config_oscontainer_source_url,
                "dest": self.widget("install-oscontainer-fs").get_text,
                "user": self._get_config_oscontainer_source_username,
                "passwd": self._get_config_oscontainer_source_password,
                "insecure": self._get_config_oscontainer_isecure,
                "root_password": self._get_config_oscontainer_root_password,
            }
            for key, getter in bootstrap_arg_keys.items():
                bootstrap_args[key] = getter()

        parentobj = self._customize_window or self
        progWin = vmmAsyncJob(
            self._do_async_install,
            [guest, installer, bootstrap_args],
            self._install_finished_cb,
            [guest, parentobj],
            _("Creating Virtual Machine"),
            _(
                "The virtual machine is now being "
                "created. Allocation of disk storage "
                "and retrieval of the installation "
                "images may take a few minutes to "
                "complete."
            ),
            parentobj.topwin,
        )
        progWin.run()

    def _do_async_install(self, asyncjob, guest, installer, bootstrap_args):
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
                continue  # pragma: no cover

            poolname = pool.name()
            if poolname not in refresh_pools:
                refresh_pools.append(poolname)

        log.debug("Starting background install process")
        installer.start_install(guest, meter=meter)
        log.debug("Install completed")

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
            time.sleep(0.1)

        if not foundvm:
            raise RuntimeError(  # pragma: no cover
                _("VM '%s' didn't show up after expected time.") % guest.name
            )
        vm = foundvm

        if vm.is_shutoff():
            # Domain is already shutdown, but no error was raised.
            # Probably means guest had no 'install' phase, as in
            # for live cds. Try to restart the domain.
            vm.startup()  # pragma: no cover
        elif installer.requires_postboot_xml_changes():
            # Register a status listener, which will restart the
            # guest after the install has finished
            def cb():
                vm.connect_opt_out("state-changed", self._check_install_status)
                return False

            self.idle_add(cb)

        # Kick off pool updates
        for poolname in refresh_pools:
            try:
                pool = self.conn.get_pool_by_name(poolname)
                self.idle_add(pool.refresh)
            except Exception:  # pragma: no cover
                log.debug(
                    "Error looking up pool=%s for refresh after VM creation.",
                    poolname,
                    exc_info=True,
                )

    def _check_install_status(self, vm):
        """
        Watch the domain that we are installing, waiting for the state
        to change, so we can restart it as needed
        """
        if vm.is_crashed():  # pragma: no cover
            log.debug("VM crashed, cancelling install plans.")
            return True

        if not vm.is_shutoff():
            return  # pragma: no cover

        if vm.get_install_abort():
            log.debug("User manually shutdown VM, not restarting guest after install.")
            return True

        # Hitting this from the test suite is hard because we can't force
        # the test driver VM to stop behind virt-manager's back
        try:  # pragma: no cover
            log.debug("Install should be completed, starting VM.")
            vm.startup()
        except Exception as e:  # pragma: no cover
            self.err.show_err(_("Error continuing install: %s") % str(e))

        return True  # pragma: no cover

    def _create_directory_tree(self, asyncjob, meter, bootstrap_args):
        """
        Call bootstrap method from virtBootstrap and show logger messages
        as state/details.
        """
        import logging

        if self.conn.config.CLITestOptions.fake_virtbootstrap:
            from .lib.testmock import fakeVirtBootstrap as virtBootstrap
        else:  # pragma: no cover
            import virtBootstrap  # pylint: disable=import-error

        meter.start(_("Bootstrapping container"), None)

        def progress_update_cb(prog):
            meter.start(_(prog["status"]), None)

        asyncjob.details_enable()

        # Use logging filter to show messages of the progress on the GUI
        class SetStateFilter(logging.Filter):
            def filter(self, record):
                asyncjob.details_update("%s\n" % record.getMessage())
                return True

        # Use string buffer to store log messages
        log_stream = io.StringIO()

        # Get virt-bootstrap logger
        vbLogger = logging.getLogger("virtBootstrap")
        vbLogger.setLevel(logging.DEBUG)
        # Create handler to store log messages in the string buffer
        hdlr = logging.StreamHandler(log_stream)
        hdlr.setFormatter(logging.Formatter("%(message)s"))
        # Use logging filter to show messages on GUI
        hdlr.addFilter(SetStateFilter())
        vbLogger.addHandler(hdlr)

        # Key word arguments to be passed
        kwargs = {
            "uri": bootstrap_args["src"],
            "dest": bootstrap_args["dest"],
            "not_secure": bootstrap_args["insecure"],
            "progress_cb": progress_update_cb,
        }
        if bootstrap_args["user"] and bootstrap_args["passwd"]:
            kwargs["username"] = bootstrap_args["user"]
            kwargs["password"] = bootstrap_args["passwd"]
        if bootstrap_args["root_password"]:
            kwargs["root_password"] = bootstrap_args["root_password"]
        log.debug("Start container bootstrap")
        try:
            virtBootstrap.bootstrap(**kwargs)
            # Success - uncheck the 'install-oscontainer-bootstrap' checkbox

            def cb():
                self.widget("install-oscontainer-bootstrap").set_active(False)

            self.idle_add(cb)
        except Exception as err:
            asyncjob.set_error(
                "virt-bootstrap did not complete successfully",
                "%s\n%s" % (err, log_stream.getvalue()),
            )
