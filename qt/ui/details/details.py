from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QFormLayout, QComboBox,
    QLineEdit, QCheckBox, QGroupBox, QScrollArea, QTextEdit,
    QTabWidget, QSpinBox, QDoubleSpinBox, QProgressBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ..lib.i18n import _, ngettext


EDIT_XML = 0
EDIT_NAME = 1
EDIT_MEM = 2
EDIT_VCPUS = 3
EDIT_AUTOSTART = 4
EDIT_BOOTORDER = 5
EDIT_KERNEL = 6
EDIT_DISK = 7
EDIT_NET = 8
EDIT_GFX = 9
EDIT_VIDEO = 10


HW_LIST_TYPE_GENERAL = 0
HW_LIST_TYPE_OS = 1
HW_LIST_TYPE_STATS = 2
HW_LIST_TYPE_CPU = 3
HW_LIST_TYPE_MEMORY = 4
HW_LIST_TYPE_BOOT = 5
HW_LIST_TYPE_DISK = 6
HW_LIST_TYPE_NIC = 7
HW_LIST_TYPE_GRAPHICS = 8
HW_LIST_TYPE_SOUND = 9
HW_LIST_TYPE_HOSTDEV = 10
HW_LIST_TYPE_VIDEO = 11
HW_LIST_TYPE_WATCHDOG = 12
HW_LIST_TYPE_CONTROLLER = 13
HW_LIST_TYPE_FILESYSTEM = 14
HW_LIST_TYPE_TPM = 15
HW_LIST_TYPE_RNG = 16
HW_LIST_TYPE_VSOCK = 17


class vmmDetails(QWidget):
    def __init__(self, vm, conn, engine):
        super().__init__()
        self.vm = vm
        self.conn = conn
        self.engine = engine
        
        self._active_edits = set()
        self._stats_timer = None
        self._cpu_history = []
        self._mem_history = []
        
        self._init_ui()
        self._populate_hw_list()
        self._refresh_details()
        self._start_stats_timer()
    
    def _start_stats_timer(self):
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats_display)
        self._stats_timer.start(2000)
    
    def _update_stats_display(self):
        if not self.vm or not hasattr(self, '_cpu_label'):
            return
        
        try:
            cpu_pct = self.conn.host_cpu_time_percentage()
            self._cpu_label.setText(f"{cpu_pct:.1f} %")
            self._cpu_progress.setValue(int(cpu_pct))
            
            self._cpu_history.append(cpu_pct)
            if len(self._cpu_history) > 30:
                self._cpu_history.pop(0)
            
            mem_usage = self.conn.stats_memory()
            host_mem = self.conn.host_memory_size()
            mem_pct = (mem_usage / host_mem * 100) if host_mem > 0 else 0
            self._mem_label.setText(f"{mem_usage} MiB / {host_mem} MiB")
            self._mem_progress.setValue(int(mem_pct))
            
            self._mem_history.append(mem_pct)
            if len(self._mem_history) > 30:
                self._mem_history.pop(0)
            
            if hasattr(self.vm, 'domain') and self.vm.domain:
                state = self.vm.domain.state(0, 0)[0]
                self._state_label.setText(self._state_to_str(state))
        except Exception:
            pass
    
    def _state_to_str(self, state):
        states = {
            0: _("No state"),
            1: _("Running"),
            2: _("Blocked"),
            3: _("Paused"),
            4: _("Shutdown"),
            5: _("Shutoff"),
            6: _("Crashed"),
            7: _("Suspended"),
            8: _("Suspended (pmsuspended)"),
        }
        return states.get(state, _("Unknown"))
    
    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        
        self._hw_list = QTreeWidget()
        self._hw_list.setHeaderHidden(True)
        self._hw_list.currentItemChanged.connect(self._hw_changed)
        main_layout.addWidget(self._hw_list, 1)
        
        self._details_container = QWidget()
        details_layout = QVBoxLayout(self._details_container)
        
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(QWidget())
        self._scroll_widget = self._scroll.widget()
        self._details_layout = QVBoxLayout(self._scroll_widget)
        
        details_layout.addWidget(self._scroll)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self._apply_btn = QPushButton(_("Apply"))
        self._apply_btn.clicked.connect(self._apply_changes)
        self._apply_btn.setEnabled(False)
        button_layout.addWidget(self._apply_btn)
        
        self._cancel_btn = QPushButton(_("Cancel"))
        self._cancel_btn.clicked.connect(self._cancel_changes)
        self._cancel_btn.setEnabled(False)
        button_layout.addWidget(self._cancel_btn)
        
        details_layout.addLayout(button_layout)
        
        main_layout.addWidget(self._details_container, 3)
    
    def _populate_hw_list(self):
        self._hw_list.clear()
        
        items = [
            (HW_LIST_TYPE_GENERAL, _("Overview"), "computer"),
            (HW_LIST_TYPE_OS, _("OS Information"), "computer"),
            (HW_LIST_TYPE_STATS, _("Performance"), "utilities-system-monitor"),
            (HW_LIST_TYPE_CPU, _("CPUs"), "processor"),
            (HW_LIST_TYPE_MEMORY, _("Memory"), "memory"),
            (HW_LIST_TYPE_BOOT, _("Boot Options"), "drive-harddisk"),
            (HW_LIST_TYPE_DISK, _("Disks"), "drive-harddisk"),
            (HW_LIST_TYPE_NIC, _("Network Interfaces"), "network-idle"),
            (HW_LIST_TYPE_GRAPHICS, _("Graphics"), "video-display"),
            (HW_LIST_TYPE_SOUND, _("Sound"), "audio-card"),
            (HW_LIST_TYPE_VIDEO, _("Video"), "video-display"),
            (HW_LIST_TYPE_WATCHDOG, _("Watchdog"), "clock"),
            (HW_LIST_TYPE_CONTROLLER, _("Controller"), "preferences-system"),
            (HW_LIST_TYPE_HOSTDEV, _("Host Devices"), "computer"),
            (HW_LIST_TYPE_FILESYSTEM, _("Filesystems"), "folder"),
            (HW_LIST_TYPE_TPM, _("TPM"), "security-high"),
            (HW_LIST_TYPE_RNG, _("RNG"), "drive-harddisk"),
            (HW_LIST_TYPE_VSOCK, _("VSOCK"), "network-idle"),
        ]
        
        for hw_type, label, icon in items:
            item = QTreeWidgetItem(self._hw_list)
            item.setText(0, label)
            item.setData(0, Qt.ItemDataRole.UserRole, hw_type)
        
        if self._hw_list.topLevelItemCount() > 0:
            self._hw_list.setCurrentItem(self._hw_list.topLevelItem(0))
    
    def _refresh_details(self):
        if not self.vm or not self.vm.domain:
            return
        
        try:
            self.vm.refresh()
        except Exception:
            pass
        
        current_item = self._hw_list.currentItem()
        if current_item:
            self._hw_changed(current_item, None)
    
    def _hw_changed(self, current, previous):
        if not current:
            return
        
        hw_type = current.data(0, Qt.ItemDataRole.UserRole)
        
        while self._details_layout.count():
            item = self._details_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if hw_type == HW_LIST_TYPE_GENERAL:
            self._build_general_tab()
        elif hw_type == HW_LIST_TYPE_OS:
            self._build_os_tab()
        elif hw_type == HW_LIST_TYPE_STATS:
            self._build_stats_tab()
        elif hw_type == HW_LIST_TYPE_CPU:
            self._build_cpu_tab()
        elif hw_type == HW_LIST_TYPE_MEMORY:
            self._build_memory_tab()
        elif hw_type == HW_LIST_TYPE_BOOT:
            self._build_boot_tab()
        elif hw_type == HW_LIST_TYPE_DISK:
            self._build_disk_tab()
        elif hw_type == HW_LIST_TYPE_NIC:
            self._build_nic_tab()
        elif hw_type == HW_LIST_TYPE_GRAPHICS:
            self._build_graphics_tab()
        elif hw_type == HW_LIST_TYPE_SOUND:
            self._build_sound_tab()
        elif hw_type == HW_LIST_TYPE_VIDEO:
            self._build_video_tab()
        elif hw_type == HW_LIST_TYPE_WATCHDOG:
            self._build_watchdog_tab()
        elif hw_type == HW_LIST_TYPE_CONTROLLER:
            self._build_controller_tab()
        elif hw_type == HW_LIST_TYPE_HOSTDEV:
            self._build_hostdev_tab()
        elif hw_type == HW_LIST_TYPE_FILESYSTEM:
            self._build_filesystem_tab()
        elif hw_type == HW_LIST_TYPE_TPM:
            self._build_tpm_tab()
        elif hw_type == HW_LIST_TYPE_RNG:
            self._build_rng_tab()
        elif hw_type == HW_LIST_TYPE_VSOCK:
            self._build_vsock_tab()
    
    def _build_general_tab(self):
        group = QGroupBox(_("General"))
        layout = QFormLayout(group)
        
        name_label = QLabel(self.vm.get_name())
        layout.addRow(_("Name:"), name_label)
        
        uuid_label = QLabel(self.vm.get_uuid())
        layout.addRow(_("UUID:"), uuid_label)
        
        self._state_label = QLabel(self.vm.run_status())
        layout.addRow(_("Status:"), self._state_label)
        
        autostart_label = QLabel(_("Yes") if self.vm.get_autostart() else _("No"))
        layout.addRow(_("Autostart:"), autostart_label)
        
        self._details_layout.addWidget(group)
    
    def _build_os_tab(self):
        group = QGroupBox(_("Operating System"))
        layout = QFormLayout(group)
        
        os_type_label = QLabel(str(self.vm.get_xmlobj().os.type))
        layout.addRow(_("Type:"), os_label := QLabel(str(self.vm.get_xmlobj().os.type)))
        
        os_variant = self.vm.get_xmlobj().os.os_variant
        variant_label = QLabel(os_variant or _("None"))
        layout.addRow(_("Variant:"), variant_label)
        
        self._details_layout.addWidget(group)
    
    def _build_stats_tab(self):
        group = QGroupBox(_("Resource Usage"))
        layout = QVBoxLayout(group)
        
        cpu_group = QGroupBox(_("CPU"))
        cpu_layout = QFormLayout(cpu_group)
        
        self._cpu_progress = QProgressBar()
        self._cpu_progress.setRange(0, 100)
        self._cpu_progress.setValue(0)
        cpu_layout.addRow(_("Usage:"), self._cpu_progress)
        
        self._cpu_label = QLabel("0 %")
        cpu_layout.addRow(_("Host CPU:"), self._cpu_label)
        
        layout.addWidget(cpu_group)
        
        mem_group = QGroupBox(_("Memory"))
        mem_layout = QFormLayout(mem_group)
        
        self._mem_progress = QProgressBar()
        self._mem_progress.setRange(0, 100)
        self._mem_progress.setValue(0)
        mem_layout.addRow(_("Usage:"), self._mem_progress)
        
        self._mem_label = QLabel("0 MiB / 0 MiB")
        mem_layout.addRow(_("Memory:"), self._mem_label)
        
        layout.addWidget(mem_group)
        
        self._details_layout.addWidget(group)
    
    def _build_cpu_tab(self):
        group = QGroupBox(_("CPU Configuration"))
        layout = QFormLayout(group)
        
        vcpus = self.vm.get_xmlobj().vcpus or 1
        cpu_label = QLabel(str(vcpus))
        layout.addRow(_("vCPUs:"), cpu_label)
        
        max_vcpus = self.vm.get_xmlobj().maxvcpus or vcpus
        max_label = QLabel(str(max_vcpus))
        layout.addRow(_("Max vCPUs:"), max_label)
        
        topology = self.vm.get_xmlobj().cpu.topology
        if topology:
            topo_label = QLabel(f"{topology.sockets}, {topology.cores}, {topology.threads}")
            layout.addRow(_("Topology:"), topo_label)
        
        layout.addWidget(group)
        self._details_layout.addWidget(group)
    
    def _build_memory_tab(self):
        group = QGroupBox(_("Memory Configuration"))
        layout = QFormLayout(group)
        
        mem = self.vm.get_xmlobj().memory
        mem_label = QLabel(f"{mem} MiB")
        layout.addRow(_("Memory:"), mem_label)
        
        max_mem = self.vm.get_xmlobj().maxmemory
        if max_mem:
            max_label = QLabel(f"{max_mem} MiB")
            layout.addRow(_("Max Memory:"), max_label)
        
        layout.addWidget(group)
        self._details_layout.addWidget(group)
    
    def _build_boot_tab(self):
        group = QGroupBox(_("Boot Options"))
        layout = QFormLayout(group)
        
        kernel = self.vm.get_xmlobj().os.kernel
        kernel_label = QLabel(kernel or _("None"))
        layout.addRow(_("Kernel:"), kernel_label)
        
        initrd = self.vm.get_xmlobj().os.initrd
        initrd_label = QLabel(initrd or _("None"))
        layout.addRow(_("Initrd:"), initrd_label)
        
        cmdline = self.vm.get_xmlobj().os.cmdline
        cmdline_label = QLabel(cmdline or _("None"))
        layout.addRow(_("Kernel Args:"), cmdline_label)
        
        layout.addWidget(group)
        self._details_layout.addWidget(group)
    
    def _build_disk_tab(self):
        group = QGroupBox(_("Disks"))
        layout = QVBoxLayout(group)
        
        disks = self.vm.get_xmlobj().devices.disk or []
        if not disks:
            no_disks = QLabel(_("No disks configured"))
            layout.addWidget(no_disks)
        else:
            for i, disk in enumerate(disks):
                disk_group = QGroupBox(_("Disk %d") % (i + 1))
                disk_layout = QFormLayout(disk_group)
                disk_layout.addRow(_("Type:"), QLabel(disk.device))
                disk_layout.addRow(_("Bus:"), QLabel(disk.bus or "-"))
                disk_layout.addRow(_("Target:"), QLabel(disk.target or "-"))
                
                source = disk.get_source_path()
                if source:
                    disk_layout.addRow(_("Source:"), QLabel(source))
                
                disk_cache = getattr(disk, 'cache', None)
                if disk_cache:
                    disk_layout.addRow(_("Cache:"), QLabel(disk_cache))
                
                layout.addWidget(disk_group)
        
        self._details_layout.addWidget(group)
    
    def _build_nic_tab(self):
        group = QGroupBox(_("Network Interfaces"))
        layout = QVBoxLayout(group)
        
        nics = self.vm.get_xmlobj().devices.interface or []
        if not nics:
            no_nics = QLabel(_("No network interfaces configured"))
            layout.addWidget(no_nics)
        else:
            for i, nic in enumerate(nics):
                nic_group = QGroupBox(_("Interface %d") % (i + 1))
                nic_layout = QFormLayout(nic_group)
                nic_layout.addRow(_("Type:"), QLabel(nic.type))
                nic_layout.addRow(_("MAC:"), QLabel(nic.macaddr or "-"))
                nic_layout.addRow(_("Source:"), QLabel(str(nic.source) or "-"))
                nic_layout.addRow(_("Model:"), QLabel(nic.model or "-"))
                layout.addWidget(nic_group)
        
        self._details_layout.addWidget(group)
    
    def _build_graphics_tab(self):
        group = QGroupBox(_("Graphics"))
        layout = QVBoxLayout(group)
        
        gfxs = self.vm.get_xmlobj().devices.graphics or []
        if not gfxs:
            no_gfx = QLabel(_("No graphics configured"))
            layout.addWidget(no_gfx)
        else:
            for i, gfx in enumerate(gfxs):
                gfx_group = QGroupBox(_("Graphics %d") % (i + 1))
                gfx_layout = QFormLayout(gfx_group)
                gfx_layout.addRow(_("Type:"), QLabel(gfx.type))
                gfx_layout.addRow(_("Listen:"), QLabel(gfx.listen or "-"))
                gfx_layout.addRow(_("Port:"), QLabel(str(gfx.port) if gfx.port else "-"))
                
                tls_port = getattr(gfx, 'tls_port', None)
                if tls_port:
                    gfx_layout.addRow(_("TLS Port:"), QLabel(str(tls_port)))
                
                layout.addWidget(gfx_group)
        
        self._details_layout.addWidget(group)
    
    def _build_sound_tab(self):
        group = QGroupBox(_("Sound Devices"))
        layout = QVBoxLayout(group)
        
        sounds = self.vm.get_xmlobj().devices.sound or []
        if not sounds:
            no_sound = QLabel(_("No sound devices configured"))
            layout.addWidget(no_sound)
        else:
            for i, sound in enumerate(sounds):
                sound_group = QGroupBox(_("Sound %d") % (i + 1))
                sound_layout = QFormLayout(sound_group)
                sound_layout.addRow(_("Model:"), QLabel(sound.model))
                layout.addWidget(sound_group)
        
        self._details_layout.addWidget(group)
    
    def _build_video_tab(self):
        group = QGroupBox(_("Video Devices"))
        layout = QVBoxLayout(group)
        
        videos = self.vm.get_xmlobj().devices.video or []
        if not videos:
            no_video = QLabel(_("No video devices configured"))
            layout.addWidget(no_video)
        else:
            for i, video in enumerate(videos):
                video_group = QGroupBox(_("Video %d") % (i + 1))
                video_layout = QFormLayout(video_group)
                video_layout.addRow(_("Model:"), QLabel(video.model))
                
                ram = getattr(video, 'ram', None)
                if ram:
                    video_layout.addRow(_("VRAM:"), QLabel(str(ram)))
                
                heads = getattr(video, 'heads', None)
                if heads:
                    video_layout.addRow(_("Heads:"), QLabel(str(heads)))
                
                layout.addWidget(video_group)
        
        self._details_layout.addWidget(group)
    
    def _build_watchdog_tab(self):
        group = QGroupBox(_("Watchdog"))
        layout = QVBoxLayout(group)
        
        watchdogs = self.vm.get_xmlobj().devices.watchdog or []
        if not watchdogs:
            no_watchdog = QLabel(_("No watchdog configured"))
            layout.addWidget(no_watchdog)
        else:
            for i, watchdog in enumerate(watchdogs):
                wd_layout = QFormLayout()
                wd_layout.addRow(_("Model:"), QLabel(watchdog.model))
                wd_layout.addRow(_("Action:"), QLabel(watchdog.action))
                layout.addLayout(wd_layout)
        
        self._details_layout.addWidget(group)
    
    def _build_controller_tab(self):
        group = QGroupBox(_("Controllers"))
        layout = QVBoxLayout(group)
        
        controllers = self.vm.get_xmlobj().devices.controller or []
        if not controllers:
            no_ctrl = QLabel(_("No controllers configured"))
            layout.addWidget(no_ctrl)
        else:
            for i, ctrl in enumerate(controllers):
                ctrl_group = QGroupBox(_("Controller %d") % (i + 1))
                ctrl_layout = QFormLayout(ctrl_group)
                ctrl_layout.addRow(_("Type:"), QLabel(ctrl.type))
                ctrl_layout.addRow(_("Model:"), QLabel(ctrl.model or "-"))
                layout.addWidget(ctrl_group)
        
        self._details_layout.addWidget(group)
    
    def _build_hostdev_tab(self):
        group = QGroupBox(_("Host Devices"))
        layout = QVBoxLayout(group)
        
        hostdevs = self.vm.get_xmlobj().devices.hostdev or []
        if not hostdevs:
            no_hostdev = QLabel(_("No host devices configured"))
            layout.addWidget(no_hostdev)
        else:
            for i, hostdev in enumerate(hostdevs):
                hd_group = QGroupBox(_("Host Device %d") % (i + 1))
                hd_layout = QFormLayout(hd_group)
                
                source = hostdev.source
                if source:
                    if hasattr(source, 'address'):
                        addr = source.address
                        addr_str = f"{addr.domain}:{addr.bus}:{addr.slot}.{addr.function}"
                        hd_layout.addRow(_("Address:"), QLabel(addr_str))
                
                layout.addWidget(hd_group)
        
        self._details_layout.addWidget(group)
    
    def _build_filesystem_tab(self):
        group = QGroupBox(_("Filesystems"))
        layout = QVBoxLayout(group)
        
        filesystems = self.vm.get_xmlobj().devices.fs or []
        if not filesystems:
            no_fs = QLabel(_("No filesystems configured"))
            layout.addWidget(no_fs)
        else:
            for i, fs in enumerate(filesystems):
                fs_group = QGroupBox(_("Filesystem %d") % (i + 1))
                fs_layout = QFormLayout(fs_group)
                fs_layout.addRow(_("Type:"), QLabel(fs.type))
                fs_layout.addRow(_("Source:"), QLabel(fs.source or "-"))
                fs_layout.addRow(_("Target:"), QLabel(fs.target or "-"))
                layout.addWidget(fs_group)
        
        self._details_layout.addWidget(group)
    
    def _build_tpm_tab(self):
        group = QGroupBox(_("TPM"))
        layout = QVBoxLayout(group)
        
        tpms = self.vm.get_xmlobj().devices.tpm or []
        if not tpms:
            no_tpm = QLabel(_("No TPM configured"))
            layout.addWidget(no_tpm)
        else:
            for tpm in tpms:
                tpm_layout = QFormLayout()
                tpm_layout.addRow(_("Type:"), QLabel(tpm.type))
                tpm_layout.addRow(_("Model:"), QLabel(tpm.model))
                layout.addLayout(tpm_layout)
        
        self._details_layout.addWidget(group)
    
    def _build_rng_tab(self):
        group = QGroupBox(_("Random Number Generator"))
        layout = QVBoxLayout(group)
        
        rngs = self.vm.get_xmlobj().devices.rng or []
        if not rngs:
            no_rng = QLabel(_("No RNG configured"))
            layout.addWidget(no_rng)
        else:
            for rng in rngs:
                rng_layout = QFormLayout()
                rng_layout.addRow(_("Type:"), QLabel(rng.type))
                rng_layout.addRow(_("Model:"), QLabel(rng.model))
                layout.addLayout(rng_layout)
        
        self._details_layout.addWidget(group)
    
    def _build_vsock_tab(self):
        group = QGroupBox(_("VSOCK"))
        layout = QVBoxLayout(group)
        
        vsocks = self.vm.get_xmlobj().devices.vsock or []
        if not vsocks:
            no_vsock = QLabel(_("No VSOCK configured"))
            layout.addWidget(no_vsock)
        else:
            for vsock in vsocks:
                vs_layout = QFormLayout()
                cid = getattr(vsock, 'cid', None)
                vs_layout.addRow(_("CID:"), QLabel(str(cid) if cid else "-"))
                layout.addLayout(vs_layout)
        
        self._details_layout.addWidget(group)
    
    def _apply_changes(self):
        if not self._active_edits:
            return
        
        try:
            xml = self.vm.get_xml_to_define()
            self.conn.get_backend().defineXML(xml)
            self._active_edits.clear()
            self._apply_btn.setEnabled(False)
            self._cancel_btn.setEnabled(False)
            QMessageBox.information(self, _("Success"), _("Changes applied successfully"))
        except Exception as e:
            QMessageBox.critical(self, _("Error"), _("Failed to apply changes: %s") % str(e))
    
    def _cancel_changes(self):
        self._active_edits.clear()
        self._apply_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._refresh_details()
    
    def refresh_vm(self, vm):
        self.vm = vm
        self._refresh_details()
    
    def cleanup(self):
        if self._stats_timer:
            self._stats_timer.stop()
            self._stats_timer = None
